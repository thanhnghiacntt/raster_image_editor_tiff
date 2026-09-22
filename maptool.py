# -*- coding: utf-8 -*-
"""Công cụ bản đồ: kéo / co giãn / xoay ảnh và căn theo 2 điểm khống chế."""

import math

from qgis.PyQt.QtCore import QEvent, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.core import QgsPointXY
from qgis.gui import QgsMapTool, QgsVertexMarker

from .overlay import HANDLE_UV, OPPOSITE

# Thứ tự các bước của chế độ căn 2 điểm
TP_PICK_IMG_1, TP_PICK_MAP_1, TP_PICK_IMG_2, TP_PICK_MAP_2, TP_DONE = range(5)

TP_MESSAGES = {
    TP_PICK_IMG_1: "Căn 2 điểm - Bước 1/4: bấm vào MỘT ĐIỂM NHẬN BIẾT TRÊN ẢNH.",
    TP_PICK_MAP_1: "Căn 2 điểm - Bước 2/4: bấm vào VỊ TRÍ THẬT của điểm vừa chọn.",
    TP_PICK_IMG_2: "Căn 2 điểm - Bước 3/4: bấm vào ĐIỂM THỨ HAI TRÊN ẢNH.",
    TP_PICK_MAP_2: "Căn 2 điểm - Bước 4/4: bấm vào VỊ TRÍ THẬT của điểm thứ hai.",
}


class AlignImageMapTool(QgsMapTool):
    """Chỉnh ảnh trực tiếp trên canvas bằng chuột."""

    placementChanged = pyqtSignal()     # vị trí ảnh vừa thay đổi
    editStarted = pyqtSignal()          # bắt đầu một thao tác (để lưu Undo)
    editReverted = pyqtSignal()         # thao tác kết thúc mà không đổi gì
    undoRequested = pyqtSignal()        # Ctrl+Z trên canvas
    redoRequested = pyqtSignal()        # Ctrl+Y / Ctrl+Shift+Z trên canvas
    peekChanged = pyqtSignal(bool)      # giữ H để tạm ẩn ảnh (True = đang ẩn)
    activateRequested = pyqtSignal(object)  # bấm vào một ảnh khác -> chọn ảnh đó
    twoPointStep = pyqtSignal(int)      # đổi bước của chế độ căn 2 điểm
    twoPointFinished = pyqtSignal(bool, str)

    def __init__(self, canvas, item):
        super().__init__(canvas)
        self.canvas = canvas
        self.item = item
        self.lock_aspect = True
        # Hàm (điểm canvas) -> ImageOverlayItem khác nằm dưới con trỏ, hoặc None.
        self.find_item_at = None

        self._mode = None               # 'move' | 'scale' | 'rotate'
        self._handle = None
        self._start_placement = None
        self._start_map_pt = None
        self._start_angle = 0.0
        self._anchor_pt = None
        self._anchor_pixel = None
        self._grab_offset = (0.0, 0.0)
        self._peeking = False

        self._two_point = False
        self._tp_step = TP_PICK_IMG_1
        self._tp_img = [None, None]
        self._tp_map = [None, None]
        self._tp_markers = []

    def set_item(self, item):
        """Chuyển sang chỉnh ảnh khác (khi có nhiều ảnh)."""
        if item is self.item:
            return
        editing = self.item.show_handles if self.item is not None else True
        self._mode = None
        self.stop_two_point()
        self._stop_peek()
        if self.item is not None:
            self.item.set_hover(None)
            self.item.set_show_handles(False)
        self.item = item
        if item is not None:
            item.set_show_handles(editing)

    def _other_item_at(self, pos):
        if self.find_item_at is None:
            return None
        other = self.find_item_at(pos)
        return other if (other is not None and other is not self.item) else None

    # --------------------------------------------------------------- vòng đời
    def activate(self):
        super().activate()
        self.item.set_show_handles(True)
        self.canvas.setCursor(QCursor(Qt.ArrowCursor))
        self._filter_watch(True)

    def deactivate(self):
        self._mode = None
        self.stop_two_point()
        self._stop_peek()
        self.item.set_hover(None)
        self.item.set_show_handles(False)
        self._filter_watch(False)
        super().deactivate()

    def _filter_watch(self, install):
        """Giành lại Ctrl+Z / Ctrl+Y từ menu Edit của QGIS khi công cụ đang bật.

        Qt gửi ShortcutOverride tới widget đang có focus trước khi kích hoạt
        phím tắt toàn cục; nhận sự kiện này khiến phím được chuyển thành
        keyPressEvent bình thường và tới được `keyPressEvent` bên dưới.
        """
        targets = [self.canvas]
        try:
            targets.append(self.canvas.viewport())
        except Exception:
            pass
        for obj in targets:
            try:
                if install:
                    obj.installEventFilter(self)
                else:
                    obj.removeEventFilter(self)
            except Exception:
                pass

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.ShortcutOverride
                and self.item is not None and self.item.has_image()
                and event.modifiers() & Qt.ControlModifier
                and event.key() in (Qt.Key_Z, Qt.Key_Y)):
            event.accept()
            return True
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------- căn theo 2 điểm
    def start_two_point(self):
        self.clear_two_point_markers()
        self._two_point = True
        self._tp_step = TP_PICK_IMG_1
        self._tp_img = [None, None]
        self._tp_map = [None, None]
        self.twoPointStep.emit(self._tp_step)

    def stop_two_point(self):
        was_on = self._two_point
        self._two_point = False
        self.clear_two_point_markers()
        if was_on:
            self.twoPointStep.emit(TP_DONE)

    def is_two_point(self):
        return self._two_point

    def clear_two_point_markers(self):
        for m in self._tp_markers:
            try:
                self.canvas.scene().removeItem(m)
            except Exception:
                pass
        self._tp_markers = []

    def _add_marker(self, point, color, icon):
        m = QgsVertexMarker(self.canvas)
        m.setCenter(point)
        m.setColor(QColor(color))
        m.setIconType(icon)
        m.setIconSize(13)
        m.setPenWidth(3)
        self._tp_markers.append(m)

    def _two_point_click(self, map_pt):
        p = self.item.placement
        if p is None:
            return
        if self._tp_step == TP_PICK_IMG_1:
            self._tp_img[0] = p.map_to_pixel(map_pt.x(), map_pt.y())
            self._add_marker(map_pt, '#ff8000', QgsVertexMarker.ICON_CIRCLE)
            self._tp_step = TP_PICK_MAP_1
        elif self._tp_step == TP_PICK_MAP_1:
            self._tp_map[0] = map_pt
            self._add_marker(map_pt, '#00a0ff', QgsVertexMarker.ICON_CROSS)
            self._tp_step = TP_PICK_IMG_2
        elif self._tp_step == TP_PICK_IMG_2:
            self._tp_img[1] = p.map_to_pixel(map_pt.x(), map_pt.y())
            self._add_marker(map_pt, '#ff8000', QgsVertexMarker.ICON_CIRCLE)
            self._tp_step = TP_PICK_MAP_2
        elif self._tp_step == TP_PICK_MAP_2:
            self._tp_map[1] = map_pt
            self._apply_two_point()
            return
        self.twoPointStep.emit(self._tp_step)

    def _apply_two_point(self):
        from .placement import Placement
        base = self.item.placement
        try:
            new_p = Placement.from_two_points(
                base, self._tp_img[0], self._tp_map[0],
                self._tp_img[1], self._tp_map[1])
        except Exception as exc:      # 2 điểm trùng nhau chẳng hạn
            self.stop_two_point()
            self.twoPointFinished.emit(False, str(exc))
            return
        self.editStarted.emit()
        self.item.set_placement(new_p)
        self.stop_two_point()
        self.placementChanged.emit()
        self.twoPointFinished.emit(True, "Đã căn ảnh theo 2 điểm khống chế.")

    # ------------------------------------------------------------- sự kiện chuột
    @staticmethod
    def _map_point(event):
        try:
            return event.snapPoint()      # bám dính theo cấu hình dự án nếu có
        except Exception:
            return event.mapPoint()

    def canvasMoveEvent(self, event):
        if not self.item.has_image():
            return
        if self._mode is None:
            if self._two_point:
                self.item.set_hover(None)
                self.canvas.setCursor(QCursor(Qt.CrossCursor))
            else:
                hit = self.item.hit_test(event.pos())
                self.item.set_hover(hit if hit != 'body' else None)
                if hit is None and self._other_item_at(event.pos()) is not None:
                    self.canvas.setCursor(QCursor(Qt.PointingHandCursor))
                else:
                    self._update_cursor(hit)
            return

        map_pt = QgsPointXY(self.toMapCoordinates(event.pos()))
        if self._mode == 'move':
            self._do_move(map_pt, event.modifiers())
        elif self._mode == 'scale':
            self._do_scale(map_pt, event.modifiers())
        elif self._mode == 'rotate':
            self._do_rotate(map_pt, event.modifiers())
        self.placementChanged.emit()

    def canvasPressEvent(self, event):
        if not self.item.has_image() and self.find_item_at is None:
            return
        if event.button() != Qt.LeftButton:
            return
        if self._two_point:
            self._two_point_click(QgsPointXY(self._map_point(event)))
            return

        handle = self.item.hit_test(event.pos()) if self.item.has_image() else None
        if handle is None:
            # Bấm trúng một ảnh khác: chọn ảnh đó rồi kéo luôn.
            other = self._other_item_at(event.pos())
            if other is None:
                return
            self.activateRequested.emit(other)
            if self.item is not other:
                return
            handle = self.item.hit_test(event.pos())
            if handle is None:
                return
        self.item.set_hover(handle if handle != 'body' else None)
        self._start_placement = self.item.placement.clone()
        self._start_map_pt = QgsPointXY(self.toMapCoordinates(event.pos()))
        self.editStarted.emit()

        if handle == 'body':
            self._mode = 'move'
        elif handle == 'rot':
            self._mode = 'rotate'
            self._start_angle = self._angle_from_center(self._start_map_pt,
                                                        self._start_placement)
        else:
            self._mode = 'scale'
            self._handle = handle
            sp = self._start_placement
            u, v = HANDLE_UV[OPPOSITE[handle]]
            self._anchor_pixel = (u * sp.width, v * sp.height)
            self._anchor_pt = sp.pixel_to_map(*self._anchor_pixel)

            # Bù trừ chỗ bấm lệch: cạnh có thể được nắm ở bất kỳ đâu và thường
            # lệch vài pixel khỏi đường viền, không bù thì ảnh nhảy một cái
            # ngay lúc nhấn chuột.
            hu, hv = HANDLE_UV[handle]
            h_map = sp.pixel_to_map(hu * sp.width, hv * sp.height)
            self._grab_offset = (
                self._axis_proj(self._start_map_pt, sp)[0]
                - self._axis_proj(h_map, sp)[0],
                self._axis_proj(self._start_map_pt, sp)[1]
                - self._axis_proj(h_map, sp)[1])

    def _axis_proj(self, map_pt, placement):
        """Chiếu (map_pt - điểm neo) lên 2 trục của ảnh -> (dọc X, dọc Y)."""
        ex, ey = placement.axes()
        dx = map_pt.x() - self._anchor_pt.x()
        dy = map_pt.y() - self._anchor_pt.y()
        return (dx * ex[0] + dy * ex[1], dx * ey[0] + dy * ey[1])

    def canvasReleaseEvent(self, event):
        if self._mode is None:
            return
        unchanged = (self._start_placement is not None
                     and self.item.placement is not None
                     and self.item.placement.to_dict() == self._start_placement.to_dict())
        self._mode = None
        self._handle = None
        if unchanged:
            # Bấm mà không kéo -> bỏ mục Undo đã lưu lúc nhấn chuột.
            self.editReverted.emit()
        self.placementChanged.emit()

    def keyPressEvent(self, event):
        if not self.item.has_image():
            return
        key = event.key()
        if key == Qt.Key_H and not event.modifiers():
            # Giữ H để tạm giấu ảnh, xem nền bên dưới rồi thả ra.
            if not event.isAutoRepeat() and not self._peeking:
                self._peeking = True
                self.peekChanged.emit(True)
            event.accept()
            return
        if event.modifiers() & Qt.ControlModifier:
            if key == Qt.Key_Z and event.modifiers() & Qt.ShiftModifier:
                self.redoRequested.emit()
                event.accept()
                return
            if key == Qt.Key_Z:
                self.undoRequested.emit()
                event.accept()
                return
            if key == Qt.Key_Y:
                self.redoRequested.emit()
                event.accept()
                return
        if key == Qt.Key_Escape:
            if self._two_point:
                self.stop_two_point()
                self.twoPointFinished.emit(False, "Đã hủy chế độ căn 2 điểm.")
            return
        step_map = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                    Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}
        if key not in step_map:
            return
        mupp = self.canvas.mapUnitsPerPixel()
        factor = 10.0 if event.modifiers() & Qt.ShiftModifier else 1.0
        dx, dy = step_map[key]
        p = self.item.placement
        self.editStarted.emit()
        p.set_center(p.cx + dx * mupp * factor, p.cy + dy * mupp * factor)
        self.item.set_placement(p)
        self.placementChanged.emit()
        event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_H and not event.isAutoRepeat():
            self._stop_peek()
            event.accept()

    def _stop_peek(self):
        if self._peeking:
            self._peeking = False
            self.peekChanged.emit(False)

    # ---------------------------------------------------------- các phép chỉnh
    def _do_move(self, map_pt, modifiers):
        sp = self._start_placement
        dx = map_pt.x() - self._start_map_pt.x()
        dy = map_pt.y() - self._start_map_pt.y()
        if modifiers & Qt.ShiftModifier:     # khóa theo trục ngang/dọc
            if abs(dx) > abs(dy):
                dy = 0.0
            else:
                dx = 0.0
        p = sp.clone()
        p.set_center(sp.cx + dx, sp.cy + dy)
        self.item.set_placement(p)

    def _do_scale(self, map_pt, modifiers):
        sp = self._start_placement
        a, b = self._axis_proj(map_pt, sp)   # chiều dài theo trục ngang / dọc của ảnh
        a -= self._grab_offset[0]
        b -= self._grab_offset[1]

        span_x = abs(HANDLE_UV[self._handle][0] - HANDLE_UV[OPPOSITE[self._handle]][0])
        span_y = abs(HANDLE_UV[self._handle][1] - HANDLE_UV[OPPOSITE[self._handle]][1])
        is_corner = span_x > 0 and span_y > 0

        # Tay nắm cạnh: chỉ đổi đúng một trục (X hoặc Y), trục kia giữ nguyên.
        # Tay nắm góc: đổi cả hai trục.
        sx, sy = sp.sx, sp.sy
        if span_x > 0:
            sx = abs(a) / (span_x * sp.width)
        if span_y > 0:
            sy = abs(b) / (span_y * sp.height)

        min_s = 1e-9
        sx = max(sx, min_s)
        sy = max(sy, min_s)

        if is_corner:
            # Chỉ tay nắm góc mới xét khóa tỉ lệ; Shift đảo ngược lựa chọn đó.
            lock = self.lock_aspect
            if modifiers & Qt.ShiftModifier:
                lock = not lock
            if lock:
                ratio = sp.aspect                  # sy / sx ban đầu
                sx = (sx + sy / ratio) / 2.0
                sy = sx * ratio

        p = sp.clone()
        p.anchor_at_pixel(self._anchor_pixel[0], self._anchor_pixel[1],
                          sx, sy, self._anchor_pt)
        self.item.set_placement(p)

    def _do_rotate(self, map_pt, modifiers):
        sp = self._start_placement
        now = self._angle_from_center(map_pt, sp)
        delta = math.degrees(now - self._start_angle)
        rot = sp.rotation + delta
        if modifiers & Qt.ShiftModifier:
            rot = round(rot / 15.0) * 15.0
        rot = (rot + 180.0) % 360.0 - 180.0
        p = sp.clone()
        p.rotation = rot
        self.item.set_placement(p)

    @staticmethod
    def _angle_from_center(map_pt, placement):
        return math.atan2(map_pt.y() - placement.cy, map_pt.x() - placement.cx)

    # ------------------------------------------------------------------ con trỏ
    def _update_cursor(self, handle):
        if handle is None:
            cursor = Qt.ArrowCursor
        elif handle == 'body':
            cursor = Qt.SizeAllCursor
        elif handle == 'rot':
            cursor = Qt.CrossCursor
        elif handle in ('tl', 'br'):
            cursor = Qt.SizeFDiagCursor
        elif handle in ('tr', 'bl'):
            cursor = Qt.SizeBDiagCursor
        elif handle in ('l', 'r'):
            cursor = Qt.SizeHorCursor
        else:
            cursor = Qt.SizeVerCursor
        self.canvas.setCursor(QCursor(cursor))
