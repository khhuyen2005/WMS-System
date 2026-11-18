from django.urls import path
from . import views, stockcheck_views, pdf_exports

urlpatterns = [
    # Dashboard
    # Trang chủ mặc định sẽ tự động điều hướng
    path('', views.home, name='wms_home'),

    # Trang dashboard chỉ dành cho quản lý
    path('dashboard/', views.dashboard, name='wms_dashboard'),

    # Goods catalog
    path('hang-hoa/them/<str:kind>/', views.create_goods, name='wms_create_goods'),
    path('hang-hoa/<str:kind>/', views.goods, name='wms_goods'),

    # Partner and branch directories
    path('doi-tac/', views.partners, name='wms_partners'),
    path('doi-tac/them/', views.create_partner, name='wms_create_partner'),
    path('doi-tac/<int:pk>/trang-thai/', views.partner_status, name='wms_partner_status'),

    path(
        'chi-nhanh/',
        views.branches,
        name='wms_branches'
    ),

    path(
        'chi-nhanh/them/',
        views.create_branch,
        name='wms_create_branch'
    ),

    path(
        'chi-nhanh/<int:pk>/trang-thai/',
        views.branch_status,
        name='wms_branch_status'
    ),

    # Warehouse locations
    path('vi-tri/', views.positions, name='wms_positions'),
    path('vi-tri/them/', views.create_position, name='wms_create_position'),
    path('ton-kho/', views.inventory, name='wms_inventory'),

    # Receipt and issue documents

    # API cap nhat trang thai khoa kiem kho cho form nhap/xuat
    path(
        'api/khoa-kiem-kho/trang-thai/',
        views.document_lock_status,
        name='wms_document_lock_status'
    ),

    path('phieu/<str:direction>/', views.documents, name='wms_documents'),
    path('phieu/<str:direction>/tao/', views.new_document, name='wms_new_document'),
    path('phieu/<str:direction>/<int:pk>/sua/', views.edit_document, name='wms_edit_document'),
    path('phieu/<str:direction>/<int:pk>/xoa-nhap/', views.delete_draft_document, name='wms_delete_draft_document'),
# Xuất PDF phiếu nhập/xuất đã phê duyệt.
    path(
        'phieu/<str:direction>/<int:pk>/xuat-pdf/',
        pdf_exports.export_document_pdf,
        name='wms_document_pdf'
    ),

    path('phieu/<str:direction>/<int:pk>/<str:action>/', views.document_action, name='wms_document_action'),
    path('phieu/<str:direction>/<int:pk>/', views.document_detail, name='wms_document_detail'),

    # Legacy stock counting
    path('kiem-ke/', views.stock_counts, name='wms_counts'),
    path('kiem-ke/tao/', views.new_count, name='wms_new_count'),
    path('kiem-ke/<int:pk>/', views.count_detail, name='wms_count_detail'),
    path('kiem-ke/<int:pk>/<str:action>/', views.count_action, name='wms_count_action'),
    path('kiem-dem/<int:pk>/ghi/', views.record_count, name='wms_record_count'),

    # New stock-check workflow
    path('kiem-kho/', stockcheck_views.stock_checks, name='wms_stock_checks'),
    path('kiem-kho/tao/', stockcheck_views.create_stock_check, name='wms_create_stock_check'),

    # API khoa tam khi dang tao phieu kiem kho
    path(
        'kiem-kho/khoa-tam/dong-bo/',
        stockcheck_views.sync_stockcheck_draft,
        name='wms_sync_stockcheck_draft'
    ),

    # API giai phong khoa tam khi bo tao phieu
    path(
        'kiem-kho/khoa-tam/giai-phong/',
        stockcheck_views.release_stockcheck_draft,
        name='wms_release_stockcheck_draft'
    ),

    path('kiem-kho/<int:pk>/sua/', stockcheck_views.edit_stock_check, name='wms_edit_stock_check'),
    path('kiem-kho/<int:pk>/xoa/', stockcheck_views.delete_stock_check, name='wms_delete_stock_check'),
    path('kiem-kho/<int:pk>/', stockcheck_views.stock_check_detail, name='wms_stock_check_detail'),
    path('kiem-kho/<int:pk>/<str:action>/', stockcheck_views.stock_check_action, name='wms_stock_check_action'),

    # Stock adjustment and safety limits
    path('dieu-chinh/', views.adjustments, name='wms_adjustments'),
    path('dieu-chinh/<int:pk>/<str:action>/', views.adjustment_action, name='wms_adjustment_action'),
    path('nguong-ton/', views.thresholds, name='wms_thresholds'),
    path('nguong-ton/<int:pk>/sua/', views.update_threshold, name='wms_update_threshold'),

    # Audit and reporting
    path('lich-su/', views.activity, name='wms_activity'),
    path('bao-cao/', views.report, name='wms_report'),
    path('bao-cao/xuat-csv/', views.export_inventory_csv, name='wms_export_csv'),

    # User accounts
    path('tai-khoan/', views.users, name='wms_users'),
    path('tai-khoan/<int:pk>/trang-thai/', views.toggle_user_status, name='wms_toggle_user_status'),

    # Excel import
    path('nhap-excel/', views.import_excel, name='wms_import_excel'),

    # Correction requests
    path('xu-ly-phieu/', views.correction_requests, name='wms_corrections'),
    path('xu-ly-phieu/<str:direction>/<int:pk>/yeu-cau/', views.request_correction, name='wms_request_correction'),
    path('xu-ly-phieu/<int:pk>/<str:action>/', views.correction_action, name='wms_correction_action'),
]
