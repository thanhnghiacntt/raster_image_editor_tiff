# Nhật ký thay đổi — Raster Image Editor Tiff

## 1.2.0

### Tính năng mới: làm việc với nhiều ảnh
- Nạp nhiều ảnh (chọn nhiều file một lúc). Mục *1. Ảnh nguồn* có danh sách ảnh: chọn ảnh cần
  chỉnh, ô đánh dấu hiện/ẩn, nút *Lên / Xuống* đổi thứ tự chồng, *Phóng tới*, *Gỡ ảnh*.
- Bấm vào một ảnh trên bản đồ là chọn và kéo được ảnh đó ngay. Ảnh đang chọn có khung đỏ, tay nắm
  luôn nổi trên cùng dù bị ảnh khác đè; ảnh khác có khung vàng nét đứt và nhãn số thứ tự.
- Mỗi ảnh có vị trí, độ mờ, lịch sử hoàn tác (Ctrl+Z / Ctrl+Y) riêng.
- Kiểu xuất mới ở mục *4*: ghép các ảnh đang hiện thành một GeoTIFF (mặc định từ ảnh thứ 2),
  mỗi ảnh ra một file riêng, hoặc chỉ ảnh đang chọn.
- Ghép ảnh: lưới chung thẳng hướng Bắc, độ phân giải theo ảnh mịn nhất, ảnh trên đè ảnh dưới,
  góc trong suốt của ảnh xoay không đè lên ảnh khác; dùng được mọi hệ tọa độ đầu ra.
- Xuất tile lấy tất cả ảnh đang hiện.
- Đổi hệ tọa độ bản đồ thì mọi ảnh (và lịch sử hoàn tác của từng ảnh) được dời theo.

### Thay đổi trong mã nguồn

| File | Chỗ thay đổi |
|---|---|
| `mosaic.py` | **File mới.** `export_mosaic()` ghép nhiều ảnh bằng `gdal.Warp` (khai báo `srcAlpha` để GDAL coi kênh 4 là mặt nạ). |
| `dock.py` | Lớp `ImageLayer` (ảnh + lịch sử riêng); danh sách `layers` / ảnh đang chọn `active`; `item`, `_undo`, `_redo`, `_aspect` thành thuộc tính theo ảnh đang chọn. Giao diện danh sách ảnh + nút; ô *Xuất*. Hàm mới: `load_images()`, `_add_layer()`, `set_active()`, `move_active()`, `remove_active_image()`, `export_mode()`, `_export_targets()`; `clear_image()` gỡ tất cả; `do_export()` xử lý 3 kiểu xuất; `_on_map_crs_changed()` quy đổi mọi ảnh. |
| `overlay.py` | Tách `paint()` thành `paint_image()` / `paint_decorations()`; thêm `paint_outline()`, `paint_label()`, `contains()`; lớp mới `FrameOverlayItem` vẽ khung + tay nắm trên cùng. |
| `maptool.py` | `set_item()` đổi ảnh đang chỉnh; `find_item_at` + tín hiệu `activateRequested` để bấm chọn ảnh khác trên bản đồ. |
| `tiledialog.py` | Nhận danh sách `items`; nướng từng ảnh thành lớp tạm; phạm vi = hợp các ảnh. |
| `metadata.txt`, `README.md` | Phiên bản 1.2.0, mô tả tính năng. |

## 1.1.0

### Tính năng mới

**Chọn hệ tọa độ cho file GeoTIFF xuất ra**
- Mục *4. Xuất GeoTIFF* có bộ chọn CRS của QGIS (EPSG:4326, EPSG:3857, VN-2000…) và các nút
  nhanh *Theo bản đồ*, *EPSG:4326*, *EPSG:3857*.
- Trùng hệ của bản đồ: góc xoay ghi thẳng vào GeoTransform, không nội suy.
- Khác hệ: ảnh được chiếu lại bằng `gdal.Warp`, luôn thẳng hướng Bắc, theo thuật toán nội suy
  đã chọn. File `.prj` đi kèm theo hệ đầu ra.

**Nạp ảnh đã có tọa độ thì đặt đúng vị trí**
- Đọc GeoTransform, GCP và CRS trong GeoTIFF, ảnh kèm world file (`.tfw`, `.pgw`, `.jgw`…).
- Bản đồ tự phóng tới ảnh; hệ tọa độ đầu ra mặc định theo file gốc.
- Đọc được ảnh 16 bit / số thực (tự co giãn độ sáng), ảnh bảng màu, nodata (thành trong suốt),
  file lưu từ dưới lên (tự lật lại). Ảnh trên 8000 pixel được đọc thu nhỏ.
- File khác hệ tọa độ với bản đồ: lệch dưới 0,5 pixel thì tự quy đổi; lệch nhiều hơn thì hỏi
  *chiếu lại ảnh* / *đổi CRS dự án* / *đặt gần đúng* / *hủy*.

### Sửa lỗi
- Đổi hệ tọa độ dự án khi đang có ảnh làm ảnh lệch khỏi chỗ. Nay ảnh và cả lịch sử hoàn tác
  được quy đổi theo.
- Hộp thoại xuất tile tính phạm vi theo hệ tọa độ của ảnh thay vì luôn lấy CRS dự án.

### Thay đổi trong mã nguồn

| File | Chỗ thay đổi |
|---|---|
| `georef.py` | **File mới.** `read_raster()` đọc ảnh + tọa độ; `gdal_dataset_to_qimage()` chuyển raster GDAL sang ảnh 8 bit; `normalize_orientation()` lật ảnh lưu ngược; `placement_from_geotransform()`; `fit_placement()` khớp vị trí sang CRS bản đồ và đo sai lệch theo pixel; `placement_to_crs()`; `warp_to_crs()` chiếu lại ảnh. |
| `exporter.py` | Thêm `crs_to_wkt()`. `export_geotiff()` có thêm tham số `dst_crs`; chiếu lại khi khác hệ; `.prj` ghi theo hệ đầu ra. |
| `dock.py` | Thêm `QUICK_CRS`, `crs_name()`; mở rộng bộ lọc file ảnh. Mục 3: nhãn hệ tọa độ bản đồ chuyển lên đầu. Mục 4: bộ chọn CRS `crs_out`, nút nhanh, dòng ghi chú. Viết lại `_load_image()`; thêm `_place_georeferenced()`, `_ask_georef_choice()`; nhóm hàm hệ tọa độ `_map_crs()`, `_placement_crs`, `_set_map_crs()`, `_on_map_crs_changed()`, `_convert_state()`, `_on_northup_toggled()`, `_on_out_crs_changed()`; `do_export()` truyền `dst_crs`; lắng nghe `destinationCrsChanged` của bản đồ. |
| `tiledialog.py` | Thêm `_map_crs()`, `_image_crs()`, `_extent_crs()` và dùng trong `_extent_3857()`, `_bake_image_layer()`, `build_metadata()`. |
| `metadata.txt` | `version=1.1.0`, thêm `changelog`, cập nhật `about`. |
| `README.md` | Mô tả tính năng mới, cách dùng, ghi chú kỹ thuật, giới hạn. |

Các file không đổi: `__init__.py`, `plugin.py`, `placement.py`, `overlay.py`, `maptool.py`,
`tiles.py`, `resources.py`, `install.ps1`, `icons/`.

## 1.0.0
- Phát hành đầu tiên.
