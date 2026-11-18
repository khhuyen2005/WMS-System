
"""Xuất PDF chứng từ kho đã phê duyệt của XONXEN SHOP."""

from decimal import Decimal
from html import escape
from io import BytesIO
from pathlib import Path

from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import PhieuNhap, PhieuXuat
from .views import authorized


# ==============================================
# 1. MÀU SẮC THƯƠNG HIỆU
# ==============================================

ORANGE = colors.HexColor('#A43D10')
PALE_ORANGE = colors.HexColor('#FFF1E7')
GRAY = colors.HexColor('#616161')


# ==============================================
# 2. FONT TIẾNG VIỆT
# ==============================================

def _register_fonts():
    """
    Ưu tiên Arial hoặc Tahoma trên Windows.
    Có thêm DejaVu Sans nếu chạy trên Linux.
    """

    candidates = [
        (
            Path('C:/Windows/Fonts/arial.ttf'),
            Path('C:/Windows/Fonts/arialbd.ttf'),
        ),
        (
            Path('C:/Windows/Fonts/tahoma.ttf'),
            Path('C:/Windows/Fonts/tahomabd.ttf'),
        ),
        (
            Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
            Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        ),
    ]

    for normal, bold in candidates:
        if normal.is_file() and bold.is_file():

            registered = pdfmetrics.getRegisteredFontNames()

            if 'XonxenRegular' not in registered:
                pdfmetrics.registerFont(
                    TTFont(
                        'XonxenRegular',
                        str(normal),
                    )
                )

            if 'XonxenBold' not in registered:
                pdfmetrics.registerFont(
                    TTFont(
                        'XonxenBold',
                        str(bold),
                    )
                )

            pdfmetrics.registerFontFamily(
                'XonxenRegular',
                normal='XonxenRegular',
                bold='XonxenBold',
            )

            return

    raise RuntimeError(
        'Không tìm thấy font Unicode Arial/Tahoma. '
        'Hãy kiểm tra thư mục C:\\Windows\\Fonts.'
    )


# ==============================================
# 3. HÀM ĐỊNH DẠNG
# ==============================================

def _s(value):
    """
    Chuyển dữ liệu thành chữ an toàn
    để đưa vào PDF.
    """

    if value is None:
        value = '—'

    return escape(str(value)).replace(
        '\n',
        '<br/>',
    )


def _number(value):
    """Định dạng số lượng và tiền."""

    if value is None:
        return '—'

    return f'{Decimal(value):,.2f}'


def _date(value):
    """Định dạng ngày giờ của chứng từ."""

    if not value:
        return '—'

    if timezone.is_aware(value):
        value = timezone.localtime(value)

    return value.strftime('%d/%m/%Y %H:%M')


def _recipient_label(direction, kind, internal):
    """Xác định tên người giao/nhận theo nghiệp vụ."""

    if internal:
        return 'Nguồn chứng từ'

    if direction == 'nhap':
        if kind == 'NVL':
            return 'Nhà cung cấp NVL'

        return 'Xưởng gia công giao TP'

    if kind == 'NVL':
        return 'Xưởng gia công nhận NVL'

    return 'Chi nhánh nhận thành phẩm'


# ==============================================
# 4. CHÂN TRANG PDF
# ==============================================

def _page_footer(canvas, document):
    canvas.saveState()

    width, _ = A4

    canvas.setStrokeColor(
        colors.HexColor('#E7D7CA')
    )

    canvas.line(
        18 * mm,
        17 * mm,
        width - 18 * mm,
        17 * mm,
    )

    canvas.setFont(
        'XonxenRegular',
        8,
    )

    canvas.setFillColor(GRAY)

    canvas.drawString(
        18 * mm,
        12 * mm,
        'XONXEN SHOP | Chứng từ quản lý kho',
    )

    canvas.drawRightString(
        width - 18 * mm,
        12 * mm,
        f'Trang {document.page}',
    )

    canvas.restoreState()


# ==============================================
# 5. TẠO NỘI DUNG PDF
# ==============================================

def _render_pdf(doc, direction, lines):

    _register_fonts()

    output = BytesIO()

    pdf = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=23 * mm,
        title=(
            doc.ma_phieu_nhap
            if direction == 'nhap'
            else doc.ma_phieu_xuat
        ),
        author='XONXEN SHOP',
    )

    # ==========================================
    # KIỂU CHỮ
    # ==========================================

    regular = ParagraphStyle(
        'x-regular',
        fontName='XonxenRegular',
        fontSize=9.2,
        leading=14,
        textColor=colors.HexColor('#292929'),
        spaceAfter=0,
    )

    small = ParagraphStyle(
        'x-small',
        parent=regular,
        fontSize=8,
        leading=11,
    )

    right = ParagraphStyle(
        'x-right',
        parent=small,
        alignment=TA_RIGHT,
    )

    center = ParagraphStyle(
        'x-center',
        parent=small,
        alignment=TA_CENTER,
    )

    bold = ParagraphStyle(
        'x-bold',
        parent=regular,
        fontName='XonxenBold',
    )

    title_style = ParagraphStyle(
        'x-title',
        parent=bold,
        fontSize=17,
        leading=21,
        alignment=TA_CENTER,
        textColor=ORANGE,
        spaceAfter=6,
    )

    sub = ParagraphStyle(
        'x-sub',
        parent=small,
        alignment=TA_CENTER,
        spaceAfter=14,
    )

    def p(value, style=regular):
        return Paragraph(
            _s(value),
            style,
        )

    def field(label, value):
        return Paragraph(
            f'<font color="#666666">{_s(label)}:</font> '
            f'<b>{_s(value)}</b>',
            regular,
        )

    # ==========================================
    # THÔNG TIN CHỨNG TỪ
    # ==========================================

    direction_name = (
        'NHẬP'
        if direction == 'nhap'
        else 'XUẤT'
    )

    doc_code = (
        doc.ma_phieu_nhap
        if direction == 'nhap'
        else doc.ma_phieu_xuat
    )

    internal = bool(doc.kiem_kho_id)

    if internal:
        recipient = (
            f'Điều chỉnh nội bộ từ '
            f'{doc.kiem_kho.ma_phieu}'
        )

    elif doc.doi_tac_id:
        recipient = doc.doi_tac.ten_doi_tac

    else:
        recipient = '—'

    # ==========================================
    # TIÊU ĐỀ
    # ==========================================

    story = [
        Paragraph(
            'XONXEN SHOP',
            ParagraphStyle(
                'x-brand',
                parent=bold,
                fontSize=12,
                leading=17,
                textColor=ORANGE,
            ),
        ),

        Spacer(1, 4 * mm),

        Paragraph(
            f'PHIẾU {direction_name} KHO',
            title_style,
        ),

        Paragraph(
            f'Mã chứng từ: {_s(doc_code)}',
            sub,
        ),
    ]

    # ==========================================
    # BẢNG THÔNG TIN CHUNG
    # ==========================================

    info = [
        [
            field('Kho', doc.kho.ten_kho),

            field(
                'Loại kho',
                doc.kho.get_loai_kho_display(),
            ),
        ],

        [
            field(
                'Ngày lập',
                _date(doc.thoi_gian_lap),
            ),

            field(
                'Ngày duyệt',
                _date(doc.thoi_gian_phe_duyet),
            ),
        ],

        [
            field(
                'Người lập',
                doc.nguoi_lap.ho_ten,
            ),

            field(
                'Người duyệt',
                (
                    doc.nguoi_phe_duyet.ho_ten
                    if doc.nguoi_phe_duyet
                    else '—'
                ),
            ),
        ],

        [
            field(
                _recipient_label(
                    direction,
                    doc.kho.loai_kho,
                    internal,
                ),
                recipient,
            ),

            field(
                'Trạng thái',
                'Đã phê duyệt',
            ),
        ],
    ]

    info_table = Table(
        info,
        colWidths=[
            87 * mm,
            87 * mm,
        ],
        hAlign='LEFT',
    )

    info_table.setStyle(
        TableStyle([
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'TOP',
            ),
            (
                'LEFTPADDING',
                (0, 0),
                (-1, -1),
                0,
            ),
            (
                'RIGHTPADDING',
                (0, 0),
                (-1, -1),
                6,
            ),
            (
                'TOPPADDING',
                (0, 0),
                (-1, -1),
                4,
            ),
            (
                'BOTTOMPADDING',
                (0, 0),
                (-1, -1),
                4,
            ),
        ])
    )

    story.extend([
        info_table,
        Spacer(1, 6 * mm),
    ])

    # ==========================================
    # GHI CHÚ RIÊNG CHỨNG TỪ KIỂM KHO
    # ==========================================

    if internal:

        story.extend([
            p(
                'CHỨNG TỪ ĐIỀU CHỈNH NỘI BỘ TỪ KIỂM KHO',
                bold,
            ),

            p(
                'Tồn kho đã được cập nhật khi duyệt '
                'phiếu kiểm kho; chứng từ này không '
                'cập nhật tồn lần nữa.',
                small,
            ),

            Spacer(1, 5 * mm),
        ])

    # ==========================================
    # BẢNG HÀNG HÓA
    # ==========================================

    headers = [
        'STT',
        'Mã SKU',
        'Tên hàng / thuộc tính',
        'Kệ / vị trí',
        'ĐVT',
        'SL',
        'Đơn giá',
        'Thành tiền',
    ]

    rows = [
        [
            p(header, center)
            for header in headers
        ]
    ]

    total = Decimal('0')

    complete_prices = bool(lines)

    for index, line in enumerate(lines, 1):

        product = line.hang_hoa

        quantity = (
            line.so_luong_nhap
            if direction == 'nhap'
            else line.so_luong_xuat
        )

        has_price = line.don_gia is not None

        complete_prices = (
            complete_prices and has_price
        )

        amount = (
            quantity * line.don_gia
            if has_price
            else None
        )

        if amount is not None:
            total += amount

        # Thuộc tính của sản phẩm.
        attributes = ', '.join(
            str(value)
            for value in [
                product.mau_ma,
                product.mau_sac,
                product.kich_co,
            ]
            if value
        )

        item_name = product.ten_hang

        if attributes:
            item_name += f'\n{attributes}'

        # Kệ và vị trí.
        position = line.vi_tri

        position_name = (
            f'{position.ke.ten_ke}\n'
            f'{position.ten_vi_tri} '
            f'({position.ma_vi_tri})'
        )

        rows.append([
            p(index, center),

            p(
                product.ma_hang,
                small,
            ),

            p(
                item_name,
                small,
            ),

            p(
                position_name,
                small,
            ),

            p(
                product.don_vi_tinh.ten_don_vi_tinh,
                center,
            ),

            p(
                _number(quantity),
                right,
            ),

            p(
                _number(line.don_gia),
                right,
            ),

            p(
                _number(amount),
                right,
            ),
        ])

    # Tổng bề rộng = 174 mm, vừa giấy A4.
    widths = [
        9 * mm,
        17 * mm,
        39 * mm,
        33 * mm,
        12 * mm,
        15 * mm,
        24 * mm,
        25 * mm,
    ]

    goods_table = Table(
        rows,
        colWidths=widths,
        repeatRows=1,
        hAlign='LEFT',
    )

    goods_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                PALE_ORANGE,
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'TOP',
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.35,
                colors.HexColor('#E7D7CA'),
            ),
            (
                'LEFTPADDING',
                (0, 0),
                (-1, -1),
                3,
            ),
            (
                'RIGHTPADDING',
                (0, 0),
                (-1, -1),
                3,
            ),
            (
                'TOPPADDING',
                (0, 0),
                (-1, -1),
                6,
            ),
            (
                'BOTTOMPADDING',
                (0, 0),
                (-1, -1),
                6,
            ),
            (
                'ROWBACKGROUNDS',
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor('#FFFCFA'),
                ],
            ),
        ])
    )

    story.append(goods_table)

    story.append(
        Spacer(1, 6 * mm)
    )

    # ==========================================
    # TỔNG TIỀN
    # ==========================================

    if complete_prices:
        total_text = (
            f'{_number(total)} VNĐ'
        )
    else:
        total_text = (
            'Chưa đủ dữ liệu đơn giá'
        )

    story.append(
        Paragraph(
            f'<b>TỔNG TIỀN: {total_text}</b>',

            ParagraphStyle(
                'x-total',
                parent=bold,
                alignment=TA_RIGHT,
                textColor=ORANGE,
                fontSize=11,
            ),
        )
    )

    # ==========================================
    # GHI CHÚ
    # ==========================================

    if doc.ghi_chu:

        story.extend([
            Spacer(1, 5 * mm),

            field(
                'Ghi chú',
                doc.ghi_chu,
            ),
        ])

    # ==========================================
    # KHU VỰC CHỮ KÝ
    # ==========================================

    story.append(
        Spacer(1, 12 * mm)
    )

    signature_table = Table(
        [
            [
                p(
                    'NGƯỜI LẬP PHIẾU',
                    center,
                ),

                p(
                    'NGƯỜI GIAO / NHẬN',
                    center,
                ),

                p(
                    'NGƯỜI PHÊ DUYỆT',
                    center,
                ),
            ],

            [
                p(
                    '(Ký, ghi rõ họ tên)',
                    center,
                ),

                p(
                    '(Ký, ghi rõ họ tên)',
                    center,
                ),

                p(
                    '(Ký, ghi rõ họ tên)',
                    center,
                ),
            ],
        ],

        colWidths=[
            58 * mm,
            58 * mm,
            58 * mm,
        ],
    )

    signature_table.setStyle(
        TableStyle([
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'TOP',
            ),
            (
                'TOPPADDING',
                (0, 0),
                (-1, -1),
                4,
            ),
            (
                'BOTTOMPADDING',
                (0, 0),
                (-1, -1),
                4,
            ),
        ])
    )

    story.append(signature_table)

    # ==========================================
    # XUẤT TỆP PDF
    # ==========================================

    pdf.build(
        story,
        onFirstPage=_page_footer,
        onLaterPages=_page_footer,
    )

    return output.getvalue()


# ==============================================
# 6. VIEW TẢI PDF
# ==============================================

@authorized
def export_document_pdf(request, direction, pk):

    if direction not in ('nhap', 'xuat'):
        raise Http404(
            'Loại phiếu không hợp lệ.'
        )

    model = (
        PhieuNhap
        if direction == 'nhap'
        else PhieuXuat
    )

    # Lấy phiếu từ cơ sở dữ liệu.
    doc = get_object_or_404(
        model.objects.select_related(
            'kho',
            'doi_tac',
            'nguoi_lap',
            'nguoi_phe_duyet',
            'kiem_kho',
        ),
        pk=pk,
    )

    # Kiểm tra quyền xem theo loại kho.
    if (
        request.wms_kind
        and doc.kho.loai_kho != request.wms_kind
    ):
        return HttpResponseForbidden(
            'Không có quyền xuất phiếu thuộc kho khác.'
        )

    # Chỉ cho tải chứng từ đã duyệt.
    if doc.trang_thai != 'da_duyet':
        return HttpResponseForbidden(
            'Chỉ phiếu đã phê duyệt '
            'mới được xuất PDF.'
        )

    # Lấy đúng các dòng hàng hóa đã lưu.
    lines = list(
        doc.chi_tiet.select_related(
            'hang_hoa__don_vi_tinh',
            'vi_tri__ke',
        ).order_by('pk')
    )

    # Tạo PDF trong bộ nhớ.
    content = _render_pdf(
        doc,
        direction,
        lines,
    )

    # Lấy mã chứng từ để đặt tên tệp.
    filename = (
        doc.ma_phieu_nhap
        if direction == 'nhap'
        else doc.ma_phieu_xuat
    )

    # Trả tệp PDF về trình duyệt.
    response = HttpResponse(
        content,
        content_type='application/pdf',
    )

    response['Content-Disposition'] = (
        f'attachment; filename="{filename}.pdf"'
    )

    response['X-Content-Type-Options'] = 'nosniff'

    return response
