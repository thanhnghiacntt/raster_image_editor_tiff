# -*- coding: utf-8 -*-
"""Lớp plugin chính: gắn nút vào thanh công cụ và quản lý dock."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from .dock import RasterImageEditorTiffDock
from .resources import plugin_icon

MENU_TITLE = "&Raster Image Editor Tiff"


class RasterImageEditorTiffPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    # -------------------------------------------------------------- vòng đời
    def initGui(self):  # noqa: N802
        self.action = QAction(plugin_icon(),
                              "Raster Image Editor Tiff — căn ảnh & xuất GeoTIFF",
                              self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(MENU_TITLE, self.action)

    def unload(self):
        if self.dock is not None:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginRasterMenu(MENU_TITLE, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    # ----------------------------------------------------------------- dock
    def toggle_dock(self, checked):
        if checked:
            if self.dock is None:
                self.dock = RasterImageEditorTiffDock(
                    self.iface, self.iface.mainWindow())
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
                self.dock.visibilityChanged.connect(self._on_dock_visibility)
            self.dock.show()
            self.dock.raise_()
        elif self.dock is not None:
            self.dock.hide()

    def _on_dock_visibility(self, visible):
        if self.action is not None and self.action.isChecked() != visible:
            self.action.blockSignals(True)
            self.action.setChecked(visible)
            self.action.blockSignals(False)
