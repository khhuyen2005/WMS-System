from django.contrib import admin,messages
from django.core.exceptions import ValidationError,PermissionDenied
from . import models as m
from .services import approve_receipt,start_count,approve_adjustment,finish_count

admin.site.site_header='XONXEN SHOP | WMS'
admin.site.site_title='XONXEN WMS'
admin.site.index_title='Quản trị kho'

class ReadonlyConfirmedAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.trang_thai in ('da_duyet','da_huy'):
            return [f.name for f in obj._meta.fields if f.name!='id']
        return super().get_readonly_fields(request,obj)
    def has_delete_permission(self,request,obj=None):
        if obj and obj.trang_thai in ('da_duyet','da_huy'): return False
        return super().has_delete_permission(request,obj)

class NhapInline(admin.TabularInline):
    model=m.ChiTietPhieuNhap;extra=1
    def has_add_permission(self,request,obj=None): return not (obj and obj.trang_thai=='da_duyet') and super().has_add_permission(request,obj)
    def has_change_permission(self,request,obj=None): return not (obj and obj.trang_thai=='da_duyet') and super().has_change_permission(request,obj)
    def has_delete_permission(self,request,obj=None): return not (obj and obj.trang_thai=='da_duyet') and super().has_delete_permission(request,obj)

class XuatInline(admin.TabularInline):
    model=m.ChiTietPhieuXuat;extra=1
    def has_add_permission(self,request,obj=None): return not (obj and obj.trang_thai=='da_duyet') and super().has_add_permission(request,obj)
    def has_change_permission(self,request,obj=None): return not (obj and obj.trang_thai=='da_duyet') and super().has_change_permission(request,obj)
    def has_delete_permission(self,request,obj=None): return not (obj and obj.trang_thai=='da_duyet') and super().has_delete_permission(request,obj)

@admin.register(m.PhieuNhap)
class PhieuNhapAdmin(ReadonlyConfirmedAdmin):
    list_display=['ma_phieu_nhap','kho','doi_tac','trang_thai','thoi_gian_lap','nguoi_phe_duyet']
    list_filter=['trang_thai','kho'];inlines=[NhapInline];actions=['approve']
    @admin.action(description='Phê duyệt phiếu nhập đã chọn')
    def approve(self,request,queryset):
        for obj in queryset:
            try: approve_receipt(obj.pk,request.user,'nhap');self.message_user(request,f'Đã duyệt {obj}')
            except (ValidationError,PermissionDenied) as exc:self.message_user(request,f'{obj}: {exc}',messages.ERROR)

@admin.register(m.PhieuXuat)
class PhieuXuatAdmin(ReadonlyConfirmedAdmin):
    list_display=['ma_phieu_xuat','kho','doi_tac','trang_thai','thoi_gian_lap','nguoi_phe_duyet']
    list_filter=['trang_thai','kho'];inlines=[XuatInline];actions=['approve']
    @admin.action(description='Phê duyệt phiếu xuất đã chọn')
    def approve(self,request,queryset):
        for obj in queryset:
            try: approve_receipt(obj.pk,request.user,'xuat');self.message_user(request,f'Đã duyệt {obj}')
            except (ValidationError,PermissionDenied) as exc:self.message_user(request,f'{obj}: {exc}',messages.ERROR)

class ScopeInline(admin.TabularInline):model=m.PhamViKiemKe;extra=1
@admin.register(m.DotKiemKe)
class DotKiemKeAdmin(admin.ModelAdmin):
    list_display=['ma_dot','kho','trang_thai','thoi_gian_bat_dau'];inlines=[ScopeInline];actions=['start','finish']
    @admin.action(description='Bắt đầu kiểm kê và khóa vị trí')
    def start(self,request,queryset):
        for obj in queryset:
            try:start_count(obj.pk,request.user)
            except (ValidationError,PermissionDenied) as exc:self.message_user(request,str(exc),messages.ERROR)
    @admin.action(description='Hoàn thành kiểm kê và mở khóa')
    def finish(self,request,queryset):
        for obj in queryset:
            try:finish_count(obj.pk,request.user)
            except (ValidationError,PermissionDenied) as exc:self.message_user(request,str(exc),messages.ERROR)

@admin.register(m.DieuChinhTonKho)
class DieuChinhAdmin(admin.ModelAdmin):
    list_display=['id','chi_tiet_kiem_ke','so_luong_dieu_chinh','trang_thai'];actions=['approve']
    @admin.action(description='Phê duyệt điều chỉnh tồn kho')
    def approve(self,request,queryset):
        for obj in queryset:
            try:approve_adjustment(obj.pk,request.user)
            except (ValidationError,PermissionDenied) as exc:self.message_user(request,str(exc),messages.ERROR)

@admin.register(m.TonKho)
class TonKhoAdmin(admin.ModelAdmin):
    list_display=['hang_hoa','vi_tri','so_luong_ton','thoi_gian_cap_nhat'];list_filter=['vi_tri__ke__khu_vuc__kho'];search_fields=['hang_hoa__ma_hang','hang_hoa__ten_hang']
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(m.NhatKyGiaoDich)
class LogAdmin(admin.ModelAdmin):
    list_display=['thoi_gian','nguoi_thuc_hien','loai_giao_dich','hanh_dong','so_luong_truoc','so_luong_sau'];list_filter=['loai_giao_dich'];
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

class ProtectedLineAdmin(admin.ModelAdmin):
    def has_change_permission(self,request,obj=None):
        if obj and ((hasattr(obj,'phieu_nhap') and obj.phieu_nhap.trang_thai=='da_duyet') or (hasattr(obj,'phieu_xuat') and obj.phieu_xuat.trang_thai=='da_duyet')):return False
        return super().has_change_permission(request,obj)
    def has_delete_permission(self,request,obj=None):
        if obj and ((hasattr(obj,'phieu_nhap') and obj.phieu_nhap.trang_thai=='da_duyet') or (hasattr(obj,'phieu_xuat') and obj.phieu_xuat.trang_thai=='da_duyet')):return False
        return super().has_delete_permission(request,obj)

admin.site.register(m.ChiTietPhieuNhap,ProtectedLineAdmin)
admin.site.register(m.ChiTietPhieuXuat,ProtectedLineAdmin)

for cls in [m.Kho,m.KhuVuc,m.Ke,m.ViTriLuuTru,m.NhomHang,m.DonViTinh,m.HangHoa,m.DoiTac,m.VaiTro,m.Quyen,m.VaiTroQuyen,m.TaiKhoan,m.YeuCauXuLyPhieu,m.ChiTietYeuCauXuLyPhieu,m.NguongTonAnToan,m.PhamViKiemKe,m.ChiTietKiemKe]:
    admin.site.register(cls)
