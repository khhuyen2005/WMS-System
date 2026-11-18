
"""Nghiep vu phieu kiem kho.

Quy trinh:
1. Nhan vien lap phieu, nhap so luong thuc te.
2. Phieu o trang thai Cho duyet.
3. Quan ly phe duyet de can bang ton kho hoac tu choi.

Khoa kiem kho:
- Mot phan: khoa theo hang hoa + vi tri trong kho.
- Toan bo: khoa toan bo kho.
"""

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    ChiTietPhieuKiemKho,
    NhatKyGiaoDich,
    PhieuKiemKho,
    PhieuNhap,
    PhieuXuat,
    ChiTietPhieuNhap,
    ChiTietPhieuXuat,
    TonKho,
    KhoaTamKiemKho,
)

from .services import (
    assert_not_locked,
    assert_no_pending_stockcheck,
    lock_warehouse,
    manager_account,
)


MAX_LINES = 100
MAX_ALL_LINES = 5000
MAX_QUANTITY = Decimal('999999999999.99')


# ==========================================================
# 1. SINH MA PHIEU KIEM KHO
# ==========================================================

def next_stock_check_code():
    """Ma phieu theo nam: KK-2026-001, KK-2026-002..."""

    year = timezone.localdate().year
    prefix = f'KK-{year}-'
    pattern = re.compile(rf'^KK-{year}-(\d+)$')

    numbers = []

    codes = PhieuKiemKho.objects.filter(
        ma_phieu__startswith=prefix
    ).values_list('ma_phieu', flat=True)

    for code in codes:
        match = pattern.match(code)

        if match:
            numbers.append(int(match.group(1)))

    next_number = (max(numbers) if numbers else 0) + 1

    return f'{prefix}{next_number:03d}'


# ==========================================================
# 2. KIEM TRA SO LUONG THUC TE
# ==========================================================

def parse_quantity(raw):
    """
    So luong thuc te:
    - Khong am.
    - Toi da 2 chu so thap phan.
    """

    try:
        number = Decimal(str(raw).strip())

        if (
            not number.is_finite()
            or number < 0
            or number > MAX_QUANTITY
            or number.as_tuple().exponent < -2
        ):
            raise InvalidOperation

        return number

    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            'Số lượng thực tế phải là số không âm, '
            'tối đa 2 chữ số thập phân.'
        )


# ==========================================================
# 3. TAO PHIEU KIEM KHO
# ==========================================================

def create_stock_check(
    account,
    kho,
    note,
    entries,
    loai_kiem_ke="mot_phan",
    draft_token=None,
):
    """
    Lap phieu kiem kho o trang thai Cho duyet.

    entries:
        Danh sach (ton_kho_id, so_luong_thuc_te).

    Ton he thong duoc lay tu database.

    Co che khoa:
        - Mot phan: hang hoa + vi tri.
        - Toan bo: ca kho.
        - Bo qua khoa tam cua chinh phien dang luu.
    """

    if not entries:
        raise ValidationError(
            'Phiếu kiểm kho cần ít nhất một sản phẩm.'
        )

    if loai_kiem_ke not in ('mot_phan', 'toan_bo'):
        raise ValidationError(
            'Loại kiểm kê không hợp lệ.'
        )

    limit = (
        MAX_ALL_LINES
        if loai_kiem_ke == 'toan_bo'
        else MAX_LINES
    )

    if len(entries) > limit:
        raise ValidationError(
            f'Loại kiểm kê này tối đa {limit} dòng hàng. '
            'Nếu kho quá lớn, cần tổ chức nhiều đợt kiểm kê riêng.'
        )

    note = (note or '').strip()

    if len(note) > 500:
        raise ValidationError(
            'Ghi chú tối đa 500 ký tự.'
        )

    with transaction.atomic():

        # Dong bo voi nghiep vu nhap/xuat
        lock_warehouse(kho.pk)

        # --------------------------------------------------
        # KIEM KE TOAN BO
        # --------------------------------------------------

        if loai_kiem_ke == 'toan_bo':

            other_pending = (
                PhieuKiemKho.objects.filter(
                    kho_id=kho.pk,
                    trang_thai='cho_duyet',
                )
                .first()
            )

            if other_pending:
                raise ValidationError(
                    f'Kho đang có phiếu '
                    f'{other_pending.ma_phieu} chờ duyệt. '
                    'Hãy xử lý phiếu đó trước khi '
                    'kiểm kê toàn bộ.'
                )

            # Lay tat ca dong ton kho thuc te
            expected_ids = set(
                TonKho.objects.filter(
                    vi_tri__ke__khu_vuc__kho_id=kho.pk
                ).values_list(
                    'pk',
                    flat=True,
                )
            )

            try:
                submitted_ids = [
                    int(raw_id)
                    for raw_id, _ in entries
                ]

            except (TypeError, ValueError):
                raise ValidationError(
                    'Danh sách hàng kiểm kê không hợp lệ.'
                )

            if (
                set(submitted_ids) != expected_ids
                or len(submitted_ids) != len(expected_ids)
            ):
                raise ValidationError(
                    'Kiểm kê toàn bộ phải có đủ '
                    'các dòng tồn của kho. '
                    'Vui lòng tải lại trang và '
                    'điền số lượng thực tế.'
                )

        # --------------------------------------------------
        # DOC VA KIEM TRA CAC DONG TON
        # --------------------------------------------------

        seen = set()
        prepared = []

        for raw_id, raw_quantity in entries:

            try:
                stock_id = int(raw_id)

            except (TypeError, ValueError):
                raise ValidationError(
                    'Vui lòng chọn sản phẩm ở tất cả các dòng.'
                )

            if stock_id in seen:
                raise ValidationError(
                    'Mỗi dòng tồn kho chỉ được kiểm '
                    'một lần trong phiếu.'
                )

            seen.add(stock_id)

            stock = (
                TonKho.objects
                .select_for_update()
                .select_related(
                    'hang_hoa',
                    'vi_tri__ke__khu_vuc__kho',
                )
                .filter(pk=stock_id)
                .first()
            )

            if (
                stock is None
                or stock.vi_tri.kho.pk != kho.pk
            ):
                raise ValidationError(
                    'Sản phẩm không thuộc kho đã chọn.'
                )

            # Kiem tra khoa vi tri cua nghiep vu cu
            assert_not_locked(stock.vi_tri_id)

            quantity = parse_quantity(raw_quantity)

            prepared.append(
                (stock, quantity)
            )

        # --------------------------------------------------
        # KIEM TRA TRUNG KHOA
        # --------------------------------------------------

        # Chi kiem tra trung hang hoa + vi tri.
        # Khong chan cung ma hang tai vi tri khac.
        #
        # Khoa tam cua chinh phien dang luu
        # duoc bo qua, nhung cac khoa khac van bi chan.

        selected_pairs = [
            (
                stock.hang_hoa_id,
                stock.vi_tri_id,
            )
            for stock, _ in prepared
        ]

        assert_no_pending_stockcheck(
            kho.pk,
            selected_pairs,
            ignore_draft_for=(
                (account.pk, draft_token)
                if draft_token
                else None
            ),
        )

        # --------------------------------------------------
        # TAO PHIEU KIEM KHO
        # --------------------------------------------------

        phieu = None

        # Thu lai neu trung ma phieu
        for _ in range(5):

            try:
                with transaction.atomic():

                    phieu = PhieuKiemKho.objects.create(
                        kho=kho,
                        nguoi_lap=account,
                        ma_phieu=next_stock_check_code(),
                        loai_kiem_ke=loai_kiem_ke,
                        ghi_chu=note,
                    )

                break

            except IntegrityError:
                continue

        if phieu is None:
            raise ValidationError(
                'Không thể tạo mã phiếu tự động. '
                'Vui lòng thử lại.'
            )

        # --------------------------------------------------
        # LUU CHI TIET PHIEU
        # --------------------------------------------------

        ChiTietPhieuKiemKho.objects.bulk_create([
            ChiTietPhieuKiemKho(
                phieu=phieu,
                hang_hoa=stock.hang_hoa,
                vi_tri=stock.vi_tri,
                so_luong_he_thong=stock.so_luong_ton,
                so_luong_thuc_te=quantity,
            )
            for stock, quantity in prepared
        ])

        return phieu


# ==========================================================
# 4. KIEM TRA QUYEN SUA / XOA PHIEU
# ==========================================================

def _check_pending_owner(phieu, account):
    """
    Nguoi lap hoac Quan ly kho duoc sua/xoa
    phieu dang Cho duyet.
    """

    is_manager = (
        account.user.is_superuser
        or account.vai_tro.ten_vai_tro == 'Quản lý kho'
    )

    if not (
        is_manager
        or phieu.nguoi_lap_id == account.pk
    ):
        raise PermissionDenied(
            'Bạn không có quyền sửa hoặc '
            'xóa phiếu kiểm kho này.'
        )

    if phieu.trang_thai != 'cho_duyet':
        raise PermissionDenied(
            'Chỉ được sửa hoặc xóa phiếu kiểm kho '
            'đang Chờ duyệt.'
        )


# ==========================================================
# 5. SUA PHIEU KIEM KHO CHO DUYET
# ==========================================================

@transaction.atomic
def update_pending_stock_check(
    pk,
    account,
    note,
    entries,
):
    """
    Sua phieu Cho duyet, khong thay doi TonKho.

    Giu nguyen:
    - Ma phieu.
    - Kho.
    - Loai kiem ke.

    Kiem tra xung dot khoa theo:
        Hang hoa + vi tri.
    """

    phieu = (
        PhieuKiemKho.objects
        .select_for_update()
        .select_related(
            'nguoi_lap',
            'kho',
        )
        .get(pk=pk)
    )

    _check_pending_owner(phieu, account)

    lock_warehouse(phieu.kho_id)

    note = (note or '').strip()

    if len(note) > 500:
        raise ValidationError(
            'Ghi chú tối đa 500 ký tự.'
        )

    limit = (
        MAX_ALL_LINES
        if phieu.loai_kiem_ke == 'toan_bo'
        else MAX_LINES
    )

    if not entries or len(entries) > limit:
        raise ValidationError(
            f'Phiếu cần từ 1 đến {limit} dòng kiểm kho.'
        )

    # ------------------------------------------------------
    # KIEM TRA TON CUA CAC DONG CU
    # ------------------------------------------------------

    old_lines = list(
        phieu.chi_tiet.select_related(
            'hang_hoa',
            'vi_tri',
        )
    )

    for old in old_lines:

        current = stock_for_line(old)

        if (
            current is None
            or current.so_luong_ton
            != old.so_luong_he_thong
        ):
            raise ValidationError(
                f'Tồn kho {old.hang_hoa.ma_hang} '
                f'đã thay đổi so với lúc lập phiếu. '
                'Hãy từ chối phiếu cũ và '
                'lập phiếu kiểm kho mới.'
            )

    # ------------------------------------------------------
    # DOC CAC DONG TON KHO MOI
    # ------------------------------------------------------

    seen = set()
    prepared = []

    for raw_id, raw_quantity in entries:

        try:
            stock_id = int(raw_id)

        except (TypeError, ValueError):
            raise ValidationError(
                'Danh sách sản phẩm không hợp lệ.'
            )

        if stock_id in seen:
            raise ValidationError(
                'Một dòng tồn kho không được nhập hai lần.'
            )

        seen.add(stock_id)

        stock = (
            TonKho.objects
            .select_for_update()
            .select_related(
                'hang_hoa',
                'vi_tri__ke__khu_vuc__kho',
            )
            .filter(pk=stock_id)
            .first()
        )

        if (
            stock is None
            or stock.vi_tri.kho.pk != phieu.kho_id
        ):
            raise ValidationError(
                'Sản phẩm không thuộc kho đang kiểm kê.'
            )

        assert_not_locked(stock.vi_tri_id)

        prepared.append(
            (
                stock,
                parse_quantity(raw_quantity),
            )
        )

    # ------------------------------------------------------
    # KIEM KE TOAN BO PHAI DU CAC DONG TON
    # ------------------------------------------------------

    if phieu.loai_kiem_ke == 'toan_bo':

        all_ids = set(
            TonKho.objects.filter(
                vi_tri__ke__khu_vuc__kho_id=phieu.kho_id
            ).values_list(
                'id',
                flat=True,
            )
        )

        if seen != all_ids:
            raise ValidationError(
                'Kiểm kê Toàn bộ phải có đầy đủ '
                'các dòng tồn kho hiện tại.'
            )

    # ------------------------------------------------------
    # KIEM TRA PHIEU CHO DUYET KHAC
    # ------------------------------------------------------

    other_pending = (
        PhieuKiemKho.objects.filter(
            kho_id=phieu.kho_id,
            trang_thai='cho_duyet',
        )
        .exclude(pk=phieu.pk)
    )

    if phieu.loai_kiem_ke == 'toan_bo':

        if other_pending.exists():
            raise ValidationError(
                'Kho có phiếu kiểm kho khác '
                'đang Chờ duyệt.'
            )

    else:

        if other_pending.filter(
            loai_kiem_ke='toan_bo'
        ).exists():
            raise ValidationError(
                'Kho đang có phiếu kiểm kê '
                'Toàn bộ chờ duyệt.'
            )

        # Lay dung cac cap hang hoa + vi tri
        selected_pairs = {
            (
                stock.hang_hoa_id,
                stock.vi_tri_id,
            )
            for stock, _ in prepared
        }

        selected_goods = {
            hang_id
            for hang_id, _ in selected_pairs
        }

        selected_positions = {
            vi_tri_id
            for _, vi_tri_id in selected_pairs
        }

        possible_conflicts = (
            ChiTietPhieuKiemKho.objects
            .select_related(
                'hang_hoa',
                'vi_tri',
                'phieu',
            )
            .filter(
                phieu__in=other_pending,
                hang_hoa_id__in=selected_goods,
                vi_tri_id__in=selected_positions,
            )
        )

        for line in possible_conflicts:

            pair = (
                line.hang_hoa_id,
                line.vi_tri_id,
            )

            if pair in selected_pairs:
                raise ValidationError(
                    f'Mã {line.hang_hoa.ma_hang} '
                    f'tại vị trí {line.vi_tri.ma_vi_tri} '
                    f'đang được kiểm theo phiếu '
                    f'{line.phieu.ma_phieu}.'
                )

    # ------------------------------------------------------
    # KIEM TRA KHOA TAM CUA CAC PHIEN DANG LAP
    # ------------------------------------------------------

    temporary_locks = (
        KhoaTamKiemKho.objects.filter(
            kho_id=phieu.kho_id,
            het_han_luc__gt=timezone.now(),
        )
    )

    if phieu.loai_kiem_ke == 'toan_bo':

        if temporary_locks.exists():
            raise ValidationError(
                'Kho đang có phiên kiểm kho khác. '
                'Chưa thể sửa phiếu.'
            )

    else:

        selected_goods_ids = {
            stock.hang_hoa_id
            for stock, _ in prepared
        }

        # Chan:
        # - Khoa tam toan bo kho.
        # - Dung dong TonKho dang duoc khoa.
        # - Khoa tam cu chua gan vi tri, neu co.
        conflict = temporary_locks.filter(
            Q(hang_hoa__isnull=True)
            | Q(ton_kho_id__in=seen)
            | Q(
                ton_kho__isnull=True,
                hang_hoa_id__in=selected_goods_ids,
            )
        ).exists()

        if conflict:
            raise ValidationError(
                'Có sản phẩm tại vị trí được chọn '
                'đang được lập phiếu kiểm kho '
                'ở phiên khác.'
            )

    # ------------------------------------------------------
    # CAP NHAT CHI TIET TRONG CUNG TRANSACTION
    # ------------------------------------------------------

    # Xoa chi tiet cu khong lam thay doi TonKho
    phieu.chi_tiet.all().delete()

    ChiTietPhieuKiemKho.objects.bulk_create([
        ChiTietPhieuKiemKho(
            phieu=phieu,
            hang_hoa=stock.hang_hoa,
            vi_tri=stock.vi_tri,
            so_luong_he_thong=stock.so_luong_ton,
            so_luong_thuc_te=quantity,
        )
        for stock, quantity in prepared
    ])

    phieu.ghi_chu = note

    phieu.save(
        update_fields=['ghi_chu']
    )

    NhatKyGiaoDich.objects.create(
        nguoi_thuc_hien=account,
        loai_giao_dich='kiem_kho',
        hanh_dong='SUA_PHIEU_KIEM_KHO',
        noi_dung_thay_doi=(
            f'Sửa phiếu kiểm kho {phieu.ma_phieu} '
            f'đang Chờ duyệt; {len(prepared)} dòng; '
            'không tác động tồn kho.'
        ),
    )

    return phieu


# ==========================================================
# 6. XOA PHIEU KIEM KHO CHO DUYET
# ==========================================================

@transaction.atomic
def delete_pending_stock_check(pk, account):
    """
    Xoa phieu Cho duyet.

    Khoa cho duyet dua tren du lieu cua phieu.
    Xoa phieu thi khoa cho duyet tu duoc giai phong.
    """

    phieu = (
        PhieuKiemKho.objects
        .select_for_update()
        .get(pk=pk)
    )

    _check_pending_owner(phieu, account)

    lock_warehouse(phieu.kho_id)

    code = phieu.ma_phieu

    phieu.delete()

    NhatKyGiaoDich.objects.create(
        nguoi_thuc_hien=account,
        loai_giao_dich='kiem_kho',
        hanh_dong='XOA_PHIEU_KIEM_KHO',
        noi_dung_thay_doi=(
            f'Xóa phiếu kiểm kho {code} '
            'khi đang Chờ duyệt. '
            'Đã giải phóng khóa nhập/xuất, '
            'không tác động tồn kho.'
        ),
    )

    return code


# ==========================================================
# 7. LAY TON KHO HIEN TAI
# ==========================================================

def stock_for_line(line):
    return TonKho.objects.filter(
        hang_hoa=line.hang_hoa,
        vi_tri=line.vi_tri,
    ).first()


# ==========================================================
# 8. TAO CHUNG TU CAN BANG KIEM KHO
# ==========================================================

def create_balance_vouchers(phieu, actor):
    """
    Tao chung tu nhap/xuat tu dong sau khi duyet kiem kho.

    KHONG cong/tru ton kho lan thu hai.

    Moi phieu kiem kho toi da co:
    - 1 phieu nhap can bang.
    - 1 phieu xuat can bang.
    """

    if phieu.trang_thai != 'da_duyet':
        raise ValidationError(
            'Phiếu kiểm kho chưa được phê duyệt.'
        )

    lines = list(
        phieu.chi_tiet.select_related(
            'hang_hoa',
            'vi_tri',
        )
    )

    grouped = {
        'nhap': [
            line
            for line in lines
            if line.chenh_lech > 0
        ],
        'xuat': [
            line
            for line in lines
            if line.chenh_lech < 0
        ],
    }

    results = {}

    for direction, adjusted in grouped.items():

        klass = (
            PhieuNhap
            if direction == 'nhap'
            else PhieuXuat
        )

        detail_klass = (
            ChiTietPhieuNhap
            if direction == 'nhap'
            else ChiTietPhieuXuat
        )

        code_field = (
            'ma_phieu_nhap'
            if direction == 'nhap'
            else 'ma_phieu_xuat'
        )

        detail_fk = (
            'phieu_nhap'
            if direction == 'nhap'
            else 'phieu_xuat'
        )

        quantity_field = (
            'so_luong_nhap'
            if direction == 'nhap'
            else 'so_luong_xuat'
        )

        code = (
            ('PN-' if direction == 'nhap' else 'PX-')
            + phieu.ma_phieu
        )

        existing = klass.objects.filter(
            kiem_kho=phieu
        ).first()

        if not adjusted:

            if existing:
                raise ValidationError(
                    'Phiếu kiểm kho có chứng từ '
                    'điều chỉnh không khớp.'
                )

            continue

        if existing:

            actual = sorted(
                (
                    row.hang_hoa_id,
                    row.vi_tri_id,
                    getattr(row, quantity_field),
                )
                for row in existing.chi_tiet.all()
            )

            expected = sorted(
                (
                    line.hang_hoa_id,
                    line.vi_tri_id,
                    abs(line.chenh_lech),
                )
                for line in adjusted
            )

            if getattr(existing, code_field) != code:
                raise ValidationError(
                    'Mã chứng từ kiểm kho hiện hữu không khớp.'
                )

            if (
                actual != expected
                or existing.trang_thai != 'da_duyet'
            ):
                raise ValidationError(
                    'Chi tiết chứng từ kiểm kho '
                    'hiện hữu không khớp.'
                )

            results[direction] = existing

            continue

        doc = klass.objects.create(
            **{code_field: code},
            kho=phieu.kho,
            doi_tac=None,
            nguoi_lap=phieu.nguoi_lap,
            nguoi_phe_duyet=actor,
            thoi_gian_phe_duyet=(
                phieu.thoi_gian_phe_duyet
                or timezone.now()
            ),
            trang_thai='da_duyet',
            kiem_kho=phieu,
            ghi_chu=(
                f'Chứng từ điều chỉnh nội bộ '
                f'do kiểm kho {phieu.ma_phieu}. '
                'Tồn kho đã được cân bằng khi '
                'phê duyệt kiểm kho; '
                'không ghi tăng/giảm thêm '
                'từ chứng từ này.'
            ),
        )

        for line in adjusted:

            detail = detail_klass(
                **{
                    detail_fk: doc,
                    quantity_field: abs(line.chenh_lech),
                },
                hang_hoa=line.hang_hoa,
                vi_tri=line.vi_tri,
                don_gia=(
                    line.hang_hoa.don_gia
                    or Decimal('0.00')
                ),
            )

            detail.full_clean()
            detail.save()

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
            loai_giao_dich=direction,
            hanh_dong='SINH_PHIEU_KIEM_KHO',
            noi_dung_thay_doi=(
                f'Tự sinh chứng từ {code} '
                f'từ kiểm kho {phieu.ma_phieu}, '
                f'{len(adjusted)} dòng. '
                'Không thay đổi tồn kho lần hai.'
            ),
        )

        results[direction] = doc

    return results


# ==========================================================
# 9. PHE DUYET PHIEU KIEM KHO
# ==========================================================

@transaction.atomic
def approve_stock_check(pk, user):
    """
    Quan ly phe duyet:
        Ton kho = so luong thuc te.

    Chi duyet khi ton hien tai van bang
    ton he thong luc lap phieu.

    Ngan ghi de cac bien dong hop le.
    """

    actor = manager_account(user)

    phieu = (
        PhieuKiemKho.objects
        .select_for_update()
        .get(pk=pk)
    )

    lock_warehouse(phieu.kho_id)

    if phieu.trang_thai != 'cho_duyet':
        raise ValidationError(
            'Chỉ phiếu đang chờ duyệt '
            'mới được phê duyệt.'
        )

    lines = list(
        phieu.chi_tiet.select_related(
            'hang_hoa',
            'vi_tri',
        )
    )

    if not lines:
        raise ValidationError(
            'Phiếu chưa có dòng sản phẩm.'
        )

    stocks = {}

    # ------------------------------------------------------
    # KIEM TRA TON HIEN TAI
    # ------------------------------------------------------

    for line in lines:

        assert_not_locked(line.vi_tri_id)

        stock = (
            TonKho.objects
            .select_for_update()
            .filter(
                hang_hoa=line.hang_hoa,
                vi_tri=line.vi_tri,
            )
            .first()
        )

        if (
            stock is None
            or stock.so_luong_ton
            != line.so_luong_he_thong
        ):

            current = (
                'không còn tồn'
                if stock is None
                else f'{stock.so_luong_ton.normalize():f}'
            )

            raise ValidationError(
                f'Tồn kho của '
                f'{line.hang_hoa.ma_hang} tại '
                f'{line.vi_tri.ma_vi_tri} '
                'đã thay đổi sau khi lập phiếu '
                f'(lúc lập: '
                f'{line.so_luong_he_thong.normalize():f}, '
                f'hiện tại: {current}). '
                'Hãy từ chối phiếu này và '
                'lập phiếu kiểm kho mới.'
            )

        stocks[line.pk] = stock

    # ------------------------------------------------------
    # CAP NHAT TON KHO
    # ------------------------------------------------------

    changed = 0

    for line in lines:

        stock = stocks[line.pk]

        before = stock.so_luong_ton
        after = line.so_luong_thuc_te

        if before == after:
            continue

        stock.so_luong_ton = after

        stock.save(
            update_fields=[
                'so_luong_ton',
                'thoi_gian_cap_nhat',
            ]
        )

        changed += 1

        NhatKyGiaoDich.objects.create(
            nguoi_thuc_hien=actor,
            hang_hoa=line.hang_hoa,
            vi_tri=line.vi_tri,
            loai_giao_dich='kiem_kho',
            hanh_dong='CAN_BANG_KHO',
            noi_dung_thay_doi=(
                f'Phiếu kiểm kho {phieu.ma_phieu}: '
                f'tồn hệ thống '
                f'{before.normalize():f} → '
                f'thực tế {after.normalize():f} '
                f'(chênh lệch {after - before:+f})'
            ),
            so_luong_truoc=before,
            so_luong_sau=after,
        )

    # ------------------------------------------------------
    # CAP NHAT TRANG THAI PHIEU
    # ------------------------------------------------------

    phieu.trang_thai = 'da_duyet'
    phieu.nguoi_phe_duyet = actor
    phieu.thoi_gian_phe_duyet = timezone.now()

    phieu.save(
        update_fields=[
            'trang_thai',
            'nguoi_phe_duyet',
            'thoi_gian_phe_duyet',
        ]
    )

    # Tao chung tu can bang, khong ghi ton lan 2
    create_balance_vouchers(phieu, actor)

    NhatKyGiaoDich.objects.create(
        nguoi_thuc_hien=actor,
        loai_giao_dich='kiem_kho',
        hanh_dong='PHE_DUYET_KIEM_KHO',
        noi_dung_thay_doi=(
            f'Phê duyệt phiếu kiểm kho '
            f'{phieu.ma_phieu}: '
            f'{len(lines)} sản phẩm, '
            f'{changed} sản phẩm được điều chỉnh tồn.'
        ),
    )

    return phieu


# ==========================================================
# 10. TU CHOI PHIEU KIEM KHO
# ==========================================================

@transaction.atomic
def reject_stock_check(pk, user, reason):
    """
    Quan ly tu choi phieu.
    Ton kho khong thay doi.
    """

    actor = manager_account(user)

    reason = (reason or '').strip()

    if not reason:
        raise ValidationError(
            'Vui lòng nhập lý do từ chối phiếu.'
        )

    if len(reason) > 500:
        raise ValidationError(
            'Lý do từ chối tối đa 500 ký tự.'
        )

    phieu = (
        PhieuKiemKho.objects
        .select_for_update()
        .get(pk=pk)
    )

    lock_warehouse(phieu.kho_id)

    if phieu.trang_thai != 'cho_duyet':
        raise ValidationError(
            'Chỉ từ chối phiếu đang chờ duyệt.'
        )

    phieu.trang_thai = 'tu_choi'
    phieu.ly_do_tu_choi = reason
    phieu.nguoi_phe_duyet = actor
    phieu.thoi_gian_phe_duyet = timezone.now()

    phieu.save(
        update_fields=[
            'trang_thai',
            'ly_do_tu_choi',
            'nguoi_phe_duyet',
            'thoi_gian_phe_duyet',
        ]
    )

    NhatKyGiaoDich.objects.create(
        nguoi_thuc_hien=actor,
        loai_giao_dich='kiem_kho',
        hanh_dong='TU_CHOI',
        noi_dung_thay_doi=(
            f'Từ chối phiếu kiểm kho '
            f'{phieu.ma_phieu}. '
            f'Lý do: {reason}'
        ),
    )

    return phieu
