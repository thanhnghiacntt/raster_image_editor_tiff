# Raster Image Editor Tiff — plugin QGIS

Đưa một ảnh thường (PNG/JPG/TIF… chưa có tọa độ) lên bản đồ QGIS, **kéo – xoay – co giãn
bằng chuột** cho khớp đúng vị trí thật, rồi **xuất ra file GeoTIFF** có hệ tọa độ.

## Tính năng

| Nhóm | Chi tiết |
|---|---|
| Nạp ảnh | PNG, JPG, TIF, BMP, GIF, WEBP. Ảnh lớn được thu nhỏ khi hiển thị cho mượt, khi xuất vẫn dùng ảnh gốc. |
| Chỉnh bằng chuột | Kéo giữa ảnh để **di chuyển**; kéo **bất kỳ điểm nào trên một cạnh** để co giãn **riêng theo trục X hoặc Y**; kéo ô vuông ở **góc** để co giãn **cả hai trục**; kéo nút tròn xanh phía trên để **xoay**. Cạnh đang rê chuột tới sẽ sáng lên màu xanh. Điểm neo (cạnh/góc đối diện) luôn đứng yên, kể cả khi ảnh đang xoay, và ảnh không bị nhảy khi bấm hơi lệch khỏi đường viền. |
| Khi phóng to | Tay nắm cạnh nằm ở giữa cạnh khi còn nhìn thấy; nếu điểm giữa bị ra ngoài màn hình thì tay nắm tự lùi về giữa phần cạnh còn hiển thị. Cạnh nằm hẳn ngoài khung nhìn thì ẩn tay nắm. Không phải thu nhỏ lại chỉ để với tới tay nắm. |
| Phím tắt | `Ctrl+Z` = hoàn tác · `Ctrl+Y` (hoặc `Ctrl+Shift+Z`) = làm lại · `Shift` khi kéo = khóa theo trục ngang/dọc · `Shift` khi kéo **góc** = đảo trạng thái khóa tỉ lệ · `Shift` khi xoay = bắt góc 15° · phím **mũi tên** = dịch từng pixel (giữ `Shift` = 10 pixel) · giữ `H` = tạm giấu ảnh để nhìn nền · `Esc` = hủy chế độ căn 2 điểm. |
| Căn theo 2 điểm | Bấm 1 điểm nhận biết trên ảnh → bấm vị trí thật của nó trên bản đồ → làm tiếp với điểm thứ 2. Plugin tự tính tịnh tiến + xoay + tỉ lệ (phép đồng dạng). Điểm đích **bám dính (snap)** theo cấu hình snapping của dự án. |
| Nhập tọa độ tay | Tâm ảnh X/Y, kích thước 1 pixel theo X/Y, góc xoay — nhập số trực tiếp. |
| Hoàn tác / Làm lại | `Ctrl+Z` và `Ctrl+Y` (hoặc 2 nút trên bảng điều khiển), 60 bước mỗi chiều. Áp dụng cho cả kéo chuột, nhập số, *Vừa khung nhìn* và *Căn theo 2 điểm*. Bấm chuột mà không kéo thì không ghi vào lịch sử. Khi công cụ đang bật, plugin giành lại `Ctrl+Z` từ menu *Edit* của QGIS. |
| So sánh với nền | Ô **Hiện ảnh trên bản đồ** để bật/tắt phần ảnh — khung viền đỏ và các tay nắm vẫn còn nên vẫn kéo chỉnh được khi đang ẩn. Hoặc **giữ phím `H`** để giấu tạm, thả ra là hiện lại (không làm đổi trạng thái ô đánh dấu). Kèm thanh trượt **độ mờ** để chồng mờ ảnh lên nền. |
| Hỗ trợ | Khóa tỉ lệ (chỉ áp dụng cho tay nắm góc và ô nhập số — tay nắm cạnh luôn co giãn tự do một trục), *Vừa khung nhìn*. |
| Xuất GeoTIFF | Nén DEFLATE/LZW/ZSTD/JPEG/không nén, giữ kênh alpha, tạo overview, ghi kèm world file `.tfw` + `.prj`, tự thêm vào bản đồ. |
| Xuất bộ tile | Cắt thành tile Web Mercator (EPSG:3857) như plugin *QTiles*: nguồn là **ảnh đã căn**, **ảnh + các lớp đang hiện** hoặc **chỉ các lớp**; phạm vi theo ảnh / khung nhìn / toàn bộ lớp; chọn dải zoom, ô 256 hay 512 px, PNG hoặc JPG. Đầu ra: **thư mục z/x/y**, **file ZIP** hoặc **MBTiles**. Kèm sơ đồ XYZ hay TMS, bỏ qua ô trống, `metadata.json`, và trang xem thử `viewer.html` chạy bằng Leaflet. Có thanh tiến trình và nút Hủy. |
| Góc xoay khi xuất | Mặc định ghi thẳng góc xoay vào GeoTransform → **không nội suy lại, không mất chất lượng**. Nếu cần ảnh thẳng hướng Bắc (một số phần mềm không đọc được GeoTransform xoay), bật *Nắn ảnh thẳng hướng Bắc* và chọn thuật toán nội suy. |

Hệ tọa độ đầu ra = **hệ tọa độ của dự án**. Hãy đặt CRS dự án đúng trước khi căn ảnh.

## Cài đặt

**Cách 1 — chạy script:**

```bash
powershell -ExecutionPolicy Bypass -File install.ps1
```

**Cách 2 — thủ công:** chép cả thư mục `raster_image_editor_tiff` vào

```
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
```

Sau đó mở QGIS → *Plugins → Manage and Install Plugins → Installed* → tích **Raster Image Editor Tiff**.
(Nếu QGIS đang mở sẵn, dùng plugin *Plugin Reloader* hoặc khởi động lại QGIS.)

## Cách dùng

1. Mở bản đồ nền (OpenStreetMap, ảnh vệ tinh, lớp vector…) và đặt CRS dự án.
2. Bấm biểu tượng **Raster Image Editor Tiff** trên thanh công cụ (hoặc menu *Raster → Raster Image Editor Tiff*).
3. **Bước 1** – chọn file ảnh → *Nạp ảnh*. Ảnh hiện giữa khung nhìn kèm khung đỏ và các tay nắm.
4. **Bước 2** – bấm *Bật chế độ kéo/chỉnh ảnh*, rồi kéo/xoay/co giãn cho khớp.
   Giảm *Độ mờ* xuống ~50% để nhìn xuyên qua ảnh, hoặc giữ phím `H` (hay bỏ chọn *Hiện ảnh trên bản đồ*) để nháy tắt/bật mà đối chiếu với nền.
   Muốn nhanh và chính xác: dùng *Căn theo 2 điểm* với 2 mốc rõ ràng (ngã tư, góc nhà…),
   chọn 2 điểm càng xa nhau càng tốt.
5. **Bước 3** – tinh chỉnh bằng số nếu cần (ví dụ đặt đúng kích thước 1 pixel = 0.5 m).
6. **Bước 4** – chọn đường dẫn `.tif` → **XUẤT GEOTIFF**.

## Ghi chú kỹ thuật

* `placement.py` — toàn bộ phép biến đổi affine: pixel ↔ tọa độ bản đồ, sinh GeoTransform
  6 tham số của GDAL (có thành phần xoay), dựng phép đặt từ 2 cặp điểm khống chế.
* `overlay.py` — `QgsMapCanvasItem` vẽ ảnh + tay nắm; ảnh được vẽ trực tiếp theo tọa độ
  canvas nên tự đúng khi zoom/pan/xoay canvas.
* `maptool.py` — `QgsMapTool` xử lý chuột, bàn phím và quy trình căn 2 điểm.
* `exporter.py` — QImage → mảng numpy → dataset GDAL trong bộ nhớ → `CreateCopy` (giữ xoay)
  hoặc `gdal.Warp` (nắn thẳng hướng Bắc).
* `tiles.py` — toán lưới tile Web Mercator, 3 kiểu ghi (thư mục / ZIP / MBTiles)
  và bộ kết xuất dùng `QgsMapRendererParallelJob` với cờ `RenderMapTile`.
* `resources.py` — nạp biểu tượng dùng chung (`icons/logo.png`) cho nút trên
  thanh công cụ, menu *Raster*, tiêu đề bảng điều khiển và hộp thoại xuất tile;
  `icons/icon.svg` chỉ là phương án dự phòng khi thiếu file logo.
* `tiledialog.py` — hộp thoại xuất tile; phần xử lý nằm trong `export_tiles()`
  tách hẳn khỏi giao diện. Ảnh đã căn được nướng ra GeoTIFF tạm rồi nạp thành
  lớp raster để QGIS tự lo việc chiếu lại sang EPSG:3857.
* Nén JPEG chỉ ghi 3 băng (RGB); phần trong suốt được trộn lên nền trắng.

## Giới hạn đã biết

* Chỉ dùng phép biến đổi affine (tịnh tiến + xoay + tỉ lệ). Ảnh bị **méo phi tuyến**
  (bản đồ giấy cũ cong vênh) nên dùng công cụ *Georeferencer* sẵn có của QGIS với nhiều GCP.
* Ảnh được ghi ra dưới dạng 8 bit RGB(A); ảnh 16 bit sẽ bị hạ xuống 8 bit.
