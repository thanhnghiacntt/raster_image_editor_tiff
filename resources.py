# -*- coding: utf-8 -*-
"""Truy xuất tài nguyên đi kèm plugin (biểu tượng…)."""

import os

from qgis.PyQt.QtGui import QIcon

PLUGIN_DIR = os.path.dirname(__file__)
ICON_DIR = os.path.join(PLUGIN_DIR, 'icons')

# Ưu tiên logo PNG; icon.svg chỉ là phương án dự phòng nếu thiếu file.
ICON_CANDIDATES = ('logo.png', 'icon.svg')

_cache = {}


def icon_path():
    """Đường dẫn tới file biểu tượng đầu tiên tìm được, hoặc None."""
    for name in ICON_CANDIDATES:
        path = os.path.join(ICON_DIR, name)
        if os.path.exists(path):
            return path
    return None


def plugin_icon():
    """QIcon của plugin, dùng chung cho nút công cụ, menu, dock và hộp thoại."""
    if 'icon' not in _cache:
        path = icon_path()
        _cache['icon'] = QIcon(path) if path else QIcon()
    return _cache['icon']
