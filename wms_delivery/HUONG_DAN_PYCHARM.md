# XONXEN SHOP – Bản bổ sung WMS theo 25 bảng ERD

## 0. Phạm vi và tình trạng hiện tại
Bộ này **không ghi đè code KhoNVL/KhoThanhPham**. Nó thêm app `wms_core` có 25 model gần tương ứng ERD, giao diện dashboard, quản trị danh mục, phê duyệt phiếu nhập/xuất, tồn theo vị trí, cảnh báo, kiểm kê và nhật ký. Đây là **bản demo nền tảng**, chưa phải phiên bản nghiệm thu hoàn chỉnh. Chức năng yêu cầu hủy/sửa phiếu đã duyệt hiện chỉ mới có bảng dữ liệu, **chưa có dịch vụ áp dụng nghiệp vụ**; vì vậy không phê duyệt loại yêu cầu này từ giao diện quản trị.

## 1. Cài vào dự án hiện có trên PyCharm
1. Sao lưu toàn bộ dự án, đặc biệt file `db.sqlite3`.
2. Giải nén gói bổ sung. Copy thư mục `wms_delivery` vào **cùng cấp** với `manage.py` trong dự án hiện tại.
3. Mở PyCharm > File > Open > chọn thư mục có `manage.py`.
4. Mở Terminal ở thư mục đó, chọn interpreter Python 3.12. Nếu `.venv` từ ZIP không dùng được, tạo môi trường mới: `py -3.12 -m venv .venv` trên Windows, kích hoạt `.venv\\Scripts\\activate` rồi `pip install -r requirements.txt`.
5. Chạy: `python wms_delivery/cai_dat_vao_du_an.py` (tự chép app và sửa `WMS/settings.py`, `WMS/urls.py`).
6. Chạy lần lượt:

```powershell
python manage.py check
python manage.py makemigrations wms_core
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_wms_demo
python manage.py runserver
```

Nếu đã có tài khoản superuser, lệnh `createsuperuser` không bắt buộc. Dùng mật khẩu của riêng bạn, không gửi lên chat.

7. Truy cập `http://127.0.0.1:8000/` để xem dashboard và `http://127.0.0.1:8000/admin/` để quản trị dữ liệu. Nếu có lỗi `no such table`, kiểm tra lệnh migrate.

## 2. Dữ liệu kho mẫu
- `Kho nguyên vật liệu XONXEN (demo)`: khu `Khu vải và phụ liệu`, kệ 01 và kệ 02, mỗi kệ có ô 01–03. Mã vị trí: `NVL-K01-O01` ... `NVL-K02-O03`.
- `Kho thành phẩm XONXEN (demo)`: khu `Khu thời trang thành phẩm`, 2 kệ × 3 ô. Mã vị trí: `TP-K01-O01` ... `TP-K02-O03`.
- 6 nguyên vật liệu, 10 SKU thành phẩm, 5 nhà cung cấp lấy từ file Excel người dùng cung cấp, 2 chi nhánh theo báo cáo. Vị trí phân bổ theo vòng lặp là **giả lập**.
- Ngưỡng tồn ban đầu **giả lập bằng 20% tồn đầu kỳ**, không phải định mức thực tế do XONXEN xác nhận. Quản lý có thể chỉnh ngưỡng ở Admin > Ngưỡng tồn an toàn.

## 3. Kịch bản demo chạy trực tiếp
1. Đăng nhập admin bằng superuser.
2. Vào `WMS chuẩn ERD > Phiếu nhập`: Thêm phiếu, kho, đối tác, tài khoản người lập; thêm dòng mặt hàng, vị trí thuộc kho và số lượng; **Save**. Kiểm tra tồn chưa đổi.
3. Vào danh sách phiếu nhập, chọn phiếu rồi menu Action > `Phê duyệt phiếu nhập đã chọn` > Go. Tồn theo vị trí tăng, có log.
4. Làm tương tự với Phiếu xuất, chỉ xuất nhỏ hơn hoặc bằng tồn tại **đúng vị trí**. Thử nhập số lượng vượt tồn rồi duyệt, hệ thống từ chối và không trừ tồn.
5. Vào `Đợt kiểm kê`, tạo đợt và thêm phạm vi vị trí. Sau khi lưu, chọn Action > `Bắt đầu kiểm kê và khóa vị trí`. Thử duyệt phiếu nhập/xuất ở vị trí đó để thấy cảnh báo khóa.
6. Vào Chi tiết kiểm kê nhập số thực đếm. Nếu chênh lệch, tạo Điều chỉnh tồn kho với số lượng điều chỉnh = thực tế - hệ thống rồi phê duyệt. Sau đó chọn Action > `Hoàn thành kiểm kê và mở khóa`.
7. Truy cập dashboard để xem báo cáo tồn, cảnh báo thiếu và nhật ký giao dịch.

## 4. Ánh xạ 25 bảng ERD
`wms_core/models.py` gồm đủ 25 model có tên tương ứng danh sách ERD. Django 5.1 chưa hỗ trợ composite PK trực tiếp theo cách đang dùng; ba bảng `VaiTroQuyen`, `TonKho`, `NguongTonAnToan` sử dụng ID tự tăng + `UniqueConstraint` trên cặp khóa nghiệp vụ. `TaiKhoan` liên kết OneToOne tới `django.contrib.auth.User`; mật khẩu hash được Django quản lý thay vì tạo trường plaintext hoặc hash thủ công.

## 5. Cảnh báo quan trọng / phần việc còn thiếu để hoàn thiện nghiệm thu
- Đây là app bổ sung nên dữ liệu của hai app cũ **chưa tự động đồng bộ** sang `wms_core`. Khi demo, hãy dùng giao diện WMS mới + Admin mới, không nhập giao dịch ở hai app cũ.
- Chưa xây hoàn thiện nghiệp vụ duyệt yêu cầu hủy hoặc sửa phiếu đã xác nhận; bảng `YeuCauXuLyPhieu` và `ChiTietYeuCauXuLyPhieu` mới là lưu trữ. Cấm sửa số lượng của phiếu đã xác nhận.
- Các bản ghi kiểm kê phải được bảo vệ khỏi sửa sau khi phê duyệt; hiện phần chỉnh sửa thủ công trong Django Admin mới chỉ bảo vệ phiếu đã duyệt ở mức giao diện, cần khóa thêm ở service/API và phân quyền chính xác trước vận hành thật.
- Django Admin chỉ phù hợp demo nghiệp vụ quản trị, cần bổ sung trang tạo phiếu nhập/xuất cho nhân viên kho, phê duyệt riêng cho quản lý, xuất báo cáo Excel và kiểm thử tự động để hoàn thành toàn bộ FR.
- Sử dụng SQLite cho demo nhanh. Báo cáo chỉ định PostgreSQL; khi chuyển lên PostgreSQL phải cấu hình DB riêng, chạy lại migration và chuyển dữ liệu kiểm soát. `select_for_update()` ở SQLite không tạo khóa hàng hiệu lực như PostgreSQL, vì vậy **không dùng SQLite để kiểm thử tình huống đồng thời của NFR-08**.
- `seed_wms_demo` chỉ tạo tồn đầu kỳ một lần, không cập nhật đè số lượng đã giao dịch. Muốn đặt lại bản demo hãy khôi phục bản sao DB, không tự ý xóa phiếu và nhật ký.

## 6. Hệ thống công nghệ
Giữ Django 5.1.1 của dự án cũ. Để khớp báo cáo, triển khai cuối cùng nên dùng PostgreSQL. Dữ liệu Excel gốc giữ nguyên; JSON nhập ban đầu bên trong app đã được trích xuất, chỉ gồm trường quản lý WMS, không dùng đơn giá.
