# -*- coding: utf-8 -*-
"""Item vẽ ảnh lên canvas của QGIS kèm các tay nắm (handle) để chỉnh."""

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen, QTransform
from qgis.gui import QgsMapCanvasItem

HANDLE_SIZE = 9          # cạnh hình vuông tay nắm (pixel màn hình)
HANDLE_TOLERANCE = 11    # bán kính bắt chuột cho tay nắm góc / nút xoay
EDGE_TOLERANCE = 9       # bề rộng vùng bắt chuột dọc theo cả cạnh
ROTATE_OFFSET = 34       # khoảng cách nút xoay so với cạnh trên
VIEW_MARGIN = 20         # chừa mép khi kéo tay nắm cạnh về vùng nhìn thấy
EXTRA_MARKER_MIN = 90    # cạnh nhìn thấy dài hơn ngần này thì vẽ thêm dấu phụ

# Tên tay nắm góc/cạnh -> vị trí tương đối (0..1) trên ảnh
HANDLE_UV = {
    'tl': (0.0, 0.0), 'tr': (1.0, 0.0), 'br': (1.0, 1.0), 'bl': (0.0, 1.0),
    't': (0.5, 0.0), 'r': (1.0, 0.5), 'b': (0.5, 1.0), 'l': (0.0, 0.5),
}
CORNERS = ('tl', 'tr', 'br', 'bl')
EDGES = ('t', 'r', 'b', 'l')
# Tay nắm đối diện (điểm neo đứng yên khi co giãn)
OPPOSITE = {'tl': 'br', 'br': 'tl', 'tr': 'bl', 'bl': 'tr',
            't': 'b', 'b': 't', 'l': 'r', 'r': 'l'}
# Cạnh -> chỉ số 2 góc tạo nên cạnh đó trong danh sách [TL, TR, BR, BL]
EDGE_ENDS = {'t': (0, 1), 'r': (1, 2), 'b': (2, 3), 'l': (3, 0)}

MAX_PREVIEW_PX = 2600    # ảnh lớn hơn sẽ được thu nhỏ để vẽ cho mượt

COL_OUTLINE = QColor(255, 40, 40)
COL_HOVER = QColor(0, 150, 255)
COL_OTHER = QColor(255, 210, 0)       # khung các ảnh không được chọn


def _clip_segment(p0, p1, rect):
    """Cắt đoạn thẳng p0->p1 theo hình chữ nhật (Liang-Barsky).

    Trả về (t0, t1) là khoảng tham số còn lại, hoặc None nếu nằm hẳn ngoài.
    """
    dx = p1.x() - p0.x()
    dy = p1.y() - p0.y()
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p0.x() - rect.left()), (dx, rect.right() - p0.x()),
                 (-dy, p0.y() - rect.top()), (dy, rect.bottom() - p0.y())):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                t0 = max(t0, r)
            else:
                if r < t0:
                    return None
                t1 = min(t1, r)
    return (t0, t1) if t1 >= t0 else None


def _dist_to_segment(pt, a, b):
    vx, vy = b.x() - a.x(), b.y() - a.y()
    len2 = vx * vx + vy * vy
    if len2 < 1e-12:
        return ((pt.x() - a.x()) ** 2 + (pt.y() - a.y()) ** 2) ** 0.5
    t = ((pt.x() - a.x()) * vx + (pt.y() - a.y()) * vy) / len2
    t = max(0.0, min(1.0, t))
    cx, cy = a.x() + t * vx, a.y() + t * vy
    return ((pt.x() - cx) ** 2 + (pt.y() - cy) ** 2) ** 0.5


class ImageOverlayItem(QgsMapCanvasItem):
    """Vẽ ảnh theo `Placement` hiện tại; luôn nằm trên tất cả các lớp."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self.image = None          # QImage gốc (dùng khi xuất file)
        self._preview = None       # QImage thu nhỏ (dùng để vẽ)
        self.placement = None
        self.image_opacity = 1.0
        self.show_handles = True
        self.show_image = True     # tắt để so sánh với nền bên dưới
        self.hover = None          # tên tay nắm con trỏ đang rê tới
        # False khi có FrameOverlayItem vẽ khung/tay nắm lên trên mọi ảnh.
        self.draw_decorations = True
        self.label = ''            # tên hiện cạnh khung khi có nhiều ảnh
        self.listeners = []        # hàm gọi lại mỗi khi ảnh đổi (để vẽ lại khung)
        self.setZValue(1000)
        self.setPos(QPointF(0, 0))

    def _notify(self):
        self.update()
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                pass

    # ------------------------------------------------------------------ nạp ảnh
    def set_image(self, image):
        self.image = image
        if image is None or image.isNull():
            self.image = None
            self._preview = None
        elif max(image.width(), image.height()) > MAX_PREVIEW_PX:
            self._preview = image.scaled(MAX_PREVIEW_PX, MAX_PREVIEW_PX,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            self._preview = image
        self.prepareGeometryChange()
        self._notify()

    def set_placement(self, placement):
        self.placement = placement
        self.prepareGeometryChange()
        self._notify()

    def set_opacity_value(self, value):
        self.image_opacity = max(0.0, min(1.0, float(value)))
        self._notify()

    def set_show_handles(self, state):
        self.show_handles = bool(state)
        self._notify()

    def set_image_visible(self, state):
        """Bật/tắt phần ảnh; khung viền và tay nắm vẫn giữ nguyên."""
        if bool(state) != self.show_image:
            self.show_image = bool(state)
            self._notify()

    def set_hover(self, name):
        if name != self.hover:
            self.hover = name
            self._notify()

    def has_image(self):
        return self.image is not None and self.placement is not None

    # ------------------------------------------------------- QGraphicsItem API
    def boundingRect(self):
        # Luôn phủ toàn bộ khung nhìn -> không bao giờ bị cắt khi kéo/xoay.
        rect = QRectF(0, 0, self._canvas.width(), self._canvas.height())
        return rect.adjusted(-80, -80, 80, 80).translated(-self.pos())

    def updatePosition(self):
        # Ảnh được vẽ trực tiếp bằng tọa độ canvas nên item luôn nằm ở gốc.
        self.setPos(QPointF(0, 0))
        self.prepareGeometryChange()
        self.update()

    # ----------------------------------------------------------------- hình học
    def canvas_corners(self):
        """4 góc ảnh ở tọa độ canvas (QPointF): TL, TR, BR, BL."""
        if self.placement is None:
            return None
        off = self.pos()
        return [self.toCanvasCoordinates(p) - off for p in self.placement.corners()]

    def _view_rect(self):
        m = VIEW_MARGIN
        return QRectF(m, m,
                      max(1.0, self._canvas.width() - 2 * m),
                      max(1.0, self._canvas.height() - 2 * m))

    def visible_edge_span(self, name, corners=None):
        """Đoạn của cạnh `name` còn nằm trong khung nhìn, dạng (điểm đầu, điểm cuối).

        Trả về None nếu cạnh nằm hẳn ngoài màn hình.
        """
        corners = corners or self.canvas_corners()
        if not corners:
            return None
        i, j = EDGE_ENDS[name]
        a, b = corners[i], corners[j]
        clipped = _clip_segment(a, b, self._view_rect())
        if clipped is None:
            return None
        t0, t1 = clipped
        d = b - a
        return a + d * t0, a + d * t1

    def _edge_handle_point(self, name, corners):
        """Chỗ đặt tay nắm của một cạnh.

        Ưu tiên đúng điểm giữa cạnh cho ổn định; nếu điểm đó bị ra ngoài màn
        hình (thường gặp khi phóng to) thì lùi về giữa phần cạnh còn nhìn thấy.
        Trả về None khi cạnh nằm hẳn ngoài khung nhìn.
        """
        i, j = EDGE_ENDS[name]
        true_mid = (corners[i] + corners[j]) / 2.0
        if self._view_rect().contains(true_mid):
            return true_mid
        span = self.visible_edge_span(name, corners)
        if span is None:
            return None
        return (span[0] + span[1]) / 2.0

    def handle_points(self):
        """dict: tên tay nắm -> QPointF trên canvas.

        Tay nắm góc nằm đúng ở góc ảnh. Cạnh nào ra khỏi màn hình hoàn toàn
        thì không có trong dict.
        """
        corners = self.canvas_corners()
        if corners is None:
            return {}
        out = {}
        for idx, name in enumerate(CORNERS):
            out[name] = corners[idx]
        for name in EDGES:
            pt = self._edge_handle_point(name, corners)
            if pt is not None:
                out[name] = pt

        # Nút xoay: nhô ra ngoài cạnh trên, theo hướng "lên" của ảnh.
        if 't' in out:
            up = corners[0] - corners[3]          # TL - BL
            length = (up.x() ** 2 + up.y() ** 2) ** 0.5
            if length > 1e-6:
                out['rot'] = out['t'] + up * (ROTATE_OFFSET / length)
        return out

    def edge_markers(self, name, corners=None):
        """Các dấu vẽ dọc cạnh, để lộ rõ là kéo được ở bất kỳ đâu trên cạnh."""
        corners = corners or self.canvas_corners()
        if not corners:
            return []
        main = self._edge_handle_point(name, corners)
        if main is None:
            return []
        span = self.visible_edge_span(name, corners)
        if span is None:
            return [main]
        a, b = span
        d = b - a
        length = (d.x() ** 2 + d.y() ** 2) ** 0.5
        if length < EXTRA_MARKER_MIN:
            return [main]
        return [a + d * 0.15, main, a + d * 0.85]

    @staticmethod
    def _image_transform(corners, img_w, img_h):
        """QTransform đưa hệ pixel của ảnh sang hệ pixel canvas."""
        tl, tr, _br, bl = corners
        ex = (tr - tl) / float(img_w)
        ey = (bl - tl) / float(img_h)
        return QTransform(ex.x(), ex.y(), ey.x(), ey.y(), tl.x(), tl.y())

    # ----------------------------------------------------------------- vẽ hình
    def paint(self, painter, option=None, widget=None):
        self.paint_image(painter)
        if self.draw_decorations:
            self.paint_decorations(painter)

    def paint_image(self, painter):
        if self._preview is None or self.placement is None or not self.show_image:
            return
        corners = self.canvas_corners()
        if corners is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(self.image_opacity)
        painter.setTransform(
            self._image_transform(corners, self._preview.width(),
                                  self._preview.height()),
            True)
        painter.drawImage(QPointF(0, 0), self._preview)
        painter.restore()

    def paint_outline(self, painter):
        """Khung mảnh nét đứt + nhãn tên, dùng cho các ảnh không được chọn."""
        corners = self.canvas_corners() if self.placement is not None else None
        if not corners or self._preview is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(1.0)
        painter.setBrush(Qt.NoBrush)
        under = QPen(QColor(0, 0, 0, 160), 3)
        under.setCosmetic(True)
        painter.setPen(under)
        painter.drawPolygon(*corners)
        pen = QPen(COL_OTHER, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPolygon(*corners)
        painter.restore()
        self.paint_label(painter, COL_OTHER)

    def paint_label(self, painter, color):
        if not self.label:
            return
        corners = self.canvas_corners()
        if not corners:
            return
        # Đặt nhãn phía TRÊN góc cao nhất trên màn hình, nằm ngoài ảnh để không
        # che mất chi tiết đang cần căn.
        anchor = min(corners, key=lambda c: (c.y(), c.x()))
        painter.save()
        font = QFont()
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        w = fm.boundingRect(self.label).width()
        h = fm.height() + 4
        box = QRectF(anchor.x() - 4, anchor.y() - h - 6, w + 10, h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 170)))
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QPen(color))
        painter.drawText(box, Qt.AlignCenter, self.label)
        painter.restore()

    def paint_decorations(self, painter):
        """Khung đỏ, tay nắm, nút xoay của ảnh đang được chỉnh."""
        if not self.show_handles or self._preview is None or self.placement is None:
            return
        corners = self.canvas_corners()
        if corners is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(1.0)

        # Khung viền: cả cạnh đều là vùng kéo được nên vẽ đậm; cạnh đang rê
        # chuột tới thì tô sáng lên.
        for name in EDGES:
            i, j = EDGE_ENDS[name]
            active = (self.hover == name)
            pen = QPen(COL_HOVER if active else COL_OUTLINE, 5 if active else 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(corners[i], corners[j])

        handles = self.handle_points()

        # Cần xoay
        if 'rot' in handles and 't' in handles:
            painter.setPen(QPen(COL_OUTLINE, 1, Qt.DashLine))
            painter.drawLine(handles['t'], handles['rot'])

        half = HANDLE_SIZE / 2.0
        # Dấu phụ dọc cạnh
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        for name in EDGES:
            active = (self.hover == name)
            painter.setBrush(QBrush(COL_HOVER if active else QColor(255, 255, 255)))
            for p in self.edge_markers(name, corners):
                painter.drawRect(QRectF(p.x() - half, p.y() - half,
                                        HANDLE_SIZE, HANDLE_SIZE))
        # Tay nắm góc
        for name in CORNERS:
            active = (self.hover == name)
            painter.setBrush(QBrush(COL_HOVER if active else QColor(255, 255, 255)))
            p = handles[name]
            s = HANDLE_SIZE + (3 if active else 0)
            painter.drawRect(QRectF(p.x() - s / 2.0, p.y() - s / 2.0, s, s))
        # Nút xoay
        if 'rot' in handles:
            active = (self.hover == 'rot')
            painter.setBrush(QBrush(COL_HOVER if active else QColor(80, 200, 120)))
            painter.drawEllipse(handles['rot'], half + (3 if active else 1),
                                half + (3 if active else 1))
        painter.restore()
        self.paint_label(painter, COL_OUTLINE)

    # ------------------------------------------------------------ bắt sự kiện
    def hit_test(self, canvas_pt):
        """Tên tay nắm dưới con trỏ, 'body' nếu trong ảnh, None nếu ở ngoài.

        Thứ tự ưu tiên: nút xoay -> góc -> tay nắm cạnh -> bất kỳ điểm nào
        dọc theo cạnh -> thân ảnh.
        """
        if not self.has_image() or not self.show_handles:
            return None
        corners = self.canvas_corners()
        if not corners:
            return None
        handles = self.handle_points()

        def dist(p):
            return ((p.x() - canvas_pt.x()) ** 2 + (p.y() - canvas_pt.y()) ** 2) ** 0.5

        if 'rot' in handles and dist(handles['rot']) <= HANDLE_TOLERANCE:
            return 'rot'

        best, best_d = None, float(HANDLE_TOLERANCE)
        for name in CORNERS:
            d = dist(handles[name])
            if d <= best_d:
                best, best_d = name, d
        if best:
            return best

        best, best_d = None, float(HANDLE_TOLERANCE)
        for name in EDGES:
            if name in handles:
                d = dist(handles[name])
                if d <= best_d:
                    best, best_d = name, d
        if best:
            return best

        # Kéo được ở bất kỳ đâu dọc theo cạnh, không cần đúng tay nắm.
        best, best_d = None, float(EDGE_TOLERANCE)
        for name in EDGES:
            i, j = EDGE_ENDS[name]
            d = _dist_to_segment(canvas_pt, corners[i], corners[j])
            if d <= best_d:
                best, best_d = name, d
        if best:
            return best

        return 'body' if self._point_inside(canvas_pt) else None

    def contains(self, canvas_pt):
        """Điểm trên canvas có nằm trong ảnh không (không phụ thuộc tay nắm)."""
        return self.has_image() and self._point_inside(canvas_pt)

    def _point_inside(self, pt):
        corners = self.canvas_corners()
        if not corners:
            return False
        # Điểm nằm trong tứ giác lồi <=> mọi tích có hướng cùng dấu.
        sign = 0
        n = len(corners)
        for i in range(n):
            a, b = corners[i], corners[(i + 1) % n]
            cross = ((b.x() - a.x()) * (pt.y() - a.y())
                     - (b.y() - a.y()) * (pt.x() - a.x()))
            if abs(cross) < 1e-9:
                continue
            s = 1 if cross > 0 else -1
            if sign == 0:
                sign = s
            elif s != sign:
                return False
        return True


class FrameOverlayItem(QgsMapCanvasItem):
    """Vẽ khung + tay nắm của mọi ảnh lên TRÊN CÙNG.

    Khi nhiều ảnh chồng nhau, tay nắm của ảnh đang chọn sẽ bị ảnh nằm trên che
    mất nếu vẽ chung với ảnh; item này luôn ở trên nên tay nắm luôn nhìn thấy.
    `items_provider()` trả về danh sách (item, đang_chọn).
    """

    def __init__(self, canvas, items_provider):
        super().__init__(canvas)
        self._canvas = canvas
        self.items_provider = items_provider
        self.setZValue(5000)
        self.setPos(QPointF(0, 0))

    def boundingRect(self):
        rect = QRectF(0, 0, self._canvas.width(), self._canvas.height())
        return rect.adjusted(-80, -80, 80, 80).translated(-self.pos())

    def updatePosition(self):
        self.setPos(QPointF(0, 0))
        self.prepareGeometryChange()
        self.update()

    def paint(self, painter, option=None, widget=None):
        entries = list(self.items_provider())
        active = [it for it, is_active in entries if is_active]
        if not active or not active[0].show_handles:
            return
        for it, is_active in entries:
            if not is_active and it.has_image():
                it.paint_outline(painter)
        active[0].paint_decorations(painter)
