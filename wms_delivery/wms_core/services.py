"""All stock changes must go through these transactional services."""
from decimal import Decimal
from collections import defaultdict
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from django.db.models import F
from .models import *


def manager_account(user):
    account = TaiKhoan.objects.select_related('vai_tro').filter(user=user,trang_thai=True).first()
    if not account: raise PermissionDenied('Cần tài khoản WMS đang hoạt động')
    if not (user.is_superuser or account.vai_tro.ten_vai_tro == 'Quản lý kho'):
        raise PermissionDenied('Chỉ quản lý kho được phê duyệt')
    return account


def assert_not_locked(vi_tri_id):
    if PhamViKiemKe.objects.filter(vi_tri_id=vi_tri_id,trang_thai_khoa=True).exists():
        raise ValidationError('Vị trí đang bị khóa do kiểm kê')


@transaction.atomic
def approve_receipt(pk, user, direction):
    """direction: 'nhap' or 'xuat'. Row locking requires PostgreSQL for concurrent workers."""
    actor = manager_account(user)
    klass = PhieuNhap if direction == 'nhap' else PhieuXuat
    doc = klass.objects.select_for_update().get(pk=pk)
    if doc.trang_thai not in ('nhap','cho_duyet'): raise ValidationError('Phiếu đã xử lý')
    lines = list(doc.chi_tiet.select_related('vi_tri__ke__khu_vuc','hang_hoa'))
    if not lines: raise ValidationError('Phiếu chưa có dòng hàng')
    combined = defaultdict(Decimal)
    for ln in lines:
        ln.full_clean()
        assert_not_locked(ln.vi_tri_id)
        if ln.vi_tri.kho.id != doc.kho_id: raise ValidationError('Vị trí không đúng kho')
        if ln.hang_hoa.nhom_hang.loai_hang != doc.kho.loai_kho: raise ValidationError('Loại hàng không phù hợp kho')
        count = ln.so_luong_nhap if direction == 'nhap' else ln.so_luong_xuat
        combined[(ln.hang_hoa_id,ln.vi_tri_id)] += count
    # Sorted locks reduce deadlock risk and prevent duplicate deductions.
    for (goods_id, pos_id), count in sorted(combined.items()):
        stock = TonKho.objects.select_for_update().filter(hang_hoa_id=goods_id,vi_tri_id=pos_id).first()
        if stock is None:
            if direction == 'xuat': raise ValidationError('Không có tồn ở vị trí xuất')
            stock = TonKho.objects.create(hang_hoa_id=goods_id,vi_tri_id=pos_id,so_luong_ton=0)
        before = stock.so_luong_ton
        after = before + count if direction == 'nhap' else before - count
        if after < 0: raise ValidationError(f'Xuất vượt tồn: hàng #{goods_id}, vị trí #{pos_id}; tồn {before}')
        stock.so_luong_ton = after
        stock.save(update_fields=['so_luong_ton','thoi_gian_cap_nhat'])
        NhatKyGiaoDich.objects.create(nguoi_thuc_hien=actor,phieu_nhap=doc if direction=='nhap' else None,
          phieu_xuat=doc if direction=='xuat' else None,hang_hoa_id=goods_id,vi_tri_id=pos_id,
          loai_giao_dich=direction,hanh_dong='PHE_DUYET',noi_dung_thay_doi=f'{direction} {count}',
          so_luong_truoc=before,so_luong_sau=after)
    doc.trang_thai='da_duyet';doc.nguoi_phe_duyet=actor;doc.thoi_gian_phe_duyet=timezone.now()
    doc.save(update_fields=['trang_thai','nguoi_phe_duyet','thoi_gian_phe_duyet'])
    return doc


@transaction.atomic
def start_count(pk,user):
    manager_account(user)
    batch=DotKiemKe.objects.select_for_update().get(pk=pk)
    if batch.trang_thai!='nhap': raise ValidationError('Đợt kiểm kê phải ở trạng thái nháp')
    scopes=list(batch.pham_vi.select_related('vi_tri__ke__khu_vuc'))
    if not scopes: raise ValidationError('Chưa có vị trí kiểm kê')
    for scope in scopes:
        if scope.vi_tri.kho.id != batch.kho_id: raise ValidationError('Vị trí kiểm kê không thuộc kho')
        if PhamViKiemKe.objects.filter(vi_tri=scope.vi_tri,trang_thai_khoa=True).exclude(pk=scope.pk).exists():
            raise ValidationError('Vị trí đang được kiểm kê ở đợt khác')
        scope.trang_thai_khoa=True;scope.thoi_gian_khoa=timezone.now()
        scope.save(update_fields=['trang_thai_khoa','thoi_gian_khoa'])
        for stock in TonKho.objects.filter(vi_tri=scope.vi_tri).select_for_update():
            ChiTietKiemKe.objects.get_or_create(pham_vi=scope,hang_hoa=stock.hang_hoa,
                     defaults={'so_luong_he_thong':stock.so_luong_ton})
    batch.trang_thai='dang_kiem';batch.thoi_gian_bat_dau=timezone.now()
    batch.save(update_fields=['trang_thai','thoi_gian_bat_dau'])


@transaction.atomic
def approve_adjustment(pk,user):
    actor=manager_account(user)
    adj=DieuChinhTonKho.objects.select_for_update().select_related('chi_tiet_kiem_ke__pham_vi').get(pk=pk)
    if adj.trang_thai!='cho_duyet': raise ValidationError('Điều chỉnh đã được xử lý')
    line=adj.chi_tiet_kiem_ke
    if line.so_luong_thuc_te is None: raise ValidationError('Chưa nhập số lượng kiểm đếm')
    delta=line.so_luong_thuc_te-line.so_luong_he_thong
    if adj.so_luong_dieu_chinh!=delta: raise ValidationError('Số lượng điều chỉnh phải bằng chênh lệch thực tế - hệ thống')
    stock=TonKho.objects.select_for_update().get(hang_hoa=line.hang_hoa,vi_tri=line.pham_vi.vi_tri)
    before=stock.so_luong_ton;after=before+delta
    if after<0: raise ValidationError('Điều chỉnh tạo tồn âm')
    stock.so_luong_ton=after;stock.save(update_fields=['so_luong_ton','thoi_gian_cap_nhat'])
    line.chenh_lech=delta;line.save(update_fields=['chenh_lech'])
    adj.trang_thai='da_duyet';adj.nguoi_phe_duyet=actor;adj.thoi_gian_phe_duyet=timezone.now()
    adj.save(update_fields=['trang_thai','nguoi_phe_duyet','thoi_gian_phe_duyet'])
    NhatKyGiaoDich.objects.create(nguoi_thuc_hien=actor,dot_kiem_ke=line.pham_vi.dot_kiem_ke,
      dieu_chinh=adj,hang_hoa=line.hang_hoa,vi_tri=line.pham_vi.vi_tri,loai_giao_dich='kiem_ke',
      hanh_dong='DIEU_CHINH',noi_dung_thay_doi=adj.ly_do,so_luong_truoc=before,so_luong_sau=after)


@transaction.atomic
def finish_count(pk,user):
    actor=manager_account(user)
    batch=DotKiemKe.objects.select_for_update().get(pk=pk)
    if batch.trang_thai!='dang_kiem': raise ValidationError('Đợt kiểm kê chưa bắt đầu')
    for scope in batch.pham_vi.all():
        for line in scope.chi_tiet.all():
            if line.so_luong_thuc_te is None: raise ValidationError('Còn dòng chưa kiểm đếm')
            if line.so_luong_thuc_te != line.so_luong_he_thong:
                if not DieuChinhTonKho.objects.filter(chi_tiet_kiem_ke=line,trang_thai='da_duyet').exists():
                    raise ValidationError('Còn chênh lệch chưa được phê duyệt điều chỉnh')
        scope.trang_thai_khoa=False;scope.thoi_gian_mo_khoa=timezone.now()
        scope.nguoi_xac_nhan_mo_khoa=actor
        scope.save(update_fields=['trang_thai_khoa','thoi_gian_mo_khoa','nguoi_xac_nhan_mo_khoa'])
    batch.trang_thai='hoan_tat';batch.thoi_gian_ket_thuc=timezone.now()
    batch.save(update_fields=['trang_thai','thoi_gian_ket_thuc'])
