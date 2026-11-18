
import datetime as _dt
import json
import uuid

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError, OperationalError
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import stockcheck

from .models import (
    Kho,
    PhieuKiemKho,
    ChiTietPhieuKiemKho,
    TonKho,
    KhoaTamKiemKho,
)

from .views import authorized, base, manager_only, restricted


VALID_STATUS = {'cho_duyet', 'da_duyet', 'tu_choi'}


# ==========================================================
# KHOA TAM KHI DANG LAP PHIEU KIEM KHO
# ==========================================================

STOCKCHECK_LOCK_SECONDS = 120


def sync_temporary_stockcheck_locks(
    account,
    kho,
    phien_tao,
    loai_kiem_ke,
    ton_kho_ids,
):
    """
    Dong bo khoa tam theo cac dong ton kho duoc chon.

    Kiem ke mot phan:
        Khoa theo kho + hang hoa + vi tri.
        Moi TonKho la mot cap hang hoa / vi tri rieng.

    Kiem ke toan bo:
        Khoa toan bo kho.

    Ham phai duoc goi trong transaction.atomic().
    """

    # ------------------------------------------------------
    # 1. KIEM TRA PHIEN LAP PHIEU
    # ------------------------------------------------------

    try:
        token = uuid.UUID(str(phien_tao))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(
            'Phiên lập phiếu kiểm kho không hợp lệ.'
        )

    if loai_kiem_ke not in ('mot_phan', 'toan_bo'):
        raise ValidationError(
            'Loại kiểm kê không hợp lệ.'
        )

    if not isinstance(ton_kho_ids, (list, tuple)):
        raise ValidationError(
            'Danh sách hàng hóa không hợp lệ.'
        )

    max_lines = (
        5000 if loai_kiem_ke == 'toan_bo'
        else 100
    )

    if len(ton_kho_ids) > max_lines:
        raise ValidationError(
            f'Loại kiểm kê này tối đa {max_lines} dòng hàng.'
        )

    # ------------------------------------------------------
    # 2. CHUYEN DANH SACH TON KHO VE ID
    # ------------------------------------------------------

    try:
        stock_ids = {
            int(value)
            for value in ton_kho_ids
            if str(value).strip()
        }
    except (ValueError, TypeError):
        raise ValidationError(
            'Mã tồn kho không hợp lệ.'
        )

    if any(pk <= 0 for pk in stock_ids):
        raise ValidationError(
            'Mã tồn kho không hợp lệ.'
        )

    # ------------------------------------------------------
    # 3. CHI LAY TON KHO THUOC KHO DANG KIEM
    # ------------------------------------------------------

    stock_rows = list(
        TonKho.objects.filter(
            pk__in=stock_ids,
            vi_tri__ke__khu_vuc__kho=kho,
        ).values_list(
            'pk',
            'hang_hoa_id',
            'vi_tri_id',
        )
    )

    if len(stock_rows) != len(stock_ids):
        raise ValidationError(
            'Có sản phẩm không thuộc kho đang kiểm.'
        )

    # Cap (hang hoa, vi tri) duoc chon
    selected_pairs = {
        (hang_id, vi_tri_id)
        for _, hang_id, vi_tri_id in stock_rows
    }

    goods_ids = {
        hang_id
        for _, hang_id, _ in stock_rows
    }

    position_ids = {
        vi_tri_id
        for _, _, vi_tri_id in stock_rows
    }

    # ------------------------------------------------------
    # 4. DONG BO THEO KHO
    # ------------------------------------------------------

    Kho.objects.select_for_update().get(pk=kho.pk)

    now = timezone.now()

    expires_at = now + timedelta(
        seconds=STOCKCHECK_LOCK_SECONDS
    )

    # Xoa khoa tam da het han
    KhoaTamKiemKho.objects.filter(
        kho=kho,
        het_han_luc__lte=now,
    ).delete()

    # ------------------------------------------------------
    # 5. KIEM TRA PHIEU KIEM KHO CHO DUYET
    # ------------------------------------------------------

    pending = PhieuKiemKho.objects.filter(
        kho=kho,
        trang_thai='cho_duyet',
    )

    if loai_kiem_ke == 'toan_bo':

        # Toan bo khong duoc chong len phieu cho duyet
        if pending.exists():
            raise ValidationError(
                'Kho đang có phiếu kiểm kho chờ duyệt. '
                'Không thể bắt đầu kiểm kê toàn bộ.'
            )

    else:

        # Neu co phieu toan bo dang cho duyet
        # thi khong the kiem ke mot phan.
        if pending.filter(
            loai_kiem_ke='toan_bo'
        ).exists():
            raise ValidationError(
                'Kho đang có phiếu kiểm kê toàn bộ '
                'chờ duyệt.'
            )

        # Lay cac cap hang hoa + vi tri dang cho duyet
        existing_pairs = set(
            ChiTietPhieuKiemKho.objects.filter(
                phieu__kho=kho,
                phieu__trang_thai='cho_duyet',
                hang_hoa_id__in=goods_ids,
                vi_tri_id__in=position_ids,
            ).values_list(
                'hang_hoa_id',
                'vi_tri_id',
            )
        )

        # Chi chan khi trung dung hang hoa va vi tri
        if selected_pairs & existing_pairs:
            raise ValidationError(
                'Sản phẩm tại vị trí được chọn '
                'đã có phiếu kiểm kho chờ duyệt. '
                'Vui lòng chọn vị trí khác.'
            )

    # ------------------------------------------------------
    # 6. KIEM TRA KHOA TAM CUA PHIEN KHAC
    # ------------------------------------------------------

    other_locks = KhoaTamKiemKho.objects.filter(
        kho=kho,
        het_han_luc__gt=now,
    ).exclude(
        nguoi_giu=account,
        phien_tao=token,
    )

    if loai_kiem_ke == 'toan_bo':

        # Kiem ke toan bo khong duoc trung bat ky khoa nao
        if other_locks.exists():
            raise ValidationError(
                'Kho đang được một phiên khác kiểm kho.'
            )

    else:

        # Khoa toan bo hoac dung dong ton kho duoc chon
        if other_locks.filter(
            Q(hang_hoa__isnull=True) |
            Q(ton_kho_id__in=stock_ids)
        ).exists():
            raise ValidationError(
                'Sản phẩm tại vị trí này đang được '
                'kiểm kho trong một phiên khác.'
            )

    # ------------------------------------------------------
    # 7. XAC DINH CAC KHOA CAN GIU
    # ------------------------------------------------------

    if loai_kiem_ke == 'toan_bo':

        wanted = {
            f'KHO:{kho.pk}': (None, None)
        }

    else:

        wanted = {
            f'TON:{kho.pk}:{stock_id}': (
                hang_id,
                stock_id,
            )
            for stock_id, hang_id, _ in stock_rows
        }

    # ------------------------------------------------------
    # 8. GIAI PHONG NHUNG KHOA DA BO CHON
    # ------------------------------------------------------

    KhoaTamKiemKho.objects.filter(
        nguoi_giu=account,
        phien_tao=token,
    ).exclude(
        ma_khoa__in=wanted.keys()
    ).delete()

    # ------------------------------------------------------
    # 9. TAO MOI HOAC GIA HAN KHOA TAM
    # ------------------------------------------------------

    for key, (hang_id, stock_id) in wanted.items():

        lock = (
            KhoaTamKiemKho.objects
            .select_for_update()
            .filter(ma_khoa=key)
            .first()
        )

        if lock is not None:

            # Khong duoc chiem khoa cua phien khac
            if (
                lock.nguoi_giu_id != account.pk
                or lock.phien_tao != token
            ):
                raise ValidationError(
                    'Sản phẩm vừa được một phiên khác khóa.'
                )

            # Gia han khoa
            lock.het_han_luc = expires_at

            lock.save(
                update_fields=[
                    'het_han_luc',
                    'thoi_gian_cap_nhat',
                ]
            )

        else:

            # Tao khoa moi theo dong ton kho
            KhoaTamKiemKho.objects.create(
                kho=kho,
                hang_hoa_id=hang_id,
                ton_kho_id=stock_id,
                ma_khoa=key,
                phien_tao=token,
                nguoi_giu=account,
                het_han_luc=expires_at,
            )

    return len(wanted)


# ==========================================================
# HAM HO TRO
# ==========================================================

def error_text(exc):
    return '; '.join(exc.messages)


def read_date(request, name):
    raw = request.GET.get(name, '').strip()

    if not raw:
        return None

    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        return None


# ==========================================================
# API DONG BO KHOA TAM KIEM KHO
# ==========================================================

@authorized
@require_POST
def sync_stockcheck_draft(request):

    try:
        data = json.loads(request.body)

        if not isinstance(data, dict):
            raise ValueError()

        kho_id = int(data.get('kho') or 0)

        kho = restricted(
            Kho.objects.all(),
            request,
            'loai_kho',
        ).filter(pk=kho_id).first()

        if kho is None:
            return JsonResponse(
                {
                    'ok': False,
                    'message': 'Bạn không có quyền kiểm kho này.',
                },
                status=403,
            )

        with transaction.atomic():
            lock_count = sync_temporary_stockcheck_locks(
                account=request.wms_account,
                kho=kho,
                phien_tao=data.get('phien_tao'),
                loai_kiem_ke=data.get('loai_kiem_ke'),
                ton_kho_ids=data.get('ton_kho_ids', []),
            )

        return JsonResponse({
            'ok': True,
            'lock_count': lock_count,
            'expires_in': STOCKCHECK_LOCK_SECONDS,
        })

    except (ValueError, TypeError):
        return JsonResponse(
            {
                'ok': False,
                'message': 'Dữ liệu gửi lên không hợp lệ.',
            },
            status=400,
        )

    except ValidationError as exc:
        return JsonResponse(
            {
                'ok': False,
                'message': error_text(exc),
            },
            status=409,
        )

    except (IntegrityError, OperationalError):
        return JsonResponse(
            {
                'ok': False,
                'message': (
                    'Không thể khóa sản phẩm lúc này. '
                    'Vui lòng thử lại.'
                ),
            },
            status=503,
        )


# ==========================================================
# API GIAI PHONG KHOA TAM
# ==========================================================

@authorized
@require_POST
def release_stockcheck_draft(request):

    try:
        data = json.loads(request.body)

        if not isinstance(data, dict):
            raise ValueError()

        token = uuid.UUID(
            str(data.get('phien_tao', ''))
        )

    except (ValueError, TypeError, AttributeError):
        return JsonResponse(
            {
                'ok': False,
                'message': 'Phiên lập phiếu không hợp lệ.',
            },
            status=400,
        )

    # Chi duoc giai phong khoa cua tai khoan hien tai
    KhoaTamKiemKho.objects.filter(
        nguoi_giu=request.wms_account,
        phien_tao=token,
    ).delete()

    return JsonResponse({'ok': True})


# ==========================================================
# 1. DANH SACH PHIEU KIEM KHO
# ==========================================================

@authorized
def stock_checks(request):

    rows = restricted(
        PhieuKiemKho.objects.select_related(
            'kho',
            'nguoi_lap',
        ),
        request,
        'kho__loai_kho',
    )

    # So phieu dang cho quan ly duyet
    pending_count = rows.filter(
        trang_thai='cho_duyet'
    ).count()

    status = request.GET.get('status', '')

    if status in VALID_STATUS:
        rows = rows.filter(trang_thai=status)
    else:
        status = ''

    start_date = read_date(request, 'tu_ngay')
    end_date = read_date(request, 'den_ngay')

    if start_date and end_date and start_date > end_date:
        messages.error(
            request,
            'Ngày bắt đầu không được sau ngày kết thúc.',
        )
        start_date = end_date = None

    if start_date:
        rows = rows.filter(
            thoi_gian_lap__date__gte=start_date
        )

    if end_date:
        rows = rows.filter(
            thoi_gian_lap__date__lte=end_date
        )

    return render(
        request,
        'wms_core/stockcheck_list.html',
        base(
            request,
            rows=rows.order_by(
                '-thoi_gian_lap',
                '-id',
            )[:200],
            status=status,
            start_date=(
                start_date.isoformat()
                if start_date else ''
            ),
            end_date=(
                end_date.isoformat()
                if end_date else ''
            ),
            pending_count=pending_count,
            section='counts',
        ),
    )


# ==========================================================
# 2. TAO PHIEU KIEM KHO
# ==========================================================

@authorized
def create_stock_check(request):

    # Moi bieu mau co mot ma phien khoa tam rieng
    raw_token = (
        request.POST.get('phien_tao', '')
        if request.method == 'POST'
        else ''
    )

    try:
        draft_token = (
            str(uuid.UUID(raw_token))
            if raw_token
            else str(uuid.uuid4())
        )
    except (ValueError, TypeError, AttributeError):
        draft_token = str(uuid.uuid4())

    # Nhan vien chi thay kho cua minh
    # Quan ly thay moi kho
    warehouses = restricted(
        Kho.objects.all(),
        request,
        'loai_kho',
    ).order_by('pk')

    initial_lines = []
    initial_note = ''
    selected_type = 'mot_phan'

    selected_kho = (
        warehouses.first().pk
        if request.wms_kind and warehouses.exists()
        else ''
    )

    if request.method == 'POST':

        initial_note = request.POST.get(
            'ghi_chu',
            '',
        )

        selected_type = request.POST.get(
            'loai_kiem_ke',
            '',
        ).strip()

        ids = request.POST.getlist('ton_kho')
        quantities = request.POST.getlist('so_luong_thuc_te')

        initial_lines = [
            {
                'ton_kho': a,
                'so_luong_thuc_te': b,
            }
            for a, b in zip(ids, quantities)
        ]

        kho = warehouses.filter(
            pk=request.POST.get('kho') or 0
        ).first()

        selected_kho = kho.pk if kho else ''

        try:
            if kho is None:
                raise ValidationError(
                    'Vui lòng chọn kho cần kiểm.'
                )

            if len(ids) != len(quantities):
                raise ValidationError(
                    'Mỗi dòng phải có sản phẩm '
                    'và số lượng thực tế.'
                )

            with transaction.atomic():

                # Kiem tra va giu khoa truoc khi luu phieu
                sync_temporary_stockcheck_locks(
                    account=request.wms_account,
                    kho=kho,
                    phien_tao=draft_token,
                    loai_kiem_ke=selected_type,
                    ton_kho_ids=ids,
                )

                # Tao phieu kiem kho
                phieu = stockcheck.create_stock_check(
                    request.wms_account,
                    kho,
                    initial_note,
                    list(zip(ids, quantities)),
                    loai_kiem_ke=selected_type,
                    draft_token=draft_token,
                )

                # Da co phieu cho duyet thi bo khoa tam
                # Co che khoa cho duyet tiep tuc co hieu luc
                KhoaTamKiemKho.objects.filter(
                    nguoi_giu=request.wms_account,
                    phien_tao=uuid.UUID(draft_token),
                ).delete()

        except ValidationError as exc:
            messages.error(
                request,
                'Không thể tạo phiếu: ' + error_text(exc),
            )

        except (IntegrityError, OperationalError):
            messages.error(
                request,
                'Không thể tạo phiếu do xung đột dữ liệu. '
                'Vui lòng thử lại.',
            )

        else:
            messages.success(
                request,
                f'Đã tạo phiếu kiểm kho {phieu.ma_phieu} '
                'và gửi quản lý phê duyệt. '
                'Tồn kho chưa thay đổi.',
            )
            return redirect('wms_stock_checks')

    stocks = TonKho.objects.filter(
        vi_tri__ke__khu_vuc__kho__in=warehouses
    ).select_related(
        'hang_hoa',
        'vi_tri__ke__khu_vuc__kho',
    ).order_by(
        'hang_hoa__ma_hang',
        'vi_tri__ma_vi_tri',
    )

    return render(
        request,
        'wms_core/stockcheck_form.html',
        base(
            request,
            warehouses=warehouses,
            stocks=stocks,
            selected_kho=selected_kho,
            initial_lines=initial_lines,
            initial_note=initial_note,
            selected_type=selected_type,
            stockcheck_draft_token=draft_token,
            next_code=stockcheck.next_stock_check_code(),
            section='counts',
        ),
    )


# ==========================================================
# 2B. SUA PHIEU CHO DUYET
# ==========================================================

@authorized
def edit_stock_check(request, pk):

    phieu = get_object_or_404(
        PhieuKiemKho.objects.select_related(
            'kho',
            'nguoi_lap',
        ),
        pk=pk,
    )

    if (
        request.wms_kind
        and phieu.kho.loai_kho != request.wms_kind
    ):
        raise PermissionDenied(
            'Không có quyền truy cập kho này.'
        )

    if not (
        request.wms_manager
        or phieu.nguoi_lap_id == request.wms_account.pk
    ):
        raise PermissionDenied(
            'Chỉ người lập hoặc quản lý được sửa phiếu.'
        )

    if phieu.trang_thai != 'cho_duyet':
        raise PermissionDenied(
            'Chỉ được sửa phiếu đang Chờ duyệt.'
        )

    old_lines = list(
        phieu.chi_tiet.select_related(
            'hang_hoa',
            'vi_tri',
        )
    )

    initial_lines = [
        {
            'ton_kho': str(row.pk),
            'so_luong_thuc_te': str(
                line.so_luong_thuc_te
            ),
        }
        for line in old_lines
        for row in TonKho.objects.filter(
            hang_hoa_id=line.hang_hoa_id,
            vi_tri_id=line.vi_tri_id,
        )
    ]

    initial_note = phieu.ghi_chu

    if request.method == 'POST':

        initial_note = request.POST.get(
            'ghi_chu',
            '',
        )

        ids = request.POST.getlist('ton_kho')
        quantities = request.POST.getlist('so_luong_thuc_te')

        initial_lines = [
            {
                'ton_kho': str(a),
                'so_luong_thuc_te': b,
            }
            for a, b in zip(ids, quantities)
        ]

        try:
            if str(
                request.POST.get('kho', '')
            ) != str(phieu.kho_id):
                raise ValidationError(
                    'Không được thay đổi kho '
                    'của phiếu kiểm kho.'
                )

            if (
                request.POST.get('loai_kiem_ke')
                != phieu.loai_kiem_ke
            ):
                raise ValidationError(
                    'Không được đổi loại kiểm kê. '
                    'Hãy tạo phiếu mới.'
                )

            if len(ids) != len(quantities):
                raise ValidationError(
                    'Số lượng dòng kiểm kê không hợp lệ.'
                )

            stockcheck.update_pending_stock_check(
                phieu.pk,
                request.wms_account,
                initial_note,
                list(zip(ids, quantities)),
            )

        except ValidationError as exc:
            messages.error(
                request,
                'Không thể sửa phiếu: ' + error_text(exc),
            )

        else:
            messages.success(
                request,
                f'Đã cập nhật phiếu {phieu.ma_phieu}.',
            )

            return redirect(
                'wms_stock_check_detail',
                pk=phieu.pk,
            )

    warehouses = restricted(
        Kho.objects.all(),
        request,
        'loai_kho',
    ).order_by('pk')

    stocks = TonKho.objects.filter(
        vi_tri__ke__khu_vuc__kho=phieu.kho
    ).select_related(
        'hang_hoa',
        'vi_tri__ke__khu_vuc__kho',
    ).order_by(
        'hang_hoa__ma_hang',
        'vi_tri__ma_vi_tri',
    )

    return render(
        request,
        'wms_core/stockcheck_form.html',
        base(
            request,
            warehouses=warehouses,
            stocks=stocks,
            selected_kho=phieu.kho_id,
            selected_type=phieu.loai_kiem_ke,
            initial_lines=initial_lines,
            initial_note=initial_note,
            next_code=phieu.ma_phieu,
            edit_mode=True,
            edit_phieu=phieu,
            section='counts',
        ),
    )


# ==========================================================
# 2C. XOA PHIEU CHO DUYET
# ==========================================================

@authorized
@require_POST
def delete_stock_check(request, pk):

    phieu = get_object_or_404(
        PhieuKiemKho,
        pk=pk,
    )

    if (
        request.wms_kind
        and phieu.kho.loai_kho != request.wms_kind
    ):
        raise PermissionDenied(
            'Không có quyền truy cập kho này.'
        )

    if not (
        request.wms_manager
        or phieu.nguoi_lap_id == request.wms_account.pk
    ):
        raise PermissionDenied(
            'Chỉ người lập hoặc quản lý được xóa phiếu.'
        )

    if phieu.trang_thai != 'cho_duyet':
        raise PermissionDenied(
            'Chỉ được xóa phiếu đang Chờ duyệt.'
        )

    code = stockcheck.delete_pending_stock_check(
        pk,
        request.wms_account,
    )

    messages.success(
        request,
        f'Đã xóa phiếu kiểm kho {code}.',
    )

    return redirect('wms_stock_checks')


# ==========================================================
# 3. CHI TIET PHIEU KIEM KHO
# ==========================================================

@authorized
def stock_check_detail(request, pk):

    phieu = get_object_or_404(
        PhieuKiemKho.objects.select_related(
            'kho',
            'nguoi_lap',
            'nguoi_phe_duyet',
        ),
        pk=pk,
    )

    if (
        request.wms_kind
        and phieu.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden(
            'Không có quyền xem phiếu thuộc kho khác.'
        )

    lines = list(
        phieu.chi_tiet.select_related(
            'hang_hoa__don_vi_tinh',
            'vi_tri',
        ).order_by(
            'hang_hoa__ma_hang',
            'vi_tri__ma_vi_tri',
        )
    )

    # Phieu cho duyet: kiem tra ton co thay doi hay khong
    stale = False

    if phieu.trang_thai == 'cho_duyet':

        for line in lines:

            current = stockcheck.stock_for_line(line)

            line.ton_hien_tai = (
                current.so_luong_ton
                if current else None
            )

            line.da_thay_doi = (
                current is None
                or current.so_luong_ton
                != line.so_luong_he_thong
            )

            stale = stale or line.da_thay_doi

    return render(
        request,
        'wms_core/stockcheck_detail.html',
        base(
            request,
            phieu=phieu,
            lines=lines,
            diff_count=sum(
                1
                for x in lines
                if x.chenh_lech != 0
            ),
            stale=stale,
            section='counts',
        ),
    )


# ==========================================================
# 4. PHE DUYET / TU CHOI PHIEU KIEM KHO
# ==========================================================

@authorized
@require_POST
def stock_check_action(request, pk, action):

    manager_only(request)

    if action not in ('approve', 'reject'):
        raise Http404(
            'Thao tác không hợp lệ.'
        )

    get_object_or_404(
        PhieuKiemKho,
        pk=pk,
    )

    try:

        if action == 'approve':

            stockcheck.approve_stock_check(
                pk,
                request.user,
            )

            messages.success(
                request,
                'Đã phê duyệt phiếu. '
                'Tồn kho hệ thống đã được cập nhật '
                'bằng số lượng thực tế.',
            )

        else:

            stockcheck.reject_stock_check(
                pk,
                request.user,
                request.POST.get('ly_do', ''),
            )

            messages.success(
                request,
                'Đã từ chối phiếu. '
                'Tồn kho không thay đổi.',
            )

    except ValidationError as exc:
        messages.error(
            request,
            'Không thể xử lý: ' + error_text(exc),
        )

    return redirect(
        'wms_stock_check_detail',
        pk=pk,
    )
