# -*- coding: utf-8 -*-
"""Ghép nhiều ảnh đã căn thành một GeoTIFF (mosaic).

Mỗi ảnh được đưa vào GDAL kèm GeoTransform riêng (có thể xoay) và kênh alpha,
rồi `gdal.Warp` đổ tất cả lên một lưới chung thẳng hướng Bắc. Ảnh đứng sau trong
danh sách đè lên ảnh đứng trước; phần trong suốt (góc ảnh xoay, nodata) không
đè lên ảnh bên dưới.
"""

import os

from osgeo import gdal

from .exporter import (_build_mem_dataset, _creation_options, crs_to_wkt,
                       qimage_to_array, write_world_file)
from .georef import fit_placement

gdal.UseExceptions()

MAX_MOSAIC_SIDE = 30000      # giới hạn cạnh dài nhất của file ghép (pixel)


def export_mosaic(entries, crs, out_path, dst_crs=None, resolution=None,
                  resample='bilinear', compression='DEFLATE', jpeg_quality=85,
                  keep_alpha=True, build_overviews=True, world_file=False,
                  max_side=MAX_MOSAIC_SIDE):
    """Ghép `entries` = [(QImage, Placement), …] theo thứ tự DƯỚI -> TRÊN.

    - `crs`: hệ tọa độ của các Placement.
    - `dst_crs`: hệ tọa độ file đầu ra (mặc định = `crs`).
    - `resolution`: cỡ pixel đầu ra; mặc định lấy ảnh mịn nhất.
    Trả về dict: đường dẫn, kích thước, cỡ pixel, có bị làm thô vì quá lớn không.
    """
    if not entries:
        raise ValueError("Không có ảnh nào để ghép.")
    if dst_crs is None or not dst_crs.isValid():
        dst_crs = crs
    src_wkt = crs_to_wkt(crs)
    dst_wkt = crs_to_wkt(dst_crs)

    use_jpeg = (compression or '').upper() == 'JPEG'
    with_alpha = keep_alpha and not use_jpeg

    sources = []
    for image, placement in entries:
        arr = qimage_to_array(image)          # luôn 4 băng; alpha là mặt nạ nguồn
        sources.append(_build_mem_dataset(arr, placement.geotransform(), src_wkt, 4))

    # Vị trí từng ảnh trong hệ đầu ra -> cỡ pixel mịn nhất + phạm vi hợp.
    fitted = [fit_placement(p.geotransform(), p.width, p.height, crs, dst_crs)[0]
              for _, p in entries]
    if resolution is None:
        resolution = min(min(p.sx, p.sy) for p in fitted)
    bounds = fitted[0].bbox()
    for p in fitted[1:]:
        bounds.combineExtentWith(p.bbox())

    # Kênh 4 là alpha của từng ảnh: khai báo rõ, vì với nhiều ảnh nguồn GDAL không
    # tự nhận ra và sẽ chép nó thành một băng dữ liệu thường.
    common = dict(srcSRS=src_wkt or None, dstSRS=dst_wkt or None,
                  resampleAlg=resample, srcAlpha=True, dstAlpha=with_alpha,
                  multithread=True,
                  warpOptions=None if with_alpha else ['INIT_DEST=255'])

    # Quá lớn thì làm thô cỡ pixel cho vừa giới hạn.
    width = bounds.width() / resolution
    height = bounds.height() / resolution
    coarsened = False
    if max(width, height) > max_side:
        resolution *= max(width, height) / float(max_side)
        coarsened = True

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    out = gdal.Warp(out_path, sources, format='GTiff', xRes=resolution,
                    yRes=resolution,
                    creationOptions=_creation_options(compression, jpeg_quality),
                    **common)
    if out is None:
        raise RuntimeError("GDAL không ghép được ảnh.")
    final_gt = out.GetGeoTransform()
    size = (out.RasterXSize, out.RasterYSize)
    out.FlushCache()
    out = None
    sources = None

    if build_overviews:
        ds = gdal.Open(out_path, gdal.GA_Update)
        levels, factor = [], 2
        while max(ds.RasterXSize, ds.RasterYSize) // factor >= 256 and factor <= 64:
            levels.append(factor)
            factor *= 2
        if levels:
            ds.BuildOverviews('AVERAGE', levels)
        ds = None
    if world_file:
        write_world_file(out_path, final_gt, dst_wkt)

    return {'path': out_path, 'size': size, 'resolution': resolution,
            'coarsened': coarsened, 'count': len(entries)}
