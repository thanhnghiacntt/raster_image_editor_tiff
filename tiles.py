# -*- coding: utf-8 -*-
"""Xuất bộ tile XYZ / TMS (thư mục, ZIP hoặc MBTiles) — tương tự plugin QTiles.

Tile được kết xuất bằng chính bộ vẽ bản đồ của QGIS ở hệ EPSG:3857 (Web
Mercator), nên ảnh đã căn và các lớp khác đều được chiếu lại đúng.
"""

import json
import math
import os
import sqlite3
import zipfile

from qgis.PyQt.QtCore import QBuffer, QIODevice, QSize
from qgis.PyQt.QtGui import QColor, QImage
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsProject,
                       QgsRectangle)

from .exporter import qimage_to_array

ORIGIN = 20037508.342789244        # nửa chu vi Trái Đất ở Web Mercator (m)
MAX_LAT = 85.05112877980659
MERCATOR = 'EPSG:3857'
WGS84 = 'EPSG:4326'

MAX_ZOOM = 24
TILE_SIZES = (256, 512)
FORMATS = ('PNG', 'JPG')

SRC_IMAGE = 'image'                # chỉ ảnh đang căn
SRC_IMAGE_LAYERS = 'image+layers'  # ảnh nằm trên các lớp đang hiện
SRC_LAYERS = 'layers'              # chỉ các lớp đang hiện

OUT_DIR = 'dir'
OUT_ZIP = 'zip'
OUT_MBTILES = 'mbtiles'


# --------------------------------------------------------------------- toán ô
def tiles_per_axis(zoom):
    return 1 << int(zoom)


def tile_span(zoom):
    return 2.0 * ORIGIN / tiles_per_axis(zoom)


def tile_extent(zoom, x, y):
    """Phạm vi (EPSG:3857) của ô XYZ. y đếm từ trên xuống."""
    span = tile_span(zoom)
    xmin = -ORIGIN + x * span
    ymax = ORIGIN - y * span
    return QgsRectangle(xmin, ymax - span, xmin + span, ymax)


def tile_range(extent, zoom):
    """(x0, y0, x1, y1) các ô XYZ phủ `extent` (đã ở EPSG:3857), đã kẹp biên."""
    n = tiles_per_axis(zoom)
    span = tile_span(zoom)
    eps = 1e-9
    x0 = int(math.floor((extent.xMinimum() + ORIGIN) / span + eps))
    x1 = int(math.ceil((extent.xMaximum() + ORIGIN) / span - eps)) - 1
    y0 = int(math.floor((ORIGIN - extent.yMaximum()) / span + eps))
    y1 = int(math.ceil((ORIGIN - extent.yMinimum()) / span - eps)) - 1
    x0, x1 = max(0, x0), min(n - 1, max(x0, x1))
    y0, y1 = max(0, y0), min(n - 1, max(y0, y1))
    return x0, y0, x1, y1


def count_tiles(extent, zoom_min, zoom_max):
    total = 0
    for z in range(int(zoom_min), int(zoom_max) + 1):
        x0, y0, x1, y1 = tile_range(extent, z)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


def clamp_mercator(extent):
    """Cắt phạm vi về trong giới hạn hợp lệ của Web Mercator."""
    return QgsRectangle(max(-ORIGIN, extent.xMinimum()),
                        max(-ORIGIN, extent.yMinimum()),
                        min(ORIGIN, extent.xMaximum()),
                        min(ORIGIN, extent.yMaximum()))


def to_mercator(extent, src_crs):
    if src_crs is None or not src_crs.isValid():
        return clamp_mercator(extent)
    dest = QgsCoordinateReferenceSystem(MERCATOR)
    if src_crs == dest:
        return clamp_mercator(extent)
    xform = QgsCoordinateTransform(src_crs, dest, QgsProject.instance())
    return clamp_mercator(xform.transformBoundingBox(extent))


def to_wgs84(extent, src_crs):
    dest = QgsCoordinateReferenceSystem(WGS84)
    if src_crs is None or not src_crs.isValid() or src_crs == dest:
        return extent
    xform = QgsCoordinateTransform(src_crs, dest, QgsProject.instance())
    return xform.transformBoundingBox(extent)


def suggest_zooms(extent_3857, source_pixel_size=None, tile_size=256):
    """Đề xuất (zoom nhỏ nhất, zoom lớn nhất) hợp lý cho phạm vi đã cho."""
    width = max(extent_3857.width(), extent_3857.height(), 1e-6)
    # zoom nhỏ nhất: cả phạm vi gói gọn trong khoảng 1 ô
    z_min = int(max(0, math.floor(math.log(2.0 * ORIGIN / width, 2))))
    if source_pixel_size and source_pixel_size > 0:
        # zoom lớn nhất: 1 pixel tile xấp xỉ 1 pixel ảnh gốc
        z_max = math.log(2.0 * ORIGIN / (tile_size * source_pixel_size), 2)
        z_max = int(max(z_min, min(MAX_ZOOM, math.ceil(z_max))))
    else:
        z_max = min(MAX_ZOOM, z_min + 5)
    return z_min, z_max


# ------------------------------------------------------------------ nơi ghi ô
class BaseTileWriter(object):
    def __init__(self, fmt):
        self.ext = 'png' if fmt.upper() == 'PNG' else 'jpg'
        self.count = 0

    def write(self, zoom, x, y, data):
        raise NotImplementedError

    def finish(self, meta):
        pass

    def close(self):
        pass


class DirectoryTileWriter(BaseTileWriter):
    """Ghi ra cây thư mục z/x/y.png."""

    def __init__(self, root, fmt, tms=False):
        super().__init__(fmt)
        self.root = root
        self.tms = tms
        if not os.path.isdir(root):
            os.makedirs(root)

    def write(self, zoom, x, y, data):
        row = (tiles_per_axis(zoom) - 1 - y) if self.tms else y
        folder = os.path.join(self.root, str(zoom), str(x))
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, '%d.%s' % (row, self.ext)), 'wb') as fh:
            fh.write(data)
        self.count += 1

    def finish(self, meta):
        with open(os.path.join(self.root, 'metadata.json'), 'w', encoding='utf-8') as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)


class ZipTileWriter(BaseTileWriter):
    """Gói toàn bộ ô vào một file .zip."""

    def __init__(self, path, fmt, tms=False):
        super().__init__(fmt)
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        self.zip = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
        self.tms = tms

    def write(self, zoom, x, y, data):
        row = (tiles_per_axis(zoom) - 1 - y) if self.tms else y
        self.zip.writestr('%d/%d/%d.%s' % (zoom, x, row, self.ext), data)
        self.count += 1

    def finish(self, meta):
        self.zip.writestr('metadata.json',
                          json.dumps(meta, ensure_ascii=False, indent=2))

    def close(self):
        try:
            self.zip.close()
        except Exception:
            pass


class MBTilesWriter(BaseTileWriter):
    """Ghi vào file .mbtiles (SQLite, trục y theo TMS đúng đặc tả)."""

    def __init__(self, path, fmt):
        super().__init__(fmt)
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        if os.path.exists(path):
            os.remove(path)
        self.db = sqlite3.connect(path)
        cur = self.db.cursor()
        cur.execute('CREATE TABLE metadata (name text, value text)')
        cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, '
                    'tile_row integer, tile_data blob)')
        cur.execute('CREATE UNIQUE INDEX tile_index ON tiles '
                    '(zoom_level, tile_column, tile_row)')
        self.db.commit()

    def write(self, zoom, x, y, data):
        row = tiles_per_axis(zoom) - 1 - y        # MBTiles luôn dùng TMS
        self.db.execute('INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)',
                        (zoom, x, row, sqlite3.Binary(data)))
        self.count += 1
        if self.count % 200 == 0:
            self.db.commit()

    def finish(self, meta):
        b = meta['bounds']
        rows = [
            ('name', meta['name']),
            ('type', 'overlay'),
            ('version', '1.1'),
            ('description', meta['description']),
            ('format', self.ext),
            ('bounds', '%f,%f,%f,%f' % (b[0], b[1], b[2], b[3])),
            ('center', '%f,%f,%d' % ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0,
                                     meta['minzoom'])),
            ('minzoom', str(meta['minzoom'])),
            ('maxzoom', str(meta['maxzoom'])),
        ]
        self.db.executemany('INSERT INTO metadata VALUES (?, ?)', rows)
        self.db.commit()

    def close(self):
        try:
            self.db.commit()
            self.db.close()
        except Exception:
            pass


# ------------------------------------------------------------------ kết xuất
LEAFLET_HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>html,body{margin:0;height:100%}#map{height:100%}</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var map = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom: 19, attribution: '&copy; OpenStreetMap'}).addTo(map);
L.tileLayer('{z}/{x}/{y}.__EXT__', {
  minZoom: __MINZ__, maxZoom: __MAXZ__, tms: __TMS__, opacity: 1.0
}).addTo(map);
map.fitBounds([[__S__, __W__], [__N__, __E__]]);
</script>
</body>
</html>
"""


def write_leaflet_viewer(folder, meta, ext, tms):
    b = meta['bounds']
    html = (LEAFLET_HTML
            .replace('__NAME__', meta['name'])
            .replace('__EXT__', ext)
            .replace('__MINZ__', str(meta['minzoom']))
            .replace('__MAXZ__', str(meta['maxzoom']))
            .replace('__TMS__', 'true' if tms else 'false')
            .replace('__W__', '%f' % b[0]).replace('__S__', '%f' % b[1])
            .replace('__E__', '%f' % b[2]).replace('__N__', '%f' % b[3]))
    path = os.path.join(folder, 'viewer.html')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return path


class TileExporter(object):
    """Duyệt qua từng ô, kết xuất bằng QGIS rồi giao cho `writer` ghi lại."""

    def __init__(self, layers, extent_3857, zoom_min, zoom_max, writer,
                 tile_size=256, fmt='PNG', quality=85, background=None,
                 draw_labels=True, skip_blank=True):
        self.layers = list(layers)
        self.extent = extent_3857
        self.zoom_min = int(zoom_min)
        self.zoom_max = int(zoom_max)
        self.writer = writer
        self.tile_size = int(tile_size)
        self.fmt = fmt.upper()
        self.quality = int(quality)
        self.draw_labels = draw_labels
        self.skip_blank = skip_blank and self.fmt == 'PNG'
        self.background = background or QColor(0, 0, 0, 0)
        if self.fmt == 'JPG' and self.background.alpha() < 255:
            self.background = QColor(255, 255, 255)

        self.written = 0
        self.skipped = 0

        self._settings = QgsMapSettings()
        self._settings.setDestinationCrs(QgsCoordinateReferenceSystem(MERCATOR))
        self._settings.setLayers(self.layers)
        self._settings.setOutputSize(QSize(self.tile_size, self.tile_size))
        self._settings.setOutputDpi(96)
        self._settings.setBackgroundColor(self.background)
        self._set_flag('Antialiasing', True)
        self._set_flag('UseAdvancedEffects', True)
        # Báo cho bộ vẽ biết đang kết xuất một ô của lưới tile -> ký hiệu không
        # bị cắt cụt ở mép ô.
        self._set_flag('RenderMapTile', True)
        self._set_flag('DrawLabeling', bool(draw_labels))
        try:
            self._settings.setTransformContext(QgsProject.instance().transformContext())
        except AttributeError:
            pass

    def _set_flag(self, name, value):
        flag = getattr(QgsMapSettings, name, None)
        if flag is not None:
            self._settings.setFlag(flag, value)

    def total(self):
        return count_tiles(self.extent, self.zoom_min, self.zoom_max)

    def render_tile(self, zoom, x, y):
        self._settings.setExtent(tile_extent(zoom, x, y))
        job = QgsMapRendererParallelJob(self._settings)
        job.start()
        job.waitForFinished()
        return job.renderedImage()

    def _encode(self, image):
        img = image.convertToFormat(QImage.Format_ARGB32)
        if self.skip_blank and not qimage_to_array(img)[:, :, 3].any():
            return None
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        if self.fmt == 'JPG':
            img.save(buf, 'JPG', self.quality)
        else:
            img.save(buf, 'PNG')
        data = bytes(buf.data())
        buf.close()
        return data

    def run(self, progress=None):
        """Chạy toàn bộ. `progress(done, total)` trả về False để hủy giữa chừng.

        Trả về dict tóm tắt; khóa 'cancelled' cho biết có bị hủy hay không.
        """
        total = self.total()
        done = 0
        cancelled = False
        for zoom in range(self.zoom_min, self.zoom_max + 1):
            x0, y0, x1, y1 = tile_range(self.extent, zoom)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    data = self._encode(self.render_tile(zoom, x, y))
                    if data is None:
                        self.skipped += 1
                    else:
                        self.writer.write(zoom, x, y, data)
                        self.written += 1
                    done += 1
                    if progress is not None and not progress(done, total):
                        cancelled = True
                        break
                if cancelled:
                    break
            if cancelled:
                break
        return {'total': total, 'done': done, 'written': self.written,
                'skipped': self.skipped, 'cancelled': cancelled}
