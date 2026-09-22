# Raster Image Editor Tiff — plugin QGIS

Đưa một ảnh thường (PNG/JPG/TIF… chưa có tọa độ) lên bản đồ QGIS, **kéo – xoay – co giãn
bằng chuột** cho khớp đúng vị trí thật, rồi **xuất ra file GeoTIFF** có hệ tọa độ.

## Tính năng

| Nhóm | Chi tiết |
|---|---|
| Nạp ảnh | PNG, JPG, TIF, BMP, GIF, WEBP, JP2, IMG, VRT. Ảnh lớn được thu nhỏ khi hiển thị cho mượt. |
| Nhiều ảnh | Nạp bao nhiêu ảnh tùy ý (nút **…** chọn nhiều file một lúc). Danh sách ảnh: bấm để chọn ảnh cần chỉnh, ô đánh dấu để hiện/ẩn, **▲ Lên / ▼ Xuống** đổi thứ tự chồng (ảnh trên đè ảnh dưới), **Phóng tới**, **Gỡ ảnh**. Trên bản đồ, **bấm vào ảnh nào là chọn và kéo được ảnh đó ngay**; ảnh đang chọn có khung đỏ và tay nắm luôn nổi trên cùng, ảnh khác có khung vàng nét đứt kèm nhãn số thứ tự. Mỗi ảnh có vị trí, độ mờ và lịch sử hoàn tác riêng. |
| Ảnh đã có tọa độ | **GeoTIFF**, ảnh kèm **world file** (`.tfw`, `.pgw`, `.jgw`…) hoặc có **điểm khống chế GCP** được **tự đặt đúng vị trí** và bản đồ tự phóng tới ảnh. Hỗ trợ ảnh 16 bit / số thực (tự co giãn độ sáng), ảnh bảng màu, giá trị nodata (thành trong suốt), file lưu từ dưới lên (tự lật lại). Ảnh trên 8000 pixel được đọc thu nhỏ để chỉnh cho mượt. |
| | Nếu file dùng **hệ tọa độ khác bản đồ**: vùng nhỏ thì tự quy đổi (lệch dưới 0,5 pixel); vùng rộng thì hỏi — *chiếu lại ảnh sang hệ của bản đồ* (khuyên dùng), *đổi hệ tọa độ dự án* theo file, hoặc *đặt gần đúng* (có báo mức lệch). File không kèm `.prj` thì coi như cùng hệ với bản đồ. |
| Chỉnh bằng chuột | Kéo giữa ảnh để **di chuyển**; kéo **bất kỳ điểm nào trên một cạnh** để co giãn **riêng theo trục X hoặc Y**; kéo ô vuông ở **góc** để co giãn **cả hai trục**; kéo nút tròn xanh phía trên để **xoay**. Cạnh đang rê chuột tới sẽ sáng lên màu xanh. Điểm neo (cạnh/góc đối diện) luôn đứng yên, kể cả khi ảnh đang xoay, và ảnh không bị nhảy khi bấm hơi lệch khỏi đường viền. |
| Khi phóng to | Tay nắm cạnh nằm ở giữa cạnh khi còn nhìn thấy; nếu điểm giữa bị ra ngoài màn hình thì tay nắm tự lùi về giữa phần cạnh còn hiển thị. Cạnh nằm hẳn ngoài khung nhìn thì ẩn tay nắm. Không phải thu nhỏ lại chỉ để với tới tay nắm. |
| Phím tắt | `Ctrl+Z` = hoàn tác · `Ctrl+Y` (hoặc `Ctrl+Shift+Z`) = làm lại · `Shift` khi kéo = khóa theo trục ngang/dọc · `Shift` khi kéo **góc** = đảo trạng thái khóa tỉ lệ · `Shift` khi xoay = bắt góc 15° · phím **mũi tên** = dịch từng pixel (giữ `Shift` = 10 pixel) · giữ `H` = tạm giấu ảnh để nhìn nền · `Esc` = hủy chế độ căn 2 điểm. |
| Căn theo 2 điểm | Bấm 1 điểm nhận biết trên ảnh → bấm vị trí thật của nó trên bản đồ → làm tiếp với điểm thứ 2. Plugin tự tính tịnh tiến + xoay + tỉ lệ (phép đồng dạng). Điểm đích **bám dính (snap)** theo cấu hình snapping của dự án. |
| Nhập tọa độ tay | Tâm ảnh X/Y, kích thước 1 pixel theo X/Y, góc xoay — nhập số trực tiếp. |
| Hoàn tác / Làm lại | `Ctrl+Z` và `Ctrl+Y` (hoặc 2 nút trên bảng điều khiển), 60 bước mỗi chiều. Áp dụng cho cả kéo chuột, nhập số, *Vừa khung nhìn* và *Căn theo 2 điểm*. Bấm chuột mà không kéo thì không ghi vào lịch sử. Khi công cụ đang bật, plugin giành lại `Ctrl+Z` từ menu *Edit* của QGIS. |
| So sánh với nền | Ô **Hiện ảnh trên bản đồ** để bật/tắt phần ảnh — khung viền đỏ và các tay nắm vẫn còn nên vẫn kéo chỉnh được khi đang ẩn. Hoặc **giữ phím `H`** để giấu tạm, thả ra là hiện lại (không làm đổi trạng thái ô đánh dấu). Kèm thanh trượt **độ mờ** để chồng mờ ảnh lên nền. |
| Hỗ trợ | Khóa tỉ lệ (chỉ áp dụng cho tay nắm góc và ô nhập số — tay nắm cạnh luôn co giãn tự do một trục), *Vừa khung nhìn*. |
| Hệ tọa độ đầu ra | Chọn chuẩn tọa độ của file GeoTIFF bằng bộ chọn CRS của QGIS, kèm nút nhanh **Theo bản đồ**, **EPSG:4326**, **EPSG:3857**. Trùng hệ của bản đồ thì góc xoay được ghi thẳng vào GeoTransform (không nội suy); khác hệ thì ảnh được chiếu lại, luôn thẳng hướng Bắc, theo thuật toán nội suy tự chọn. Nạp GeoTIFF thì mặc định xuất lại đúng hệ của file gốc. Đổi hệ tọa độ dự án khi đang có ảnh thì ảnh được dời theo để vẫn nằm đúng chỗ (kể cả lịch sử hoàn tác). |
| Kiểu xuất | **Ghép các ảnh đang hiện thành 1 file** (mặc định khi có từ 2 ảnh): đưa về một lưới chung thẳng hướng Bắc, độ phân giải theo ảnh mịn nhất, chỗ chồng nhau lấy ảnh nằm trên trong danh sách, góc trong suốt của ảnh xoay không đè lên ảnh khác. **Mỗi ảnh ra 1 file**: `<tên>_<tên ảnh>.tif`, giữ nguyên góc xoay nếu cùng hệ tọa độ. **Chỉ ảnh đang chọn**. Ảnh đang ẩn không được xuất. |
| Xuất GeoTIFF | Nén DEFLATE/LZW/ZSTD/JPEG/không nén, giữ kênh alpha, tạo overview, ghi kèm world file `.tfw` + `.prj`, tự thêm vào bản đồ. |
| Xuất bộ tile | Cắt thành tile Web Mercator (EPSG:3857) như plugin *QTiles*: nguồn là **ảnh đã căn**, **ảnh + các lớp đang hiện** hoặc **chỉ các lớp**; phạm vi theo ảnh / khung nhìn / toàn bộ lớp; chọn dải zoom, ô 256 hay 512 px, PNG hoặc JPG. Đầu ra: **thư mục z/x/y**, **file ZIP** hoặc **MBTiles**. Kèm sơ đồ XYZ hay TMS, bỏ qua ô trống, `metadata.json`, và trang xem thử `viewer.html` chạy bằng Leaflet. Có thanh tiến trình và nút Hủy. |
| Góc xoay khi xuất | Mặc định ghi thẳng góc xoay vào GeoTransform → **không nội suy lại, không mất chất lượng**. Nếu cần ảnh thẳng hướng Bắc (một số phần mềm không đọc được GeoTransform xoay), bật *Nắn ảnh thẳng hướng Bắc* và chọn thuật toán nội suy. |

Các ô tọa độ ở mục 3 luôn theo **hệ tọa độ đang hiển thị bản đồ**; hệ tọa độ của file xuất ra chọn riêng ở mục 4.

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
3. **Bước 1** – bấm **…** chọn một hoặc nhiều ảnh (hoặc gõ đường dẫn → *Thêm ảnh*). Ảnh thường hiện giữa khung nhìn; ảnh đã có tọa độ (GeoTIFF, world file) được đặt thẳng vào đúng vị trí.
4. **Bước 2** – bấm *Bật chế độ kéo/chỉnh ảnh*, rồi kéo/xoay/co giãn cho khớp.
   Giảm *Độ mờ* xuống ~50% để nhìn xuyên qua ảnh, hoặc giữ phím `H` (hay bỏ chọn *Hiện ảnh trên bản đồ*) để nháy tắt/bật mà đối chiếu với nền.
   Muốn nhanh và chính xác: dùng *Căn theo 2 điểm* với 2 mốc rõ ràng (ngã tư, góc nhà…),
   chọn 2 điểm càng xa nhau càng tốt.
5. **Bước 3** – tinh chỉnh bằng số nếu cần (ví dụ đặt đúng kích thước 1 pixel = 0.5 m).
6. **Bước 4** – chọn **kiểu xuất** (ghép 1 file / mỗi ảnh 1 file / ảnh đang chọn), **hệ tọa độ đầu ra** (vd. EPSG:4326 hay EPSG:3857), đường dẫn `.tif` → **XUẤT GEOTIFF**.

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
* `mosaic.py` — ghép nhiều ảnh: mỗi ảnh thành một dataset GDAL kèm GeoTransform và kênh alpha
  riêng, `gdal.Warp` đổ lên lưới chung theo thứ tự dưới → trên.
* `georef.py` — đọc ảnh bằng Qt hoặc GDAL (16 bit, bảng màu, nodata, thu nhỏ ảnh lớn), lấy
  GeoTransform/GCP/CRS trong file, lật ảnh lưu ngược, khớp vị trí sang hệ của bản đồ bằng
  bình phương tối thiểu kèm đo sai lệch theo pixel, và chiếu lại ảnh khi cần.
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
* Ảnh được ghi ra dưới dạng 8 bit RGB(A); ảnh 16 bit / số thực (DEM…) được co giãn về 8 bit
  để hiển thị, nên xuất lại không giữ giá trị gốc.
* Ảnh trên 8000 pixel được nạp thu nhỏ; file xuất ra theo kích thước đã thu nhỏ.
