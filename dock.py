# -*- coding: utf-8 -*-
"""Bảng điều khiển (dock) của plugin Raster Image Editor Tiff."""

import os
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
    QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget,
)
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsProjectionSelectionWidget

try:                                     # Qt5
    from qgis.PyQt.QtWidgets import QShortcut
except ImportError:                      # Qt6
    from qgis.PyQt.QtGui import QShortcut

from . import georef
from .exporter import COMPRESSIONS, RESAMPLE_ALGS, export_geotiff
from .maptool import TP_DONE, TP_MESSAGES, AlignImageMapTool
from .mosaic import export_mosaic
from .overlay import FrameOverlayItem, ImageOverlayItem
from .placement import Placement
from .resources import plugin_icon

IMAGE_FILTER = ("Ảnh & raster (*.png *.jpg *.jpeg *.tif *.tiff *.gtif *.jp2 *.bmp "
                "*.gif *.webp *.img *.vrt);;"
                "GeoTIFF (*.tif *.tiff *.gtif);;"
                "Tất cả các file (*.*)")
QUICK_CRS = ('EPSG:4326', 'EPSG:3857')


MAX_UNDO = 60

EXPORT_ACTIVE = 'active'
EXPORT_MOSAIC = 'mosaic'
EXPORT_EACH = 'each'
EXPORT_MODES = [
    (EXPORT_ACTIVE, "Chỉ ảnh đang chọn"),
    (EXPORT_MOSAIC, "Ghép các ảnh đang hiện thành 1 file"),
    (EXPORT_EACH, "Mỗi ảnh đang hiện ra 1 file riêng"),
]


def crs_name(crs):
    if crs is None or not crs.isValid():
        return "không xác định"
    return crs.authid() or crs.description() or "hệ tự định nghĩa"


def safe_stem(name):
    """Tên file an toàn trên Windows từ tên ảnh."""
    stem = os.path.splitext(name)[0]
    stem = re.sub(r'[\\/:*?"<>|]+', '_', stem).strip(' .')
    return stem or 'anh'


class ImageLayer(object):
    """Một ảnh trong danh sách: item vẽ trên bản đồ + lịch sử hoàn tác riêng."""

    def __init__(self, item, path, number):
        self.item = item
        self.path = path
        self.number = number                 # số thứ tự theo lúc nạp: 1, 2, 3…
        self.name = os.path.basename(path) if path else 'ảnh %d' % number
        self.undo = []
        self.redo = []
        self.aspect = 1.0
        self.file_crs = None                 # hệ tọa độ gốc trong file (nếu có)
        self.info = ''
        short = self.name if len(self.name) <= 28 else self.name[:12] + '…' + self.name[-12:]
        item.label = '%d. %s' % (number, short)


class RasterImageEditorTiffDock(QDockWidget):
    """Nạp ảnh, chỉnh vị trí và xuất GeoTIFF."""

    def __init__(self, iface, parent=None):
        super().__init__("Raster Image Editor Tiff", parent)
        self.setObjectName("RasterImageEditorTiffDock")
        self.setWindowIcon(plugin_icon())
        self.iface = iface
        self.canvas = iface.mapCanvas()

        # Danh sách ảnh; phần tử đầu tiên nằm TRÊN CÙNG khi các ảnh chồng nhau.
        self.layers = []
        self.active = None
        self._counter = 0
        # Item rỗng dùng khi chưa có ảnh nào, để mọi chỗ gọi self.item vẫn an toàn.
        self._empty_item = ImageOverlayItem(self.canvas)
        self._empty_item.set_show_handles(False)
        self._empty_item.placement_crs = self._map_crs()
        self._empty_undo, self._empty_redo, self._empty_aspect = [], [], 1.0
        self.frame = FrameOverlayItem(self.canvas, self._frame_entries)
        self.tool = AlignImageMapTool(self.canvas, self._empty_item)
        self.tool.find_item_at = self._item_at

        self._syncing = False
        self._list_updating = False
        self._image_path = None
        self._loading = False          # đang nạp ảnh
        self._northup_user = False     # lựa chọn "nắn thẳng" của người dùng
        self._auto_output = True       # đường dẫn đầu ra do plugin tự điền
        self._mode_user_set = False    # người dùng đã tự chọn kiểu xuất
        # Có thể thay khi chạy tự động/kiểm thử để khỏi bật hộp thoại hỏi.
        self.ask_georef_choice = self._ask_georef_choice

        self._build_ui()
        self._connect()
        self._build_shortcuts()
        self.last_export = []           # danh sách file vừa xuất
        self.crs_out.setCrs(self._map_crs())
        self._refresh_crs_label()
        self._on_export_mode_changed(user=False)
        self._update_enabled()

    # ---------------------------------------------------- ảnh đang được chọn
    @property
    def item(self):
        return self.active.item if self.active is not None else self._empty_item

    @property
    def _undo(self):
        return self.active.undo if self.active is not None else self._empty_undo

    @_undo.setter
    def _undo(self, value):
        if self.active is not None:
            self.active.undo = value
        else:
            self._empty_undo = value

    @property
    def _redo(self):
        return self.active.redo if self.active is not None else self._empty_redo

    @_redo.setter
    def _redo(self, value):
        if self.active is not None:
            self.active.redo = value
        else:
            self._empty_redo = value

    @property
    def _aspect(self):
        return self.active.aspect if self.active is not None else self._empty_aspect

    @_aspect.setter
    def _aspect(self, value):
        if self.active is not None:
            self.active.aspect = value
        else:
            self._empty_aspect = value

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- 1. Ảnh nguồn -------------------------------------------------
        g_img = QGroupBox("1. Ảnh nguồn")
        l_img = QVBoxLayout(g_img)
        row = QHBoxLayout()
        self.ed_image = QLineEdit()
        self.ed_image.setPlaceholderText("Chọn file ảnh cần đưa vào bản đồ…")
        self.btn_browse = QPushButton("…")
        self.btn_browse.setFixedWidth(30)
        self.btn_browse.setToolTip("Chọn một hoặc NHIỀU ảnh cùng lúc (giữ Ctrl/Shift)")
        self.btn_load = QPushButton("Thêm ảnh")
        row.addWidget(self.ed_image, 1)
        row.addWidget(self.btn_browse)
        row.addWidget(self.btn_load)
        l_img.addLayout(row)

        self.lst_images = QListWidget()
        self.lst_images.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst_images.setMinimumHeight(84)
        self.lst_images.setMaximumHeight(170)
        self.lst_images.setToolTip(
            "Bấm để chọn ảnh cần chỉnh • ô đánh dấu = hiện/ẩn ảnh • nhấp đúp để "
            "phóng tới ảnh.\nẢnh nằm trên trong danh sách sẽ đè lên ảnh nằm dưới.")
        l_img.addWidget(self.lst_images)

        row_l = QHBoxLayout()
        self.btn_up = QPushButton("▲ Lên")
        self.btn_up.setToolTip("Đưa ảnh lên trên (đè lên ảnh khác)")
        self.btn_down = QPushButton("▼ Xuống")
        self.btn_zoom = QPushButton("Phóng tới")
        self.btn_remove = QPushButton("Gỡ ảnh")
        for b in (self.btn_up, self.btn_down, self.btn_zoom, self.btn_remove):
            row_l.addWidget(b)
        l_img.addLayout(row_l)

        self.lbl_info = QLabel("Chưa nạp ảnh.")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color: #666;")
        l_img.addWidget(self.lbl_info)
        root.addWidget(g_img)

        # --- 2. Chỉnh trên bản đồ ----------------------------------------
        g_edit = QGroupBox("2. Chỉnh trên bản đồ")
        l_edit = QVBoxLayout(g_edit)
        self.btn_edit = QPushButton("Bật chế độ kéo/chỉnh ảnh")
        self.btn_edit.setCheckable(True)
        l_edit.addWidget(self.btn_edit)

        row2 = QHBoxLayout()
        self.btn_two_point = QPushButton("Căn theo 2 điểm")
        self.btn_two_point.setCheckable(True)
        self.btn_fit = QPushButton("Vừa khung nhìn")
        row2.addWidget(self.btn_two_point)
        row2.addWidget(self.btn_fit)
        l_edit.addLayout(row2)

        row2b = QHBoxLayout()
        self.btn_undo = QPushButton("↶ Hoàn tác (Ctrl+Z)")
        self.btn_redo = QPushButton("↷ Làm lại (Ctrl+Y)")
        row2b.addWidget(self.btn_undo)
        row2b.addWidget(self.btn_redo)
        l_edit.addLayout(row2b)

        self.lbl_hint = QLabel(
            "Có nhiều ảnh: bấm vào ảnh nào trên bản đồ thì chỉnh ảnh đó (khung đỏ = "
            "ảnh đang chọn, khung vàng nét đứt = ảnh khác).\n"
            "Kéo giữa ảnh để di chuyển • kéo BẤT KỲ ĐIỂM NÀO TRÊN CẠNH để co "
            "giãn riêng theo X hoặc Y (cạnh sẽ sáng lên khi rê chuột tới) • "
            "kéo ô vuông ở GÓC để co giãn cả hai chiều • kéo nút tròn xanh để xoay.\n"
            "Khi phóng to, tay nắm cạnh tự bám theo phần cạnh còn nhìn thấy.\n"
            "Shift: khóa trục khi di chuyển, đảo khóa tỉ lệ khi kéo góc, "
            "bắt góc 15° khi xoay. Phím mũi tên: dịch từng pixel. "
            "Ctrl+Z / Ctrl+Y: hoàn tác / làm lại. Giữ phím H: tạm giấu ảnh để nhìn nền bên dưới.")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#666; font-size:11px;")
        l_edit.addWidget(self.lbl_hint)
        root.addWidget(g_edit)

        # --- 3. Tọa độ ----------------------------------------------------
        g_geo = QGroupBox("3. Tọa độ & kích thước")
        v_geo = QVBoxLayout(g_geo)
        self.lbl_crs = QLabel("Hệ tọa độ của bản đồ: —")
        self.lbl_crs.setWordWrap(True)
        self.lbl_crs.setStyleSheet("color:#666;")
        v_geo.addWidget(self.lbl_crs)
        grid = QGridLayout()
        v_geo.addLayout(grid)
        grid.setColumnStretch(1, 1)

        self.sp_cx = self._coord_spin()
        self.sp_cy = self._coord_spin()
        self.sp_px = self._size_spin()
        self.sp_py = self._size_spin()
        self.sp_rot = QDoubleSpinBox()
        self.sp_rot.setRange(-360.0, 360.0)
        self.sp_rot.setDecimals(4)
        self.sp_rot.setSingleStep(0.5)
        self.sp_rot.setSuffix(" °")

        grid.addWidget(QLabel("Tâm ảnh X:"), 0, 0)
        grid.addWidget(self.sp_cx, 0, 1)
        grid.addWidget(QLabel("Tâm ảnh Y:"), 1, 0)
        grid.addWidget(self.sp_cy, 1, 1)
        grid.addWidget(QLabel("Kích thước pixel X:"), 2, 0)
        grid.addWidget(self.sp_px, 2, 1)
        grid.addWidget(QLabel("Kích thước pixel Y:"), 3, 0)
        grid.addWidget(self.sp_py, 3, 1)
        grid.addWidget(QLabel("Góc xoay:"), 4, 0)
        grid.addWidget(self.sp_rot, 4, 1)

        self.cb_lock = QCheckBox("Khóa tỉ lệ (áp dụng cho tay nắm góc và ô nhập số)")
        self.cb_lock.setToolTip(
            "Bật: kéo tay nắm ở góc giữ nguyên tỉ lệ khung ảnh, đổi một ô "
            "kích thước pixel sẽ đổi ô kia theo.\n"
            "Tay nắm ở cạnh luôn co giãn riêng theo một trục, không phụ thuộc "
            "tùy chọn này.")
        self.cb_lock.setChecked(True)
        grid.addWidget(self.cb_lock, 5, 0, 1, 2)

        self.lbl_span = QLabel("—")
        self.lbl_span.setStyleSheet("color:#666;")
        grid.addWidget(QLabel("Kích thước thực:"), 6, 0)
        grid.addWidget(self.lbl_span, 6, 1)

        self.cb_show_image = QCheckBox("Hiện ảnh trên bản đồ "
                                       "(bỏ chọn để so với nền — hoặc giữ phím H)")
        self.cb_show_image.setChecked(True)
        self.cb_show_image.setToolTip(
            "Bỏ chọn để tạm giấu ảnh mà vẫn giữ khung viền và tay nắm, "
            "tiện đối chiếu với lớp nền bên dưới.")
        grid.addWidget(self.cb_show_image, 7, 0, 1, 2)

        row3 = QHBoxLayout()
        self.sl_opacity = QSlider(Qt.Horizontal)
        self.sl_opacity.setRange(10, 100)
        self.sl_opacity.setValue(100)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setFixedWidth(38)
        row3.addWidget(self.sl_opacity, 1)
        row3.addWidget(self.lbl_opacity)
        grid.addWidget(QLabel("Độ mờ:"), 8, 0)
        grid.addLayout(row3, 8, 1)
        root.addWidget(g_geo)

        # --- 4. Xuất ------------------------------------------------------
        g_out = QGroupBox("4. Xuất GeoTIFF")
        l_out = QVBoxLayout(g_out)

        l_out.addWidget(QLabel("Hệ tọa độ của file xuất ra:"))
        self.crs_out = QgsProjectionSelectionWidget()
        try:
            self.crs_out.setOptionVisible(QgsProjectionSelectionWidget.ProjectCrs, True)
        except AttributeError:
            pass
        self.crs_out.setToolTip("Chọn chuẩn tọa độ cho GeoTIFF, ví dụ EPSG:4326 (WGS 84 "
                                "kinh/vĩ độ), EPSG:3857 (Web Mercator), VN-2000…")
        l_out.addWidget(self.crs_out)

        row_crs = QHBoxLayout()
        self.btn_crs_map = QPushButton("Theo bản đồ")
        self.btn_crs_map.setToolTip("Dùng đúng hệ tọa độ đang hiển thị bản đồ")
        row_crs.addWidget(self.btn_crs_map)
        self.btn_crs_quick = []
        for code in QUICK_CRS:
            btn = QPushButton(code)
            btn.setToolTip(QgsCoordinateReferenceSystem(code).description())
            row_crs.addWidget(btn)
            self.btn_crs_quick.append((btn, code))
        l_out.addLayout(row_crs)

        self.lbl_crs_note = QLabel("")
        self.lbl_crs_note.setWordWrap(True)
        self.lbl_crs_note.setStyleSheet("color:#666; font-size:11px;")
        l_out.addWidget(self.lbl_crs_note)

        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Xuất:"))
        self.cmb_export_mode = QComboBox()
        for key, label in EXPORT_MODES:
            self.cmb_export_mode.addItem(label, key)
        row_mode.addWidget(self.cmb_export_mode, 1)
        l_out.addLayout(row_mode)
        self.lbl_mode_note = QLabel("")
        self.lbl_mode_note.setWordWrap(True)
        self.lbl_mode_note.setStyleSheet("color:#666; font-size:11px;")
        l_out.addWidget(self.lbl_mode_note)

        row4 = QHBoxLayout()
        self.ed_output = QLineEdit()
        self.ed_output.setPlaceholderText("Đường dẫn file .tif đầu ra…")
        self.btn_out_browse = QPushButton("…")
        self.btn_out_browse.setFixedWidth(30)
        row4.addWidget(self.ed_output, 1)
        row4.addWidget(self.btn_out_browse)
        l_out.addLayout(row4)

        g2 = QGridLayout()
        self.cmb_comp = QComboBox()
        self.cmb_comp.addItems(COMPRESSIONS)
        self.sp_quality = QSpinBox()
        self.sp_quality.setRange(10, 100)
        self.sp_quality.setValue(85)
        self.sp_quality.setEnabled(False)
        g2.addWidget(QLabel("Nén:"), 0, 0)
        g2.addWidget(self.cmb_comp, 0, 1)
        g2.addWidget(QLabel("Chất lượng JPEG:"), 1, 0)
        g2.addWidget(self.sp_quality, 1, 1)

        self.cmb_resample = QComboBox()
        self.cmb_resample.addItems(RESAMPLE_ALGS)
        self.cmb_resample.setCurrentText('bilinear')
        self.cmb_resample.setEnabled(False)
        g2.addWidget(QLabel("Nội suy khi nắn:"), 2, 0)
        g2.addWidget(self.cmb_resample, 2, 1)
        g2.setColumnStretch(1, 1)
        l_out.addLayout(g2)

        self.cb_northup = QCheckBox("Nắn ảnh thẳng hướng Bắc (nội suy lại)")
        self.cb_alpha = QCheckBox("Giữ kênh trong suốt (alpha)")
        self.cb_alpha.setChecked(True)
        self.cb_ovr = QCheckBox("Tạo overview (kim tự tháp)")
        self.cb_ovr.setChecked(True)
        self.cb_wld = QCheckBox("Ghi kèm world file (.tfw + .prj)")
        self.cb_add = QCheckBox("Thêm vào bản đồ sau khi xuất")
        self.cb_add.setChecked(True)
        for cb in (self.cb_northup, self.cb_alpha, self.cb_ovr, self.cb_wld, self.cb_add):
            l_out.addWidget(cb)

        self.btn_export = QPushButton("XUẤT GEOTIFF")
        self.btn_export.setMinimumHeight(32)
        l_out.addWidget(self.btn_export)

        self.btn_clear = QPushButton("Gỡ tất cả ảnh khỏi bản đồ")
        l_out.addWidget(self.btn_clear)
        root.addWidget(g_out)

        # --- 5. Xuất tile -------------------------------------------------
        g_tile = QGroupBox("5. Xuất bộ tile bản đồ")
        l_tile = QVBoxLayout(g_tile)
        self.btn_tiles = QPushButton("Xuất tile XYZ / MBTiles…")
        self.btn_tiles.setMinimumHeight(30)
        l_tile.addWidget(self.btn_tiles)
        lbl_tile = QLabel(
            "Cắt ảnh đã căn (và/hoặc các lớp đang hiện) thành bộ tile Web "
            "Mercator: thư mục z/x/y, file ZIP hoặc MBTiles — dùng được cho "
            "Leaflet, OpenLayers, Mapbox, QGIS…")
        lbl_tile.setWordWrap(True)
        lbl_tile.setStyleSheet("color:#666; font-size:11px;")
        l_tile.addWidget(lbl_tile)
        root.addWidget(g_tile)

        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        self.setWidget(scroll)
        self.setMinimumWidth(330)

    @staticmethod
    def _coord_spin():
        sp = QDoubleSpinBox()
        sp.setRange(-1e12, 1e12)
        sp.setDecimals(6)
        sp.setSingleStep(1.0)
        sp.setKeyboardTracking(False)
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return sp

    @staticmethod
    def _size_spin():
        sp = QDoubleSpinBox()
        sp.setRange(1e-12, 1e9)
        sp.setDecimals(10)
        sp.setSingleStep(0.01)
        sp.setKeyboardTracking(False)
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return sp

    # -------------------------------------------------------------- tín hiệu
    def _connect(self):
        self.btn_browse.clicked.connect(self._browse_image)
        self.btn_load.clicked.connect(self._load_image)
        self.ed_image.returnPressed.connect(self._load_image)
        self.lst_images.currentRowChanged.connect(self._on_list_row)
        self.lst_images.itemChanged.connect(self._on_list_item_changed)
        self.lst_images.itemDoubleClicked.connect(lambda _it: self.zoom_to_image())
        self.btn_up.clicked.connect(lambda: self.move_active(-1))
        self.btn_down.clicked.connect(lambda: self.move_active(1))
        self.btn_zoom.clicked.connect(self.zoom_to_image)
        self.btn_remove.clicked.connect(self.remove_active_image)
        self.cmb_export_mode.currentIndexChanged.connect(self._on_export_mode_changed)
        self.ed_output.textEdited.connect(self._on_output_edited)
        self.btn_edit.toggled.connect(self._toggle_edit)
        self.btn_two_point.toggled.connect(self._toggle_two_point)
        self.btn_fit.clicked.connect(self.fit_to_canvas)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        self.btn_clear.clicked.connect(self.clear_image)
        self.btn_out_browse.clicked.connect(self._browse_output)
        self.btn_export.clicked.connect(self.do_export)
        self.btn_tiles.clicked.connect(self.open_tile_dialog)
        self.cmb_comp.currentTextChanged.connect(self._on_comp_changed)
        self.cb_northup.toggled.connect(self._on_northup_toggled)
        self.crs_out.crsChanged.connect(self._on_out_crs_changed)
        self.btn_crs_map.clicked.connect(lambda: self.crs_out.setCrs(self._map_crs()))
        for btn, code in self.btn_crs_quick:
            btn.clicked.connect(
                lambda _=False, c=code: self.crs_out.setCrs(QgsCoordinateReferenceSystem(c)))
        self.cb_lock.toggled.connect(self._on_lock_changed)
        self.cb_show_image.toggled.connect(self._on_show_image)
        self.sl_opacity.valueChanged.connect(self._on_opacity)

        for sp in (self.sp_cx, self.sp_cy, self.sp_px, self.sp_py, self.sp_rot):
            sp.valueChanged.connect(self._on_field_changed)

        self.tool.placementChanged.connect(self._refresh_fields)
        self.tool.editStarted.connect(self.push_undo)
        self.tool.editReverted.connect(self.drop_last_undo)
        self.tool.undoRequested.connect(self.undo)
        self.tool.peekChanged.connect(self._on_peek)
        self.tool.redoRequested.connect(self.redo)
        self.tool.twoPointStep.connect(self._on_two_point_step)
        self.tool.activateRequested.connect(self._activate_item)
        self.tool.twoPointFinished.connect(self._on_two_point_finished)
        self.canvas.mapToolSet.connect(self._on_map_tool_set)
        self.canvas.destinationCrsChanged.connect(self._on_map_crs_changed)
        QgsProject.instance().crsChanged.connect(self._refresh_crs_label)

    def _build_shortcuts(self):
        """Ctrl+Z / Ctrl+Y khi con trỏ đang ở trong bảng điều khiển.

        Phạm vi giới hạn trong dock nên không đụng phím tắt Undo của QGIS;
        khi đang thao tác trên canvas thì `AlignImageMapTool` xử lý (xem
        `maptool._filter_watch`).
        """
        self._shortcuts = []
        wanted = [(QKeySequence("Ctrl+Z"), self.undo),
                  (QKeySequence("Ctrl+Y"), self.redo),
                  (QKeySequence("Ctrl+Shift+Z"), self.redo)]
        for std, slot in ((QKeySequence.Undo, self.undo),
                          (QKeySequence.Redo, self.redo)):
            for seq in QKeySequence.keyBindings(std):
                wanted.append((seq, slot))

        seen = set()
        for seq, slot in wanted:
            text = seq.toString()
            if not text or text in seen:     # tránh phím tắt trùng -> Qt bỏ qua cả hai
                continue
            seen.add(text)
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    # ------------------------------------------------------------- nạp / gỡ
    def _browse_image(self):
        start = os.path.dirname(self.ed_image.text()) or ''
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn một hoặc nhiều ảnh", start, IMAGE_FILTER)
        for path in paths:
            self.ed_image.setText(path)
            self._load_image()

    def load_images(self, paths):
        """Nạp lần lượt nhiều ảnh (tiện khi gọi từ mã / kiểm thử)."""
        for path in paths:
            self.ed_image.setText(path)
            self._load_image()

    def _load_image(self):
        path = self.ed_image.text().strip('"').strip()
        if not path or not os.path.isfile(path):
            self._msg("Không tìm thấy file ảnh.", Qgis.Warning)
            return
        try:
            src = georef.read_raster(path)
        except Exception as exc:
            self._msg(str(exc), Qgis.Critical)
            return

        image = src.image
        notes = list(src.notes)
        placement = None
        placement_crs = self._map_crs()
        file_crs = None
        exact = True

        if src.is_georeferenced:
            self._loading = True
            try:
                result = self._place_georeferenced(src, notes)
            except Exception as exc:
                result = None
                notes.append("Không đặt được theo tọa độ trong file (%s) — ảnh được "
                             "đặt giữa khung nhìn." % exc)
            finally:
                self._loading = False
            if result == 'cancel':
                return
            if result is not None:
                image, placement, placement_crs, file_crs, exact = result

        georeferenced = placement is not None
        if placement is None:
            placement = Placement.fit_in_extent(self.canvas.extent(),
                                                image.width(), image.height())

        self._image_path = path
        layer = self._add_layer(path, image, placement, placement_crs)
        layer.file_crs = file_crs
        info = "%s — %d × %d pixel" % (os.path.basename(path), image.width(),
                                       image.height())
        if georeferenced:
            info += "\nCó sẵn tọa độ: %s" % crs_name(file_crs or placement_crs)
        layer.info = info
        self.lbl_info.setText(info)

        if len(self.layers) == 2 and not self._mode_user_set:
            # Từ ảnh thứ hai trở đi, mặc định ghép thành một file.
            self._set_export_mode(EXPORT_MOSAIC)
        if file_crs is not None and len(self.layers) == 1:
            # Mặc định xuất lại đúng hệ tọa độ của file gốc.
            self.crs_out.setCrs(file_crs)
        self._apply_default_output()

        self._refresh_crs_label()
        self._refresh_fields()
        self._on_out_crs_changed()
        self._update_enabled()
        self.btn_edit.setChecked(True)

        if georeferenced:
            self.zoom_to_image()
            head = ("Đã đặt ảnh ĐÚNG VỊ TRÍ theo tọa độ trong file." if exact
                    else "Đã đặt ảnh GẦN ĐÚNG theo tọa độ trong file.")
        else:
            head = ("Đã nạp ảnh. Kéo/chỉnh trên bản đồ rồi bấm XUẤT GEOTIFF."
                    if len(self.layers) == 1 else
                    "Đã thêm ảnh %d. Bấm vào ảnh trên bản đồ (hoặc trong danh sách) "
                    "để chọn ảnh cần chỉnh." % self.active.number)
        level = (Qgis.Success if (georeferenced and exact and not notes)
                 else Qgis.Warning if (georeferenced and not exact) else Qgis.Info)
        self._msg(" ".join([head] + notes), level, 8 if notes else 5)

    def _place_georeferenced(self, src, notes):
        """Tính vị trí ảnh từ GeoTransform/CRS trong file.

        Trả về (ảnh, placement, crs_của_placement, crs_của_file, chính_xác) hoặc
        'cancel'.
        """
        map_crs = self._map_crs()
        image, gt, flipped = georef.normalize_orientation(src.image, src.geotransform)
        if flipped:
            notes.append("File lưu ảnh theo chiều từ dưới lên — đã lật lại cho đúng.")
        if src.georef_kind == 'gcps':
            notes.append("Vị trí lấy từ các điểm khống chế (GCP) trong file.")

        file_crs = src.crs
        if file_crs is None:
            file_crs = map_crs
            notes.append("File không kèm hệ tọa độ — coi như cùng hệ %s với bản đồ."
                         % crs_name(map_crs))
        same_crs = (not file_crs.isValid() or not map_crs.isValid()
                    or file_crs == map_crs)

        w, h = image.width(), image.height()
        placement, err = georef.fit_placement(gt, w, h, file_crs, map_crs)
        if err <= georef.GEOREF_TOLERANCE_PX:
            if not same_crs:
                notes.append("Đã quy đổi từ %s sang %s của bản đồ (lệch tối đa %.2f "
                             "pixel)." % (crs_name(file_crs), crs_name(map_crs), err))
            return image, placement, map_crs, src.crs, True

        choice = 'warp' if same_crs else self.ask_georef_choice(file_crs, map_crs, err)
        if choice == 'cancel':
            return 'cancel'
        if choice == 'approx':
            notes.append("Đặt gần đúng: lệch tối đa khoảng %.1f pixel so với tọa độ "
                         "thật." % err)
            return image, placement, map_crs, src.crs, False
        if choice == 'project':
            self._set_map_crs(file_crs)
            map_crs = file_crs
            notes.append("Đã đổi hệ tọa độ dự án sang %s." % crs_name(file_crs))
            placement, err = georef.fit_placement(gt, w, h, file_crs, file_crs)
            if err <= georef.GEOREF_TOLERANCE_PX:
                return image, placement, map_crs, src.crs, True
            same_crs = True

        image, gt2 = georef.warp_to_crs(image, gt, file_crs, map_crs,
                                        resample=self.cmb_resample.currentText())
        placement, err = georef.fit_placement(gt2, image.width(), image.height(),
                                              map_crs, map_crs)
        if same_crs:
            notes.append("Ảnh trong file bị xiên — đã nắn thẳng để đặt chính xác.")
        else:
            notes.append("Đã chiếu lại ảnh từ %s sang %s để đặt chính xác."
                         % (crs_name(file_crs), crs_name(map_crs)))
        return image, placement, map_crs, src.crs, True

    def _ask_georef_choice(self, file_crs, map_crs, err_px):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Ảnh dùng hệ tọa độ khác bản đồ")
        box.setText("Ảnh dùng %s, còn bản đồ đang dùng %s.\n"
                    "Nếu đặt thẳng lên bản đồ, vị trí sẽ lệch tối đa khoảng "
                    "%.1f pixel ảnh." % (crs_name(file_crs), crs_name(map_crs), err_px))
        box.setInformativeText("Chọn cách đưa ảnh vào bản đồ:")
        b_warp = box.addButton("Chiếu lại ảnh sang %s (khuyên dùng)" % crs_name(map_crs),
                               QMessageBox.AcceptRole)
        b_proj = box.addButton("Đổi hệ tọa độ dự án sang %s" % crs_name(file_crs),
                               QMessageBox.AcceptRole)
        b_approx = box.addButton("Đặt gần đúng", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(b_warp)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is b_warp:
            return 'warp'
        if clicked is b_proj:
            return 'project'
        if clicked is b_approx:
            return 'approx'
        return 'cancel'

    # ------------------------------------------------------- danh sách ảnh
    def _add_layer(self, path, image, placement, placement_crs):
        self._counter += 1
        item = ImageOverlayItem(self.canvas)
        item.draw_decorations = False          # FrameOverlayItem vẽ khung/tay nắm
        item.set_show_handles(False)
        item.listeners.append(self.frame.update)
        item.placement_crs = placement_crs
        item.source_path = path
        item.set_image(image)
        item.set_placement(placement)
        layer = ImageLayer(item, path, self._counter)
        layer.aspect = placement.aspect
        self.layers.insert(0, layer)           # ảnh mới nạp nằm trên cùng
        self._restack()
        self._rebuild_list()
        self.set_active(layer)
        return layer

    def _frame_entries(self):
        return [(l.item, l is self.active) for l in reversed(self.layers)]

    def _item_at(self, canvas_pt):
        """Ảnh đang hiện nằm trên cùng tại điểm canvas, hoặc None."""
        for layer in self.layers:
            if layer.item.show_image and layer.item.contains(canvas_pt):
                return layer.item
        return None

    def _layer_of(self, item):
        for layer in self.layers:
            if layer.item is item:
                return layer
        return None

    def _activate_item(self, item):
        layer = self._layer_of(item)
        if layer is not None:
            self.set_active(layer)

    def set_active(self, layer):
        """Chọn ảnh để chỉnh (None = không chọn ảnh nào)."""
        if layer is self.active:
            self._sync_list_selection()
            return
        # Chuyển tool trước khi đổi self.active: tool gỡ trạng thái (giữ H, căn
        # 2 điểm…) trên ảnh cũ thông qua các tín hiệu dùng self.item.
        self.tool.set_item(layer.item if layer is not None else self._empty_item)
        self.active = layer
        self._sync_list_selection()
        self._sync_active_ui()
        self.frame.update()

    def _sync_list_selection(self):
        row = self.layers.index(self.active) if self.active in self.layers else -1
        self._list_updating = True
        self.lst_images.setCurrentRow(row)
        self._list_updating = False

    def _sync_active_ui(self):
        item = self.item
        self.cb_show_image.blockSignals(True)
        self.cb_show_image.setChecked(item.show_image)
        self.cb_show_image.blockSignals(False)
        self.sl_opacity.blockSignals(True)
        self.sl_opacity.setValue(int(round(item.image_opacity * 100)))
        self.sl_opacity.blockSignals(False)
        self.lbl_opacity.setText("%d%%" % self.sl_opacity.value())
        self.lbl_info.setText(self.active.info if self.active is not None
                              else "Chưa nạp ảnh.")
        self._refresh_fields()
        self._update_enabled()
        self._on_out_crs_changed()

    def _rebuild_list(self):
        self._list_updating = True
        self.lst_images.clear()
        for layer in self.layers:
            it = QListWidgetItem(layer.item.label)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if layer.item.show_image else Qt.Unchecked)
            it.setToolTip(layer.path or '')
            self.lst_images.addItem(it)
        self._list_updating = False
        self._sync_list_selection()

    def _restack(self):
        """Thứ tự vẽ theo danh sách: phần tử đầu nằm trên cùng."""
        for z, layer in enumerate(reversed(self.layers)):
            layer.item.setZValue(1000 + z)
        self.frame.update()

    def _on_list_row(self, row):
        if self._list_updating:
            return
        if 0 <= row < len(self.layers):
            self.set_active(self.layers[row])

    def _on_list_item_changed(self, it):
        if self._list_updating:
            return
        row = self.lst_images.row(it)
        if not (0 <= row < len(self.layers)):
            return
        layer = self.layers[row]
        layer.item.set_image_visible(it.checkState() == Qt.Checked)
        if layer is self.active:
            self._sync_active_ui()

    def _set_list_check(self, layer):
        if layer not in self.layers:
            return
        it = self.lst_images.item(self.layers.index(layer))
        if it is None:
            return
        self._list_updating = True
        it.setCheckState(Qt.Checked if layer.item.show_image else Qt.Unchecked)
        self._list_updating = False

    def move_active(self, delta):
        """delta = -1 đưa ảnh lên trên, +1 đưa xuống dưới."""
        if self.active is None:
            return
        i = self.layers.index(self.active)
        j = i + delta
        if not (0 <= j < len(self.layers)):
            return
        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        self._restack()
        self._rebuild_list()
        self._update_enabled()

    def _drop_layer(self, layer):
        layer.item.listeners = []
        try:
            self.canvas.scene().removeItem(layer.item)
        except Exception:
            pass

    def remove_active_image(self):
        if self.active is None:
            return
        layer = self.active
        idx = self.layers.index(layer)
        self.set_active(None)
        self.layers.remove(layer)
        self._drop_layer(layer)
        self._rebuild_list()
        self._restack()
        if self.layers:
            self.set_active(self.layers[min(idx, len(self.layers) - 1)])
        else:
            self.btn_edit.setChecked(False)
            self._sync_active_ui()

    def clear_image(self):
        """Gỡ toàn bộ ảnh."""
        self.tool.stop_two_point()
        self.set_active(None)
        for layer in self.layers:
            self._drop_layer(layer)
        self.layers = []
        self._empty_item.placement_crs = self._map_crs()
        self._image_path = None
        self._rebuild_list()
        self.lbl_info.setText("Chưa nạp ảnh.")
        self.btn_edit.setChecked(False)
        self._update_enabled()
        self.frame.update()

    # ------------------------------------------------------------- chế độ tool
    def _toggle_edit(self, checked):
        if checked:
            if not self.item.has_image():
                self.btn_edit.setChecked(False)
                return
            self.canvas.setMapTool(self.tool)
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
        self.btn_edit.setText("Đang chỉnh ảnh (bấm để tắt)" if checked
                              else "Bật chế độ kéo/chỉnh ảnh")

    def _on_map_tool_set(self, new_tool, old_tool=None):
        active = new_tool is self.tool
        if self.btn_edit.isChecked() != active:
            self.btn_edit.blockSignals(True)
            self.btn_edit.setChecked(active)
            self.btn_edit.blockSignals(False)
            self.btn_edit.setText("Đang chỉnh ảnh (bấm để tắt)" if active
                                  else "Bật chế độ kéo/chỉnh ảnh")
        if not active and self.btn_two_point.isChecked():
            self.btn_two_point.setChecked(False)

    def _toggle_two_point(self, checked):
        if checked:
            if not self.item.has_image():
                self.btn_two_point.setChecked(False)
                return
            self.btn_edit.setChecked(True)
            self.tool.start_two_point()
        else:
            self.tool.stop_two_point()

    def _on_two_point_step(self, step):
        if step == TP_DONE:
            if self.btn_two_point.isChecked():
                self.btn_two_point.blockSignals(True)
                self.btn_two_point.setChecked(False)
                self.btn_two_point.blockSignals(False)
            self.lbl_hint.setStyleSheet("color:#666; font-size:11px;")
            return
        self.lbl_hint.setText(TP_MESSAGES[step] + "\n(Nhấn Esc để hủy.)")
        self.lbl_hint.setStyleSheet("color:#0a5; font-weight:bold; font-size:11px;")

    def _on_two_point_finished(self, ok, message):
        self._msg(message, Qgis.Success if ok else Qgis.Warning)
        self._refresh_fields()

    # ------------------------------------------------------------- hệ tọa độ
    def _map_crs(self):
        """Hệ tọa độ đang hiển thị bản đồ — cũng là hệ của các ô tọa độ ở mục 3."""
        crs = self.canvas.mapSettings().destinationCrs()
        if not crs.isValid():
            crs = QgsProject.instance().crs()
        return crs

    @property
    def _placement_crs(self):
        return getattr(self.item, 'placement_crs', None) if self.item is not None else None

    @_placement_crs.setter
    def _placement_crs(self, crs):
        for layer in self.layers:
            layer.item.placement_crs = crs
        self._empty_item.placement_crs = crs

    def _set_map_crs(self, crs):
        QgsProject.instance().setCrs(crs)
        if self.canvas.mapSettings().destinationCrs() != crs:
            self.canvas.setDestinationCrs(crs)

    def _on_map_crs_changed(self, *args):
        """Bản đồ đổi hệ tọa độ: dời MỌI ảnh theo để vẫn nằm đúng chỗ ngoài thực địa."""
        if self.tool is None:
            return
        new = self._map_crs()
        old = self._placement_crs
        follow_out = (old is not None and old.isValid()
                      and self.crs_out.crs() == old)
        if old is not None and old.isValid() and new.isValid() and old != new:
            worst = 0.0
            for layer in self.layers:
                if not layer.item.has_image():
                    continue
                try:
                    placement, err = georef.placement_to_crs(layer.item.placement, old, new)
                    layer.undo = [self._convert_state(d, old, new) for d in layer.undo]
                    layer.redo = [self._convert_state(d, old, new) for d in layer.redo]
                    layer.item.set_placement(placement)
                    layer.aspect = placement.aspect
                    worst = max(worst, err)
                except Exception as exc:
                    self._msg("Không quy đổi được vị trí %s sang %s: %s"
                              % (layer.name, crs_name(new), exc), Qgis.Warning)
            if worst > georef.GEOREF_TOLERANCE_PX:
                self._msg("Bản đồ đổi sang %s: ảnh đã được dời theo, lệch tối đa "
                          "khoảng %.1f pixel." % (crs_name(new), worst), Qgis.Warning)
        self._placement_crs = new
        if follow_out:
            self.crs_out.setCrs(new)
        self._refresh_crs_label()
        self._refresh_fields()
        self._on_out_crs_changed()
        self._update_history_buttons()

    @staticmethod
    def _convert_state(state, old, new):
        placement, _ = georef.placement_to_crs(Placement.from_dict(state), old, new)
        return placement.to_dict()

    def _on_northup_toggled(self, checked):
        if self.cb_northup.isEnabled():
            self._northup_user = checked
        self.cmb_resample.setEnabled(checked or not self.cb_northup.isEnabled())

    def export_mode(self):
        return self.cmb_export_mode.currentData() or EXPORT_ACTIVE

    def _set_export_mode(self, mode):
        for i in range(self.cmb_export_mode.count()):
            if self.cmb_export_mode.itemData(i) == mode:
                self.cmb_export_mode.blockSignals(True)
                self.cmb_export_mode.setCurrentIndex(i)
                self.cmb_export_mode.blockSignals(False)
                self._on_export_mode_changed(user=False)
                return

    def _on_export_mode_changed(self, *args, user=True):
        if user:
            self._mode_user_set = True
        mode = self.export_mode()
        if mode == EXPORT_MOSAIC:
            note = ("Ghép mọi ảnh đang hiện (đánh dấu trong danh sách) thành một "
                    "GeoTIFF; chỗ chồng nhau lấy ảnh nằm trên trong danh sách.")
        elif mode == EXPORT_EACH:
            note = ("Mỗi ảnh đang hiện ra một file: <tên file>_<tên ảnh>.tif, cùng "
                    "thư mục với đường dẫn bên dưới.")
        else:
            note = "Chỉ xuất ảnh đang chọn trong danh sách."
        self.lbl_mode_note.setText(note)
        self._apply_default_output()
        self._on_out_crs_changed()

    def _on_output_edited(self, _text):
        self._auto_output = False

    def _default_output(self):
        layer = self.active or (self.layers[-1] if self.layers else None)
        if layer is None or not layer.path:
            return ''
        folder = os.path.dirname(layer.path)
        if self.export_mode() == EXPORT_MOSAIC:
            first = self.layers[-1]            # ảnh nạp đầu tiên nằm cuối danh sách
            return os.path.join(folder, safe_stem(first.name) + "_ghep.tif")
        if self.export_mode() == EXPORT_EACH:
            return os.path.join(folder, "georef.tif")
        return os.path.splitext(layer.path)[0] + "_georef.tif"

    def _apply_default_output(self):
        if self._auto_output or not self.ed_output.text().strip():
            self.ed_output.setText(self._default_output())
            self._auto_output = True

    def _on_out_crs_changed(self, *args):
        out = self.crs_out.crs()
        src = self._placement_crs if self._placement_crs is not None else self._map_crs()
        differs = out.isValid() and src.isValid() and out != src
        mosaic = self.export_mode() == EXPORT_MOSAIC
        self.cb_northup.blockSignals(True)
        if differs or mosaic:
            self.cb_northup.setChecked(True)
            self.cb_northup.setEnabled(False)
            if differs:
                self.lbl_crs_note.setText(
                    "Khác hệ của bản đồ (%s): ảnh sẽ được chiếu lại sang %s — luôn "
                    "thẳng hướng Bắc và nội suy theo thuật toán chọn bên dưới."
                    % (crs_name(src), crs_name(out)))
            else:
                self.lbl_crs_note.setText(
                    "Ghép nhiều ảnh: các ảnh được đưa về một lưới chung thẳng hướng "
                    "Bắc (có nội suy), độ phân giải theo ảnh mịn nhất.")
        else:
            self.cb_northup.setEnabled(True)
            self.cb_northup.setChecked(self._northup_user)
            self.lbl_crs_note.setText(
                "Trùng hệ của bản đồ: góc xoay được ghi thẳng vào GeoTIFF, không nội "
                "suy lại ảnh.")
        self.cb_northup.blockSignals(False)
        self.cmb_resample.setEnabled(differs or self.cb_northup.isChecked())

    # ------------------------------------------------------------ đồng bộ UI
    def _refresh_crs_label(self):
        crs = self._map_crs()
        self.lbl_crs.setText("Tọa độ bên dưới theo hệ của bản đồ: %s" % crs_name(crs))
        geographic = crs.isValid() and crs.isGeographic()
        for sp in (self.sp_px, self.sp_py):
            sp.setSingleStep(1e-6 if geographic else 0.01)

    def _refresh_fields(self):
        p = self.item.placement
        if p is None:
            return
        self._syncing = True
        try:
            self.sp_cx.setValue(p.cx)
            self.sp_cy.setValue(p.cy)
            self.sp_px.setValue(p.sx)
            self.sp_py.setValue(p.sy)
            self.sp_rot.setValue(p.rotation)
        finally:
            self._syncing = False
        units = "°" if self._map_crs().isGeographic() else "đvbđ"
        self.lbl_span.setText("%.4f × %.4f %s"
                              % (p.width * p.sx, p.height * p.sy, units))

    def _on_field_changed(self):
        if self._syncing or self.item.placement is None:
            return
        sender = self.sender()
        p = self.item.placement.clone()
        self.push_undo()

        sx, sy = self.sp_px.value(), self.sp_py.value()
        if self.cb_lock.isChecked():
            if sender is self.sp_px:
                sy = sx * self._aspect
            elif sender is self.sp_py:
                sx = sy / self._aspect if self._aspect else sx
        p.cx = self.sp_cx.value()
        p.cy = self.sp_cy.value()
        p.sx = max(sx, 1e-12)
        p.sy = max(sy, 1e-12)
        p.rotation = self.sp_rot.value()
        self.item.set_placement(p)
        if not self.cb_lock.isChecked():
            self._aspect = p.aspect
        self._refresh_fields()

    def _on_lock_changed(self, checked):
        self.tool.lock_aspect = checked
        if checked and self.item.placement is not None:
            self._aspect = self.item.placement.aspect

    def _on_show_image(self, checked):
        self.item.set_image_visible(checked)
        self.sl_opacity.setEnabled(checked and self.item.has_image())
        if self.active is not None:
            self._set_list_check(self.active)

    def _on_peek(self, hidden):
        """Giữ phím H trên canvas: tạm giấu ảnh, thả ra thì trả về như cũ."""
        self.item.set_image_visible(False if hidden
                                    else self.cb_show_image.isChecked())

    def _on_opacity(self, value):
        self.item.set_opacity_value(value / 100.0)
        self.lbl_opacity.setText("%d%%" % value)

    def _on_comp_changed(self, text):
        self.sp_quality.setEnabled(text.upper() == 'JPEG')
        if text.upper() == 'JPEG' and self.cb_alpha.isChecked():
            self.cb_alpha.setChecked(False)
        self.cb_alpha.setEnabled(text.upper() != 'JPEG')

    def _update_enabled(self):
        has = self.item.has_image()
        for w in (self.btn_edit, self.btn_two_point, self.btn_fit,
                  self.sp_cx, self.sp_cy, self.sp_px, self.sp_py, self.sp_rot,
                  self.cb_lock, self.cb_show_image, self.sl_opacity,
                  self.btn_zoom, self.btn_remove):
            w.setEnabled(has)
        many = len(self.layers) > 1
        idx = self.layers.index(self.active) if self.active in self.layers else -1
        self.btn_up.setEnabled(many and idx > 0)
        self.btn_down.setEnabled(many and 0 <= idx < len(self.layers) - 1)
        self.btn_export.setEnabled(bool(self.layers))
        self.btn_clear.setEnabled(bool(self.layers))
        self.sl_opacity.setEnabled(has and self.cb_show_image.isChecked())
        self._update_history_buttons()

    def _update_history_buttons(self):
        has = self.item is not None and self.item.has_image()
        self.btn_undo.setEnabled(has and bool(self._undo))
        self.btn_redo.setEnabled(has and bool(self._redo))
        self.btn_undo.setText("↶ Hoàn tác (Ctrl+Z)" if not self._undo
                              else "↶ Hoàn tác %d (Ctrl+Z)" % len(self._undo))
        self.btn_redo.setText("↷ Làm lại (Ctrl+Y)" if not self._redo
                              else "↷ Làm lại %d (Ctrl+Y)" % len(self._redo))

    # --------------------------------------------------------------- thao tác
    def push_undo(self):
        """Lưu trạng thái HIỆN TẠI trước khi thực hiện một thay đổi mới."""
        if self.item.placement is None:
            return
        self._undo.append(self.item.placement.to_dict())
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo = []            # nhánh mới -> bỏ toàn bộ lịch sử làm lại
        self._update_history_buttons()

    def drop_last_undo(self):
        """Bỏ mục vừa lưu khi hóa ra thao tác không làm thay đổi gì."""
        if self._undo:
            self._undo.pop()
        self._update_history_buttons()

    def undo(self):
        if not self._undo or self.item is None or self.item.placement is None:
            return
        self._redo.append(self.item.placement.to_dict())
        if len(self._redo) > MAX_UNDO:
            self._redo.pop(0)
        self.item.set_placement(Placement.from_dict(self._undo.pop()))
        self._after_history_move()

    def redo(self):
        if not self._redo or self.item is None or self.item.placement is None:
            return
        self._undo.append(self.item.placement.to_dict())
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self.item.set_placement(Placement.from_dict(self._redo.pop()))
        self._after_history_move()

    def _after_history_move(self):
        if self.cb_lock.isChecked():
            self._aspect = self.item.placement.aspect
        self._refresh_fields()
        self._update_history_buttons()

    def fit_to_canvas(self):
        if not self.item.has_image():
            return
        self.push_undo()
        p = self.item.placement
        self.item.set_placement(
            Placement.fit_in_extent(self.canvas.extent(), p.width, p.height))
        self._aspect = self.item.placement.aspect
        self._refresh_fields()

    def zoom_to_image(self):
        if not self.item.has_image():
            return
        self.canvas.setExtent(self.item.placement.bbox().buffered(
            self.item.placement.bbox().width() * 0.05))
        self.canvas.refresh()

    # ------------------------------------------------------------------ xuất
    def _browse_output(self):
        start = self.ed_output.text() or (self._image_path or '')
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu GeoTIFF", start, "GeoTIFF (*.tif *.tiff)")
        if path:
            if not path.lower().endswith(('.tif', '.tiff')):
                path += '.tif'
            self.ed_output.setText(path)
            self._auto_output = False

    def _export_targets(self):
        if self.export_mode() == EXPORT_ACTIVE:
            return [self.active] if (self.active is not None
                                     and self.item.has_image()) else []
        return [l for l in self.layers if l.item.show_image and l.item.has_image()]

    def do_export(self):
        targets = self._export_targets()
        if not targets:
            self._msg("Không có ảnh nào để xuất (các ảnh đang bị ẩn?).", Qgis.Warning)
            return
        out_path = self.ed_output.text().strip('"').strip()
        if not out_path:
            self._msg("Hãy chọn đường dẫn file GeoTIFF đầu ra.", Qgis.Warning)
            return
        if not out_path.lower().endswith(('.tif', '.tiff')):
            out_path += '.tif'

        crs = self._placement_crs if self._placement_crs is not None else self._map_crs()
        if not crs.isValid():
            self._msg("Bản đồ chưa có hệ tọa độ hợp lệ.", Qgis.Critical)
            return
        dst_crs = self.crs_out.crs()
        if not dst_crs.isValid():
            dst_crs = crs

        common = dict(dst_crs=dst_crs,
                      compression=self.cmb_comp.currentText(),
                      jpeg_quality=self.sp_quality.value(),
                      resample=self.cmb_resample.currentText(),
                      keep_alpha=self.cb_alpha.isChecked(),
                      build_overviews=self.cb_ovr.isChecked(),
                      world_file=self.cb_wld.isChecked())
        mode = self.export_mode()
        written = []
        extra = ''
        self.setCursor(Qt.WaitCursor)
        try:
            if mode == EXPORT_MOSAIC:
                # Danh sách: phần tử đầu nằm trên cùng -> GDAL cần thứ tự dưới lên trên.
                entries = [(l.item.image, l.item.placement) for l in reversed(targets)]
                info = export_mosaic(entries, crs, out_path, **common)
                written.append(out_path)
                extra = " (ghép %d ảnh, %d × %d pixel%s)" % (
                    info['count'], info['size'][0], info['size'][1],
                    ", đã giảm độ phân giải vì quá lớn" if info['coarsened'] else "")
            else:
                base, ext = os.path.splitext(out_path)
                used = set()
                for layer in targets:
                    if mode == EXPORT_EACH:
                        stem = "%s_%s" % (base, safe_stem(layer.name))
                        path, k = stem + ext, 2
                        while path.lower() in used:
                            path, k = "%s_%d%s" % (stem, k, ext), k + 1
                        used.add(path.lower())
                    else:
                        path = out_path
                    export_geotiff(layer.item.image, layer.item.placement, crs, path,
                                   north_up=self.cb_northup.isChecked(), **common)
                    written.append(path)
        except Exception as exc:
            self.unsetCursor()
            self._msg("Lỗi khi xuất: %s" % exc, Qgis.Critical, 0)
            return
        self.unsetCursor()

        if self.cb_add.isChecked():
            for path in written:
                layer = self.iface.addRasterLayer(
                    path, os.path.splitext(os.path.basename(path))[0])
                if layer is None or not layer.isValid():
                    self._msg("Đã xuất file nhưng không thêm được vào bản đồ: %s" % path,
                              Qgis.Warning)
        if len(written) == 1:
            text = "Đã xuất GeoTIFF theo %s%s: %s" % (crs_name(dst_crs), extra, written[0])
        else:
            text = "Đã xuất %d file GeoTIFF theo %s vào %s" % (
                len(written), crs_name(dst_crs), os.path.dirname(written[0]))
        self._msg(text, Qgis.Success, 8)
        self.last_export = written

    # -------------------------------------------------------------- xuất tile
    def open_tile_dialog(self):
        from .tiledialog import TileExportDialog
        if not self.item.has_image() and not self.canvas.layers():
            self._msg("Chưa có ảnh hoặc lớp nào để cắt thành tile.", Qgis.Warning)
            return
        items = [l.item for l in self.layers if l.item.show_image and l.item.has_image()]
        dlg = TileExportDialog(self.iface, self.item, self, items=items)
        dlg.exec_()

    # ------------------------------------------------------------------ tiện
    def _msg(self, text, level=Qgis.Info, duration=5):
        self.iface.messageBar().pushMessage("Raster Image Editor Tiff", text,
                                            level=level, duration=duration)

    def cleanup(self):
        """Gỡ toàn bộ item khỏi canvas khi tắt plugin."""
        try:
            self.tool.stop_two_point()
            if self.canvas.mapTool() is self.tool:
                self.canvas.unsetMapTool(self.tool)
            for layer in self.layers:
                self._drop_layer(layer)
            self.canvas.scene().removeItem(self._empty_item)
            self.canvas.scene().removeItem(self.frame)
        except Exception:
            pass
        self.layers = []
        self.active = None
        self.tool = None

    def closeEvent(self, event):
        if self.btn_edit.isChecked():
            self.btn_edit.setChecked(False)
        super().closeEvent(event)
