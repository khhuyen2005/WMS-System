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
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
