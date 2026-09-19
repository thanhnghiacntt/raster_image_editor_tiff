# -*- coding: utf-8 -*-
"""Đọc ảnh đã có tọa độ (GeoTIFF, ảnh kèm world file, GCP…) và đặt đúng vị trí.

Luồng xử lý:
  1. `read_raster()`  — đọc điểm ảnh (Qt hoặc GDAL) + GeoTransform + CRS của file.
  2. `normalize_orientation()` — lật ảnh nếu GeoTransform bị lật (trục Y hướng lên).
  3. `fit_placement()` — đưa GeoTransform về mô hình `Placement` trong CRS của
     khung bản đồ và đo sai lệch (đơn vị: pixel ảnh).
  4. Sai lệch lớn (khác CRS trên vùng rộng, ảnh bị xiên) thì `warp_to_crs()`
     chiếu lại ảnh cho chính xác.
"""

import math
import os

import numpy as np
from osgeo import gdal
from qgis.PyQt.QtGui import QImage
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsPointXY, QgsProject)

from .exporter import crs_to_wkt, qimage_to_array
from .placement import Placement

gdal.UseExceptions()

MAX_SIDE = 8000              # cạnh dài nhất khi nạp để chỉnh; lớn hơn sẽ đọc thu nhỏ
GEOREF_TOLERANCE_PX = 0.5    # sai lệch dưới mức này coi như đặt chính xác
GDAL_FIRST_EXT = ('.tif', '.tiff', '.gtif', '.jp2', '.img', '.vrt', '.ecw', '.sid')


class RasterSource(object):
    """Kết quả đọc một file ảnh."""

    def __init__(self):
        self.image = None           # QImage 8 bit RGBA
        self.geotransform = None    # tuple 6 số, theo kích thước `image`
        self.crs = None             # QgsCoordinateReferenceSystem hoặc None
        self.georef_kind = None     # 'geotransform' | 'gcps' | None
        self.scale = 1.0            # > 1 khi phải đọc thu nhỏ
        self.full_size = None       # (rộng, cao) gốc của file
        self.notes = []

    @property
    def is_georeferenced(self):
        return self.geotransform is not None


# --------------------------------------------------------------------- đọc file
def _open_dataset(path):
    try:
        return gdal.Open(path, gdal.GA_ReadOnly)
    except RuntimeError:
        return None


def _is_default_geotransform(gt):
    return (abs(gt[0]) < 1e-12 and abs(gt[1] - 1.0) < 1e-12 and abs(gt[2]) < 1e-12
            and abs(gt[3]) < 1e-12 and abs(gt[4]) < 1e-12
            and abs(abs(gt[5]) - 1.0) < 1e-12)


def read_georef(ds):
    """(geotransform, crs, kiểu) của dataset GDAL; (None, None, None) nếu không có."""
    gt = None
    kind = None
    wkt = ''
    try:
        gt = ds.GetGeoTransform(can_return_null=True)
    except (RuntimeError, TypeError):
        gt = None
    if gt is not None:
        kind = 'geotransform'
        wkt = ds.GetProjection() or ''
    elif ds.GetGCPCount() >= 3:
        try:
            gt = gdal.GCPsToGeoTransform(ds.GetGCPs())
        except RuntimeError:
            gt = None
        if gt:
            kind = 'gcps'
            wkt = ds.GetGCPProjection() or ''
        else:
            gt = None

    if gt is not None and _is_default_geotransform(gt) and not wkt:
        return None, None, None
    if gt is not None:
        a, b, d, e = gt[1], gt[2], gt[4], gt[5]
        if abs(a * e - b * d) < 1e-30:
            return None, None, None

    crs = None
    if wkt:
        crs = QgsCoordinateReferenceSystem.fromWkt(wkt)
        if not crs.isValid():
            crs = None
    return (tuple(float(v) for v in gt) if gt is not None else None), crs, kind


def array_to_qimage(rgba):
    """Mảng numpy (cao, rộng, 4) uint8 R,G,B,A -> QImage độc lập với mảng."""
    buf = np.ascontiguousarray(rgba, dtype=np.uint8)
    h, w = buf.shape[0], buf.shape[1]
    data = buf.tobytes()
    img = QImage(data, w, h, 4 * w, QImage.Format_RGBA8888)
    return img.copy()


def _stretch_params(arrays, nodatas):
    """Ngưỡng co giãn 2%–98% chung cho các băng (giữ cân bằng màu)."""
    samples = []
    for arr, nodata in zip(arrays, nodatas):
        valid = np.isfinite(arr)
        if nodata is not None:
            valid &= arr != nodata
        vals = arr[valid]
        if vals.size:
            step = max(1, vals.size // 200000)
            samples.append(vals[::step].astype(np.float64))
    if not samples:
        return 0.0, 1.0
    allv = np.concatenate(samples)
    lo, hi = np.percentile(allv, (2.0, 98.0))
    if hi <= lo:
        lo, hi = float(allv.min()), float(allv.max())
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def _to_byte(arr, lo, hi):
    if arr.dtype == np.uint8:
        return arr
    out = (arr.astype(np.float64) - lo) * (255.0 / (hi - lo))
    out = np.nan_to_num(out, nan=0.0, posinf=255.0, neginf=0.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def gdal_dataset_to_qimage(ds, max_side=MAX_SIDE):
    """Đọc dataset GDAL bất kỳ thành QImage RGBA 8 bit. Trả về (QImage, hệ số thu nhỏ)."""
    width, height = ds.RasterXSize, ds.RasterYSize
    count = ds.RasterCount
    if count == 0 or width == 0 or height == 0:
        raise RuntimeError("File không có dữ liệu ảnh.")

    scale = max(1.0, max(width, height) / float(max_side))
    bw = max(1, int(round(width / scale)))
    bh = max(1, int(round(height / scale)))

    bands = [ds.GetRasterBand(i) for i in range(1, count + 1)]
    interp = {}
    for idx, band in enumerate(bands):
        interp.setdefault(band.GetColorInterpretation(), idx)
    alpha_idx = interp.get(gdal.GCI_AlphaBand)
    color_idx = [i for i in range(count) if i != alpha_idx]
    palette = bands[0].GetColorTable() if len(color_idx) == 1 else None

    def read(band, nearest=False):
        alg = (gdal.GRIORA_NearestNeighbour if (nearest or scale <= 1.0)
               else gdal.GRIORA_Average)
        return band.ReadAsArray(0, 0, width, height, buf_xsize=bw, buf_ysize=bh,
                                resample_alg=alg)

    rgba = np.zeros((bh, bw, 4), dtype=np.uint8)
    rgba[..., 3] = 255

    if palette is not None:
        idx_arr = read(bands[color_idx[0]], nearest=True)
        lut = np.zeros((max(256, palette.GetCount()), 4), dtype=np.uint8)
        for i in range(palette.GetCount()):
            entry = palette.GetColorEntry(i)
            lut[i] = (entry[0], entry[1], entry[2],
                      entry[3] if len(entry) > 3 else 255)
        rgba[:] = lut[np.clip(idx_arr, 0, lut.shape[0] - 1).astype(np.intp)]
    elif len(color_idx) >= 3:
        order = [interp.get(gdal.GCI_RedBand), interp.get(gdal.GCI_GreenBand),
                 interp.get(gdal.GCI_BlueBand)]
        if None in order or alpha_idx in order:
            order = color_idx[:3]
        arrays = [read(bands[i]) for i in order]
        nodatas = [bands[i].GetNoDataValue() for i in order]
        lo, hi = _stretch_params(arrays, nodatas)
        for k, arr in enumerate(arrays):
            rgba[..., k] = _to_byte(arr, lo, hi)
    else:
        i = color_idx[0] if color_idx else 0
        arr = read(bands[i])
        lo, hi = _stretch_params([arr], [bands[i].GetNoDataValue()])
        gray = _to_byte(arr, lo, hi)
        rgba[..., 0] = gray
        rgba[..., 1] = gray
        rgba[..., 2] = gray

    if alpha_idx is not None:
        a = read(bands[alpha_idx])
        rgba[..., 3] = a if a.dtype == np.uint8 else np.clip(a, 0, 255).astype(np.uint8)
    else:
        flags = bands[color_idx[0] if color_idx else 0].GetMaskFlags()
        if flags != gdal.GMF_ALL_VALID and not (flags & gdal.GMF_ALPHA):
            mask_band = bands[color_idx[0] if color_idx else 0].GetMaskBand()
            mask = read(mask_band, nearest=True)
            rgba[..., 3] = np.where(mask > 0, rgba[..., 3], 0).astype(np.uint8)

    return array_to_qimage(rgba), scale


def read_raster(path, max_side=MAX_SIDE):
    """Đọc file ảnh: điểm ảnh + thông tin tọa độ nếu có."""
    src = RasterSource()
    ext = os.path.splitext(path)[1].lower()
    ds = _open_dataset(path)

    image = None
    if ext not in GDAL_FIRST_EXT:
        image = QImage(path)
        if image.isNull():
            image = None
    if image is None:
        if ds is None:
            raise RuntimeError("Không đọc được ảnh (định dạng không hỗ trợ?).")
        image, scale = gdal_dataset_to_qimage(ds, max_side)
        src.scale = scale
        if scale > 1.0:
            src.notes.append(
                "Ảnh gốc %d × %d pixel quá lớn, đã nạp ở kích thước %d × %d "
                "(1/%.1f) để chỉnh cho mượt; file xuất ra sẽ theo kích thước này."
                % (ds.RasterXSize, ds.RasterYSize, image.width(), image.height(),
                   scale))
    src.image = image

    if ds is not None:
        src.full_size = (ds.RasterXSize, ds.RasterYSize)
        gt, crs, kind = read_georef(ds)
        if gt is not None:
            # Quy GeoTransform về đúng kích thước ảnh đã nạp.
            fx = ds.RasterXSize / float(image.width())
            fy = ds.RasterYSize / float(image.height())
            gt = (gt[0], gt[1] * fx, gt[2] * fy, gt[3], gt[4] * fx, gt[5] * fy)
        src.geotransform, src.crs, src.georef_kind = gt, crs, kind
        ds = None
    return src


# ---------------------------------------------------------------- hình học
def normalize_orientation(image, gt):
    """Lật ảnh theo chiều dọc nếu GeoTransform bị lật (định thức dương).

    Trả về (image, geotransform, đã_lật). Sau bước này ảnh luôn theo quy ước
    hàng đầu tiên ở phía "trên" nên biểu diễn được bằng `Placement`.
    """
    det = gt[1] * gt[5] - gt[2] * gt[4]
    if det <= 0:
        return image, gt, False
    h = image.height()
    flipped = image.mirrored(False, True)
    new_gt = (gt[0] + gt[2] * h, gt[1], -gt[2], gt[3] + gt[5] * h, gt[4], -gt[5])
    return flipped, new_gt, True


def placement_from_geotransform(gt, width, height):
    """GeoTransform 6 số -> Placement (tâm, cỡ pixel X/Y, góc xoay).

    Nếu GeoTransform có độ xiên (hai trục không vuông góc) thì phần xiên bị bỏ
    qua; dùng `fit_placement()` để biết sai lệch.
    """
    x0, a, b, y0, d, e = gt
    sx = math.hypot(a, d)
    if sx <= 0:
        raise ValueError("GeoTransform không hợp lệ (kích thước pixel bằng 0).")
    c, s = a / sx, d / sx
    sy = b * s - e * c
    if sy <= 0:
        raise ValueError("GeoTransform bị lật, cần gọi normalize_orientation() trước.")
    rotation = math.degrees(math.atan2(d, a))
    cx = x0 + (width / 2.0) * a + (height / 2.0) * b
    cy = y0 + (width / 2.0) * d + (height / 2.0) * e
    return Placement(cx, cy, sx, sy, rotation, width, height)


def _make_transform(src_crs, dst_crs):
    if (src_crs is None or dst_crs is None or not src_crs.isValid()
            or not dst_crs.isValid() or src_crs == dst_crs):
        return None
    return QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())


def fit_placement(gt, width, height, src_crs, dst_crs, samples=5):
    """Đặt ảnh (GeoTransform trong `src_crs`) vào `dst_crs`.

    Lấy lưới điểm trên ảnh, chiếu sang `dst_crs`, khớp bình phương tối thiểu
    một phép affine rồi quy về `Placement`. Trả về (placement, sai_lệch_px) với
    sai lệch là khoảng cách lớn nhất giữa vị trí theo `Placement` và vị trí
    thật, tính bằng số pixel ảnh.
    """
    xform = _make_transform(src_crs, dst_crs)
    pts = []
    truth = []
    for i in range(samples):
        for j in range(samples):
            px = width * i / float(samples - 1)
            py = height * j / float(samples - 1)
            x = gt[0] + px * gt[1] + py * gt[2]
            y = gt[3] + px * gt[4] + py * gt[5]
            if xform is not None:
                q = xform.transform(QgsPointXY(x, y))
                x, y = q.x(), q.y()
            pts.append((px, py))
            truth.append((x, y))

    if xform is None:
        # Cùng hệ tọa độ: dùng nguyên GeoTransform, khỏi sai số làm tròn.
        fit_gt = tuple(gt)
    else:
        # Dời gốc về trọng tâm trước khi khớp: tọa độ cỡ hàng triệu mét làm
        # bình phương tối thiểu mất độ chính xác, sinh ra góc xoay giả.
        P = np.array(pts, dtype=np.float64)
        T_ = np.array(truth, dtype=np.float64)
        pm, tm = P.mean(axis=0), T_.mean(axis=0)
        A = np.column_stack([np.ones(len(P)), P[:, 0] - pm[0], P[:, 1] - pm[1]])
        (cx_, a, b), _, _, _ = np.linalg.lstsq(A, T_[:, 0] - tm[0], rcond=None)
        (cy_, d, e), _, _, _ = np.linalg.lstsq(A, T_[:, 1] - tm[1], rcond=None)
        x0 = tm[0] + cx_ - a * pm[0] - b * pm[1]
        y0 = tm[1] + cy_ - d * pm[0] - e * pm[1]
        fit_gt = (x0, a, b, y0, d, e)
    placement = placement_from_geotransform(fit_gt, width, height)

    worst = 0.0
    for (px, py), (tx, ty) in zip(pts, truth):
        q = placement.pixel_to_map(px, py)
        worst = max(worst, math.hypot(q.x() - tx, q.y() - ty))
    pixel = (placement.sx + placement.sy) / 2.0
    return placement, (worst / pixel if pixel > 0 else float('inf'))


def placement_to_crs(placement, src_crs, dst_crs):
    """Chuyển một Placement sang CRS khác (dùng khi dự án đổi hệ tọa độ)."""
    return fit_placement(placement.geotransform(), placement.width,
                         placement.height, src_crs, dst_crs)


def warp_to_crs(image, gt, src_crs, dst_crs, resample='bilinear', max_side=MAX_SIDE):
    """Chiếu lại ảnh sang `dst_crs` (hoặc nắn thẳng trong cùng CRS).

    Trả về (QImage, geotransform thẳng hướng Bắc trong `dst_crs`).
    """
    arr = qimage_to_array(image)
    h, w = arr.shape[0], arr.shape[1]
    src_wkt = crs_to_wkt(src_crs)
    dst_wkt = crs_to_wkt(dst_crs) if dst_crs is not None else src_wkt

    mem = gdal.GetDriverByName('MEM').Create('', w, h, 4, gdal.GDT_Byte)
    mem.SetGeoTransform([float(v) for v in gt])
    if src_wkt:
        mem.SetProjection(src_wkt)
    interps = [gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand,
               gdal.GCI_AlphaBand]
    for i in range(4):
        band = mem.GetRasterBand(i + 1)
        band.WriteArray(arr[:, :, i])
        band.SetColorInterpretation(interps[i])

    common = dict(srcSRS=src_wkt or None, dstSRS=dst_wkt or None,
                  resampleAlg=resample, dstAlpha=True, multithread=True)
    # Xem trước kích thước đầu ra (VRT không tốn bộ nhớ) để khỏi phình quá lớn.
    probe = gdal.Warp('', mem, format='VRT', **common)
    ow, oh = probe.RasterXSize, probe.RasterYSize
    probe = None
    size_opts = {}
    if max(ow, oh) > max_side:
        k = max_side / float(max(ow, oh))
        size_opts = dict(width=max(1, int(round(ow * k))),
                         height=max(1, int(round(oh * k))))

    out = gdal.Warp('', mem, format='MEM', **dict(common, **size_opts))
    if out is None:
        raise RuntimeError("GDAL không chiếu lại được ảnh.")
    rgba = np.dstack([out.GetRasterBand(i + 1).ReadAsArray() for i in range(4)])
    new_gt = tuple(float(v) for v in out.GetGeoTransform())
    out = None
    mem = None
    return array_to_qimage(rgba), new_gt
