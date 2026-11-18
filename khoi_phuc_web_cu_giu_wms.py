"""Khôi phục routes web gốc, giữ WMS mới ở /wms/; KHÔNG đụng DB/migrations."""
from pathlib import Path
from datetime import datetime
import shutil

root = Path(__file__).resolve().parent
urls = root / 'WMS' / 'urls.py'
if not (root / 'manage.py').is_file() or not urls.is_file():
    raise SystemExit('LỖI: Đặt script cùng cấp với manage.py rồi chạy từ thư mục dự án.')
for required in (root/'KhoNVL'/'urls.py', root/'KhoThanhPham'/'urls.py'):
    if not required.is_file():
        raise SystemExit(f'LỖI: Không thấy {required}. Không thực hiện thay đổi.')
original = urls.read_text(encoding='utf-8')
if "path('KhoNVL/', include('KhoNVL.urls'))" in original and "path('KhoThanhPham/', include('KhoThanhPham.urls'))" in original:
    print('Các tuyến trang cũ đã có. Không thay đổi WMS/urls.py.')
    raise SystemExit(0)
backup = urls.with_name('urls_backup_truoc_khoi_phuc_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.py')
shutil.copy2(urls, backup)
new = '''from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    # GIỮ NGUYÊN mọi trang gốc (import Excel, thêm nguyên vật liệu, nhập/xuất ...)
    path('KhoNVL/', include('KhoNVL.urls')),
    path('KhoThanhPham/', include('KhoThanhPham.urls')),
    path('', RedirectView.as_view(url='/KhoNVL/', permanent=False)),
]

# Giữ bộ WMS mới song song, chưa chuyển nghiệp vụ cũ sang bảng mới.
if 'wms_core' in settings.INSTALLED_APPS:
    urlpatterns += [
        path('wms/', include('wms_core.urls')),
        path('dang-nhap/', auth_views.LoginView.as_view(template_name='wms_core/login.html'), name='login'),
        path('dang-xuat/', auth_views.LogoutView.as_view(), name='logout'),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
'''
urls.write_text(new, encoding='utf-8')
print('ĐÃ KHÔI PHỤC: /KhoNVL/ và /KhoThanhPham/ gọi lại đúng app gốc.')
print('Bộ WMS bổ sung vẫn ở /wms/; database và migration KHÔNG thay đổi.')
print('Bản sao lưu WMS/urls.py cũ:', backup.name)
print('Chạy tiếp: python manage.py check')
