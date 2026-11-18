
"""All stock changes must go through these transactional services."""

from decimal import Decimal
from collections import defaultdict

from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from .models import *


# ==========================================================
# 1. PHAN QUYEN QUAN LY
# ==========================================================

def manager_account(user):
    account = (
        TaiKhoan.objects
        .select_related('vai_tro')
        .filter(
            user=user,
            user__is_active=True,
            trang_thai=True,
        )
        .first()
    )

    if not account:
        raise PermissionDenied(
            'Cần tài khoản WMS đang hoạt động.'
        )

    if not (
        user.is_superuser
        or account.vai_tro.ten_vai_tro == 'Quản lý kho'
    ):
        raise PermissionDenied(
            'Chỉ quản lý kho được phê duyệt.'
        )

    return account


# ==========================================================
# 2. KIEM TRA KHOA VI TRI TU QUY TRINH KIEM KE CU
# ==========================================================

def assert_not_locked(vi_tri_id):
    if PhamViKiemKe.objects.filter(
        vi_tri_id=vi_tri_id,
        trang_thai_khoa=True,
    ).exists():
        raise ValidationError(
            'Vị trí đang bị khóa do kiểm kê.'
        )


# ==========================================================
# 3. DONG BO GIAO DICH THEO KHO
# ==========================================================

def lock_warehouse(kho_id):
    """
    Goi trong transaction.atomic().

    PostgreSQL ho tro select_for_update() theo row.
    SQLite khong co row-level SELECT FOR UPDATE.
    """
    return (
        Kho.objects
        .select_for_update()
        .get(pk=kho_id)
    )


# ==========================================================
# 4. KIEM TRA KHOA KIEM KHO
# ==========================================================

def assert_no_pending_stockcheck(
    kho_id,
    goods_ids,
    *,
    ignore_draft_for=None,
):
    """
    Kiem tra khoa kiem kho truoc khi thao tac ton.

    Cach moi:
        Truyen danh sach (hang_hoa_id, vi_tri_id).
        Chi chan dung san pham tai dung vi tri.

    Cach cu:
        Truyen danh sach hang_hoa_id.
        Tam thoi kiem tra toan bo ma hang de tuong thich
        voi nhung file chua duoc cap nhat.

    ignore_draft_for:
        (account_id, draft_token)
        Chi su dung khi tao phieu kiem kho.
        Khong su dung cho nhap/xuat.
    """

    # ------------------------------------------------------
    # 4.1. CHUAN HOA DANH SACH HANG HOA / VI TRI
    # ------------------------------------------------------

    raw_items = [
        item
        for item in goods_ids
        if item is not None
    ]

    specific_positions = (
        bool(raw_items)
        and all(
            isinstance(item, (tuple, list))
            and len(item) == 2
            for item in raw_items
        )
    )

    selected_pairs = None

    try:
        if specific_positions:
            selected_pairs = {
                (int(hang_id), int(vi_tri_id))
                for hang_id, vi_tri_id in raw_items
            }

            ids = {
                hang_id
                for hang_id, _ in selected_pairs
            }

        else:
            # Ho tro cac loi goi cu chua chuyen doi
            if any(
                isinstance(item, (tuple, list))
                for item in raw_items
            ):
                raise ValidationError(
                    'Danh sách sản phẩm và vị trí không hợp lệ.'
                )

            ids = {
                int(item)
                for item in raw_items
            }

    except (TypeError, ValueError):
        raise ValidationError(
            'Mã hàng hóa hoặc vị trí không hợp lệ.'
        )

    if any(pk <= 0 for pk in ids):
        raise ValidationError(
            'Mã hàng hóa không hợp lệ.'
        )

    if selected_pairs is not None and any(
        vi_tri_id <= 0
        for _, vi_tri_id in selected_pairs
    ):
        raise ValidationError(
            'Mã vị trí không hợp lệ.'
        )

    # ------------------------------------------------------
    # 4.2. PHIEU KIEM KHO TOAN BO DANG CHO DUYET
    # ------------------------------------------------------

    full_pending = (
        PhieuKiemKho.objects.filter(
            kho_id=kho_id,
            trang_thai='cho_duyet',
            loai_kiem_ke='toan_bo',
        )
        .first()
    )

    if full_pending:
        raise ValidationError(
            f'Kho đang kiểm kê toàn bộ theo phiếu '
            f'{full_pending.ma_phieu} (Chờ duyệt). '
            'Tạm dừng nhập/xuất trong kho '
            'cho đến khi phiếu được xử lý.'
        )

    # ------------------------------------------------------
    # 4.3. KHOA TAM DANG HIEU LUC
    # ------------------------------------------------------

    temporary_locks = KhoaTamKiemKho.objects.filter(
        kho_id=kho_id,
        het_han_luc__gt=timezone.now(),
    )

    # Bo qua khoa cua chinh phien lap kiem kho
    # khi va chi khi duoc truyen tham so nay.
    if ignore_draft_for is not None:
        owner_id, session_id = ignore_draft_for

        temporary_locks = temporary_locks.exclude(
            nguoi_giu_id=owner_id,
            phien_tao=session_id,
        )

    # Khoa tam toan bo kho: chan moi giao dich
    full_draft = temporary_locks.filter(
        hang_hoa__isnull=True,
    ).exists()

    if full_draft:
        raise ValidationError(
            'Kho đang được lập phiếu kiểm kho toàn bộ. '
            'Tạm khóa mọi giao dịch nhập/xuất '
            'cho đến khi hoàn tất hoặc hủy thao tác.'
        )

    if not ids:
        return

    # ------------------------------------------------------
    # 4.4. PHIEU KIEM KHO MOT PHAN CHO DUYET
    # ------------------------------------------------------

    pending_lines = (
        ChiTietPhieuKiemKho.objects
        .select_related(
            'phieu',
            'hang_hoa',
            'vi_tri',
        )
        .filter(
            phieu__kho_id=kho_id,
            phieu__trang_thai='cho_duyet',
            hang_hoa_id__in=ids,
        )
        .order_by(
            'phieu_id',
            'hang_hoa__ma_hang',
        )
    )

    for line in pending_lines:

        # Cach moi: chi chan trung dung vi tri
        if selected_pairs is not None:
            pair = (
                line.hang_hoa_id,
                line.vi_tri_id,
            )

            if pair not in selected_pairs:
                continue

        # Cach cu: chan theo ma hang cho den khi
        # tat ca file duoc cap nhat.
        raise ValidationError(
            f'Mã hàng {line.hang_hoa.ma_hang} '
            f'tại vị trí {line.vi_tri.ma_vi_tri} '
            f'đang được kiểm theo phiếu '
            f'{line.phieu.ma_phieu} (Chờ duyệt). '
            'Tạm khóa nhập/xuất tại vị trí này.'
        )

    # ------------------------------------------------------
    # 4.5. KHOA TAM MOT PHAN
    # ------------------------------------------------------

    draft_lines = (
        temporary_locks
        .select_related(
            'hang_hoa',
            'ton_kho__vi_tri',
        )
        .filter(
            hang_hoa_id__in=ids,
        )
        .order_by(
            'hang_hoa__ma_hang',
        )
    )

    for lock in draft_lines:

        # Cach moi: phai trung hang hoa + vi tri
        if selected_pairs is not None:

            if lock.ton_kho_id is not None:
                pair = (
                    lock.hang_hoa_id,
                    lock.ton_kho.vi_tri_id,
                )

                if pair not in selected_pairs:
                    continue

            # Neu gap khoa tam cu khong co ton_kho_id,
            # tam thoi chan theo ma hang de an toan.

        location_text = ''

        if lock.ton_kho_id is not None:
            location_text = (
                f' tại vị trí '
                f'{lock.ton_kho.vi_tri.ma_vi_tri}'
            )

        raise ValidationError(
            f'Mã hàng {lock.hang_hoa.ma_hang}'
            f'{location_text} đang được lập phiếu kiểm kho. '
            'Tạm khóa nhập/xuất tại phạm vi đang kiểm.'
        )


# ==========================================================
# 5. PHE DUYET PHIEU NHAP / XUAT
# ==========================================================

@transaction.atomic
def approve_receipt(pk, user, direction):
    """
    direction: 'nhap' hoac 'xuat'.

    Chi cap nhat ton khi chung tu duoc phe duyet.
    """

    if direction not in ('nhap', 'xuat'):
        raise ValidationError(
            'Invalid document direction.'
        )

    actor = manager_account(user)

    klass = (
        PhieuNhap
        if direction == 'nhap'
        else PhieuXuat
    )

    doc = (
        klass.objects
        .select_related('kho', 'doi_tac')
        .select_for_update()
        .get(pk=pk)
    )

    if doc.kiem_kho_id:
        raise ValidationError(
            'Không được duyệt lại chứng từ cân bằng kiểm kho.'
        )

    if doc.trang_thai != 'cho_duyet':
        raise ValidationError(
            'Chỉ phiếu chờ duyệt mới được phê duyệt.'
        )

    # Kiem tra doi tac dung nghiep vu
    expected_partner_type = (
        'NCC'
        if direction == 'nhap'
        and doc.kho.loai_kho == 'NVL'

        else 'XUONG'
        if (
            (
                direction == 'nhap'
                and doc.kho.loai_kho == 'TP'
            )
            or (
                direction == 'xuat'
                and doc.kho.loai_kho == 'NVL'
            )
        )

        else 'CHINHANH'
    )

    if (
        doc.doi_tac_id is None
        or doc.doi_tac.loai_doi_tac != expected_partner_type
        or not doc.doi_tac.trang_thai
    ):
        raise ValidationError(
            'Nguồn cung cấp hoặc nơi nhận '
            'không hợp lệ cho loại kho.'
        )

    lock_warehouse(doc.kho_id)

    lines = list(
        doc.chi_tiet.select_related(
            'vi_tri__ke__khu_vuc',
            'hang_hoa',
        )
    )

    if not lines:
        raise ValidationError(
            'Phiếu chưa có dòng hàng.'
        )

    # Khoa theo hang hoa + vi tri, khong khoa ca SKU
    assert_no_pending_stockcheck(
        doc.kho_id,
        [
            (ln.hang_hoa_id, ln.vi_tri_id)
            for ln in lines
        ],
    )

    combined = defaultdict(Decimal)

    for ln in lines:

        ln.full_clean()
        assert_not_locked(ln.vi_tri_id)

        if ln.vi_tri.kho.id != doc.kho_id:
            raise ValidationError(
                'Vị trí không đúng kho.'
            )

        if (
            ln.hang_hoa.nhom_hang.loai_hang
            != doc.kho.loai_kho
        ):
            raise ValidationError(
                'Loại hàng không phù hợp kho.'
            )

        count = (
            ln.so_luong_nhap
            if direction == 'nhap'
            else ln.so_luong_xuat
        )

        combined[
            (ln.hang_hoa_id, ln.vi_tri_id)
        ] += count

    # Khoa cac dong ton theo thu tu on dinh
    for (goods_id, pos_id), count in sorted(
        combined.items()
    ):

        stock = (
            TonKho.objects
            .select_for_update()
            .filter(
                hang_hoa_id=goods_id,
                vi_tri_id=pos_id,
            )
            .first()
        )

        if stock is None:

            if direction == 'xuat':
                raise ValidationError(
                    'Không có tồn ở vị trí xuất.'
                )

            stock = TonKho.objects.create(
                hang_hoa_id=goods_id,
                vi_tri_id=pos_id,
                so_luong_ton=0,
            )

        before = stock.so_luong_ton

        after = (
            before + count
            if direction == 'nhap'
            else before - count
        )

        if after < 0:
            raise ValidationError(
                f'Xuất vượt tồn: hàng #{goods_id}, '
                f'vị trí #{pos_id}; tồn {before}.'
            )

        stock.so_luong_ton = after

        stock.save(
            update_fields=[
                'so_luong_ton',
                'thoi_gian_cap_nhat',
            ]
        )

        NhatKyGiaoDich.objects.create(
            nguoi_thuc_hien=actor,
            phieu_nhap=(
                doc if direction == 'nhap'
                else None
            ),
            phieu_xuat=(
                doc if direction == 'xuat'
                else None
            ),
            hang_hoa_id=goods_id,
            vi_tri_id=pos_id,
            loai_giao_dich=direction,
            hanh_dong='PHE_DUYET',
            noi_dung_thay_doi=(
                f'{direction} {count}'
            ),
            so_luong_truoc=before,
            so_luong_sau=after,
        )

    doc.trang_thai = 'da_duyet'
    doc.nguoi_phe_duyet = actor
    doc.thoi_gian_phe_duyet = timezone.now()

    doc.save(
        update_fields=[
            'trang_thai',
            'nguoi_phe_duyet',
            'thoi_gian_phe_duyet',
        ]
    )

    return doc


# ==========================================================
# 6. BAT DAU DOT KIEM KE CU
# ==========================================================

@transaction.atomic
def start_count(pk, user):

    manager_account(user)

    batch = (
        DotKiemKe.objects
        .select_for_update()
        .get(pk=pk)
    )

    if batch.trang_thai != 'nhap':
        raise ValidationError(
            'Đợt kiểm kê phải ở trạng thái nháp.'
        )

    lock_warehouse(batch.kho_id)

    # Khong de quy trinh kiem ke cu chong
    # voi phieu kiem kho cho duyet.
    if PhieuKiemKho.objects.filter(
        kho_id=batch.kho_id,
        trang_thai='cho_duyet',
    ).exists():
        raise ValidationError(
            'Kho có phiếu kiểm kho đang chờ duyệt; '
            'không thể bắt đầu đợt kiểm kê vị trí.'
        )

    # Tam chan bat dau dot kiem ke cu neu
    # dang co phien lap phieu kiem kho moi.
    if KhoaTamKiemKho.objects.filter(
        kho_id=batch.kho_id,
        het_han_luc__gt=timezone.now(),
    ).exists():
        raise ValidationError(
            'Kho đang có phiên lập phiếu kiểm kho. '
            'Vui lòng hoàn tất phiên đó trước.'
        )

    scopes = list(
        batch.pham_vi.select_related(
            'vi_tri__ke__khu_vuc'
        )
    )

    if not scopes:
        raise ValidationError(
            'Chưa có vị trí kiểm kê.'
        )

    for scope in scopes:

        if scope.vi_tri.kho.id != batch.kho_id:
            raise ValidationError(
                'Vị trí kiểm kê không thuộc kho.'
            )

        if PhamViKiemKe.objects.filter(
            vi_tri=scope.vi_tri,
            trang_thai_khoa=True,
        ).exclude(pk=scope.pk).exists():
            raise ValidationError(
                'Vị trí đang được kiểm kê ở đợt khác.'
            )

        scope.trang_thai_khoa = True
        scope.thoi_gian_khoa = timezone.now()

        scope.save(
            update_fields=[
                'trang_thai_khoa',
                'thoi_gian_khoa',
            ]
        )

        for stock in (
            TonKho.objects
            .filter(vi_tri=scope.vi_tri)
            .select_for_update()
        ):

            ChiTietKiemKe.objects.get_or_create(
                pham_vi=scope,
                hang_hoa=stock.hang_hoa,
                defaults={
                    'so_luong_he_thong': stock.so_luong_ton
                },
            )

    batch.trang_thai = 'dang_kiem'
    batch.thoi_gian_bat_dau = timezone.now()

    batch.save(
        update_fields=[
            'trang_thai',
            'thoi_gian_bat_dau',
        ]
    )


# ==========================================================
# 7. PHE DUYET DIEU CHINH TON KHO
# ==========================================================

@transaction.atomic
def approve_adjustment(pk, user):

    actor = manager_account(user)

    adj = (
        DieuChinhTonKho.objects
        .select_for_update()
        .select_related(
            'chi_tiet_kiem_ke__pham_vi'
        )
        .get(pk=pk)
    )

    if adj.trang_thai != 'cho_duyet':
        raise ValidationError(
            'Điều chỉnh đã được xử lý.'
        )

    line = adj.chi_tiet_kiem_ke

    kho_id = line.pham_vi.vi_tri.kho.id

    lock_warehouse(kho_id)

    assert_no_pending_stockcheck(
        kho_id,
        [
            (
                line.hang_hoa_id,
                line.pham_vi.vi_tri_id,
            )
        ],
    )

    if line.so_luong_thuc_te is None:
        raise ValidationError(
            'Chưa nhập số lượng kiểm đếm.'
        )

    delta = (
        line.so_luong_thuc_te
        - line.so_luong_he_thong
    )

    if adj.so_luong_dieu_chinh != delta:
        raise ValidationError(
            'Số lượng điều chỉnh phải bằng '
            'chênh lệch thực tế - hệ thống.'
        )

    stock = (
        TonKho.objects
        .select_for_update()
        .get(
            hang_hoa=line.hang_hoa,
            vi_tri=line.pham_vi.vi_tri,
        )
    )

    before = stock.so_luong_ton
    after = before + delta

    if after < 0:
        raise ValidationError(
            'Điều chỉnh tạo tồn âm.'
        )

    stock.so_luong_ton = after

    stock.save(
        update_fields=[
            'so_luong_ton',
            'thoi_gian_cap_nhat',
        ]
    )

    line.chenh_lech = delta

    line.save(
        update_fields=['chenh_lech']
    )

    adj.trang_thai = 'da_duyet'
    adj.nguoi_phe_duyet = actor
    adj.thoi_gian_phe_duyet = timezone.now()

    adj.save(
        update_fields=[
            'trang_thai',
            'nguoi_phe_duyet',
            'thoi_gian_phe_duyet',
        ]
    )

    NhatKyGiaoDich.objects.create(
        nguoi_thuc_hien=actor,
        dot_kiem_ke=line.pham_vi.dot_kiem_ke,
        dieu_chinh=adj,
        hang_hoa=line.hang_hoa,
        vi_tri=line.pham_vi.vi_tri,
        loai_giao_dich='kiem_ke',
        hanh_dong='DIEU_CHINH',
        noi_dung_thay_doi=adj.ly_do,
        so_luong_truoc=before,
        so_luong_sau=after,
    )


# ==========================================================
# 8. KET THUC DOT KIEM KE CU
# ==========================================================

@transaction.atomic
def finish_count(pk, user):

    actor = manager_account(user)

    batch = (
        DotKiemKe.objects
        .select_for_update()
        .get(pk=pk)
    )

    if batch.trang_thai != 'dang_kiem':
        raise ValidationError(
            'Đợt kiểm kê chưa bắt đầu.'
        )

    for scope in batch.pham_vi.all():

        for line in scope.chi_tiet.all():

            if line.so_luong_thuc_te is None:
                raise ValidationError(
                    'Còn dòng chưa kiểm đếm.'
                )

            if (
                line.so_luong_thuc_te
                != line.so_luong_he_thong
            ):
                if not DieuChinhTonKho.objects.filter(
                    chi_tiet_kiem_ke=line,
                    trang_thai='da_duyet',
                ).exists():
                    raise ValidationError(
                        'Còn chênh lệch chưa được '
                        'phê duyệt điều chỉnh.'
                    )

        scope.trang_thai_khoa = False
        scope.thoi_gian_mo_khoa = timezone.now()
        scope.nguoi_xac_nhan_mo_khoa = actor

        scope.save(
            update_fields=[
                'trang_thai_khoa',
                'thoi_gian_mo_khoa',
                'nguoi_xac_nhan_mo_khoa',
            ]
        )

    batch.trang_thai = 'hoan_tat'
    batch.thoi_gian_ket_thuc = timezone.now()

    batch.save(
        update_fields=[
            'trang_thai',
            'thoi_gian_ket_thuc',
        ]
    )


# ==========================================================
# 9. PHE DUYET HUY PHIEU DA DUYET
# ==========================================================

@transaction.atomic
def approve_cancellation(pk, user):
    """
    Hoan tac chung tu da duyet dung mot lan.
    Khong xoa cac dong chi tiet goc.
    """

    actor = manager_account(user)

    req = (
        YeuCauXuLyPhieu.objects
        .select_for_update()
        .get(pk=pk)
    )

    if (
        req.trang_thai != 'cho_duyet'
        or req.loai_yeu_cau != 'huy'
    ):
        raise ValidationError(
            'Yêu cầu không còn chờ duyệt hủy.'
        )

    direction = (
        'nhap' if req.phieu_nhap_id
        else 'xuat'
    )

    doc = (
        PhieuNhap.objects
        .select_for_update()
        .get(pk=req.phieu_nhap_id)

        if direction == 'nhap'

        else PhieuXuat.objects
        .select_for_update()
        .get(pk=req.phieu_xuat_id)
    )

    if doc.kiem_kho_id:
        raise ValidationError(
            'Không được hủy riêng chứng từ '
            'sinh từ cân bằng kiểm kho.'
        )

    if doc.trang_thai != 'da_duyet':
        raise ValidationError(
            'Phiếu không còn ở trạng thái đã duyệt.'
        )

    lock_warehouse(doc.kho_id)

    lines = list(
        doc.chi_tiet.select_related(
            'vi_tri',
            'hang_hoa',
        )
    )

    # Kiem tra khoa theo hang hoa + vi tri
    assert_no_pending_stockcheck(
        doc.kho_id,
        [
            (ln.hang_hoa_id, ln.vi_tri_id)
            for ln in lines
        ],
    )

    combined = defaultdict(Decimal)

    for ln in lines:

        assert_not_locked(ln.vi_tri_id)

        qty = (
            ln.so_luong_nhap
            if direction == 'nhap'
            else ln.so_luong_xuat
        )

        combined[
            (ln.hang_hoa_id, ln.vi_tri_id)
        ] += qty

    locks = {}

    for key, count in sorted(
        combined.items()
    ):

        stock = (
            TonKho.objects
            .select_for_update()
            .filter(
                hang_hoa_id=key[0],
                vi_tri_id=key[1],
            )
            .first()
        )

        if stock is None:
            raise ValidationError(
                'Không tìm thấy dòng tồn kho '
                'để hoàn tác.'
            )

        new = (
            stock.so_luong_ton - count
            if direction == 'nhap'
            else stock.so_luong_ton + count
        )

        if new < 0:
            raise ValidationError(
                'Không thể hủy phiếu nhập vì số hàng '
                'đã được xuất; cần xử lý nghiệp vụ bổ sung.'
            )

        locks[key] = (
            stock,
            count,
            new,
        )

    for (goods_id, pos_id), (
        stock,
        count,
        new,
    ) in locks.items():

        before = stock.so_luong_ton
        stock.so_luong_ton = new

        stock.save(
            update_fields=[
                'so_luong_ton',
                'thoi_gian_cap_nhat',
            ]
        )

        NhatKyGiaoDich.objects.create(
            nguoi_thuc_hien=actor,
            yeu_cau=req,
            phieu_nhap=(
                doc if direction == 'nhap'
                else None
            ),
            phieu_xuat=(
                doc if direction == 'xuat'
                else None
            ),
            hang_hoa_id=goods_id,
            vi_tri_id=pos_id,
            loai_giao_dich='huy_' + direction,
            hanh_dong='HOAN_TAC',
            noi_dung_thay_doi=req.ly_do,
            so_luong_truoc=before,
            so_luong_sau=new,
        )

    doc.trang_thai = 'da_huy'

    doc.save(
        update_fields=['trang_thai']
    )

    req.trang_thai = 'da_duyet'
    req.nguoi_phe_duyet = actor
    req.thoi_gian_phe_duyet = timezone.now()

    req.noi_dung_xu_ly = (
        'Đã duyệt hủy và ghi bút toán hoàn tác tồn kho'
    )

    req.save(
        update_fields=[
            'trang_thai',
            'nguoi_phe_duyet',
            'thoi_gian_phe_duyet',
            'noi_dung_xu_ly',
        ]
    )
