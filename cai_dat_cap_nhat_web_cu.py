"""Run at project root after unzipping package. Preserves the original apps and database."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parent
if not (root/'manage.py').exists() or not (root/'WMS'/'urls.py').exists():
    raise SystemExit('Đặt các tệp trong ZIP vào cùng thư mục manage.py trước khi chạy.')
backup=root/'_BACKUP_TRUOC_NANG_CAP'
backup.mkdir(exist_ok=True)
for name in ('urls.py','settings.py'):
    p=root/'WMS'/name
    target=backup/name
    if not target.exists():shutil.copy2(p,target)
app=root/'wms_core'
if not (app/'models.py').exists():raise SystemExit('Không thấy wms_core. Hãy copy nguyên thư mục wms_core.')
settings=root/'WMS'/'settings.py'
s=settings.read_text(encoding='utf-8')
if "'wms_core'" not in s:
    s=s.replace("    'KhoThanhPham',", "    'KhoThanhPham',\n    'wms_core',")
if "LOGIN_URL = '/dang-nhap/'" not in s:
    s += "\nLOGIN_URL = '/dang-nhap/'\nLOGIN_REDIRECT_URL = '/KhoNVL/'\nLOGOUT_REDIRECT_URL = '/dang-nhap/'\n"
settings.write_text(s,encoding='utf-8')
urls=root/'WMS'/'urls.py'
u="""from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('dang-nhap/', auth_views.LoginView.as_view(template_name='wms_core/login.html'), name='login'),
    path('dang-xuat/', auth_views.LogoutView.as_view(), name='logout'),
    path('KhoNVL/', include('wms_core.urls')),
    path('KhoThanhPham/', RedirectView.as_view(url='/KhoNVL/hang-hoa/TP/', permanent=False)),
    path('', RedirectView.as_view(url='/KhoNVL/', permanent=False)),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
"""
urls.write_text(u,encoding='utf-8')
print('Đã kết nối giao diện WMS nâng cấp tại /KhoNVL/. Đã sao lưu urls.py và settings.py cũ. Không sửa db.sqlite3.')
