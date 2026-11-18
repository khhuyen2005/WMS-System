from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='wms_home', permanent=False)),
    path('wms/', include('wms_core.urls')),
    path('KhoNVL/', RedirectView.as_view(pattern_name='wms_home', permanent=False)),
    path('dang-nhap/', auth_views.LoginView.as_view(template_name='wms_core/login.html'), name='login'),
    path('dang-xuat/', auth_views.LogoutView.as_view(), name='logout'),
    # Existing app code and migrations are PRESERVED for migration/reference.
    # Old write forms are intentionally not routed: they would update a second stock ledger.
]

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='wms_home', permanent=False)),
    path('wms/', include('wms_core.urls')),
    path('KhoNVL/', RedirectView.as_view(pattern_name='wms_home', permanent=False)),

    # URL Đăng nhập, Đăng xuất
    path('dang-nhap/', auth_views.LoginView.as_view(template_name='wms_core/login.html'), name='login'),
    path('dang-xuat/', auth_views.LogoutView.as_view(), name='logout'),

    # 4 URL XỬ LÝ QUÊN MẬT KHẨU
    # 1. Trang nhập email để lấy link
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='wms_core/password_reset_form.html',
        email_template_name='wms_core/password_reset_email.html',
        subject_template_name='wms_core/password_reset_subject.txt',
        success_url='/password_reset/done/'
    ), name='password_reset'),

    # 2. Trang thông báo "Gửi email thành công"
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='wms_core/password_reset_done.html'
    ), name='password_reset_done'),

    # 3. Trang đặt lại mật khẩu mới (Người dùng click từ email vào đây)
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='wms_core/password_reset_confirm.html',
        success_url='/reset/done/'
    ), name='password_reset_confirm'),

    # 4. Trang thông báo "Đặt lại mật khẩu thành công"
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='wms_core/password_reset_complete.html'
    ), name='password_reset_complete'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
