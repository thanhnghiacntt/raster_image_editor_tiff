# -*- coding: utf-8 -*-
"""Ghi ảnh đã căn ra file GeoTIFF (kèm world file, nén, xoay về hướng Bắc)."""

import os

import numpy as np
from osgeo import gdal, osr
from qgis.PyQt.QtGui import QImage

gdal.UseExceptions()

RESAMPLE_ALGS = ['near', 'bilinear', 'cubic', 'cubicspline', 'lanczos', 'average']
COMPRESSIONS = ['DEFLATE', 'LZW', 'ZSTD', 'JPEG', 'NONE']


def qimage_to_array(image):
    """QImage -> mảng numpy (h, w, 4) kiểu uint8 theo thứ tự R, G, B, A."""
    img = image.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    try:
        nbytes = img.sizeInBytes()
    except AttributeError:                     # Qt < 5.10
        nbytes = img.byteCount()
    ptr.setsize(nbytes)
    bpl = img.bytesPerLine()
    try:
        buf = np.frombuffer(memoryview(ptr), dtype=np.uint8, count=nbytes)
    except (TypeError, ValueError):            # sip.voidptr cũ
        buf = np.frombuffer(ptr.asstring(nbytes), dtype=np.uint8)
    return buf.reshape(h, bpl)[:, :w * 4].reshape(h, w, 4).copy()


def _creation_options(compression, jpeg_quality, tiled=True):
    opts = ['BIGTIFF=IF_SAFER']
    if tiled:
        opts += ['TILED=YES', 'BLOCKXSIZE=256', 'BLOCKYSIZE=256']
    if compression and compression.upper() != 'NONE':
        opts.append('COMPRESS=%s' % compression.upper())
        if compression.upper() == 'JPEG':
            opts.append('JPEG_QUALITY=%d' % int(jpeg_quality))
            opts.append('PHOTOMETRIC=YCBCR')
        elif compression.upper() in ('DEFLATE', 'ZSTD', 'LZW'):
            opts.append('PREDICTOR=2')
    return opts


def _build_mem_dataset(arr, geotransform, wkt, nbands):
    h, w = arr.shape[0], arr.shape[1]
    ds = gdal.GetDriverByName('MEM').Create('', w, h, nbands, gdal.GDT_Byte)
    ds.SetGeoTransform([float(v) for v in geotransform])
    if wkt:
        ds.SetProjection(wkt)
    interps = [gdal.GCI_RedBand, gdal.GCI_GreenBand,
               gdal.GCI_BlueBand, gdal.GCI_AlphaBand]
    for i in range(nbands):
        band = ds.GetRasterBand(i + 1)
        band.WriteArray(arr[:, :, i])
        band.SetColorInterpretation(interps[i])
    return ds


def write_world_file(path, geotransform, wkt=None):
    """Ghi file .tfw (+ .prj) tương ứng với GeoTIFF vừa xuất."""
    gt = geotransform
    base = os.path.splitext(path)[0]
    lines = [gt[1], gt[4], gt[2], gt[5],
             gt[0] + 0.5 * gt[1] + 0.5 * gt[2],
             gt[3] + 0.5 * gt[4] + 0.5 * gt[5]]
    with open(base + '.tfw', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join('%.12f' % v for v in lines) + '\n')
    if wkt:
        with open(base + '.prj', 'w', encoding='utf-8') as fh:
            fh.write(wkt)


def export_geotiff(image, placement, crs, out_path,
                   compression='DEFLATE', jpeg_quality=85,
                   north_up=False, resample='bilinear',
                   keep_alpha=True, build_overviews=True,
                   world_file=False):
    """Xuất `image` (QImage) đã căn theo `placement` ra GeoTIFF tại `out_path`.

    - `crs`: QgsCoordinateReferenceSystem của dự án.
    - `north_up`: nếu ảnh có góc xoay, nắn lại thành ảnh thẳng hướng Bắc
      (ảnh sẽ được nội suy lại); nếu False, góc xoay được ghi thẳng vào
      GeoTransform của GeoTIFF (không mất chất lượng).
    Trả về đường dẫn file đã ghi.
    """
    arr = qimage_to_array(image)
    gt = placement.geotransform()

    wkt = ''
    if crs is not None and crs.isValid():
        wkt = crs.toWkt()
        srs = osr.SpatialReference()
        if srs.SetFromUserInput(wkt) == 0:
            wkt = srs.ExportToWkt()

    use_jpeg = (compression or '').upper() == 'JPEG'
    nbands = 3 if (use_jpeg or not keep_alpha) else 4
    if nbands == 3:
        # Trộn ảnh lên nền trắng để phần trong suốt không bị đen.
        alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
        rgb = arr[:, :, :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)
        arr = np.clip(rgb, 0, 255).astype(np.uint8)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    src = _build_mem_dataset(arr, gt, wkt, nbands)
    co = _creation_options(compression, jpeg_quality)
    rotated = abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12

    try:
        if north_up and rotated:
            warp_opts = gdal.WarpOptions(
                format='GTiff',
                creationOptions=co,
                resampleAlg=resample,
                dstAlpha=(nbands == 4),
                warpOptions=None if nbands == 4 else ['INIT_DEST=255'],
                multithread=True,
                srcSRS=wkt or None,
                dstSRS=wkt or None,
            )
            out = gdal.Warp(out_path, src, options=warp_opts)
        else:
            out = gdal.GetDriverByName('GTiff').CreateCopy(out_path, src, 0, co)
        if out is None:
            raise RuntimeError('GDAL không tạo được file: %s' % out_path)
        final_gt = out.GetGeoTransform()
        out.FlushCache()
        out = None
    finally:
        src = None

    if build_overviews:
        ds = gdal.Open(out_path, gdal.GA_Update)
        if ds is not None:
            levels = []
            factor = 2
            while max(ds.RasterXSize, ds.RasterYSize) // factor >= 256 and factor <= 64:
                levels.append(factor)
                factor *= 2
            if levels:
                ds.BuildOverviews('AVERAGE', levels)
            ds = None

    if world_file:
        write_world_file(out_path, final_gt, wkt)

    return out_path
