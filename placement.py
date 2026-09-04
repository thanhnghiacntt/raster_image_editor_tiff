# -*- coding: utf-8 -*-
"""Mô hình toán học cho việc đặt ảnh lên bản đồ.

Quy ước:
  * pixel (px, py): gốc ở góc trên - trái của ảnh, py tăng khi đi xuống.
  * rotation: độ, dương = xoay ngược chiều kim đồng hồ trên bản đồ.
  * sx, sy: kích thước 1 pixel theo đơn vị bản đồ (luôn dương).
"""

import math

from qgis.core import QgsPointXY, QgsRectangle


class Placement:
    """Phép biến đổi affine (tịnh tiến + xoay + tỉ lệ) đưa ảnh vào hệ tọa độ bản đồ."""

    def __init__(self, cx, cy, sx, sy, rotation, width, height):
        self.cx = float(cx)
        self.cy = float(cy)
        self.sx = abs(float(sx)) or 1e-12
        self.sy = abs(float(sy)) or 1e-12
        self.rotation = float(rotation)
        self.width = int(width)
        self.height = int(height)

    # ------------------------------------------------------------------ utils
    def clone(self):
        return Placement(self.cx, self.cy, self.sx, self.sy,
                         self.rotation, self.width, self.height)

    def axes(self):
        """Trả về 2 vector đơn vị của hệ trục ảnh trong tọa độ bản đồ.

        ex: hướng cột tăng dần (sang phải trong ảnh)
        ey: hướng hàng giảm dần (lên trên trong ảnh)
        """
        rad = math.radians(self.rotation)
        c, s = math.cos(rad), math.sin(rad)
        return (c, s), (-s, c)

    @property
    def aspect(self):
        """Tỉ lệ sy/sx - dùng để khóa tỉ lệ khi co giãn."""
        return self.sy / self.sx

    # -------------------------------------------------------------- transform
    def pixel_to_map(self, px, py):
        ex, ey = self.axes()
        u = (px - self.width / 2.0) * self.sx
        v = -(py - self.height / 2.0) * self.sy
        return QgsPointXY(self.cx + ex[0] * u + ey[0] * v,
                          self.cy + ex[1] * u + ey[1] * v)

    def map_to_pixel(self, x, y):
        ex, ey = self.axes()
        dx, dy = x - self.cx, y - self.cy
        u = dx * ex[0] + dy * ex[1]
        v = dx * ey[0] + dy * ey[1]
        return (u / self.sx + self.width / 2.0,
                self.height / 2.0 - v / self.sy)

    def corners(self):
        """4 góc theo thứ tự: trên-trái, trên-phải, dưới-phải, dưới-trái."""
        w, h = self.width, self.height
        return [self.pixel_to_map(0, 0), self.pixel_to_map(w, 0),
                self.pixel_to_map(w, h), self.pixel_to_map(0, h)]

    def bbox(self):
        pts = self.corners()
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        return QgsRectangle(min(xs), min(ys), max(xs), max(ys))

    def geotransform(self):
        """GeoTransform 6 tham số của GDAL (hỗ trợ cả thành phần xoay)."""
        rad = math.radians(self.rotation)
        c, s = math.cos(rad), math.sin(rad)
        gt1 = self.sx * c
        gt2 = self.sy * s
        gt4 = self.sx * s
        gt5 = -self.sy * c
        gt0 = self.cx - (self.width / 2.0) * gt1 - (self.height / 2.0) * gt2
        gt3 = self.cy - (self.width / 2.0) * gt4 - (self.height / 2.0) * gt5
        return (gt0, gt1, gt2, gt3, gt4, gt5)

    # ---------------------------------------------------------------- helpers
    def set_center(self, x, y):
        self.cx, self.cy = float(x), float(y)

    def anchor_at_pixel(self, px, py, new_sx, new_sy, anchor_map_pt):
        """Đặt lại tỉ lệ sao cho pixel (px, py) đứng yên tại `anchor_map_pt`."""
        self.sx = abs(new_sx) or 1e-12
        self.sy = abs(new_sy) or 1e-12
        ex, ey = self.axes()
        u = (px - self.width / 2.0) * self.sx
        v = -(py - self.height / 2.0) * self.sy
        self.cx = anchor_map_pt.x() - (ex[0] * u + ey[0] * v)
        self.cy = anchor_map_pt.y() - (ex[1] * u + ey[1] * v)

    @staticmethod
    def fit_in_extent(extent, width, height, fill=0.7):
        """Đặt ảnh vào giữa `extent`, giữ nguyên tỉ lệ, chiếm `fill` phần khung."""
        if width <= 0 or height <= 0:
            width = height = 1
        avail_w = extent.width() * fill
        avail_h = extent.height() * fill
        if avail_w <= 0 or avail_h <= 0:
            avail_w = avail_h = 1.0
        s = min(avail_w / width, avail_h / height)
        return Placement(extent.center().x(), extent.center().y(),
                         s, s, 0.0, width, height)

    @staticmethod
    def from_two_points(base, img_pt_a, map_pt_a, img_pt_b, map_pt_b):
        """Tính vị trí mới từ 2 cặp điểm (điểm trên ảnh -> tọa độ thật).

        Dùng phép đồng dạng: tỉ lệ đều + xoay + tịnh tiến.
        `img_pt_a/b` là tọa độ pixel (px, py) trên ảnh.
        """
        w, h = base.width, base.height
        # Chuyển pixel sang hệ "ảnh có trục y hướng lên" đã chuẩn hóa quanh tâm.
        qa = (img_pt_a[0] - w / 2.0, -(img_pt_a[1] - h / 2.0))
        qb = (img_pt_b[0] - w / 2.0, -(img_pt_b[1] - h / 2.0))
        dq = (qb[0] - qa[0], qb[1] - qa[1])
        dm = (map_pt_b.x() - map_pt_a.x(), map_pt_b.y() - map_pt_a.y())
        len_q = math.hypot(*dq)
        len_m = math.hypot(*dm)
        if len_q < 1e-9 or len_m < 1e-12:
            raise ValueError("Hai điểm quá gần nhau, không tính được tỉ lệ.")
        scale = len_m / len_q
        rot = math.degrees(math.atan2(dm[1], dm[0]) - math.atan2(dq[1], dq[0]))
        rot = (rot + 180.0) % 360.0 - 180.0
        rad = math.radians(rot)
        c, s = math.cos(rad), math.sin(rad)
        # map = center + R * scale * q  =>  center = A' - R * scale * qa
        cx = map_pt_a.x() - scale * (c * qa[0] - s * qa[1])
        cy = map_pt_a.y() - scale * (s * qa[0] + c * qa[1])
        return Placement(cx, cy, scale, scale, rot, w, h)

    # ------------------------------------------------------------------- misc
    def to_dict(self):
        return {'cx': self.cx, 'cy': self.cy, 'sx': self.sx, 'sy': self.sy,
                'rotation': self.rotation, 'width': self.width, 'height': self.height}

    @staticmethod
    def from_dict(d):
        return Placement(d['cx'], d['cy'], d['sx'], d['sy'],
                         d['rotation'], d['width'], d['height'])

    def __repr__(self):
        return ("Placement(cx=%g, cy=%g, sx=%g, sy=%g, rot=%g, %dx%d)"
                % (self.cx, self.cy, self.sx, self.sy,
                   self.rotation, self.width, self.height))
