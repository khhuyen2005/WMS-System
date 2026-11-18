from decimal import Decimal, InvalidOperation
from functools import wraps
from collections import defaultdict
import csv
import uuid
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired

from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Sum, Q

from django.http import (
    HttpResponseForbidden,
    Http404,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import *
from . import services
from .forms import HangHoaForm, next_nvl_code, next_tp_code



# ==========================================================
# 1. PHÂN QUYỀN VÀ HÀM DÙNG CHUNG
# ==========================================================

def account_for(user):
    return TaiKhoan.objects.select_related('vai_tro').filter(
        user=user, user__is_active=True, trang_thai=True
    ).first()


def authorized(view):
    @login_required
    @wraps(view)
    def inner(request, *args, **kwargs):
        account = account_for(request.user)
        if account is None:
            return HttpResponseForbidden(
                'Tài khoản chưa được phân quyền WMS.'
            )

        request.wms_account = account
        role = account.vai_tro.ten_vai_tro
        request.wms_manager = (
            request.user.is_superuser or role == 'Quản lý kho'
        )
        request.wms_kind = (
            'NVL' if role == 'Nhân viên kho NVL'
            else 'TP' if role == 'Nhân viên kho thành phẩm'
            else None
        )

        if (
            request.wms_kind and kwargs.get('kind')
            and kwargs['kind'] != request.wms_kind
        ):
            return HttpResponseForbidden(
                'Không có quyền truy cập kho này.'
            )
        return view(request, *args, **kwargs)
    return inner


def base(request, **extra):
    data = {
        'is_manager': request.wms_manager,
        'role_name': request.wms_account.vai_tro.ten_vai_tro,
        'allowed_kind': request.wms_kind,
        'warehouse_options': (
            Kho.objects.filter(loai_kho=request.wms_kind)
            if request.wms_kind else Kho.objects.all()
        ),
    }
    data.update(extra)
    return data


def restricted(qs, request, field):
    if request.wms_kind:
        return qs.filter(**{field: request.wms_kind})
    return qs


def decimal_pos(raw):
    try:
        number = Decimal(str(raw))
        if not number.is_finite() or number <= 0:
            raise InvalidOperation
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('Số lượng phải là số dương hợp lệ.')


def decimal_price(raw):
    try:
        number = Decimal(str(raw))
        if not number.is_finite() or number < 0:
            raise InvalidOperation
        if number.as_tuple().exponent < -2:
            raise ValidationError('Đơn giá chỉ có tối đa 2 số thập phân.')
        if number >= Decimal('100000000000000'):
            raise ValidationError('Đơn giá vượt giới hạn cho phép.')
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('Đơn giá phải là số không âm hợp lệ.')


def generate_document_code(prefix):
    """
    Tự động sinh mã phiếu.

    Ví dụ:
    PN-20261104-A81C2D74
    PX-20261104-B73F1952
    KK-20261104-C92E4108
    """
    today = timezone.localtime().strftime('%Y%m%d')
    random_code = uuid.uuid4().hex[:12].upper()

    return f'{prefix}-{today}-{random_code}'


def manager_only(request):
    if not request.wms_manager:
        raise PermissionDenied('Chỉ quản lý kho được thao tác.')


def manager_action(request, fn):
    manager_only(request)
    try:
        fn()
        messages.success(
            request, 'Đã xử lý thành công và ghi nhận trên hệ thống.'
        )
    except (ValidationError, ValueError) as exc:
        messages.error(request, 'Không thể xử lý: ' + str(exc))


# ==========================================================
# 2. TỔNG QUAN
# ==========================================================


@authorized
def home(request):
    # Nếu là quản lý -> Chuyển thẳng vào xem Dashboard
    if request.wms_manager:
        return redirect('wms_dashboard')

    # Nếu là nhân viên -> Hiển thị trang chào mừng (Welcome)
    return render(request, 'wms_core/welcome.html', base(request, section='home'))


@authorized
def dashboard(request):
    manager_only(request)  # DÒNG MỚI THÊM: Chặn nhân viên nếu họ cố tình gõ URL /dashboard/

    stocks = restricted(TonKho.objects.select_related('hang_hoa__nhom_hang', 'vi_tri__ke__khu_vuc__kho'), request,
                        'vi_tri__ke__khu_vuc__kho__loai_kho')
    # ... (Giữ nguyên các đoạn code phía dưới của hàm này)

    from collections import defaultdict
    from datetime import timedelta
    from decimal import Decimal
    from django.utils import timezone

    # ==================================================
    # 1. BO LOC KHO VA PHAN QUYEN
    # ==================================================

    requested_kind = (
        request.GET.get('kho') or 'ALL'
    ).upper()

    if requested_kind not in ('ALL', 'NVL', 'TP'):
        requested_kind = 'ALL'

    # Nhan vien chi duoc xem kho cua minh
    kho_filter = request.wms_kind or requested_kind

    goods_qs = HangHoa.objects.select_related(
        'nhom_hang',
        'don_vi_tinh'
    )

    stocks_qs = TonKho.objects.all()

    # Chi tinh chung tu da duyet
    # Khong tinh chung tu can bang kiem kho
    receipts = PhieuNhap.objects.filter(
        trang_thai='da_duyet',
        kiem_kho__isnull=True
    )

    issues = PhieuXuat.objects.filter(
        trang_thai='da_duyet',
        kiem_kho__isnull=True
    )

    if kho_filter in ('NVL', 'TP'):

        goods_qs = goods_qs.filter(
            nhom_hang__loai_hang=kho_filter
        )

        stocks_qs = stocks_qs.filter(
            vi_tri__ke__khu_vuc__kho__loai_kho=kho_filter
        )

        receipts = receipts.filter(
            kho__loai_kho=kho_filter
        )

        issues = issues.filter(
            kho__loai_kho=kho_filter
        )

    # ==================================================
    # 2. TONG HOP TON KHO THEO MA HANG
    # ==================================================

    qty_by_good = defaultdict(
        lambda: Decimal('0')
    )

    for stock in stocks_qs:
        qty_by_good[
            stock.hang_hoa_id
        ] += stock.so_luong_ton

    # ==================================================
    # 3. XU HUONG NHAP XUAT 30 NGAY
    # ==================================================

    today = timezone.localdate()
    first_day = today - timedelta(days=29)

    days = [
        first_day + timedelta(days=i)
        for i in range(30)
    ]

    trend = {
        day.isoformat(): {
            'nhap': 0.0,
            'xuat': 0.0
        }
        for day in days
    }

    export_by_good = defaultdict(
        lambda: Decimal('0')
    )

    incoming_30d = (
        ChiTietPhieuNhap.objects.filter(
            phieu_nhap__in=receipts,
            phieu_nhap__thoi_gian_phe_duyet__date__gte=first_day
        )
        .select_related('phieu_nhap')
    )

    for line in incoming_30d:

        approved = (
            line.phieu_nhap.thoi_gian_phe_duyet
        )

        if approved:

            day = timezone.localtime(
                approved
            ).date().isoformat()

            if day in trend:
                trend[day]['nhap'] += float(
                    line.so_luong_nhap
                )

    outgoing_30d = (
        ChiTietPhieuXuat.objects.filter(
            phieu_xuat__in=issues,
            phieu_xuat__thoi_gian_phe_duyet__date__gte=first_day
        )
        .select_related('phieu_xuat')
    )

    for line in outgoing_30d:

        approved = (
            line.phieu_xuat.thoi_gian_phe_duyet
        )

        if approved:

            day = timezone.localtime(
                approved
            ).date().isoformat()

            if day in trend:

                qty = line.so_luong_xuat

                trend[day]['xuat'] += float(qty)

                export_by_good[
                    line.hang_hoa_id
                ] += qty

    # ==================================================
    # 4. XAC DINH NCC / XUONG TU PHIEU NHAP
    # ==================================================

    source_by_good = {}

    source_lines = (
        ChiTietPhieuNhap.objects.filter(
            phieu_nhap__in=receipts,
            phieu_nhap__doi_tac__isnull=False
        )
        .select_related(
            'phieu_nhap__doi_tac',
            'phieu_nhap__kho'
        )
        .order_by(
            '-phieu_nhap__thoi_gian_phe_duyet',
            '-pk'
        )
    )

    for line in source_lines:

        doc = line.phieu_nhap
        partner = doc.doi_tac

        needed = (
            'NCC'
            if doc.kho.loai_kho == 'NVL'
            else 'XUONG'
        )

        if partner.loai_doi_tac == needed:

            source_by_good.setdefault(
                line.hang_hoa_id,
                partner.ten_doi_tac
            )

    # ==================================================
    # 5. BANG DOI CHIEU NCC / XUONG
    # DUNG CHO SKU CHUA CO PHIEU NHAP DA DUYET
    # ==================================================

    fallback_ncc = {
        'NVL001': 'Cơ sở vật tư in Bình Minh',
        'NVL002': 'Đại lý phụ liệu Kim Phúc',
        'NVL003': 'Cơ sở vải Minh Long',
        'NVL004': 'Cơ sở vải An Phú',
        'NVL005': 'Cơ sở vải Minh Long',
        'NVL006': 'Đại lý phụ liệu Kim Phúc',
        'NVL007': 'Cơ sở vải An Phú',
        'NVL008': 'Đại lý phụ liệu Kim Phúc',
        'NVL009': 'Đại lý phụ liệu Kim Phúc',
        'NVL010': 'Đại lý phụ liệu Kim Phúc',
        'NVL011': 'Cơ sở vật tư in Bình Minh',
        'NVL012': 'Cơ sở vật tư in Bình Minh',
    }

    fallback_xuong = {
        'TP001': 'Xưởng gia công may An Nhiên',
        'TP002': 'Xưởng gia công may An Nhiên',
        'TP003': 'Xưởng gia công may Minh Tâm',
        'TP004': 'Xưởng gia công may Minh Tâm',
        'TP005': 'Xưởng gia công may An Nhiên',
        'TP006': 'Xưởng gia công may An Nhiên',
        'TP007': 'Xưởng gia công may Minh Tâm',
        'TP008': 'Xưởng gia công may Minh Tâm',
        'TP009': 'Xưởng gia công may An Nhiên',
        'TP010': 'Xưởng gia công may Minh Tâm',
    }

    # ==================================================
    # 6. DU LIEU CHO BIEU DO NVL VA THANH PHAM
    # ==================================================

    nvl_items = []
    tp_items = []

    nvl_colors = set()
    nvl_suppliers = set()

    tp_sizes = set()
    tp_colors = set()
    tp_suppliers = set()

    top_moving = []
    dead_stock = []

    for item in goods_qs.order_by('ma_hang'):

        qty = float(
            qty_by_good[item.pk]
        )

        issued = float(
            export_by_good[item.pk]
        )

        kind = item.nhom_hang.loai_hang

        color = (
            (item.mau_sac or '').strip()
            or 'Chưa xác định'
        )

        unit = (
            item.don_vi_tinh.ten_don_vi_tinh
        )

        # Uu tien thong tin tu phieu nhap da duyet
        source = source_by_good.get(item.pk)

        if not source:

            if kind == 'NVL':

                source = fallback_ncc.get(
                    item.ma_hang,
                    'Chưa xác định NCC'
                )

            else:

                source = fallback_xuong.get(
                    item.ma_hang,
                    'Chưa xác định xưởng'
                )

        row = {
            'ma_hang': item.ma_hang,
            'ten_hang': item.ten_hang,
            'so_luong_ton': qty,
            'don_vi': unit,
        }

        if kind == 'NVL':

            nvl_items.append({
                **row,
                'mau_sac': color,
                'ncc': source
            })

            nvl_colors.add(color)
            nvl_suppliers.add(source)

        else:

            size = (
                (item.kich_co or '').strip()
                or 'Chưa có size'
            )

            tp_items.append({
                **row,
                'mau_sac': color,
                'kich_co': size,
                'xuong': source
            })

            tp_sizes.add(size)
            tp_colors.add(color)
            tp_suppliers.add(source)

        # Top 10 luan chuyen va chua xuat
        movement = {
            **row,
            'tong_xuat': issued,
            'tong_ton': qty
        }

        if issued > 0:

            top_moving.append(movement)

        elif qty > 0:

            dead_stock.append(movement)

    top_moving.sort(
        key=lambda x: (
            -x['tong_xuat'],
            x['ma_hang']
        )
    )

    dead_stock.sort(
        key=lambda x: (
            -x['tong_ton'],
            x['ma_hang']
        )
    )

    # ==================================================
    # 7. KPI DOI TAC
    # ==================================================

    if kho_filter == 'NVL':

        partner_types = ['NCC']
        partner_label = 'Nhà cung cấp'

    elif kho_filter == 'TP':

        partner_types = ['XUONG']
        partner_label = 'Xưởng gia công'

    else:

        partner_types = [
            'NCC',
            'XUONG'
        ]

        partner_label = (
            'Đối tác (NCC / Xưởng)'
        )

    # ==================================================
    # 8. CHUAN BI DU LIEU JSON
    # ==================================================

    dashboard_payload = {

        'trend_dates': [
            day.strftime('%d/%m')
            for day in days
        ],

        'trend_nhap': [
            trend[day.isoformat()]['nhap']
            for day in days
        ],

        'trend_xuat': [
            trend[day.isoformat()]['xuat']
            for day in days
        ],

        'top_moving': top_moving[:10],
        'dead_stock': dead_stock[:10],

        'nvl_items': nvl_items,
        'tp_items': tp_items,
    }

    # ==================================================
    # 9. RENDER DASHBOARD
    # ==================================================

    return render(
        request,
        'wms_core/dashboard.html',
        base(
            request,

            section='dashboard',
            kho_filter=kho_filter,

            partner_label=partner_label,

            partner_count=(
                DoiTac.objects.filter(
                    loai_doi_tac__in=partner_types
                ).count()
            ),

            hang_count=goods_qs.count(),

            nhap_count=receipts.count(),
            xuat_count=issues.count(),

            nvl_colors=sorted(nvl_colors),
            nvl_suppliers=sorted(nvl_suppliers),

            tp_sizes=sorted(tp_sizes),
            tp_colors=sorted(tp_colors),
            tp_suppliers=sorted(tp_suppliers),

            dashboard_payload=dashboard_payload,
        ),
    )




# ==========================================================
# 3. DANH MỤC HÀNG HÓA
# ==========================================================

@authorized
def goods(request, kind):
    if kind not in ('NVL', 'TP'):
        raise Http404('Loại hàng không hợp lệ.')

    qs = HangHoa.objects.filter(
        nhom_hang__loai_hang=kind
    ).select_related(
        'don_vi_tinh', 'nhom_hang'
    ).order_by('ma_hang')

    search = request.GET.get('q', '').strip()
    if search:
        qs = qs.filter(
            Q(ma_hang__icontains=search)
            | Q(ten_hang__icontains=search)
        )

    amounts = dict(
        TonKho.objects.filter(hang_hoa__in=qs)
        .values_list('hang_hoa_id')
        .annotate(total=Sum('so_luong_ton'))
    )

    rows = [
        {'item': item, 'qty': amounts.get(item.pk, 0)}
        for item in qs[:300]
    ]

    return render(
        request, 'wms_core/goods.html',
        base(
            request, rows=rows, kind=kind,
            section='goods', search=search
        )
    )


@authorized
def create_goods(request, kind):
    if kind not in ('NVL', 'TP'):
        raise Http404('Loại hàng hóa không hợp lệ.')

    if request.wms_kind and request.wms_kind != kind:
        raise PermissionDenied(
            'Bạn không có quyền thêm hàng hóa vào kho này.'
        )

    title = (
        'Thêm nguyên vật liệu'
        if kind == 'NVL' else 'Thêm thành phẩm'
    )

    if request.method == 'POST':
        form = HangHoaForm(request.POST, kind=kind)
        if form.is_valid():
            item = form.save()
            messages.success(
                request,
                f'Đã thêm {item.ma_hang} thành công. '
                'Số lượng tồn kho không thay đổi.'
            )
            return redirect('wms_goods', kind=kind)
    else:
        form = HangHoaForm(kind=kind)

    return render(
        request,
        'wms_core/goods_form.html',
        base(
            request,
            form=form,
            kind=kind,
            title=title,
            section='goods',
            next_code=(
                next_nvl_code()
                if kind == 'NVL'
                else next_tp_code()
            )
        )
    )


# ==========================================================
# 4. ĐỐI TÁC VÀ VỊ TRÍ
# ==========================================================



@authorized
def branches(request):
    """Danh mục chi nhánh nội bộ."""
    search = request.GET.get('q', '').strip()

    rows = DoiTac.objects.filter(
        loai_doi_tac='CHINHANH'
    )

    if search:
        rows = rows.filter(
            Q(ma_doi_tac__icontains=search) |
            Q(ten_doi_tac__icontains=search)
        )

    rows = list(rows.order_by('ma_doi_tac'))


    for branch in rows:
        contact = (branch.thong_tin_lien_he or '').strip()

        branch.so_dien_tho = ''
        branch.dia_chi = ''

        for part in contact.split('|'):
            value = part.strip()
            lower_value = value.casefold()

            # Nhận diện số điện thoại
            if lower_value.startswith((
                'sđt:',
                'sdt:',
                'số điện thoại:'
            )):
                branch.so_dien_tho = value.split(':', 1)[1].strip()

            # Nhận diện địa chỉ
            elif lower_value.startswith((
                'địa chỉ:',
                'dia chi:'
            )):
                branch.dia_chi = value.split(':', 1)[1].strip()

            # Xử lý dữ liệu không có nhãn
            elif value:
                phone = value.replace(' ', '').replace('+', '')

                if phone.isdigit():
                    branch.so_dien_tho = value
                else:
                    branch.dia_chi = value


    draft = request.session.pop(
        'branch_create_draft', None
    ) or {}

    return render(
        request,
        'wms_core/branches.html',
        base(
            request,
            rows=rows,
            search=search,
            section='branches',
            branch_draft=draft,
            branch_code_error=draft.get(
                'code_error', ''
            ),
            branch_form_error=draft.get(
                'form_error', ''
            ),
            reopen_branch_modal=bool(draft),
            branch_codes=(
                list(DoiTac.objects.values_list(
                    'ma_doi_tac', flat=True
                ))
                if request.wms_manager else []
            ),
        )
    )


@authorized
@require_POST
def create_branch(request):
    """Thêm chi nhánh mới."""
    manager_only(request)

    code = request.POST.get(
        'ma_chi_nhanh', ''
    ).strip().upper()

    name = request.POST.get(
        'ten_chi_nhanh', ''
    ).strip()

    phone = request.POST.get(
        'so_dien_tho', ''
    ).strip()

    address = request.POST.get(
        'dia_chi', ''
    ).strip()

    draft = {
        'ma_chi_nhanh': code,
        'ten_chi_nhanh': name,
        'so_dien_tho': phone,
        'dia_chi': address,
    }

    def fail(message, code_error=False):
        draft['code_error'] = (
            message if code_error else ''
        )
        draft['form_error'] = (
            '' if code_error else message
        )
        request.session[
            'branch_create_draft'
        ] = draft

        return redirect('wms_branches')

    if not code or not name:
        return fail(
            'Vui lòng nhập mã và tên chi nhánh.'
        )

    if (
        len(code) > 40 or
        len(name) > 220 or
        len(address) > 500
    ):
        return fail(
            'Thông tin chi nhánh vượt độ dài cho phép.'
        )

    if phone and (
        not phone.isascii() or
        not phone.isdigit() or
        len(phone) not in (10, 11)
    ):
        return fail(
            'Số điện thoại phải gồm 10 hoặc 11 chữ số.'
        )

    if DoiTac.objects.filter(
        ma_doi_tac__iexact=code
    ).exists():
        return fail(
            f'Mã {code} đã tồn tại. Vui lòng nhập mã khác.',
            code_error=True
        )

    try:
        with transaction.atomic():
            branch = DoiTac(
                ma_doi_tac=code,
                ten_doi_tac=name,
                loai_doi_tac='CHINHANH',
                thong_tin_lien_he=(
                    f'SĐT: {phone} | Địa chỉ: {address}'
                ),
                trang_thai=True,
            )

            branch.full_clean()
            branch.save()

    except (ValidationError, IntegrityError):
        if DoiTac.objects.filter(
            ma_doi_tac__iexact=code
        ).exists():
            return fail(
                f'Mã {code} đã tồn tại. Vui lòng nhập mã khác.',
                code_error=True
            )

        return fail(
            'Không thể lưu chi nhánh. Vui lòng kiểm tra thông tin.'
        )

    request.session.pop(
        'branch_create_draft', None
    )

    messages.success(
        request,
        f'Đã thêm chi nhánh {name} thành công.'
    )

    return redirect('wms_branches')


@authorized
@require_POST
def branch_status(request, pk):
    """Chuyển trạng thái hoạt động."""
    manager_only(request)

    with transaction.atomic():
        branch = get_object_or_404(
            DoiTac.objects.select_for_update(),
            pk=pk,
            loai_doi_tac='CHINHANH'
        )

        branch.trang_thai = not branch.trang_thai
        branch.save(
            update_fields=['trang_thai']
        )

        active = branch.trang_thai
        name = branch.ten_doi_tac

    messages.success(
        request,
        f'Đã {"kích hoạt lại" if active else "ngừng hoạt động"} chi nhánh {name}.'
    )

    return redirect('wms_branches')


@authorized
def partners(request):
    """Danh sách nhà cung cấp / xưởng gia công, kèm form lỗi được giữ lại."""
    search = request.GET.get('q', '').strip()
    selected_type = request.GET.get('loai', '').strip()

    qs = DoiTac.objects.filter(
        loai_doi_tac__in=['NCC', 'XUONG']
    ).order_by('ma_doi_tac')

    if search:
        qs = qs.filter(
            Q(ma_doi_tac__icontains=search)
            | Q(ten_doi_tac__icontains=search)
        )

    if selected_type in ('NCC', 'XUONG'):
        qs = qs.filter(loai_doi_tac=selected_type)
    else:
        selected_type = ''

    rows = list(qs)
    for partner in rows:
        parts = (partner.thong_tin_lien_he or '').split('|', 1)
        phone = parts[0].strip() if parts else ''
        address = parts[1].strip() if len(parts) > 1 else ''
        partner.so_dien_tho = phone.removeprefix('SĐT:').strip()
        partner.dia_chi = address.removeprefix('Địa chỉ:').strip()

    # Sau khi nhập lỗi, giữ lại nội dung form và tự mở popup.
    # pop() chỉ hiển thị thông tin một lần, không giữ lỗi mãi trong session.
    draft = request.session.pop('partner_create_draft', None) or {}

    return render(
        request,
        'wms_core/partners.html',
        base(
            request,
            rows=rows,
            search=search,
            selected_type=selected_type,
            section='partners',
            partner_draft=draft,
            partner_code_error=draft.get('code_error', ''),
            partner_form_error=draft.get('form_error', ''),
            reopen_partner_modal=bool(draft),

            partner_codes=(
                list(DoiTac.objects.values_list('ma_doi_tac', flat=True))
                if request.wms_manager else []
            ),

        )
    )


@authorized
@require_POST
def create_partner(request):
    """Thêm đối tác: tự Hoạt động; trùng mã thì popup mở lại, không mất dữ liệu."""
    manager_only(request)

    code = request.POST.get('ma_doi_tac', '').strip().upper()
    name = request.POST.get('ten_doi_tac', '').strip()
    kind = request.POST.get('loai_doi_tac', '').strip()
    phone = request.POST.get('so_dien_tho', '').strip()
    address = request.POST.get('dia_chi', '').strip()

    # Chỉ giữ thông tin cần để phục hồi biểu mẫu sau khi bị lỗi.
    draft = {
        'ma_doi_tac': code,
        'ten_doi_tac': name,
        'loai_doi_tac': kind,
        'so_dien_tho': phone,
        'dia_chi': address,
    }

    def fail(message, field=''):
        draft['code_error'] = message if field == 'code' else ''
        draft['form_error'] = message if field != 'code' else ''
        request.session['partner_create_draft'] = draft
        return redirect('wms_partners')

    if not code or not name or not kind:
        return fail('Vui lòng nhập mã, tên và loại đối tác.')

    if kind not in ('NCC', 'XUONG'):
        return fail('Loại đối tác không hợp lệ.')

    if len(code) > 40 or len(name) > 220:
        return fail('Mã hoặc tên đối tác vượt độ dài cho phép.')

    if phone and (
        not phone.isascii()
        or not phone.isdigit()
        or len(phone) not in (10, 11)
    ):
        return fail('Số điện thoại phải gồm 10 hoặc 11 chữ số.')

    # Kiểm tra không phân biệt chữ hoa / chữ thường.
    if DoiTac.objects.filter(ma_doi_tac__iexact=code).exists():
        return fail(
            f'Mã đối tác {code} đã tồn tại. Vui lòng nhập mã khác.',
            field='code',
        )

    try:
        with transaction.atomic():
            partner = DoiTac(
                ma_doi_tac=code,
                ten_doi_tac=name,
                loai_doi_tac=kind,
                thong_tin_lien_he=f'SĐT: {phone} | Địa chỉ: {address}',
                trang_thai=True,  # Mới tạo luôn Hoạt động, không cho chọn.
            )
            partner.full_clean()
            partner.save()
    except (ValidationError, IntegrityError) as exc:
        # Trường hợp trùng mã phát sinh giữa lần kiểm tra và lần lưu.
        if DoiTac.objects.filter(ma_doi_tac__iexact=code).exists():
            return fail(
                f'Mã đối tác {code} đã tồn tại. Vui lòng nhập mã khác.',
                field='code',
            )
        return fail('Không thể lưu đối tác. Vui lòng kiểm tra thông tin.')

    request.session.pop('partner_create_draft', None)
    messages.success(request, f'Đã thêm đối tác {code} thành công.')
    return redirect('wms_partners')


@authorized
@require_POST
def partner_status(request, pk):
    """Quản lý chuyển Hoạt động / Ngừng hoạt động, không xóa dữ liệu."""
    manager_only(request)

    with transaction.atomic():
        partner = get_object_or_404(
            DoiTac.objects.select_for_update(),
            pk=pk,
            loai_doi_tac__in=['NCC', 'XUONG'],
        )
        partner.trang_thai = not partner.trang_thai
        partner.save(update_fields=['trang_thai'])
        active = partner.trang_thai
        name = partner.ten_doi_tac

    messages.success(
        request,
        f'Đã {"kích hoạt lại" if active else "ngừng hoạt động"} đối tác {name}.'
    )
    return redirect('wms_partners')




@authorized
@require_POST
def create_position(request):
    import re

    manager_only(request)

    kho_id = request.POST.get('kho', '').strip()
    area_choice = request.POST.get('khu_vuc', '').strip()
    rack_choice = request.POST.get('ke', '').strip()

    area_name = ' '.join(
        request.POST.get('ten_khu_vuc_moi', '').split()
    )

    rack_name = ' '.join(
        request.POST.get('ten_ke_moi', '').split()
    )

    tang_text = request.POST.get('tang', '').strip()

    try:
        # 1. KIEM TRA DU LIEU FORM
        if not kho_id.isdecimal():
            raise ValidationError(
                'Vui lòng chọn kho hợp lệ.'
            )

        if not area_choice or not rack_choice:
            raise ValidationError(
                'Vui lòng chọn khu vực và kệ.'
            )


        if not tang_text.isdecimal():
            raise ValidationError(
                'Tầng phải là số nguyên dương.'
            )

        tang = int(tang_text)

        if not 1 <= tang <= 999:
            raise ValidationError(
                'Tầng phải từ 1 đến 999.'
            )


        # 2. KIEM TRA KHU VUC
        if area_choice == '__new__':

            if not 1 <= len(area_name) <= 120:
                raise ValidationError(
                    'Tên khu vực mới phải từ 1 đến 120 ký tự.'
                )

            if rack_choice != '__new__':
                raise ValidationError(
                    'Khu vực mới phải tạo kệ mới.'
                )

        elif not area_choice.isdecimal():
            raise ValidationError(
                'Khu vực không hợp lệ.'
            )

        # 3. KIEM TRA KE
        if rack_choice == '__new__':

            if not 1 <= len(rack_name) <= 100:
                raise ValidationError(
                    'Tên kệ mới phải từ 1 đến 100 ký tự.'
                )

        elif not rack_choice.isdecimal():
            raise ValidationError(
                'Kệ không hợp lệ.'
            )

        # CAC THAO TAC LUU NAM TRONG CUNG TRANSACTION
        with transaction.atomic():

            # 4. XAC DINH KHO
            warehouse = Kho.objects.select_for_update().filter(
                pk=kho_id
            ).first()

            if warehouse is None:
                raise ValidationError(
                    'Không tìm thấy kho đã chọn.'
                )

            # Khong them vi tri khi dang kiem ke toan bo
            if PhieuKiemKho.objects.filter(
                kho=warehouse,
                trang_thai='cho_duyet',
                loai_kiem_ke='toan_bo'
            ).exists():
                raise ValidationError(
                    'Kho đang kiểm kê toàn bộ, '
                    'chưa thể thêm vị trí.'
                )

            # Khong tao vi tri moi khi dang lap
            # phieu kiem kho toan bo chua luu
            if KhoaTamKiemKho.objects.filter(
                kho=warehouse,
                hang_hoa__isnull=True,
                het_han_luc__gt=timezone.now(),
            ).exists():
                raise ValidationError(
                    'Kho đang được lập phiếu kiểm kho toàn bộ. '
                    'Chưa thể thêm vị trí mới.'
                )

            # 5. CHON HOAC TAO KHU VUC
            if area_choice == '__new__':

                duplicated_area = KhuVuc.objects.filter(
                    kho=warehouse,
                    ten_khu_vuc__iexact=area_name
                ).exists()

                if duplicated_area:
                    raise ValidationError(
                        'Tên khu vực đã tồn tại trong kho này. '
                        'Vui lòng chọn khu vực có sẵn.'
                    )

                area = KhuVuc(
                    kho=warehouse,
                    ten_khu_vuc=area_name
                )

                area.full_clean()
                area.save()

            else:

                area = KhuVuc.objects.filter(
                    pk=int(area_choice),
                    kho=warehouse
                ).first()

                if area is None:
                    raise ValidationError(
                        'Khu vực không thuộc kho đã chọn.'
                    )

            # 6. CHON HOAC TAO KE
            if rack_choice == '__new__':

                duplicated_rack = Ke.objects.filter(
                    khu_vuc=area,
                    ten_ke__iexact=rack_name
                ).exists()

                if duplicated_rack:
                    raise ValidationError(
                        'Tên kệ đã tồn tại trong khu vực này. '
                        'Vui lòng chọn kệ có sẵn.'
                    )

                rack = Ke(
                    khu_vuc=area,
                    ten_ke=rack_name
                )

                rack.full_clean()
                rack.save()

            else:

                rack = Ke.objects.filter(
                    pk=int(rack_choice),
                    khu_vuc=area
                ).first()

                if rack is None:
                    raise ValidationError(
                        'Kệ không thuộc khu vực đã chọn.'
                    )

            # 7. TU DONG SINH MA VI TRI
            kind = warehouse.loai_kho

            code_pattern = re.compile(
                r'^VT-'
                + re.escape(kind)
                + r'-(\d+)-(\d+)$'
            )

            warehouse_codes = ViTriLuuTru.objects.filter(
                ke__khu_vuc__kho=warehouse
            ).values_list(
                'ke_id',
                'ma_vi_tri'
            )

            all_rack_numbers = []
            current_rack_numbers = set()
            current_slots = []

            for found_rack_id, old_code in warehouse_codes:

                match = code_pattern.fullmatch(old_code)

                if not match:
                    continue

                rack_number = int(match.group(1))
                slot_number = int(match.group(2))

                all_rack_numbers.append(rack_number)

                if found_rack_id == rack.pk:

                    current_rack_numbers.add(rack_number)
                    current_slots.append(slot_number)

            # Mot ke phai co cung mot day ma
            if len(current_rack_numbers) > 1:
                raise ValidationError(
                    'Kệ đang có nhiều dãy mã vị trí. '
                    'Cần kiểm tra lại dữ liệu.'
                )

            if current_rack_numbers:

                # KE CU: TANG SO VI TRI
                rack_number = next(
                    iter(current_rack_numbers)
                )

                slot_number = max(current_slots) + 1

            else:

                # KE MOI: SINH SO KE MOI
                rack_number = max(
                    all_rack_numbers,
                    default=0
                ) + 1

                slot_number = 1

            code = (
                f'VT-{kind}-'
                f'{rack_number:02d}-'
                f'{slot_number:02d}'
            )

            # Bao dam ma khong trung
            while ViTriLuuTru.objects.filter(
                ma_vi_tri__iexact=code
            ).exists():

                slot_number += 1

                code = (
                    f'VT-{kind}-'
                    f'{rack_number:02d}-'
                    f'{slot_number:02d}'
                )

            # 8. TU SINH TEN VI TRI

            # Chi quan ly tang, khong quan ly o
            name = f'Tầng {tang}'

            # Kiem tra trung tang trong cung ke
            # Ho tro ca du lieu cu "Tang X - O Y"
            existing_names = ViTriLuuTru.objects.filter(
                ke=rack
            ).values_list('ten_vi_tri', flat=True)

            for old_name in existing_names:
                if re.fullmatch(
                    rf'Tầng\s*0*{tang}(?:\s*-\s*Ô\s*\d+)?',
                    (old_name or '').strip(),
                    flags=re.IGNORECASE
                ):
                    raise ValidationError(
                        f'Kệ này đã có Tầng {tang}.'
                    )

            # 9. LUU VI TRI
            position = ViTriLuuTru(
                ke=rack,
                ma_vi_tri=code,
                ten_vi_tri=name
            )

            position.full_clean()
            position.save()

        # Chi thong bao thanh cong khi luu xong tat ca
        messages.success(
            request,
            f'Đã tạo vị trí {code} tại '
            f'{warehouse.ten_kho} / '
            f'{area.ten_khu_vuc} / '
            f'{rack.ten_ke}. '
            'Vị trí đang trống.'
        )

    except (ValidationError, IntegrityError, ValueError) as exc:

        if isinstance(exc, ValidationError):
            error = '; '.join(exc.messages)
        else:
            error = str(exc)

        messages.error(
            request,
            'Không thể thêm vị trí: ' + error
        )

    return redirect('wms_positions')

@authorized
def positions(request):
    import re

    # 1. Chỉ lấy các vị trí chuẩn theo danh mục Excel.
    # Không xóa vị trí demo cũ khỏi database.
    qs = ViTriLuuTru.objects.filter(
        ma_vi_tri__startswith='VT-'
    ).select_related(
        'ke__khu_vuc__kho'
    ).order_by(
        'ke__khu_vuc__kho__ten_kho',
        'ke__khu_vuc__ten_khu_vuc',
        'ke__ten_ke',
        'ma_vi_tri'
    )

    # 2. Giữ phân quyền theo kho NVL / thành phẩm.
    qs = restricted(
        qs,
        request,
        'ke__khu_vuc__kho__loai_kho'
    )

    locations = list(qs)
    location_ids = [item.pk for item in locations]

    # 3. Lấy tồn kho thực tế tại từng vị trí.
    stock_by_location = {}

    stocks = TonKho.objects.filter(
        vi_tri_id__in=location_ids,
        so_luong_ton__gt=0
    ).select_related(
        'hang_hoa__don_vi_tinh'
    ).order_by(
        'hang_hoa__ma_hang'
    )

    for stock in stocks:
        stock_by_location.setdefault(
            stock.vi_tri_id, []
        ).append({
            'sku': stock.hang_hoa.ma_hang,
            'name': stock.hang_hoa.ten_hang,

            # Thong tin phan biet bien the hang hoa
            'mau_sac': stock.hang_hoa.mau_sac or '',
            'kich_co': stock.hang_hoa.kich_co or '',
            'mau_ma': stock.hang_hoa.mau_ma or '',

            'quantity': str(stock.so_luong_ton),
            'unit': stock.hang_hoa.don_vi_tinh.ten_don_vi_tinh
        })

    # 4. Xác định vị trí đang khóa do kiểm kê.
    locked_ids = set(
        PhamViKiemKe.objects.filter(
            vi_tri_id__in=location_ids,
            trang_thai_khoa=True
        ).values_list(
            'vi_tri_id',
            flat=True
        )
    )

    # 5. Tạo dữ liệu sơ đồ cho giao diện.
    positions_payload = []

    for item in locations:
        description = item.ten_vi_tri or ''


        # Chi lay thong tin Tang
        level_match = re.search(
            r'Tầng\s*(\d+)',
            description,
            flags=re.IGNORECASE
        )

        if level_match:
            level_number = int(level_match.group(1))
        else:
            try:
                level_number = int(
                    item.ma_vi_tri.rsplit('-', 1)[-1]
                )
            except (ValueError, IndexError):
                level_number = 1


        stock_items = stock_by_location.get(
            item.pk, []
        )

        positions_payload.append({
            'id': item.pk,
            'code': item.ma_vi_tri,

            'warehouse': (
                item.ke.khu_vuc.kho.ten_kho
            ),
            'warehouse_kind': (
                item.ke.khu_vuc.kho.loai_kho
            ),
            'area': (
                item.ke.khu_vuc.ten_khu_vuc
            ),
            'rack': item.ke.ten_ke,

            'level': f'Tầng {level_number}',
            'level_number': level_number,

            'locked': item.pk in locked_ids,
            'has_stock': bool(stock_items),
            'stock': stock_items
        })

    # Dữ liệu phục vụ popup Thêm vị trí
    position_warehouses = []
    position_areas = []
    position_racks = []
    position_codes = []

    if request.wms_manager:

        position_warehouses = list(
            Kho.objects.order_by('ten_kho').values(
                'id',
                'ten_kho',
                'loai_kho'
            )
        )

        position_areas = list(
            KhuVuc.objects.order_by(
                'ten_khu_vuc'
            ).values(
                'id',
                'kho_id',
                'ten_khu_vuc'
            )
        )

        position_racks = list(
            Ke.objects.order_by('ten_ke').values(
                'id',
                'khu_vuc_id',
                'ten_ke'
            )
        )

        rack_prefix = {}
        rack_max = {}

        for rack_id, code in ViTriLuuTru.objects.filter(
            ma_vi_tri__startswith='VT-'
        ).values_list('ke_id', 'ma_vi_tri'):

            parts = code.split('-')

            if len(parts) == 4 and parts[-1].isdigit():

                rack_prefix.setdefault(
                    rack_id,
                    '-'.join(parts[:3])
                )

                rack_max[rack_id] = max(
                    rack_max.get(rack_id, 0),
                    int(parts[3])
                )

        for rack in position_racks:

            prefix = rack_prefix.get(
                rack['id'],
                ''
            )

            next_number = (
                rack_max.get(rack['id'], 0) + 1
            )

            rack['prefix'] = prefix

            rack['next_code'] = (
                f'{prefix}-{next_number:02d}'
                if prefix else ''
            )

            rack['next_name'] = (
                f'Tầng {next_number}'
            )

        position_codes = list(
            ViTriLuuTru.objects.values_list(
                'ma_vi_tri',
                flat=True
            )
        )

    # 6. Trả dữ liệu về positions.html.

    # Tra du lieu ve giao dien so do vi tri


    return render(
        request,
        'wms_core/positions.html',
        base(
            request,
            section='positions',
            positions_payload=positions_payload,
            position_warehouses=position_warehouses,
            position_areas=position_areas,
            position_racks=position_racks,
            position_codes=position_codes
        )
    )




# ==========================================================
# 5. TỒN KHO
# ==========================================================

@authorized
def inventory(request):
    qs = restricted(
        TonKho.objects.select_related(
            'hang_hoa__don_vi_tinh',
            'vi_tri__ke__khu_vuc__kho'
        ),
        request, 'vi_tri__ke__khu_vuc__kho__loai_kho'
    )

    kind = request.GET.get('kind', '').upper()
    if request.wms_kind:
        kind = request.wms_kind

    if kind in ('NVL', 'TP'):
        qs = qs.filter(
            vi_tri__ke__khu_vuc__kho__loai_kho=kind
        )
    else:
        kind = ''

    return render(
        request, 'wms_core/inventory.html',
        base(
            request,
            rows=qs.order_by('hang_hoa__ma_hang'),
            section='inventory',
            kind=kind
        )
    )


# ==========================================================
# 6. DANH SÁCH PHIẾU NHẬP / XUẤT
# ==========================================================


@authorized
def documents(request, direction):
    # Kiểm tra loại phiếu
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')

    cls = PhieuNhap if direction == 'nhap' else PhieuXuat

    # Lấy phiếu theo quyền truy cập kho
    rows = restricted(
        cls.objects.select_related(
            'kho',
            'doi_tac',
            'nguoi_lap',
            'nguoi_phe_duyet'
        ),
        request,
        'kho__loai_kho'
    )

    # Giữ đúng loại kho đang xem
    # Dù không hiển thị bộ lọc Loại kho trên giao diện
    kind = request.GET.get('kind', '').upper()

    if request.wms_kind:
        kind = request.wms_kind

    if kind in ('NVL', 'TP'):
        rows = rows.filter(
            kho__loai_kho=kind
        )
    else:
        kind = ''

    # Lọc trạng thái
    status = request.GET.get('status', '')

    valid_status = {
        'nhap',
        'cho_duyet',
        'da_duyet',
        'tu_choi',
        'da_huy'
    }

    if status in valid_status:
        rows = rows.filter(
            trang_thai=status
        )
    else:
        status = ''

    # Tìm kiếm theo mã phiếu
    keyword = request.GET.get('q', '').strip()

    if keyword:
        field = (
            'ma_phieu_nhap__icontains'
            if direction == 'nhap'
            else 'ma_phieu_xuat__icontains'
        )

        rows = rows.filter(
            **{field: keyword}
        )

    # ==========================================
    # LỌC THEO KHOẢNG NGÀY
    # ==========================================

    from datetime import date

    start_date = request.GET.get(
        'tu_ngay', ''
    ).strip()

    end_date = request.GET.get(
        'den_ngay', ''
    ).strip()

    def parse_date(raw, label):
        if not raw:
            return None

        try:
            return date.fromisoformat(raw)

        except ValueError:
            messages.error(
                request,
                f'{label} không hợp lệ. '
                'Vui lòng chọn lại ngày.'
            )
            return None

    start = parse_date(start_date, 'Từ ngày')
    end = parse_date(end_date, 'Đến ngày')

    # Xóa giá trị ngày không hợp lệ
    if start_date and start is None:
        start_date = ''

    if end_date and end is None:
        end_date = ''

    # Không cho ngày bắt đầu sau ngày kết thúc
    if start and end and start > end:
        messages.error(
            request,
            'Từ ngày không được sau Đến ngày.'
        )

        start = None
        end = None
        start_date = ''
        end_date = ''

    # Lọc bao gồm cả ngày đầu và ngày cuối
    if start:
        rows = rows.filter(
            thoi_gian_lap__date__gte=start
        )

    if end:
        rows = rows.filter(
            thoi_gian_lap__date__lte=end
        )

    # ==========================================
    # HIỂN THỊ DANH SÁCH PHIẾU
    # ==========================================

    return render(
        request,
        'wms_core/documents.html',
        base(
            request,
            rows=rows.order_by(
                '-thoi_gian_lap'
            )[:200],
            direction=direction,
            kind=kind,
            status=status,
            keyword=keyword,
            start_date=start_date,
            end_date=end_date,
            section=direction
        )
    )


# ==========================================================
# 7. TẠO PHIẾU NHẬP / XUẤT CÓ ĐƠN GIÁ
# ==========================================================

def _document_partner_type(direction, kind):
    # In NVL <- supplier; in TP <- workshop;
    # Out NVL -> workshop; out TP -> branch.
    if direction == 'nhap':
        return 'NCC' if kind == 'NVL' else 'XUONG'
    return 'XUONG' if kind == 'NVL' else 'CHINHANH'


def _get_document_partner(request, direction, warehouse):
    expected = _document_partner_type(direction, warehouse.loai_kho)
    partner = DoiTac.objects.filter(
        pk=request.POST.get('doi_tac'),
        loai_doi_tac=expected,
        trang_thai=True
    ).first()
    if partner is None:
        raise ValidationError(
            'Đối tác không hợp lệ cho loại phiếu/kho đã chọn.'
        )
    return partner


def _prepare_document_lines(request, direction, warehouse):
    """Validate posted details; prices are always read from the goods catalog."""
    goods_ids = request.POST.getlist('hang_hoa')
    pos_ids = request.POST.getlist('vi_tri')
    qty_values = request.POST.getlist('so_luong')
    price_values = request.POST.getlist('don_gia')

    if not goods_ids or not (
        len(goods_ids) == len(pos_ids) == len(qty_values) == len(price_values)
    ):
        raise ValidationError('Mỗi dòng cần hàng hóa, vị trí, số lượng và đơn giá.')
    if len(goods_ids) > 100:
        raise ValidationError('Một phiếu tối đa 100 dòng hàng.')

    lines = []
    outgoing_total = defaultdict(lambda: Decimal('0'))
    for goods_id, pos_id, raw_quantity, _raw_price in zip(
        goods_ids, pos_ids, qty_values, price_values
    ):
        item = get_object_or_404(
            HangHoa.objects.select_related('nhom_hang', 'ke_mac_dinh'),
            pk=goods_id
        )
        pos = get_object_or_404(
            ViTriLuuTru.objects.select_related('ke__khu_vuc__kho'),
            pk=pos_id
        )
        if (
            item.nhom_hang.loai_hang != warehouse.loai_kho
            or pos.kho.pk != warehouse.pk
        ):
            raise ValidationError('Hàng hóa hoặc vị trí không thuộc kho đã chọn.')
        if item.trang_thai != 'hoat_dong':
            raise ValidationError(f'Hàng {item.ma_hang} đã ngừng sử dụng.')

        quantity = decimal_pos(raw_quantity)
        if quantity.as_tuple().exponent < -2:
            raise ValidationError('Số lượng tối đa 2 chữ số thập phân.')
        if item.don_gia is None:
            raise ValidationError(f'Hàng {item.ma_hang} chưa có đơn giá.')
        price = decimal_price(str(item.don_gia))

        if direction == 'nhap':
            if (
                item.ke_mac_dinh_id is not None
                and pos.ke_id != item.ke_mac_dinh_id
            ):
                raise ValidationError(
                    f'Vị trí không thuộc kệ mặc định của {item.ma_hang}.'
                )
        else:
            outgoing_total[(item.pk, pos.pk)] += quantity

        # Already locked locations must not be selected for a new stock movement.
        services.assert_not_locked(pos.pk)
        lines.append((item, pos, quantity, price))


    # Kiem tra khoa theo san pham + vi tri
    services.assert_no_pending_stockcheck(
        warehouse.pk,
        [
            (item.pk, pos.pk)
            for item, pos, quantity, price in lines
        ],
    )

    if direction == 'xuat':
        for (goods_id, pos_id), requested in sorted(outgoing_total.items()):
            stock = TonKho.objects.filter(
                hang_hoa_id=goods_id, vi_tri_id=pos_id
            ).first()
            available = stock.so_luong_ton if stock else Decimal('0')
            if requested > available:
                raise ValidationError(
                    f'Xuất vượt tồn tại vị trí #{pos_id}: '
                    f'yêu cầu {requested}, còn {available}.'
                )
    return lines


# ==========================================================
# DANH SACH HANG HOA DANG BI KHOA DO KIEM KHO
# AP DUNG CHO TAT CA NVL VA THANH PHAM
# ==========================================================

def _locked_goods_map(warehouses, goods):
    """
    Tra ve danh sach hang bi khoa theo tung kho.

    Bao gom:
    1. Phieu kiem kho dang Cho duyet.
    2. Khoa tam khi dang tao phieu kiem kho.
    3. Kiem ke toan bo: khoa moi ma hang trong kho.

    Dinh dang:
    {
        "1": ["5", "7"],
        "2": ["12"]
    }
    """

    warehouse_rows = list(
        warehouses.values('id', 'loai_kho')
    )

    if not warehouse_rows:
        return {}

    warehouse_ids = [
        row['id']
        for row in warehouse_rows
    ]

    locked = {
        str(row['id']): set()
        for row in warehouse_rows
    }

    # 1. Tim cac kho co phieu kiem ke toan bo cho duyet
    full_warehouse_ids = set(
        PhieuKiemKho.objects.filter(
            kho_id__in=warehouse_ids,
            trang_thai='cho_duyet',
            loai_kiem_ke='toan_bo',
        ).values_list('kho_id', flat=True)
    )

    # 2. Hang hoa thuoc phieu kiem ke cho duyet
    pending_goods = (
        ChiTietPhieuKiemKho.objects.filter(
            phieu__kho_id__in=warehouse_ids,
            phieu__trang_thai='cho_duyet',
        )
        .values_list(
            'phieu__kho_id',
            'hang_hoa_id',
        )
        .distinct()
    )

    for warehouse_id, goods_id in pending_goods:
        locked[str(warehouse_id)].add(
            str(goods_id)
        )

    # 3. Khoa tam khi nguoi dung dang lap phieu
    now = timezone.now()

    temporary_locks = (
        KhoaTamKiemKho.objects.filter(
            kho_id__in=warehouse_ids,
            het_han_luc__gt=now,
        )
        .values_list('kho_id', 'hang_hoa_id')
    )

    for warehouse_id, goods_id in temporary_locks:

        # hang_hoa=None nghia la khoa toan bo kho
        if goods_id is None:
            full_warehouse_ids.add(warehouse_id)

        else:
            locked[str(warehouse_id)].add(
                str(goods_id)
            )

    # 4. Neu kiem ke toan bo, khoa tat ca hang cua kho
    for row in warehouse_rows:

        warehouse_id = row['id']

        if warehouse_id not in full_warehouse_ids:
            continue

        goods_ids = goods.filter(
            nhom_hang__loai_hang=row['loai_kho']
        ).values_list('pk', flat=True)

        locked[str(warehouse_id)] = {
            str(pk)
            for pk in goods_ids
        }

    # 5. Tra ve JSON-compatible dictionary
    return {
        warehouse_id: sorted(
            goods_ids,
            key=int
        )
        for warehouse_id, goods_ids in locked.items()
    }

# ==========================================================
# KHOA KIEM KHO THEO SAN PHAM + VI TRI
# ==========================================================

def _locked_stock_positions_map(warehouses):
    """
    Tra ve trang thai khoa theo tung kho.

    {
        "1": {
            "full": False,
            "pairs": ["5:10", "5:11"],
            "legacy_goods": [],
            "positions": []
        }
    }

    pairs:
        "hang_hoa_id:vi_tri_id"

    full:
        True neu kiem ke toan bo.

    legacy_goods:
        Khoa tam cu chua co ton_kho_id.

    positions:
        Vi tri bi khoa boi dot kiem ke cu.
    """

    warehouse_ids = list(
        warehouses.values_list('pk', flat=True)
    )

    result = {
        str(pk): {
            'full': False,
            'pairs': [],
            'legacy_goods': [],
            'positions': [],
        }
        for pk in warehouse_ids
    }

    if not warehouse_ids:
        return result

    full_ids = set(
        PhieuKiemKho.objects.filter(
            kho_id__in=warehouse_ids,
            trang_thai='cho_duyet',
            loai_kiem_ke='toan_bo',
        ).values_list('kho_id', flat=True)
    )

    pairs = defaultdict(set)
    legacy_goods = defaultdict(set)
    positions = defaultdict(set)

    # 1. Khoa tu phieu kiem kho cho duyet
    pending_lines = ChiTietPhieuKiemKho.objects.filter(
        phieu__kho_id__in=warehouse_ids,
        phieu__trang_thai='cho_duyet',
    ).values_list(
        'phieu__kho_id',
        'hang_hoa_id',
        'vi_tri_id',
    )

    for kho_id, hang_id, vi_tri_id in pending_lines:
        pairs[str(kho_id)].add(
            f'{hang_id}:{vi_tri_id}'
        )

    # 2. Khoa tam khi dang tao phieu
    temporary_locks = KhoaTamKiemKho.objects.filter(
        kho_id__in=warehouse_ids,
        het_han_luc__gt=timezone.now(),
    ).values_list(
        'kho_id',
        'hang_hoa_id',
        'ton_kho__vi_tri_id',
    )

    for kho_id, hang_id, vi_tri_id in temporary_locks:
        key = str(kho_id)

        if hang_id is None:
            full_ids.add(kho_id)

        elif vi_tri_id is None:
            # Ho tro khoa tam duoc tao truoc khi doi logic
            legacy_goods[key].add(str(hang_id))

        else:
            pairs[key].add(
                f'{hang_id}:{vi_tri_id}'
            )

    # 3. Vi tri bi khoa do dot kiem ke cu
    old_position_locks = PhamViKiemKe.objects.filter(
        vi_tri__ke__khu_vuc__kho_id__in=warehouse_ids,
        trang_thai_khoa=True,
    ).values_list(
        'vi_tri__ke__khu_vuc__kho_id',
        'vi_tri_id',
    )

    for kho_id, vi_tri_id in old_position_locks:
        positions[str(kho_id)].add(
            str(vi_tri_id)
        )

    # 4. Chuyen set thanh list de tra ve JSON
    for kho_id, entry in result.items():
        entry['full'] = int(kho_id) in full_ids
        entry['pairs'] = sorted(pairs[kho_id])
        entry['legacy_goods'] = sorted(
            legacy_goods[kho_id]
        )
        entry['positions'] = sorted(
            positions[kho_id]
        )

    return result

def _document_form_context(request, direction, selected_kind, **extra):
    """Data shared by create/edit pages; also exposes stock data for JS dropdowns."""
    warehouses = restricted(Kho.objects.all(), request, 'loai_kho')
    goods = restricted(
        HangHoa.objects.select_related('nhom_hang', 'ke_mac_dinh'),
        request, 'nhom_hang__loai_hang'
    ).filter(trang_thai='hoat_dong')
    locations = restricted(
        ViTriLuuTru.objects.select_related('ke__khu_vuc__kho'),
        request, 'ke__khu_vuc__kho__loai_kho'
    )
    stocks = restricted(
        TonKho.objects.filter(so_luong_ton__gt=0),
        request, 'vi_tri__ke__khu_vuc__kho__loai_kho'
    )
    if selected_kind:
        warehouses = warehouses.filter(loai_kho=selected_kind)
        goods = goods.filter(nhom_hang__loai_hang=selected_kind)
        locations = locations.filter(ke__khu_vuc__kho__loai_kho=selected_kind)
        stocks = stocks.filter(
            vi_tri__ke__khu_vuc__kho__loai_kho=selected_kind
        )

    stock_rows = list(stocks.values(
        'hang_hoa_id', 'vi_tri_id', 'vi_tri__ke_id',
        'vi_tri__ke__ten_ke', 'vi_tri__ke__khu_vuc__kho_id',
        'so_luong_ton'
    ))
    for row in stock_rows:
        row['so_luong_ton'] = str(row['so_luong_ton'])

    partner_qs = DoiTac.objects.filter(trang_thai=True)
    if selected_kind in ('NVL', 'TP'):
        partner_qs = partner_qs.filter(
            loai_doi_tac=_document_partner_type(direction, selected_kind)
        )


    locked = _locked_goods_map(
        warehouses,
        goods,
    )

    # Khoa chi tiet theo tung vi tri
    locked_positions = _locked_stock_positions_map(
        warehouses
    )


    values = dict(
        direction=direction,
        section=direction,
        warehouses=warehouses,
        goods=goods,
        locations=locations,
        partners=partner_qs,
        stock_rows=stock_rows,
        locked_goods_by_warehouse=locked,
        locked_stock_positions_by_warehouse=locked_positions,
        selected_kind=selected_kind,
        kind=selected_kind,
    )
    values.update(extra)
    return base(request, **values)


# ==========================================================
# API KIEM TRA HANG HOA DANG BI KHOA
# DUNG CHO FORM NHAP / XUAT DANG MO
# ==========================================================

@authorized
def document_lock_status(request):

    selected_kind = (
        request.GET.get('kind', '')
        .strip()
        .upper()
    )

    # Nhan vien chi xem duoc kho cua minh
    if request.wms_kind:
        selected_kind = request.wms_kind

    if selected_kind not in ('NVL', 'TP'):
        selected_kind = ''

    warehouses = restricted(
        Kho.objects.all(),
        request,
        'loai_kho',
    )

    goods = restricted(
        HangHoa.objects.filter(
            trang_thai='hoat_dong'
        ),
        request,
        'nhom_hang__loai_hang',
    )

    if selected_kind:
        warehouses = warehouses.filter(
            loai_kho=selected_kind
        )

        goods = goods.filter(
            nhom_hang__loai_hang=selected_kind
        )

    locked = _locked_goods_map(
        warehouses,
        goods,
    )
    locked_positions = _locked_stock_positions_map(
        warehouses
    )

    response = JsonResponse({
        'ok': True,
        'locked_goods_by_warehouse': locked,
        'locked_stock_positions_by_warehouse': locked_positions,
    })


    response['Cache-Control'] = 'no-store'

    return response

def _verify_document_code(request, direction, selected_kind):
    prefix = 'PN' if direction == 'nhap' else 'PX'
    try:
        signed_data = signing.loads(
            request.POST.get('code_token', ''),
            salt='xonxen-document-code',
            max_age=7200
        )
    except (BadSignature, SignatureExpired):
        raise ValidationError(
            'Mã phiếu không hợp lệ hoặc đã hết hạn. Vui lòng tải lại trang.'
        )
    if not isinstance(signed_data, dict) or (
        signed_data.get('direction') != direction
        or signed_data.get('kind') != selected_kind
        or signed_data.get('user_id') != request.user.pk
    ):
        raise ValidationError('Thông tin mã phiếu không phù hợp.')
    code = signed_data.get('code')
    if (
        not isinstance(code, str)
        or not code.startswith(prefix + '-')
        or len(code) > 50
    ):
        raise ValidationError('Định dạng mã phiếu không hợp lệ.')
    return code


@authorized
def new_document(request, direction):
    """Create a draft receipt/issue without modifying stock."""
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')
    cls = PhieuNhap if direction == 'nhap' else PhieuXuat
    selected_kind = request.GET.get('kind', '').upper()
    if request.wms_kind:
        selected_kind = request.wms_kind
    if selected_kind not in ('NVL', 'TP'):
        selected_kind = ''

    prefix = 'PN' if direction == 'nhap' else 'PX'
    displayed_code = generate_document_code(prefix)
    code_token = signing.dumps(
        {
            'code': displayed_code,
            'direction': direction,
            'kind': selected_kind,
            'user_id': request.user.pk,
        },
        salt='xonxen-document-code'
    )

    if request.method == 'POST':
        try:
            with transaction.atomic():
                warehouse = get_object_or_404(
                    Kho, pk=request.POST.get('kho')
                )
                services.lock_warehouse(warehouse.pk)
                if request.wms_kind and warehouse.loai_kho != request.wms_kind:
                    raise ValidationError('Kho không thuộc quyền của bạn.')
                if selected_kind and warehouse.loai_kho != selected_kind:
                    raise ValidationError('Kho không đúng loại đang lập phiếu.')

                code = _verify_document_code(request, direction, selected_kind)
                partner = _get_document_partner(request, direction, warehouse)
                prepared = _prepare_document_lines(request, direction, warehouse)

                payload = {
                    'kho': warehouse,
                    'doi_tac': partner,
                    'nguoi_lap': request.wms_account,
                    'ghi_chu': request.POST.get('ghi_chu', '').strip()
                }
                if direction == 'nhap':
                    payload['ma_phieu_nhap'] = code
                else:
                    payload['ma_phieu_xuat'] = code
                doc = cls.objects.create(**payload)

                for item, pos, quantity, price in prepared:
                    if direction == 'nhap':
                        detail = ChiTietPhieuNhap(
                            phieu_nhap=doc, hang_hoa=item, vi_tri=pos,
                            so_luong_nhap=quantity, don_gia=price
                        )
                    else:
                        detail = ChiTietPhieuXuat(
                            phieu_xuat=doc, hang_hoa=item, vi_tri=pos,
                            so_luong_xuat=quantity, don_gia=price
                        )
                    detail.full_clean()
                    detail.save()

            messages.success(
                request,
                f'Đã lưu phiếu nháp {code} với {len(prepared)} dòng. '
                'Tồn kho chưa thay đổi.'
            )
            return redirect(
                'wms_document_detail', direction=direction, pk=doc.pk
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            messages.error(request, 'Không thể tạo phiếu: ' + str(exc))

    initial_lines = []
    selected_partner_id = ''
    selected_warehouse_id = ''
    initial_note = ''
    if request.method == 'POST':
        initial_lines = [
            {'hang_hoa': g, 'vi_tri': p, 'so_luong': q, 'don_gia': c}
            for g, p, q, c in zip(
                request.POST.getlist('hang_hoa'),
                request.POST.getlist('vi_tri'),
                request.POST.getlist('so_luong'),
                request.POST.getlist('don_gia')
            )
        ]
        selected_partner_id = request.POST.get('doi_tac', '')
        selected_warehouse_id = request.POST.get('kho', '')
        initial_note = request.POST.get('ghi_chu', '')

    return render(
        request, 'wms_core/new_document.html',
        _document_form_context(
            request, direction, selected_kind,
            displayed_code=displayed_code,
            code_token=code_token,
            initial_lines=initial_lines,
            selected_partner_id=selected_partner_id,
            selected_warehouse_id=selected_warehouse_id,
            initial_note=initial_note,
            edit_mode=False
        )
    )


@authorized
def edit_document(request, direction, pk):
    """Edit draft lines and recipient without modifying stock."""
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')
    cls = PhieuNhap if direction == 'nhap' else PhieuXuat

    def check_editable(doc):
        if request.wms_kind and doc.kho.loai_kho != request.wms_kind:
            raise PermissionDenied('Không có quyền thao tác trên kho khác.')
        if not request.wms_manager and doc.nguoi_lap_id != request.wms_account.pk:
            raise PermissionDenied('Chỉ quản lý hoặc người lập mới được sửa phiếu nháp.')
        if doc.kiem_kho_id or doc.trang_thai != 'nhap':
            raise PermissionDenied('Chỉ được sửa phiếu ở trạng thái Nháp.')

    doc = get_object_or_404(
        cls.objects.select_related('kho', 'doi_tac'), pk=pk
    )
    check_editable(doc)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                doc = get_object_or_404(
                    cls.objects.select_for_update().select_related('kho'), pk=pk
                )
                check_editable(doc)
                services.lock_warehouse(doc.kho_id)
                if str(request.POST.get('kho', '')) != str(doc.kho_id):
                    raise ValidationError('Không được đổi kho của phiếu đã lập.')

                partner = _get_document_partner(request, direction, doc.kho)
                prepared = _prepare_document_lines(request, direction, doc.kho)
                doc.doi_tac = partner
                doc.ghi_chu = request.POST.get('ghi_chu', '').strip()
                doc.save(update_fields=['doi_tac', 'ghi_chu'])
                doc.chi_tiet.all().delete()

                for item, pos, quantity, price in prepared:
                    if direction == 'nhap':
                        detail = ChiTietPhieuNhap(
                            phieu_nhap=doc, hang_hoa=item, vi_tri=pos,
                            so_luong_nhap=quantity, don_gia=price
                        )
                    else:
                        detail = ChiTietPhieuXuat(
                            phieu_xuat=doc, hang_hoa=item, vi_tri=pos,
                            so_luong_xuat=quantity, don_gia=price
                        )
                    detail.full_clean()
                    detail.save()

                code = (
                    doc.ma_phieu_nhap if direction == 'nhap'
                    else doc.ma_phieu_xuat
                )
                NhatKyGiaoDich.objects.create(
                    nguoi_thuc_hien=request.wms_account,
                    loai_giao_dich=direction,
                    hanh_dong=(
                        'SUA_PHIEU_NHAP' if direction == 'nhap'
                        else 'SUA_PHIEU_XUAT'
                    ),
                    noi_dung_thay_doi=(
                        f'Sửa phiếu nháp {code}: đối tác, ghi chú và '
                        f'{len(prepared)} dòng hàng. Tồn kho không đổi.'
                    )
                )

            messages.success(request, 'Đã cập nhật phiếu nháp. Tồn kho không thay đổi.')
            return redirect(
                'wms_document_detail', direction=direction, pk=doc.pk
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            messages.error(request, 'Không thể sửa phiếu: ' + str(exc))

    if request.method == 'POST':
        initial_lines = [
            {'hang_hoa': g, 'vi_tri': p, 'so_luong': q, 'don_gia': c}
            for g, p, q, c in zip(
                request.POST.getlist('hang_hoa'),
                request.POST.getlist('vi_tri'),
                request.POST.getlist('so_luong'),
                request.POST.getlist('don_gia')
            )
        ]
        selected_partner_id = request.POST.get('doi_tac', '')
        initial_note = request.POST.get('ghi_chu', '')
    else:
        initial_lines = [
            {
                'hang_hoa': str(line.hang_hoa_id),
                'vi_tri': str(line.vi_tri_id),
                'so_luong': str(
                    line.so_luong_nhap if direction == 'nhap'
                    else line.so_luong_xuat
                ),
                'don_gia': (
                    str(line.don_gia) if line.don_gia is not None else ''
                )
            }
            for line in doc.chi_tiet.all()
        ]
        selected_partner_id = str(doc.doi_tac_id or '')
        initial_note = doc.ghi_chu

    return render(
        request, 'wms_core/new_document.html',
        _document_form_context(
            request, direction, doc.kho.loai_kho,
            displayed_code=(
                doc.ma_phieu_nhap if direction == 'nhap'
                else doc.ma_phieu_xuat
            ),
            code_token='',
            edit_mode=True,
            edit_doc=doc,
            initial_lines=initial_lines,
            selected_warehouse_id=str(doc.kho_id),
            selected_partner_id=selected_partner_id,
            initial_note=initial_note,
        )
    )


@authorized
@require_POST
def delete_draft_document(request, direction, pk):
    """Delete an unsent receipt or issue draft without changing stock."""
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')
    cls = PhieuNhap if direction == 'nhap' else PhieuXuat

    try:
        with transaction.atomic():
            doc = get_object_or_404(
                cls.objects.select_for_update().select_related('kho'), pk=pk
            )
            if request.wms_kind and doc.kho.loai_kho != request.wms_kind:
                raise PermissionDenied('Không được thao tác trên kho khác.')

            if not request.wms_manager and doc.nguoi_lap_id != request.wms_account.pk:
                raise PermissionDenied(
                    'Chỉ quản lý kho hoặc người lập mới được xóa phiếu nháp.'
                )

            if doc.kiem_kho_id or doc.trang_thai != 'nhap':
                raise PermissionDenied('Chỉ được xóa phiếu ở trạng thái Nháp.')

            # Xóa chi tiết trước, vì khóa ngoại là PROTECT.

            code = doc.ma_phieu_nhap if direction == 'nhap' else doc.ma_phieu_xuat
            warehouse_kind = doc.kho.loai_kho

            doc.chi_tiet.all().delete()

            doc.delete()

            # Lưu nhật ký độc lập, không tham chiếu tới phiếu đã xóa.
            NhatKyGiaoDich.objects.create(
                nguoi_thuc_hien=request.wms_account,
                loai_giao_dich=direction,
                hanh_dong=('XOA_PHIEU_NHAP' if direction == 'nhap' else 'XOA_PHIEU_XUAT'),
                noi_dung_thay_doi=f'Người lập xóa phiếu nháp {code} (chưa ảnh hưởng tồn kho).'
            )

    except IntegrityError:
        messages.error(
            request, 'Phiếu đã có lịch sử hoặc tham chiếu nên không thể xóa trực tiếp.'
        )
        return redirect('wms_document_detail', direction=direction, pk=pk)


    messages.success(
        request,
        'Đã xóa phiếu nháp. Tồn kho không thay đổi.'
    )

    url = reverse(
        'wms_documents',
        kwargs={'direction': direction}
    )

    return redirect(f'{url}?kind={warehouse_kind}')



# ==========================================================
# 8. XEM CHI TIẾT PHIẾU
# ==========================================================

@authorized
def document_detail(request, direction, pk):
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')

    cls = PhieuNhap if direction == 'nhap' else PhieuXuat

    doc = get_object_or_404(
        cls.objects.select_related(
            'kho', 'doi_tac', 'nguoi_lap', 'nguoi_phe_duyet'
        ),
        pk=pk
    )

    if (
        request.wms_kind
        and doc.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden(
            'Không có quyền xem phiếu thuộc kho khác.'
        )

    lines = list(
        doc.chi_tiet.select_related(
            'hang_hoa__don_vi_tinh',
            'vi_tri__ke__khu_vuc__kho'
        ).all()
    )

    # Chỉ hiển thị tổng khi mọi dòng đều có đơn giá.
    has_full_prices = (
        bool(lines)
        and all(line.don_gia is not None for line in lines)
    )

    total_amount = None
    if has_full_prices:
        total_amount = sum(
            (line.thanh_tien for line in lines),
            Decimal('0')
        )

    # Hiển thị lý do từ chối nếu có.
    reject_log = NhatKyGiaoDich.objects.filter(
        **(
            {'phieu_nhap': doc}
            if direction == 'nhap'
            else {'phieu_xuat': doc}
        ),
        hanh_dong='TU_CHOI'
    ).order_by('-thoi_gian').first()

    return render(
        request, 'wms_core/document_detail.html',
        base(
            request,
            section=direction,
            direction=direction,
            kind=doc.kho.loai_kho,
            doc=doc,
            lines=lines,
            total_amount=total_amount,
            reject_log=reject_log
        )
    )


# ==========================================================
# 9. GỬI DUYỆT / PHÊ DUYỆT / TỪ CHỐI
# ==========================================================

@authorized
@require_POST
def document_action(request, direction, pk, action):
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')

    if action not in ('send', 'approve', 'reject'):
        raise Http404('Thao tác không hợp lệ.')

    cls = PhieuNhap if direction == 'nhap' else PhieuXuat

    doc = get_object_or_404(
        cls.objects.select_related('kho'),
        pk=pk
    )

    if (
        request.wms_kind
        and doc.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden(
            'Không có quyền thao tác phiếu này.'
        )

    if doc.kiem_kho_id:
        return HttpResponseForbidden(
            'Chứng từ cân bằng kiểm kho đã ghi nhận; không được xử lý lại.'
        )

    if action == 'send':
        try:
            with transaction.atomic():
                checked = cls.objects.select_for_update().get(pk=pk)

                if checked.trang_thai != 'nhap':
                    raise ValidationError(
                        'Chỉ phiếu nháp mới được gửi duyệt.'
                    )

                if (
                    not request.wms_manager
                    and checked.nguoi_lap_id != request.wms_account.pk
                ):
                    raise PermissionDenied(
                        'Chỉ người lập phiếu được gửi duyệt.'
                    )

                if not checked.chi_tiet.exists():
                    raise ValidationError('Phiếu chưa có dòng hàng.')

                services.lock_warehouse(checked.kho_id)

                # Kiem tra khoa theo san pham + vi tri
                services.assert_no_pending_stockcheck(
                    checked.kho_id,
                    checked.chi_tiet.values_list(
                        'hang_hoa_id',
                        'vi_tri_id',
                    ),
                )


                checked.trang_thai = 'cho_duyet'
                checked.save(update_fields=['trang_thai'])

            messages.success(
                request, 'Đã gửi phiếu chờ quản lý phê duyệt.'
            )
        except ValidationError as exc:
            messages.error(request, str(exc))

    elif action == 'approve':
        # Service kiểm tra khóa kiểm kê, tồn khả dụng,
        # giao dịch atomic và chống duyệt trùng.
        manager_action(
            request,
            lambda: services.approve_receipt(
                pk, request.user, direction
            )
        )

    elif action == 'reject':
        manager_only(request)
        reason = request.POST.get('ly_do', '').strip()

        try:
            if not reason:
                raise ValidationError(
                    'Vui lòng nhập lý do từ chối phiếu.'
                )
            if len(reason) > 500:
                raise ValidationError(
                    'Lý do từ chối tối đa 500 ký tự.'
                )

            with transaction.atomic():
                checked = cls.objects.select_for_update().get(pk=pk)

                if checked.trang_thai != 'cho_duyet':
                    raise ValidationError(
                        'Chỉ từ chối phiếu đang chờ duyệt.'
                    )

                checked.trang_thai = 'tu_choi'
                checked.nguoi_phe_duyet = request.wms_account
                checked.thoi_gian_phe_duyet = timezone.now()
                checked.save(
                    update_fields=[
                        'trang_thai',
                        'nguoi_phe_duyet',
                        'thoi_gian_phe_duyet'
                    ]
                )

                NhatKyGiaoDich.objects.create(
                    nguoi_thuc_hien=request.wms_account,
                    phieu_nhap=(
                        checked if direction == 'nhap' else None
                    ),
                    phieu_xuat=(
                        checked if direction == 'xuat' else None
                    ),
                    loai_giao_dich=direction,
                    hanh_dong='TU_CHOI',
                    noi_dung_thay_doi='Lý do từ chối: ' + reason
                )

            messages.success(
                request,
                'Đã từ chối phiếu. Tồn kho không thay đổi.'
            )

        except ValidationError as exc:
            messages.error(request, str(exc))

    return redirect(
        'wms_document_detail',
        direction=direction,
        pk=pk
    )


# ==========================================================
# 10. KIỂM KÊ KHO
# GIỮ NGHIỆP VỤ CŨ
# ==========================================================

@authorized
def stock_counts(request):
    qs = restricted(
        DotKiemKe.objects.select_related('kho', 'nguoi_lap'),
        request, 'kho__loai_kho'
    )
    return render(
        request, 'wms_core/counts.html',
        base(
            request,
            rows=qs.order_by('-id'),
            section='counts'
        )
    )


@authorized
@require_POST
def new_count(request):
    manager_only(request)
    warehouse = get_object_or_404(
        Kho, pk=request.POST.get('kho')
    )
    code = request.POST.get('ma_dot', '').strip()

    if not code:
        messages.error(request, 'Cần có mã đợt kiểm kê.')
        return redirect('wms_counts')

    try:
        with transaction.atomic():
            batch = DotKiemKe.objects.create(
                kho=warehouse,
                nguoi_lap=request.wms_account,
                ma_dot=code
            )

            for pos in ViTriLuuTru.objects.filter(
                ke__khu_vuc__kho=warehouse
            ):
                PhamViKiemKe.objects.create(
                    dot_kiem_ke=batch,
                    vi_tri=pos
                )

        messages.success(
            request,
            'Đã tạo đợt kiểm kê nháp '
            'và chọn toàn bộ vị trí trong kho.'
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect('wms_counts')


@authorized
@require_POST
def count_action(request, pk, action):
    if action == 'start':
        manager_action(
            request,
            lambda: services.start_count(pk, request.user)
        )
    elif action == 'finish':
        manager_action(
            request,
            lambda: services.finish_count(pk, request.user)
        )
    else:
        raise Http404('Thao tác kiểm kê không hợp lệ.')

    return redirect('wms_counts')


@authorized
def count_detail(request, pk):
    batch = get_object_or_404(
        DotKiemKe.objects.select_related('kho'),
        pk=pk
    )
    if (
        request.wms_kind
        and batch.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden('Không có quyền kho này.')

    rows = ChiTietKiemKe.objects.filter(
        pham_vi__dot_kiem_ke=batch
    ).select_related(
        'hang_hoa', 'pham_vi__vi_tri'
    )

    return render(
        request, 'wms_core/count_detail.html',
        base(
            request, batch=batch,
            rows=rows, section='counts'
        )
    )


@authorized
@require_POST
def record_count(request, pk):
    line = get_object_or_404(
        ChiTietKiemKe.objects.select_related(
            'pham_vi__dot_kiem_ke__kho'
        ),
        pk=pk
    )
    batch = line.pham_vi.dot_kiem_ke

    if (
        request.wms_kind
        and batch.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden('Không có quyền kho này.')

    if batch.trang_thai != 'dang_kiem':
        messages.error(
            request, 'Đợt chưa bắt đầu hoặc đã kết thúc.'
        )
    else:
        try:
            quantity = Decimal(
                request.POST.get('so_luong_thuc_te', '')
            )
            if not quantity.is_finite() or quantity < 0:
                raise ValueError()

            if DieuChinhTonKho.objects.filter(
                chi_tiet_kiem_ke=line
            ).exists():
                raise ValidationError(
                    'Đã lập đề nghị điều chỉnh, '
                    'không thể sửa kiểm đếm.'
                )

            line.so_luong_thuc_te = quantity
            line.chenh_lech = (
                quantity - line.so_luong_he_thong
            )
            line.nguoi_kiem_dem = request.wms_account
            line.save(
                update_fields=[
                    'so_luong_thuc_te',
                    'chenh_lech',
                    'nguoi_kiem_dem'
                ]
            )

            if line.chenh_lech != 0:
                DieuChinhTonKho.objects.create(
                    chi_tiet_kiem_ke=line,
                    nguoi_de_nghi=request.wms_account,
                    so_luong_dieu_chinh=line.chenh_lech,
                    ly_do=request.POST.get(
                        'ly_do', 'Sai lệch kiểm kê'
                    )
                )

            messages.success(
                request, 'Đã ghi nhận số lượng kiểm đếm.'
            )
        except (
            ValueError, InvalidOperation, ValidationError
        ) as exc:
            messages.error(
                request, 'Số lượng không hợp lệ: ' + str(exc)
            )

    return redirect(
        'wms_count_detail', pk=batch.pk
    )


# ==========================================================
# 11. DUYỆT ĐIỀU CHỈNH TỒN KHO
# ==========================================================

@authorized
def adjustments(request):
    manager_only(request)
    rows = DieuChinhTonKho.objects.select_related(
        'chi_tiet_kiem_ke__hang_hoa',
        'chi_tiet_kiem_ke__pham_vi__vi_tri'
    ).order_by('-id')
    return render(
        request, 'wms_core/adjustments.html',
        base(
            request, rows=rows,
            section='adjustments'
        )
    )


@authorized
@require_POST
def adjustment_action(request, pk, action):
    manager_only(request)

    if action == 'approve':
        manager_action(
            request,
            lambda: services.approve_adjustment(
                pk, request.user
            )
        )
    elif action == 'reject':
        def reject_adjustment():
            with transaction.atomic():
                adj = get_object_or_404(
                    DieuChinhTonKho.objects.select_for_update(),
                    pk=pk
                )
                if adj.trang_thai != 'cho_duyet':
                    raise ValidationError(
                        'Đề nghị không còn chờ duyệt.'
                    )
                adj.trang_thai = 'tu_choi'
                adj.save(update_fields=['trang_thai'])

        manager_action(request, reject_adjustment)
    else:
        raise Http404('Thao tác không hợp lệ.')

    return redirect('wms_adjustments')


# ==========================================================
# 12. NGƯỠNG TỒN AN TOÀN
# ==========================================================

@authorized
def thresholds(request):
    qs = restricted(
        NguongTonAnToan.objects.select_related(
            'hang_hoa', 'kho'
        ),
        request, 'kho__loai_kho'
    )
    return render(
        request, 'wms_core/thresholds.html',
        base(
            request, rows=qs,
            section='thresholds'
        )
    )


@authorized
@require_POST
def update_threshold(request, pk):
    manager_only(request)
    obj = get_object_or_404(NguongTonAnToan, pk=pk)

    try:
        quantity = Decimal(
            request.POST['muc_ton_an_toan']
        )
        if not quantity.is_finite() or quantity < 0:
            raise ValueError()

        obj.muc_ton_an_toan = quantity
        obj.nguoi_cap_nhat = request.wms_account
        obj.save()

        messages.success(
            request, 'Đã cập nhật ngưỡng tồn an toàn.'
        )
    except (ValueError, InvalidOperation):
        messages.error(
            request, 'Ngưỡng tồn phải là số không âm.'
        )

    return redirect('wms_thresholds')



# ==========================================================
# 13. NHAT KY GIAO DICH
# ==========================================================

@authorized
def activity(request):
    import re

    manager_only(request)

    rows = list(
        NhatKyGiaoDich.objects.select_related(
            'hang_hoa',
            'vi_tri',
            'nguoi_thuc_hien',
            'phieu_nhap',
            'phieu_xuat'
        ).all()[:300]
    )

    # Nhan dang ma phieu nhap, xuat va kiem kho
    code_pattern = re.compile(
        r'\b(?:PN|PX)-(?:KK-)?[A-Za-z0-9-]+\b'
        r'|\bKK-\d{4}-\d+\b',
        re.IGNORECASE
    )

    for item in rows:

        code = None

        # 1. Phieu nhap con ton tai
        if item.phieu_nhap_id:
            code = item.phieu_nhap.ma_phieu_nhap

        # 2. Phieu xuat con ton tai
        elif item.phieu_xuat_id:
            code = item.phieu_xuat.ma_phieu_xuat

        # 3. Phieu da xoa hoac phieu kiem kho:
        # Lay ma da duoc ghi lai trong noi dung nhat ky
        else:
            content = item.noi_dung_thay_doi or ''

            match = code_pattern.search(content)

            if match:
                code = match.group(0)

        # Ma phieu hien thi tren giao dien
        item.ma_phieu_hien_thi = code or '-'

    return render(
        request,
        'wms_core/activity.html',
        base(
            request,
            rows=rows,
            section='activity'
        )
    )

# ==========================================================
# 14. BÁO CÁO - GIỮ NGHIỆP VỤ CŨ
# ==========================================================

@authorized
def report(request):
    manager_only(request)
    data = []

    for warehouse in Kho.objects.all():
        stocks = TonKho.objects.filter(
            vi_tri__ke__khu_vuc__kho=warehouse
        )
        data.append({
            'kho': warehouse,
            'total': stocks.aggregate(
                total=Sum('so_luong_ton')
            )['total'] or 0,
            'sku': stocks.values(
                'hang_hoa'
            ).distinct().count(),
            'receipts': PhieuNhap.objects.filter(
                kho=warehouse,
                trang_thai='da_duyet'
            ).count(),
            'issues': PhieuXuat.objects.filter(
                kho=warehouse,
                trang_thai='da_duyet'
            ).count()
        })

    return render(
        request, 'wms_core/report.html',
        base(
            request, data=data,
            section='report'
        )
    )


# ==========================================================
# 15. TÀI KHOẢN
# ==========================================================

@authorized
def users(request):
    manager_only(request)
    rows = TaiKhoan.objects.select_related(
        'user', 'vai_tro'
    )
    return render(
        request, 'wms_core/users.html',
        base(
            request, rows=rows,
            section='users'
        )
    )

# ==========================================
# KHOA / MO KHOA TAI KHOAN
# ==========================================

@authorized
@require_POST
def toggle_user_status(request, pk):

    # Chi quan ly kho duoc thuc hien
    manager_only(request)

    with transaction.atomic():

        # Tim tai khoan can thay doi
        target = get_object_or_404(
            TaiKhoan.objects.select_related(
                'user'
            ).select_for_update(),
            pk=pk
        )

        # Khong cho tu khoa tai khoan cua minh
        if target.pk == request.wms_account.pk:

            messages.error(
                request,
                'Bạn không thể tự khóa tài khoản đang đăng nhập.'
            )

            return redirect('wms_users')

        # Bao ve tai khoan quan tri Django
        if target.user.is_superuser:

            messages.error(
                request,
                'Không thể thay đổi trạng thái tài khoản '
                'Django superuser tại trang này.'
            )

            return redirect('wms_users')

        # Dang hoat dong -> Khoa
        # Dang bi khoa -> Mo khoa
        new_active = not (
            target.trang_thai
            and target.user.is_active
        )

        # Cap nhat trang thai tai khoan WMS
        target.trang_thai = new_active

        target.save(
            update_fields=['trang_thai']
        )

        # Dong bo trang thai dang nhap Django
        target.user.is_active = new_active

        target.user.save(
            update_fields=['is_active']
        )

    # Thong bao ket qua
    if new_active:

        messages.success(
            request,
            f'Đã mở khóa tài khoản '
            f'{target.user.username}.'
        )

    else:

        messages.success(
            request,
            f'Đã khóa tài khoản '
            f'{target.user.username}.'
        )

    return redirect('wms_users')


# ==========================================================
# 16. XỬ LÝ PHIẾU CŨ
# GIỮ BACKEND, KHÔNG ĐẶT NÚT HỦY Ở GIAO DIỆN MỚI
# ==========================================================

@authorized
def correction_requests(request):
    qs = YeuCauXuLyPhieu.objects.select_related(
        'phieu_nhap', 'phieu_xuat',
        'nguoi_yeu_cau', 'nguoi_phe_duyet'
    ).order_by('-id')

    if request.wms_kind:
        qs = qs.filter(
            Q(phieu_nhap__kho__loai_kho=request.wms_kind)
            | Q(phieu_xuat__kho__loai_kho=request.wms_kind)
        )

    return render(
        request, 'wms_core/corrections.html',
        base(
            request, rows=qs[:150],
            section='corrections'
        )
    )


@authorized
@require_POST
def request_correction(request, direction, pk):
    if direction not in ('nhap', 'xuat'):
        raise Http404('Loại phiếu không hợp lệ.')

    cls = PhieuNhap if direction == 'nhap' else PhieuXuat
    doc = get_object_or_404(
        cls.objects.select_related('kho'),
        pk=pk
    )

    if (
        request.wms_kind
        and doc.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden(
            'Không thuộc phạm vi kho được phân công.'
        )

    if doc.kiem_kho_id:
        messages.error(
            request,
            'Không được yêu cầu hủy riêng chứng từ sinh từ kiểm kho.'
        )
        return redirect('wms_document_detail', direction=direction, pk=pk)

    if doc.trang_thai != 'da_duyet':
        messages.error(
            request, 'Chỉ tạo yêu cầu cho phiếu đã duyệt.'
        )
    else:
        try:
            reason = request.POST.get('ly_do', '').strip()
            if not reason:
                raise ValidationError(
                    'Cần ghi rõ lý do hủy phiếu.'
                )

            with transaction.atomic():
                lookup = (
                    {'phieu_nhap': doc}
                    if direction == 'nhap'
                    else {'phieu_xuat': doc}
                )

                if YeuCauXuLyPhieu.objects.filter(
                    trang_thai='cho_duyet',
                    **lookup
                ).exists():
                    raise ValidationError(
                        'Phiếu đang có yêu cầu xử lý chờ phê duyệt.'
                    )

                YeuCauXuLyPhieu.objects.create(
                    nguoi_yeu_cau=request.wms_account,
                    loai_yeu_cau='huy',
                    ly_do=reason,
                    noi_dung_de_nghi=(
                        'Đề nghị hủy phiếu đã xác nhận'
                    ),
                    **lookup
                )

            messages.success(
                request,
                'Đã gửi yêu cầu hủy để quản lý xem xét. '
                'Tồn kho chưa thay đổi.'
            )
        except (ValidationError, IntegrityError) as exc:
            messages.error(request, str(exc))

    return redirect(
        'wms_documents', direction=direction
    )


@authorized
@require_POST
def correction_action(request, pk, action):
    manager_only(request)

    if action not in ('approve', 'reject'):
        raise Http404('Thao tác không hợp lệ.')

    if action == 'approve':
        manager_action(
            request,
            lambda: services.approve_cancellation(
                pk, request.user
            )
        )
    else:
        def reject_correction():
            with transaction.atomic():
                req = YeuCauXuLyPhieu.objects.select_for_update().get(
                    pk=pk
                )
                if req.trang_thai != 'cho_duyet':
                    raise ValidationError(
                        'Yêu cầu không còn chờ duyệt.'
                    )

                req.trang_thai = 'tu_choi'
                req.nguoi_phe_duyet = request.wms_account
                req.thoi_gian_phe_duyet = timezone.now()
                req.noi_dung_xu_ly = request.POST.get(
                    'ghi_chu', 'Từ chối'
                )
                req.save(
                    update_fields=[
                        'trang_thai',
                        'nguoi_phe_duyet',
                        'thoi_gian_phe_duyet',
                        'noi_dung_xu_ly'
                    ]
                )

        manager_action(request, reject_correction)

    req = get_object_or_404(
        YeuCauXuLyPhieu, pk=pk
    )
    direction = 'nhap' if req.phieu_nhap_id else 'xuat'

    return redirect(
        'wms_documents', direction=direction
    )


# ==========================================================
# 17. NHẬP EXCEL
# ==========================================================




@authorized
def import_excel(request):
    # Cho phép quản lý và hai loại nhân viên kho.
    if (
        not request.wms_manager
        and request.wms_kind not in ('NVL', 'TP')
    ):
        raise PermissionDenied(
            'Tài khoản không có quyền nhập dữ liệu Excel.'
        )

    summary = None
    summary_type = None

    if request.method == 'POST':
        try:
            from .excel_import import import_single_sheet

            category = request.POST.get(
                'import_type', ''
            ).strip().upper()

            source = request.FILES.get('excel')

            if category not in ('NVL', 'TP', 'NCC'):
                raise ValidationError(
                    'Danh mục nhập Excel không hợp lệ.'
                )

            # Nhân viên chỉ nhập được đúng kho được phân quyền.
            # Quản lý kho được nhập cả 3 danh mục.
            if (
                not request.wms_manager
                and category != request.wms_kind
            ):
                raise PermissionDenied(
                    'Bạn không có quyền nhập Excel '
                    'cho danh mục này.'
                )

            if source is None:
                raise ValidationError(
                    'Vui lòng chọn tệp Excel .xlsx.'
                )

            if (
                not source.name.lower().endswith('.xlsx')
                or source.size > 5 * 1024 * 1024
            ):
                raise ValidationError(
                    'Chỉ nhận tệp .xlsx tối đa 5 MB.'
                )

            # Import Excel có thể cập nhật tồn của nhiều SKU. Để tránh
            # ghi đè số kiểm đếm, tạm chặn import cho loại kho đang có
            # bất kỳ phiếu kiểm kho chờ duyệt (kể cả kiểm một phần).
            if category in ('NVL', 'TP') and PhieuKiemKho.objects.filter(
                kho__loai_kho=category, trang_thai='cho_duyet'
            ).exists():
                raise ValidationError(
                    'Kho đang có phiếu kiểm kho chờ duyệt. '
                    'Tạm dừng nhập dữ liệu Excel cho đến khi xử lý xong.'
                )

            # Không cho nhập tồn Excel khi kho đang kiểm kê.
            if category in ('NVL', 'TP'):
                counting = DotKiemKe.objects.filter(
                    kho__loai_kho=category,
                    trang_thai='dang_kiem'
                ).exists()

                if counting:
                    raise ValidationError(
                        'Kho đang kiểm kê. '
                        'Không được nhập dữ liệu tồn kho '
                        'từ Excel cho đến khi hoàn tất.'
                    )

            # Chan nhap Excel khi kho co khoa tam kiem kho
            if category in ('NVL', 'TP'):

                has_temporary_lock = (
                    KhoaTamKiemKho.objects.filter(
                        kho__loai_kho=category,
                        het_han_luc__gt=timezone.now(),
                    ).exists()
                )

                if has_temporary_lock:
                    raise ValidationError(
                        'Kho đang có hàng hóa được kiểm kê. '
                        'Tạm dừng nhập Excel cho đến khi '
                        'hoàn tất hoặc hủy thao tác kiểm kê.'
                    )

            summary = import_single_sheet(
                source,
                request.wms_account,
                category
            )

            summary_type = category

            messages.success(
                request,
                'Đã kiểm tra và nhập dữ liệu thành công. '
                'Mã đã có được giữ nguyên; '
                'tồn kho hiện hữu không bị cộng lại.'
            )

        except (
            ValidationError,
            ValueError,
            IntegrityError
        ) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        'wms_core/import_excel.html',
        base(
            request,
            section='import_excel',
            summary=summary,
            summary_type=summary_type
        )
    )




# ==========================================================
# 18. XUẤT TỒN KHO CSV
# ==========================================================

@authorized
def export_inventory_csv(request):
    manager_only(request)

    rows = TonKho.objects.select_related(
        'hang_hoa__don_vi_tinh',
        'vi_tri__ke__khu_vuc__kho'
    ).order_by(
        'vi_tri__ke__khu_vuc__kho__ten_kho',
        'hang_hoa__ma_hang'
    )

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )
    response['Content-Disposition'] = (
        'attachment; filename="xonxen_ton_kho_hien_tai.csv"'
    )
    response.write('\ufeff'.encode('utf-8'))

    writer = csv.writer(response)
    writer.writerow([
        'Kho', 'Mã hàng', 'Tên hàng', 'Đơn vị tính',
        'Vị trí', 'Số lượng tồn', 'Cập nhật lúc'
    ])

    for row in rows.iterator():
        writer.writerow([
            row.vi_tri.kho.ten_kho,
            row.hang_hoa.ma_hang,
            row.hang_hoa.ten_hang,
            row.hang_hoa.don_vi_tinh.ten_don_vi_tinh,
            row.vi_tri.ma_vi_tri,
            str(row.so_luong_ton),
            timezone.localtime(
                row.thoi_gian_cap_nhat
            ).strftime('%d/%m/%Y %H:%M')
        ])

    return response
