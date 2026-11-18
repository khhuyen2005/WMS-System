from pathlib import Path
import shutil
root=Path(__file__).resolve().parent
project=root.parent
if not (project/'manage.py').exists() or not (project/'WMS'/'settings.py').exists():
    raise SystemExit('Hãy sao chép THƯ MỤC wms_delivery vào ngay trong thư mục có manage.py rồi chạy python wms_delivery/cai_dat_vao_du_an.py')
src=root/'wms_core';dst=project/'wms_core'
shutil.copytree(src,dst,dirs_exist_ok=True)
settings=project/'WMS'/'settings.py';content=settings.read_text(encoding='utf-8')
if "'wms_core'" not in content:content=content.replace("    'KhoThanhPham',", "    'KhoThanhPham',\n    'wms_core',")
settings.write_text(content,encoding='utf-8')
urls=project/'WMS'/'urls.py';content=urls.read_text(encoding='utf-8')
# put dashboard ahead of previous redirect, preserve both old app URLs
if "include('wms_core.urls')" not in content:
    content=content.replace("    path('admin/', admin.site.urls),", "    path('admin/', admin.site.urls),\n    path('wms/', include('wms_core.urls')),")
    content=content.replace("path('', RedirectView.as_view(url='/KhoNVL/', permanent=True))", "path('', RedirectView.as_view(url='/wms/', permanent=False))")
urls.write_text(content,encoding='utf-8')
print('Đã thêm wms_core, giữ nguyên hai app cũ. Bây giờ chạy makemigrations, migrate, createsuperuser, seed_wms_demo, runserver.')
