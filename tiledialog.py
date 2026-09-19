# -*- coding: utf-8 -*-
"""Hộp thoại xuất bộ tile XYZ / TMS / MBTiles."""

import os
import shutil
import tempfile

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressDialog, QPushButton, QSpinBox, QVBoxLayout,
)
from qgis.core import Qgis, QgsProject, QgsRasterLayer, QgsRectangle

from . import tiles as T
from .exporter import export_geotiff
from .resources import plugin_icon

SOURCES = [
    ("Chỉ ảnh đang căn", T.SRC_IMAGE),
    ("Ảnh đang căn + các lớp đang hiện", T.SRC_IMAGE_LAYERS),
    ("Chỉ các lớp đang hiện trên bản đồ", T.SRC_LAYERS),
]
EXTENTS = [
    ("Theo phạm vi ảnh", 'image'),
    ("Theo khung nhìn hiện tại", 'canvas'),
    ("Toàn bộ các lớp trên bản đồ", 'full'),
]
OUTPUTS = [
    ("Thư mục z/x/y", T.OUT_DIR),
    ("File ZIP", T.OUT_ZIP),
    ("File MBTiles", T.OUT_MBTILES),
]
WARN_TILE_COUNT = 60000


class TileExportDialog(QDialog):
    def __init__(self, iface, item, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.item = item
        self._temp_dir = None
        self._temp_layer = None
        self.show_progress = True     # tắt khi chạy tự động / kiểm thử

        self.setWindowTitle("Xuất bộ tile (XYZ / MBTiles)")
        self.setWindowIcon(plugin_icon())
        self.setMinimumWidth(520)
        self._build_ui()
        self._connect()
        self._apply_defaults()

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        g_src = QGroupBox("Nguồn & phạm vi")
        f_src = QFormLayout(g_src)
        self.cmb_source = QComboBox()
        for label, _ in SOURCES:
            self.cmb_source.addItem(label)
        self.cmb_extent = QComboBox()
        for label, _ in EXTENTS:
            self.cmb_extent.addItem(label)
        f_src.addRow("Nội dung vẽ vào tile:", self.cmb_source)
        f_src.addRow("Phạm vi:", self.cmb_extent)
        self.lbl_extent = QLabel("—")
        self.lbl_extent.setStyleSheet("color:#666;")
        self.lbl_extent.setWordWrap(True)
        f_src.addRow("Khu vực:", self.lbl_extent)
        root.addWidget(g_src)

        g_tile = QGroupBox("Thông số tile")
        f_tile = QFormLayout(g_tile)
        row_z = QHBoxLayout()
        self.sp_zmin = QSpinBox(); self.sp_zmin.setRange(0, T.MAX_ZOOM)
        self.sp_zmax = QSpinBox(); self.sp_zmax.setRange(0, T.MAX_ZOOM)
        row_z.addWidget(QLabel("từ")); row_z.addWidget(self.sp_zmin)
        row_z.addWidget(QLabel("đến")); row_z.addWidget(self.sp_zmax)
        row_z.addStretch(1)
        f_tile.addRow("Mức zoom:", row_z)

        self.cmb_size = QComboBox()
        for s in T.TILE_SIZES:
            self.cmb_size.addItem("%d × %d px" % (s, s), s)
        f_tile.addRow("Kích thước ô:", self.cmb_size)

        row_fmt = QHBoxLayout()
        self.cmb_format = QComboBox()
        self.cmb_format.addItems(T.FORMATS)
        self.sp_quality = QSpinBox(); self.sp_quality.setRange(10, 100)
        self.sp_quality.setValue(85); self.sp_quality.setEnabled(False)
        row_fmt.addWidget(self.cmb_format)
        row_fmt.addWidget(QLabel("chất lượng JPG:"))
        row_fmt.addWidget(self.sp_quality)
        row_fmt.addStretch(1)
        f_tile.addRow("Định dạng:", row_fmt)

        self.lbl_count = QLabel("—")
        self.lbl_count.setStyleSheet("font-weight:bold;")
        f_tile.addRow("Số ô sẽ tạo:", self.lbl_count)
        root.addWidget(g_tile)

        g_out = QGroupBox("Đầu ra")
        v_out = QVBoxLayout(g_out)
        f_out = QFormLayout()
        self.cmb_output = QComboBox()
        for label, _ in OUTPUTS:
            self.cmb_output.addItem(label)
        f_out.addRow("Kiểu:", self.cmb_output)
        row_path = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.btn_path = QPushButton("…"); self.btn_path.setFixedWidth(30)
        row_path.addWidget(self.ed_path, 1)
        row_path.addWidget(self.btn_path)
        f_out.addRow("Đường dẫn:", row_path)
        self.ed_name = QLineEdit("tiles")
        f_out.addRow("Tên bộ tile:", self.ed_name)
        v_out.addLayout(f_out)

        self.cb_tms = QCheckBox("Dùng sơ đồ TMS (lật trục Y)")
        self.cb_skip = QCheckBox("Bỏ qua ô trống hoàn toàn")
        self.cb_skip.setChecked(True)
        self.cb_labels = QCheckBox("Vẽ nhãn của các lớp")
        self.cb_labels.setChecked(True)
        self.cb_viewer = QCheckBox("Tạo trang xem thử Leaflet (viewer.html)")
        self.cb_viewer.setChecked(True)
        for cb in (self.cb_tms, self.cb_skip, self.cb_labels, self.cb_viewer):
            v_out.addWidget(cb)
        root.addWidget(g_out)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Xuất tile")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Đóng")
        root.addWidget(self.buttons)

    def _connect(self):
        self.buttons.accepted.connect(self.run_export)
        self.buttons.rejected.connect(self.reject)
        self.btn_path.clicked.connect(self._browse)
        self.cmb_format.currentTextChanged.connect(
            lambda t: self.sp_quality.setEnabled(t.upper() == 'JPG'))
        self.cmb_output.currentIndexChanged.connect(self._on_output_changed)
        self.cmb_source.currentIndexChanged.connect(self._refresh_estimate)
        self.cmb_extent.currentIndexChanged.connect(self._refresh_estimate)
        self.cmb_size.currentIndexChanged.connect(self._refresh_estimate)
        self.sp_zmin.valueChanged.connect(self._refresh_estimate)
        self.sp_zmax.valueChanged.connect(self._refresh_estimate)

    # -------------------------------------------------------------- mặc định
    def _apply_defaults(self):
        has_image = self.item is not None and self.item.has_image()
        if not has_image:
            self.cmb_source.setCurrentIndex(2)          # chỉ các lớp
            for i in (0, 1):
                self.cmb_source.model().item(i).setEnabled(False)
            self.cmb_extent.setCurrentIndex(1)          # theo khung nhìn
            self.cmb_extent.model().item(0).setEnabled(False)

        extent = self._extent_3857()
        pixel = self._source_pixel_size_3857(extent)
        z_min, z_max = T.suggest_zooms(extent, pixel, self.tile_size())
        self.sp_zmin.setValue(z_min)
        self.sp_zmax.setValue(z_max)
        self.ed_name.setText(self._default_name())
        self._on_output_changed()
        self._refresh_estimate()

    def _default_name(self):
        path = getattr(self.item, 'source_path', None)
        proj = QgsProject.instance().baseName()
        return os.path.splitext(os.path.basename(path))[0] if path else (proj or 'tiles')

    # ------------------------------------------------------------ lấy tham số
    def source_mode(self):
        return SOURCES[self.cmb_source.currentIndex()][1]

    def extent_mode(self):
        return EXTENTS[self.cmb_extent.currentIndex()][1]

    def output_mode(self):
        return OUTPUTS[self.cmb_output.currentIndex()][1]

    def tile_size(self):
        return self.cmb_size.currentData() or 256

    def _project_extent(self):
        mode = self.extent_mode()
        if mode == 'image' and self.item is not None and self.item.has_image():
            return self.item.placement.bbox()
        if mode == 'full':
            ext = self.canvas.fullExtent()
            if ext is not None and not ext.isEmpty():
                return ext
        return self.canvas.extent()

    def _map_crs(self):
        crs = self.canvas.mapSettings().destinationCrs()
        return crs if crs.isValid() else QgsProject.instance().crs()

    def _image_crs(self):
        crs = getattr(self.item, 'placement_crs', None)
        return crs if (crs is not None and crs.isValid()) else self._map_crs()

    def _extent_crs(self):
        """Hệ tọa độ của phạm vi trả về bởi `_project_extent()`."""
        if (self.extent_mode() == 'image' and self.item is not None
                and self.item.has_image()):
            return self._image_crs()
        return self._map_crs()

    def _extent_3857(self):
        ext = self._project_extent()
        if ext is None or ext.isEmpty():
            ext = QgsRectangle(-T.ORIGIN, -T.ORIGIN, T.ORIGIN, T.ORIGIN)
            return T.clamp_mercator(ext)
        return T.to_mercator(ext, self._extent_crs())

    def _source_pixel_size_3857(self, extent_3857):
        """Kích thước 1 pixel ảnh quy đổi ra mét ở Web Mercator."""
        if self.item is None or not self.item.has_image():
            return None
        p = self.item.placement
        if p.width <= 0:
            return None
        return max(extent_3857.width() / float(p.width),
                   extent_3857.height() / float(p.height))

    # ------------------------------------------------------------------ UI ph
    def _on_output_changed(self):
        mode = self.output_mode()
        is_mbtiles = mode == T.OUT_MBTILES
        self.cb_tms.setEnabled(not is_mbtiles)
        self.cb_viewer.setEnabled(mode == T.OUT_DIR)
        if is_mbtiles:
            self.cb_tms.setToolTip("MBTiles luôn dùng TMS theo đặc tả.")
        else:
            self.cb_tms.setToolTip("")
        self.ed_path.clear()

    def _browse(self):
        mode = self.output_mode()
        start = self.ed_path.text() or ''
        if mode == T.OUT_DIR:
            path = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa tile", start)
        elif mode == T.OUT_ZIP:
            path, _ = QFileDialog.getSaveFileName(self, "Lưu file ZIP", start, "ZIP (*.zip)")
            if path and not path.lower().endswith('.zip'):
                path += '.zip'
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Lưu file MBTiles", start,
                                                  "MBTiles (*.mbtiles)")
            if path and not path.lower().endswith('.mbtiles'):
                path += '.mbtiles'
        if path:
            self.ed_path.setText(path)

    def _refresh_estimate(self):
        extent = self._extent_3857()
        self.lbl_extent.setText(
            "X %.1f … %.1f · Y %.1f … %.1f (EPSG:3857)"
            % (extent.xMinimum(), extent.xMaximum(),
               extent.yMinimum(), extent.yMaximum()))
        if self.sp_zmax.value() < self.sp_zmin.value():
            self.lbl_count.setText("Zoom lớn nhất phải ≥ zoom nhỏ nhất")
            return
        n = T.count_tiles(extent, self.sp_zmin.value(), self.sp_zmax.value())
        text = "{:,}".format(n).replace(',', '.')
        if n > WARN_TILE_COUNT:
            self.lbl_count.setText("%s ô — rất nhiều, cân nhắc giảm zoom!" % text)
            self.lbl_count.setStyleSheet("font-weight:bold; color:#c00;")
        else:
            self.lbl_count.setText("%s ô" % text)
            self.lbl_count.setStyleSheet("font-weight:bold;")

    # ------------------------------------------------------------ các lớp vẽ
    def _build_layers(self):
        """Danh sách lớp truyền cho bộ vẽ; phần tử đầu nằm trên cùng."""
        mode = self.source_mode()
        layers = []
        if mode in (T.SRC_IMAGE, T.SRC_IMAGE_LAYERS):
            layers.append(self._bake_image_layer())
        if mode in (T.SRC_LAYERS, T.SRC_IMAGE_LAYERS):
            layers.extend(self.canvas.layers())
        return layers

    def _bake_image_layer(self):
        """Ghi ảnh đã căn ra GeoTIFF tạm rồi nạp thành lớp raster để vẽ."""
        self._temp_dir = tempfile.mkdtemp(prefix='riet_tiles_')
        path = os.path.join(self._temp_dir, 'aligned.tif')
        export_geotiff(self.item.image, self.item.placement,
                       self._image_crs(), path,
                       compression='DEFLATE', north_up=False,
                       keep_alpha=True, build_overviews=True, world_file=False)
        layer = QgsRasterLayer(path, 'aligned_image')
        if not layer.isValid():
            raise RuntimeError("Không tạo được lớp raster tạm từ ảnh đã căn.")
        self._temp_layer = layer          # giữ tham chiếu để không bị thu hồi
        return layer

    def _cleanup_temp(self):
        self._temp_layer = None
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = None

    # -------------------------------------------------------------- chạy xuất
    def validate(self):
        """Trả về (path, extent, total) hoặc None kèm thông báo lỗi cho người dùng."""
        path = self.ed_path.text().strip('"').strip()
        if not path:
            QMessageBox.warning(self, "Thiếu đường dẫn", "Hãy chọn nơi lưu bộ tile.")
            return None
        if self.sp_zmax.value() < self.sp_zmin.value():
            QMessageBox.warning(self, "Sai mức zoom",
                                "Zoom lớn nhất phải lớn hơn hoặc bằng zoom nhỏ nhất.")
            return None
        extent = self._extent_3857()
        total = T.count_tiles(extent, self.sp_zmin.value(), self.sp_zmax.value())
        if total <= 0:
            QMessageBox.warning(self, "Không có ô nào",
                                "Phạm vi đã chọn không giao với lưới tile.")
            return None
        if total > WARN_TILE_COUNT:
            answer = QMessageBox.question(
                self, "Số ô rất lớn",
                "Sẽ tạo khoảng %d ô, có thể mất rất nhiều thời gian và dung "
                "lượng.\nVẫn tiếp tục?" % total,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return None
        return path, extent, total

    def build_metadata(self, tms):
        wgs = T.to_wgs84(self._project_extent(), self._extent_crs())
        fmt = self.cmb_format.currentText()
        return {
            'name': self.ed_name.text().strip() or 'tiles',
            'description': 'Xuất từ QGIS bằng Raster Image Editor Tiff',
            'minzoom': self.sp_zmin.value(),
            'maxzoom': self.sp_zmax.value(),
            'bounds': [wgs.xMinimum(), wgs.yMinimum(),
                       wgs.xMaximum(), wgs.yMaximum()],
            'scheme': 'tms' if (tms or self.output_mode() == T.OUT_MBTILES) else 'xyz',
            'format': 'png' if fmt.upper() == 'PNG' else 'jpg',
            'tilesize': self.tile_size(),
        }

    def export_tiles(self, path, extent, progress_cb=None):
        """Phần việc thật sự — tách khỏi giao diện để gọi lại/kiểm thử được.

        `progress_cb(done, total)` trả về False để dừng giữa chừng.
        """
        fmt = self.cmb_format.currentText()
        out_mode = self.output_mode()
        tms = self.cb_tms.isChecked() and out_mode != T.OUT_MBTILES
        writer = None
        try:
            layers = self._build_layers()
            if not layers:
                raise RuntimeError("Không có lớp nào để vẽ vào tile.")
            if out_mode == T.OUT_DIR:
                writer = T.DirectoryTileWriter(path, fmt, tms)
            elif out_mode == T.OUT_ZIP:
                writer = T.ZipTileWriter(path, fmt, tms)
            else:
                writer = T.MBTilesWriter(path, fmt)

            exporter = T.TileExporter(
                layers, extent, self.sp_zmin.value(), self.sp_zmax.value(), writer,
                tile_size=self.tile_size(), fmt=fmt, quality=self.sp_quality.value(),
                draw_labels=self.cb_labels.isChecked(),
                skip_blank=self.cb_skip.isChecked())
            result = exporter.run(progress_cb)

            meta = self.build_metadata(tms)
            writer.finish(meta)
            writer.close()
            writer = None
            if out_mode == T.OUT_DIR and self.cb_viewer.isChecked():
                T.write_leaflet_viewer(path, meta, meta['format'], tms)
            result['meta'] = meta
            return result
        finally:
            if writer is not None:
                writer.close()
            self._cleanup_temp()

    def run_export(self):
        checked = self.validate()
        if checked is None:
            return
        path, extent, total = checked

        progress = None
        callback = None
        if self.show_progress:

            progress = QProgressDialog("Đang kết xuất tile…", "Hủy", 0, total, self)
            progress.setWindowTitle("Xuất bộ tile")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(500)

            def report(done, all_):
                progress.setValue(done)
                progress.setLabelText("Đang kết xuất tile… %d / %d" % (done, all_))
                QApplication.processEvents()
                return not progress.wasCanceled()

            callback = report

        try:
            result = self.export_tiles(path, extent, callback)
        except Exception as exc:
            if progress is not None:
                progress.close()
            QMessageBox.critical(self, "Lỗi khi xuất tile", str(exc))
            return
        if progress is not None:
            progress.close()

        if result['cancelled']:
            self.iface.messageBar().pushMessage(
                "Raster Image Editor Tiff",
                "Đã hủy giữa chừng — ghi được %d ô vào %s"
                % (result['written'], path), level=Qgis.Warning, duration=8)
        else:
            self.iface.messageBar().pushMessage(
                "Raster Image Editor Tiff",
                "Đã xuất %d ô (bỏ qua %d ô trống) vào %s"
                % (result['written'], result['skipped'], path),
                level=Qgis.Success, duration=8)
        self.accept()

    def reject(self):
        self._cleanup_temp()
        super().reject()
