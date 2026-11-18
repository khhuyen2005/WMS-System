# WMS System — XONXEN SHOP

Hệ thống quản lý kho (Warehouse Management System) dành cho XONXEN SHOP, được xây dựng bằng Django. Ứng dụng hỗ trợ quản lý nguyên vật liệu, thành phẩm, nhập–xuất kho, kiểm kho, vị trí lưu trữ, đối tác và báo cáo tồn kho.

## Chức năng chính

- Quản lý danh mục nguyên vật liệu và thành phẩm.
- Quản lý kho, khu vực, kệ và vị trí lưu trữ.
- Quản lý nhà cung cấp, xưởng gia công và chi nhánh nhận hàng.
- Lập, duyệt và theo dõi phiếu nhập kho, xuất kho.
- Kiểm kho, ghi nhận chênh lệch và xử lý điều chỉnh tồn.
- Thiết lập ngưỡng tồn kho và theo dõi lịch sử hoạt động.
- Quản lý tài khoản, vai trò và quyền truy cập.
- Nhập dữ liệu từ Excel, xuất báo cáo CSV và xuất phiếu PDF.
- Hỗ trợ đặt lại mật khẩu qua email.

## Công nghệ sử dụng

- Python
- Django 5
- SQLite
- HTML/CSS/JavaScript với Django Templates
- OpenPyXL và Pandas cho xử lý dữ liệu
- ReportLab cho xuất PDF

## Cấu trúc dự án

```text
WMS/                 Cấu hình Django và URL cấp dự án
wms_core/            Chức năng WMS chính
KhoNVL/              Mô hình và mã nguồn kho nguyên vật liệu cũ
KhoThanhPham/        Mô hình và mã nguồn kho thành phẩm cũ
wms_delivery/        Gói mã nguồn hỗ trợ bàn giao
xonxen_patch_v2/     Công cụ và dữ liệu nâng cấp phiên bản
manage.py             Điểm chạy các lệnh quản trị Django
requirements.txt      Danh sách thư viện Python
databasee.xlsx        Dữ liệu danh mục dùng cho đồng bộ Excel
```

Luồng ứng dụng hiện tại được phục vụ chủ yếu qua `wms_core`. Các thư mục `KhoNVL` và `KhoThanhPham` vẫn được giữ lại để tương thích dữ liệu, migration và tham khảo mã nguồn cũ.

## Yêu cầu môi trường

- Python 3.10 trở lên
- `pip`
- Git

## Cài đặt

### 1. Tải mã nguồn

```bash
git clone https://github.com/khhuyen2005/WMS-System.git
cd WMS-System
```

### 2. Tạo môi trường ảo

Trên Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

Trên macOS hoặc Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Cài thư viện

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Cấu hình thông tin bí mật

Sao chép tệp cấu hình mẫu:

Trên Windows:

```powershell
Copy-Item WMS\local_settings.py.example WMS\local_settings.py
```

Trên macOS hoặc Linux:

```bash
cp WMS/local_settings.py.example WMS/local_settings.py
```

Mở `WMS/local_settings.py` và thay các giá trị mẫu:

```python
SECRET_KEY = "khoa-bi-mat-django-cua-ban"
EMAIL_HOST_PASSWORD = "mat-khau-ung-dung-email"
```

Có thể tạo khóa Django ngẫu nhiên bằng lệnh:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Thay vì dùng `local_settings.py`, ứng dụng cũng nhận hai biến môi trường `DJANGO_SECRET_KEY` và `EMAIL_HOST_PASSWORD`.

> `WMS/local_settings.py`, database SQLite và các tệp `.env` đã được loại khỏi Git. Không đưa mật khẩu hoặc khóa bí mật vào mã nguồn.

### 5. Khởi tạo database

```bash
python manage.py migrate
python manage.py createsuperuser
```

Nếu cần tạo dữ liệu mẫu:

```bash
python manage.py seed_wms_demo
```

Nếu cần đồng bộ danh mục từ `databasee.xlsx`, nên xem trước thay đổi trước khi áp dụng:

```bash
python manage.py dong_bo_databasee --help
```

### 6. Chạy ứng dụng

```bash
python manage.py runserver
```

Mở trình duyệt tại:

- Ứng dụng: <http://127.0.0.1:8000/>
- Trang quản trị Django: <http://127.0.0.1:8000/admin/>

## Kiểm tra dự án

Chạy kiểm tra cấu hình Django:

```bash
python manage.py check
```

Chạy bộ kiểm thử:

```bash
python manage.py test
```

## Dữ liệu và bảo mật

Các tệp sau chỉ được lưu ở máy cục bộ và không được commit:

- `WMS/local_settings.py`
- `db.sqlite3` và các bản sao lưu SQLite
- `.env` và các biến thể của tệp này
- `.venv/`
- `media/` và `staticfiles/`
- Các thư mục backup cục bộ

Khi triển khai thực tế, cần tắt `DEBUG`, đặt `ALLOWED_HOSTS` phù hợp, sử dụng khóa bí mật riêng và cấu hình hệ quản trị cơ sở dữ liệu dành cho production.

## Repository

Mã nguồn được lưu tại: <https://github.com/khhuyen2005/WMS-System>

## Triển khai miễn phí

Xem hướng dẫn từng bước tại [DEPLOY_PYTHONANYWHERE.md](DEPLOY_PYTHONANYWHERE.md).
