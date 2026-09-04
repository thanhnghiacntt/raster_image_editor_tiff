# -*- coding: utf-8 -*-
"""Raster Image Editor Tiff - QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 (tên do QGIS quy định)
    from .plugin import RasterImageEditorTiffPlugin
    return RasterImageEditorTiffPlugin(iface)
