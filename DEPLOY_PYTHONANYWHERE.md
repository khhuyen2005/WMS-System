# Deploy miễn phí trên PythonAnywhere

Hướng dẫn này sử dụng tài khoản PythonAnywhere tên `khhuyen2005`. Nếu bạn dùng tên khác, hãy thay `khhuyen2005` trong toàn bộ đường dẫn và tên miền bên dưới.

## 1. Tạo tài khoản

Đăng ký gói Beginner miễn phí tại <https://www.pythonanywhere.com/registration/register/beginner/>.

Sau khi đăng nhập, mở **Consoles → Bash**.

## 2. Tải và cài dự án

Chạy lần lượt trong Bash Console:

```bash
git clone https://github.com/khhuyen2005/WMS-System.git
cd WMS-System
mkvirtualenv --python=/usr/bin/python3.11 wms-venv
pip install -r requirements.txt
```

Nếu tài khoản không có Python 3.11 tại đường dẫn trên, chọn cùng một phiên bản Python đang có trong màn hình tạo Web app.

## 3. Tạo cấu hình bí mật

```bash
cp WMS/local_settings.py.example WMS/local_settings.py
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Sao chép khóa vừa tạo, mở `WMS/local_settings.py` bằng trình chỉnh sửa của PythonAnywhere và đặt:

```python
SECRET_KEY = "khoa-vua-tao"
EMAIL_HOST_PASSWORD = ""
```

Không commit `WMS/local_settings.py`. Tệp này đã được `.gitignore` bảo vệ.

## 4. Khởi tạo ứng dụng

Trong Bash Console, tại thư mục `~/WMS-System` và khi `wms-venv` đang hoạt động:

```bash
python manage.py migrate
python manage.py setup_wms_roles
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py check
```

Muốn có dữ liệu minh họa, chạy thêm:

```bash
python manage.py seed_wms_demo
```

## 5. Tạo Web app

1. Mở tab **Web**.
2. Chọn **Add a new web app**.
3. Chọn **Manual configuration**; không chọn mẫu Django dành cho dự án mới.
4. Chọn đúng phiên bản Python đã dùng để tạo `wms-venv`.
5. Trong phần **Virtualenv**, nhập `wms-venv`.
6. Trong phần **Code**, đặt cả **Source code** và **Working directory** thành `/home/khhuyen2005/WMS-System`.

## 6. Cấu hình WSGI

Trong tab **Web**, mở liên kết WSGI configuration file, xóa nội dung cũ và thay bằng:

```python
import os
import sys

path = '/home/khhuyen2005/WMS-System'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'WMS.settings'
os.environ['DJANGO_DEBUG'] = 'False'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'khhuyen2005.pythonanywhere.com'
os.environ['DJANGO_CSRF_TRUSTED_ORIGINS'] = 'https://khhuyen2005.pythonanywhere.com'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Lưu tệp WSGI.

## 7. Cấu hình static và media

Trong phần **Static files** của tab **Web**, thêm hai mapping:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/khhuyen2005/WMS-System/staticfiles` |
| `/media/` | `/home/khhuyen2005/WMS-System/media` |

Nhấn **Reload** ở đầu tab Web rồi mở:

<https://khhuyen2005.pythonanywhere.com/>

## 8. Cập nhật phiên bản mới

Sau mỗi lần push mã nguồn mới lên GitHub, mở Bash Console và chạy:

```bash
cd ~/WMS-System
workon wms-venv
git pull origin main
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
```

Sau đó quay lại tab **Web** và nhấn **Reload**.

## Lưu ý với gói miễn phí

- Web app miễn phí cần được gia hạn định kỳ trong dashboard PythonAnywhere.
- Chỉ có một web worker và tài nguyên hạn chế, phù hợp cho học tập hoặc demo.
- SQLite phù hợp cho bản demo nhỏ; nên chuyển sang PostgreSQL khi có nhiều người sử dụng đồng thời.
- Gửi email SMTP có thể bị giới hạn trên tài khoản miễn phí. Các chức năng kho vẫn hoạt động bình thường nếu để trống `EMAIL_HOST_PASSWORD`, nhưng chức năng quên mật khẩu qua email sẽ không gửi được thư.
