"""Đồng bộ danh mục XONXEN từ databasee.xlsx, không đụng bảng giao dịch/tồn."""
from pathlib import Path
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from wms_core.models import (
    Kho, KhuVuc, Ke, ViTriLuuTru, NhomHang, DonViTinh, HangHoa, DoiTac
)

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p': 'http://schemas.openxmlformats.org/package/2006/relationships'}


def read_xlsx(path):
    """Đọc cell giá trị của .xlsx chỉ với thư viện chuẩn Python."""
    with ZipFile(path) as book:
        wb = ET.fromstring(book.read('xl/workbook.xml'))
        rels = ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))
        targets = {r.attrib['Id']: r.attrib['Target'] for r in rels}
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            root = ET.fromstring(book.read('xl/sharedStrings.xml'))
            strings = [''.join(t.text or '' for t in si.findall('.//x:t', NS))
                       for si in root.findall('x:si', NS)]
        sheets = {}
        for sh in wb.findall('x:sheets/x:sheet', NS):
            name = sh.attrib['name']
            target = targets[sh.attrib['{%s}id' % NS['r']]]
            target = target.lstrip('/')
            if not target.startswith('xl/'):
                target = 'xl/' + target
            root = ET.fromstring(book.read(target))
            rows = []
            for row in root.findall('.//x:sheetData/x:row', NS):
                cells = {}
                for cell in row.findall('x:c', NS):
                    ref = cell.attrib.get('r', '')
                    letters = re.match(r'[A-Z]+', ref)
                    if not letters:
                        continue
                    col = 0
                    for letter in letters.group():
                        col = col * 26 + ord(letter) - 64
                    value_node = cell.find('x:v', NS)
                    if cell.attrib.get('t') == 'inlineStr':
                        val = ''.join(x.text or '' for x in cell.findall('.//x:t', NS))
                    elif value_node is None:
                        val = ''
                    elif cell.attrib.get('t') == 's':
                        val = strings[int(value_node.text)]
                    else:
                        val = value_node.text or ''
                    cells[col] = str(val).strip()
                if cells:
                    rows.append([cells.get(i, '') for i in range(1, max(cells) + 1)])
            sheets[name] = rows
        return sheets


def records(sheets, name, columns):
    if name not in sheets:
        raise CommandError('Thiếu sheet: ' + name)
    rows = sheets[name]
    header_index = next((i for i, row in enumerate(rows)
                         if all(c in row for c in columns)), None)
    if header_index is None:
        raise CommandError('Sai tiêu đề cột trong sheet: ' + name)
    header = rows[header_index]
    result = []
    for row in rows[header_index + 1:]:
        item = {col: (row[header.index(col)] if header.index(col) < len(row) else '')
                for col in columns}
        if any(item.values()):
            result.append(item)
    return result


def require_unique(rows, field, label):
    keys = [row[field] for row in rows]
    if not all(keys) or len(keys) != len(set(keys)):
        raise CommandError(f'{label}: thiếu hoặc trùng mã {field}')


class Command(BaseCommand):
    help = 'Xem trước hoặc đồng bộ danh mục databasee.xlsx, giữ nguyên tồn và chứng từ'

    def add_arguments(self, parser):
        parser.add_argument('--file', default='databasee.xlsx')
        parser.add_argument('--apply', action='store_true', help='Ghi thật; mặc định chỉ xem trước')

    def handle(self, *args, **opts):
        path = Path(opts['file'])
        if not path.is_file():
            raise CommandError(f'Không tìm thấy Excel: {path.resolve()}')
        try:
            sheets = read_xlsx(path)
        except Exception as exc:
            raise CommandError('Không đọc được XLSX: ' + str(exc)) from exc

        kho_rows = records(sheets, 'Kho (ERD)', ['kho_id (PK)', 'ten_kho', 'loai_kho'])
        khu_rows = records(sheets, 'KhuVuc (ERD)', ['khu_vuc_id (PK)', 'kho_id (FK)', 'ten_khu_vuc'])
        ke_rows = records(sheets, 'Ke (ERD)', ['ke_id (PK)', 'khu_vuc_id (FK)', 'ten_ke'])
        vt_rows = records(sheets, 'ViTriLuuTru (ERD)', ['vi_tri_id (PK)', 'ke_id (FK)', 'ten_vi_tri', 'ma_vi_tri'])
        hang_rows = records(sheets, 'Danh mục 22 mã hàng', ['hang_hoa_id (PK)', 'ma_hang', 'Nhóm hàng', 'Tên hàng', 'Màu sắc', 'Size', 'Đơn vị tính'])
        dt_rows = records(sheets, 'Đối tác', ['doi_tac_id (PK)', 'ma_doi_tac', 'ten_doi_tac', 'loai_doi_tac', 'so_dien_thoai', 'dia_chi', 'trang_thai'])
        pb_rows = records(sheets, 'Phân bổ theo vị trí', ['vi_tri_id', 'Mã hàng'])

        for rows, field, label in [
            (kho_rows, 'kho_id (PK)', 'Kho'),
            (khu_rows, 'khu_vuc_id (PK)', 'Khu vực'),
            (ke_rows, 'ke_id (PK)', 'Kệ'),
            (vt_rows, 'vi_tri_id (PK)', 'Vị trí'),
            (hang_rows, 'ma_hang', 'Hàng hóa'),
            (dt_rows, 'ma_doi_tac', 'Đối tác')
        ]:
            require_unique(rows, field, label)

        if tuple(map(len, [
            kho_rows, khu_rows, ke_rows, vt_rows,
            hang_rows, dt_rows, pb_rows
        ])) != (2, 6, 15, 30, 22, 6, 22):
            raise CommandError(
                'Số dòng khác cấu trúc đã duyệt: yêu cầu 2 kho, 6 khu, '
                '15 kệ, 30 vị trí, 22 hàng, 6 đối tác, 22 phân bổ'
            )

        valid_positions = {x['vi_tri_id (PK)'] for x in vt_rows}
        valid_goods = {x['ma_hang'] for x in hang_rows}
        if any(
            x['vi_tri_id'] not in valid_positions
            or x['Mã hàng'] not in valid_goods
            for x in pb_rows
        ):
            raise CommandError('Sheet Phân bổ theo vị trí có mã hàng/vị trí không tồn tại')

        if len({x['Mã hàng'] for x in pb_rows}) != 22:
            raise CommandError('Phân bổ không đủ 22 mã hàng duy nhất')

        counts = {'tạo': 0, 'cập nhật': 0, 'giữ nguyên': 0}

        def upsert(model, lookup, values, change_existing=True):
            obj, created = model.objects.get_or_create(**lookup, defaults=values)
            if created:
                counts['tạo'] += 1
            elif change_existing:
                dirty = []
                for field, val in values.items():
                    if getattr(obj, field) != val:
                        setattr(obj, field, val)
                        dirty.append(field)
                if dirty:
                    obj.save(update_fields=dirty)
                    counts['cập nhật'] += 1
                else:
                    counts['giữ nguyên'] += 1
            else:
                counts['giữ nguyên'] += 1
            return obj

        try:
            with transaction.atomic():
                kho_map = {}
                for r in kho_rows:
                    kind = (
                        'NVL' if r['kho_id (PK)'] == 'K-NVL'
                        else 'TP' if r['kho_id (PK)'] == 'K-TP'
                        else None
                    )
                    if not kind:
                        raise CommandError('Mã kho chưa được hỗ trợ: ' + r['kho_id (PK)'])

                    matches = list(Kho.objects.filter(loai_kho=kind))
                    if len(matches) > 1:
                        raise CommandError(
                            f'Có nhiều kho loại {kind}; không tự chọn kho để tránh sai liên kết'
                        )

                    kho = (
                        matches[0] if matches
                        else upsert(Kho, {'loai_kho': kind}, {'ten_kho': r['ten_kho']})
                    )
                    kho_map[r['kho_id (PK)']] = kho

                khu_map = {}
                for r in khu_rows:
                    kho = kho_map[r['kho_id (FK)']]
                    khu_map[r['khu_vuc_id (PK)']] = upsert(
                        KhuVuc,
                        {'kho': kho, 'ten_khu_vuc': r['ten_khu_vuc']},
                        {},
                        False
                    )

                ke_map = {}
                for r in ke_rows:
                    kv = khu_map[r['khu_vuc_id (FK)']]
                    ke_map[r['ke_id (PK)']] = upsert(
                        Ke,
                        {'khu_vuc': kv, 'ten_ke': r['ten_ke']},
                        {},
                        False
                    )

                vt_map = {}
                for r in vt_rows:
                    ke = ke_map[r['ke_id (FK)']]

                    # Mã duy nhất: VT-NVL-01-01 thay vì mã lặp T1-O1
                    code = r['vi_tri_id (PK)']

                    pos = ViTriLuuTru.objects.filter(ma_vi_tri=code).first()
                    if pos:
                        if pos.ke_id != ke.pk:
                            raise CommandError(
                                f'Vị trí {code} đang thuộc kệ khác; cần kiểm tra thủ công'
                            )
                        counts['giữ nguyên'] += 1
                    else:
                        pos = ViTriLuuTru.objects.filter(
                            ke=ke,
                            ten_vi_tri=r['ten_vi_tri']
                        ).first()

                        if pos:
                            # Giữ mã cũ để không ảnh hưởng các chứng từ đã liên kết.
                            counts['giữ nguyên'] += 1
                        else:
                            pos = upsert(
                                ViTriLuuTru,
                                {'ma_vi_tri': code},
                                {'ke': ke, 'ten_vi_tri': r['ten_vi_tri']}
                            )
                    vt_map[code] = pos

                for r in hang_rows:
                    code = r['ma_hang']

                    kind = (
                        'NVL' if code.startswith('NVL')
                        else 'TP' if code.startswith('TP')
                        else None
                    )
                    if not kind:
                        raise CommandError('Mã hàng không thuộc NVL/TP: ' + code)

                    nhom, _ = NhomHang.objects.get_or_create(
                        ten_nhom='Nguyên vật liệu' if kind == 'NVL' else 'Thành phẩm',
                        loai_hang=kind
                    )
                    dvt, _ = DonViTinh.objects.get_or_create(
                        ten_don_vi_tinh=r['Đơn vị tính']
                    )

                    old = HangHoa.objects.filter(
                        ma_hang=code
                    ).select_related('nhom_hang').first()

                    if old and old.nhom_hang.loai_hang != kind:
                        raise CommandError(
                            'Mã hàng đang thuộc loại kho khác: ' + code
                        )

                    values = {
                        'ten_hang': r['Tên hàng'],
                        'mau_sac': r['Màu sắc'],
                        'kich_co': '' if r['Size'] in ('—', '-', '') else r['Size'],
                        'don_vi_tinh': dvt
                    }
                    if not old:
                        values['nhom_hang'] = nhom

                    upsert(HangHoa, {'ma_hang': code}, values)

                for r in dt_rows:
                    kind = (
                        'XUONG' if 'Xưởng' in r['loai_doi_tac']
                        else 'NCC'
                    )
                    contact = (
                        f"SĐT: {r['so_dien_thoai'].strip()} | "
                        f"Địa chỉ: {r['dia_chi']}"
                    )

                    upsert(
                        DoiTac,
                        {'ma_doi_tac': r['ma_doi_tac']},
                        {
                            'ten_doi_tac': r['ten_doi_tac'],
                            'loai_doi_tac': kind,
                            'thong_tin_lien_he': contact,
                            'trang_thai': r['trang_thai'] == 'Đang sử dụng'
                        }
                    )

                self.stdout.write(
                    'Kết quả '
                    + ('GHI THẬT' if opts['apply'] else 'XEM TRƯỚC')
                    + ': ' + str(counts)
                )
                self.stdout.write(
                    'Đã kiểm tra 22 mã hàng có 22 vị trí phân bổ hợp lệ '
                    '(không tạo dòng tồn ảo).'
                )

                if not opts['apply']:
                    transaction.set_rollback(True)
                    self.stdout.write(
                        self.style.WARNING(
                            'Đã rollback: database KHÔNG thay đổi.'
                        )
                    )

        except (KeyError, ValueError) as exc:
            raise CommandError(
                'Excel có khóa liên kết hoặc dữ liệu không hợp lệ: ' + str(exc)
            ) from exc

        if opts['apply']:
            self.stdout.write(
                self.style.SUCCESS(
                    'Đồng bộ thành công. Không sửa số lượng tồn hoặc chứng từ.'
                )
            )