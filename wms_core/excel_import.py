"""Import original XONXEN workbook; prevalidate and only create opening balances for NEW SKUs."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import load_workbook
from .models import Kho,KhuVuc,Ke,ViTriLuuTru,NhomHang,DonViTinh,HangHoa,DoiTac,TonKho,NguongTonAnToan

REQUIRED={
 'NguyenVatLieu': {'ID Vải','Tên Vải','Màu sắc','Số lượng','ĐVT'},
 'ThanhPham': {'ID Thành Phẩm','Tên Thành Phẩm','Màu sắc','Size','Số lượng'},
 'NhaCungCap': {'ID NCC Vải','Tên NCC Vải'},
}

def import_workbook(upload,account):
    try:workbook=load_workbook(upload,read_only=True,data_only=True)
    except Exception as exc:raise ValidationError('Không mở được file Excel: '+str(exc))
    data={}; errors=[]
    try:
        for sheet_name,columns in REQUIRED.items():
            if sheet_name not in workbook.sheetnames:
                errors.append('Thiếu sheet '+sheet_name);continue
            rows=workbook[sheet_name].iter_rows(values_only=True)
            headers=next(rows,None)
            if not headers:
                errors.append(sheet_name+': sheet trống');continue
            header_map={str(v).strip():idx for idx,v in enumerate(headers) if v is not None}
            missing=columns-set(header_map)
            if missing:errors.append(sheet_name+': thiếu cột '+', '.join(sorted(missing)));continue
            records=[];seen=set()
            for row_number,row in enumerate(rows,2):
                if not any(v is not None and str(v).strip() for v in row):continue
                record={key:(row[idx] if idx<len(row) else None) for key,idx in header_map.items()}
                key=('ID Vải' if sheet_name=='NguyenVatLieu' else 'ID Thành Phẩm' if sheet_name=='ThanhPham' else 'ID NCC Vải')
                code=str(record.get(key) or '').strip()
                if not code:errors.append(f'{sheet_name} dòng {row_number}: thiếu mã');continue
                if code in seen:errors.append(f'{sheet_name} dòng {row_number}: mã trùng {code}');continue
                seen.add(code)
                if sheet_name!='NhaCungCap':
                    try:
                        qty=Decimal(str(record.get('Số lượng')))
                        if not qty.is_finite() or qty<0 or qty.as_tuple().exponent < -2:
                            raise InvalidOperation()
                        if qty>Decimal('999999999999.99'):raise InvalidOperation()
                        record['_qty']=qty
                    except (InvalidOperation,TypeError):errors.append(f'{sheet_name} dòng {row_number}: số lượng không hợp lệ')
                records.append(record)
            data[sheet_name]=records
    finally:workbook.close()
    if errors:raise ValidationError(errors[:20])
    # Opening stock cannot be imported without target warehouse locations.
    targets={}
    for kind in ('NVL','TP'):
        warehouse=Kho.objects.filter(loai_kho=kind).first()
        if not warehouse:raise ValidationError(f'Chưa cấu hình kho {kind}. Chạy seed_wms_demo hoặc tạo kho/vị trí trước.')
        position=ViTriLuuTru.objects.filter(ke__khu_vuc__kho=warehouse).order_by('id').first()
        if not position:raise ValidationError(f'Kho {warehouse} chưa có vị trí lưu trữ.')
        targets[kind]=(warehouse,position)
    result={'new_goods':0,'existing_goods':0,'new_partners':0,'opening_lines':0}
    with transaction.atomic():
        for row in data['NhaCungCap']:
            code=str(row['ID NCC Vải']).strip()
            name=str(row.get('Tên NCC Vải') or '').strip()
            if not name:raise ValidationError('Tên nhà cung cấp không được trống: '+code)
            _,created=DoiTac.objects.get_or_create(ma_doi_tac=code,defaults={
                'ten_doi_tac':name,'loai_doi_tac':'XUONG' if 'xưởng' in name.lower() else 'NCC',
                'thong_tin_lien_he':' | '.join(str(row.get(k)) for k in ('SĐT','Địa chỉ','Facebook','Website') if row.get(k))})
            result['new_partners']+=int(created)
        for kind,sheet in [('NVL','NguyenVatLieu'),('TP','ThanhPham')]:
            warehouse,position=targets[kind]
            group,_=NhomHang.objects.get_or_create(ten_nhom='Vải và nguyên phụ liệu' if kind=='NVL' else 'Thời trang thành phẩm',loai_hang=kind)
            for row in data[sheet]:
                code=str(row['ID Vải'] if kind=='NVL' else row['ID Thành Phẩm']).strip()
                name=str(row['Tên Vải'] if kind=='NVL' else row['Tên Thành Phẩm']).strip()
                if not name:raise ValidationError('Tên hàng không được trống: '+code)
                unit,_=DonViTinh.objects.get_or_create(ten_don_vi_tinh=str(row.get('ĐVT') or 'Mét' if kind=='NVL' else 'Cái').strip())
                obj,created=HangHoa.objects.get_or_create(ma_hang=code,defaults={
                    'ten_hang':name,'mau_sac':str(row.get('Màu sắc') or '').strip(),
                    'kich_co':str(row.get('Size') or '').strip() if kind=='TP' else '',
                    'nhom_hang':group,'don_vi_tinh':unit})
                if not created:
                    if obj.nhom_hang.loai_hang!=kind:raise ValidationError(f'Mã {code} đang thuộc nhóm kho khác')
                    result['existing_goods']+=1
                    continue # Never replace current inventory when re-importing Excel.
                result['new_goods']+=1
                TonKho.objects.create(hang_hoa=obj,vi_tri=position,so_luong_ton=row['_qty'])
                result['opening_lines']+=1
                NguongTonAnToan.objects.get_or_create(hang_hoa=obj,kho=warehouse,defaults={
                    'muc_ton_an_toan':(row['_qty']*Decimal('0.20')).quantize(Decimal('0.01')),
                    'nguoi_cap_nhat':account})
    return result


# ==========================================================
# NHAP TUNG DANH MUC EXCEL DOC LAP
# ==========================================================

def import_single_sheet(upload, account, category):
    """Nhập NVL, thành phẩm, đối tác và tồn đầu kỳ theo vị trí."""

    config = {
        'NVL': ('NguyenVatLieu', 'ID Vải', 'Tên Vải', 'K-NVL'),
        'TP': ('ThanhPham', 'ID Thành Phẩm', 'Tên Thành Phẩm', 'K-TP'),
        'NCC': ('NhaCungCap', 'ID NCC Vải', 'Tên NCC Vải', None),
    }

    if category not in config:
        raise ValidationError('Danh mục import không hợp lệ.')

    sheet_name, code_col, name_col, warehouse_code = config[category]

    def value(v):
        return '' if v is None else str(v).strip()

    def read_sheet(wb, name, required):
        if name not in wb.sheetnames:
            raise ValidationError(f'Thiếu sheet {name} trong file Excel.')

        ws = wb[name]
        ws.reset_dimensions()

        iterator = ws.iter_rows(values_only=True)
        header = next(iterator, None)

        if not header:
            raise ValidationError(f'Sheet {name} không có tiêu đề cột.')

        columns = [value(v) for v in header]
        nonempty = [c for c in columns if c]

        if len(set(nonempty)) != len(nonempty):
            raise ValidationError(f'Sheet {name} có tên cột bị trùng.')

        missing = set(required) - set(columns)

        if missing:
            raise ValidationError(
                f'Sheet {name} thiếu cột: {", ".join(sorted(missing))}'
            )

        result = []

        for number, raw in enumerate(iterator, start=2):
            if not any(value(x) for x in raw):
                continue

            row = {
                key: raw[index] if index < len(raw) else None
                for index, key in enumerate(columns)
                if key
            }
            row['_line'] = number
            result.append(row)

        return result

    result = {
        'new_goods': 0,
        'existing_goods': 0,
        'new_partners': 0,
        'existing_partners': 0,
        'opening_lines': 0,
    }

    try:
        wb = load_workbook(upload, read_only=True, data_only=True)
    except Exception as exc:
        raise ValidationError('Không đọc được file .xlsx: ' + str(exc))

    try:
        # ==========================================
        # NHÀ CUNG CẤP VÀ XƯỞNG GIA CÔNG
        # ==========================================
        if category == 'NCC':
            partner_rows = read_sheet(
                wb, sheet_name, [code_col, name_col]
            )

            if not partner_rows:
                raise ValidationError('Danh sách đối tác đang trống.')

            seen = set()
            prepared = []

            for row in partner_rows:
                code = value(row[code_col])
                name = value(row[name_col])

                if not code or not name or code in seen:
                    raise ValidationError(
                        f'Dòng {row["_line"]}: thiếu hoặc trùng mã/tên đối tác.'
                    )

                seen.add(code)

                raw_type = value(row.get('Loại đối tác')).casefold()

                if raw_type in ('xưởng gia công', 'xuong gia cong'):
                    partner_type = 'XUONG'
                elif raw_type in ('', 'nhà cung cấp', 'nha cung cap'):
                    partner_type = 'NCC'
                else:
                    raise ValidationError(
                        f'Dòng {row["_line"]}: loại đối tác không hợp lệ.'
                    )

                status = value(row.get('Trạng thái')).casefold()

                if status not in ('', 'hoạt động', 'ngừng hoạt động'):
                    raise ValidationError(
                        f'Dòng {row["_line"]}: trạng thái không hợp lệ.'
                    )

                phone = value(row.get('SĐT'))
                address = value(row.get('Địa chỉ'))

                contact = (
                    f'SĐT: {phone or "-"} | '
                    f'Địa chỉ: {address or "-"}'
                )

                prepared.append(
                    (
                        code,
                        name,
                        partner_type,
                        contact,
                        status != 'ngừng hoạt động',
                    )
                )

        # ==========================================
        # NGUYÊN VẬT LIỆU VÀ THÀNH PHẨM
        # ==========================================
        else:
            position_columns = [
                'Mã kho',
                'Tên kho',
                'Mã khu vực',
                'Tên khu vực',
                'Mã kệ',
                'Tên kệ',
                'Mã vị trí',
                'Tên vị trí',
            ]

            required_goods = (
                set(REQUIRED[sheet_name]) | set(position_columns)
            )

            goods_rows = read_sheet(
                wb, sheet_name, required_goods
            )

            position_rows = read_sheet(
                wb, 'ViTriKho', position_columns
            )

            if not goods_rows or not position_rows:
                raise ValidationError(
                    'File thiếu dữ liệu hàng hóa hoặc vị trí.'
                )

            locations = {}
            zones = {}
            racks = {}

            # Đọc toàn bộ vị trí, kể cả ô trống
            for row in position_rows:
                line = row['_line']

                p = {
                    key: value(row.get(key))
                    for key in position_columns
                }

                if any(not v for v in p.values()):
                    raise ValidationError(
                        f'ViTriKho dòng {line}: thiếu thông tin kho/kệ/ô.'
                    )

                if p['Mã kho'] != warehouse_code:
                    raise ValidationError(
                        f'ViTriKho dòng {line}: '
                        f'mã kho phải là {warehouse_code}.'
                    )

                code = p['Mã vị trí']

                if code in locations:
                    raise ValidationError(
                        f'ViTriKho: mã vị trí {code} bị trùng.'
                    )

                z_code = p['Mã khu vực']
                z_name = p['Tên khu vực']
                k_code = p['Mã kệ']
                k_name = p['Tên kệ']

                if z_code in zones and zones[z_code] != z_name:
                    raise ValidationError(
                        f'Mã khu vực {z_code} có hai tên khác nhau.'
                    )

                if k_code in racks and racks[k_code] != (z_code, k_name):
                    raise ValidationError(
                        f'Mã kệ {k_code} có thông tin không nhất quán.'
                    )

                zones[z_code] = z_name
                racks[k_code] = (z_code, k_name)
                locations[code] = p

            # Đọc hàng hóa và phân bổ số lượng vào từng ô
            items = {}

            for row in goods_rows:
                line = row['_line']

                code = value(row.get(code_col))
                name = value(row.get(name_col))
                pos_code = value(row.get('Mã vị trí'))

                if not code or not name or pos_code not in locations:
                    raise ValidationError(
                        f'Dòng {line}: thiếu mã/tên hàng hoặc '
                        'mã vị trí không có trong ViTriKho.'
                    )

                for col in position_columns:
                    if value(row.get(col)) != locations[pos_code][col]:
                        raise ValidationError(
                            f'Dòng {line}: cột {col} '
                            'không khớp sheet ViTriKho.'
                        )

                try:
                    qty = Decimal(value(row.get('Số lượng')))

                    if (
                        not qty.is_finite()
                        or qty < 0
                        or qty.as_tuple().exponent < -2
                        or qty > Decimal('999999999999.99')
                    ):
                        raise InvalidOperation

                except (InvalidOperation, TypeError, ValueError):
                    raise ValidationError(
                        f'Dòng {line}: số lượng tồn không hợp lệ.'
                    )

                meta = (
                    name,
                    value(row.get('Màu sắc')),
                    value(row.get('Size')) if category == 'TP' else '',
                    (
                        value(row.get('ĐVT')) or 'Mét'
                    ) if category == 'NVL' else 'Cái',
                )

                if code not in items:
                    items[code] = {
                        'meta': meta,
                        'quantities': {},
                    }

                if items[code]['meta'] != meta:
                    raise ValidationError(
                        f'Mã {code} có thông tin hàng hóa '
                        'khác nhau giữa các dòng.'
                    )

                if pos_code in items[code]['quantities']:
                    raise ValidationError(
                        f'Mã {code} bị lặp tại vị trí {pos_code}.'
                    )

                items[code]['quantities'][pos_code] = qty

    finally:
        wb.close()

    # ==========================================
    # GHI DỮ LIỆU VÀO DATABASE
    # ==========================================
    with transaction.atomic():

        if category == 'NCC':
            for code, name, kind, contact, active in prepared:
                partner, created = DoiTac.objects.get_or_create(
                    ma_doi_tac=code,
                    defaults={
                        'ten_doi_tac': name,
                        'loai_doi_tac': kind,
                        'thong_tin_lien_he': contact,
                        'trang_thai': active,
                    }
                )

                if not created and partner.loai_doi_tac != kind:
                    raise ValidationError(
                        f'Đối tác {code} đã tồn tại với loại khác.'
                    )

                if created:
                    result['new_partners'] += 1
                else:
                    result['existing_partners'] += 1

            return result

        # Xác định kho
        warehouses = list(
            Kho.objects.filter(loai_kho=category)
        )

        if len(warehouses) > 1:
            raise ValidationError(
                f'Có nhiều kho {category}; cần xử lý trước khi import.'
            )

        warehouse_name = next(iter(locations.values()))['Tên kho']

        if any(
            p['Tên kho'] != warehouse_name
            for p in locations.values()
        ):
            raise ValidationError(
                'Các dòng vị trí có tên kho không nhất quán.'
            )

        warehouse = (
            warehouses[0]
            if warehouses
            else Kho.objects.create(
                ten_kho=warehouse_name,
                loai_kho=category
            )
        )

        if warehouse.ten_kho != warehouse_name:
            warehouse.ten_kho = warehouse_name
            warehouse.save(update_fields=['ten_kho'])

        # Tạo khu vực, kệ và tất cả các ô lưu trữ
        position_objects = {}

        for code, p in locations.items():
            zone, _ = KhuVuc.objects.get_or_create(
                kho=warehouse,
                ten_khu_vuc=p['Tên khu vực']
            )

            rack, _ = Ke.objects.get_or_create(
                khu_vuc=zone,
                ten_ke=p['Tên kệ']
            )

            position, created = ViTriLuuTru.objects.get_or_create(
                ma_vi_tri=code,
                defaults={
                    'ke': rack,
                    'ten_vi_tri': p['Tên vị trí'],
                }
            )

            if (
                position.ke_id != rack.pk
                or position.ten_vi_tri != p['Tên vị trí']
            ):
                raise ValidationError(
                    f'Vị trí {code} đã có trong hệ thống '
                    'nhưng thuộc kệ/ô khác.'
                )

            position_objects[code] = position

        # Xác định nhóm hàng
        group_name = (
            'Vải và nguyên phụ liệu'
            if category == 'NVL'
            else 'Thời trang thành phẩm'
        )

        group, _ = NhomHang.objects.get_or_create(
            ten_nhom=group_name,
            loai_hang=category
        )

        # Tạo hàng và tồn kho theo đúng từng vị trí
        for sku, data in items.items():
            name, color, size, unit_name = data['meta']
            quantity_by_position = data['quantities']

            goods = HangHoa.objects.select_related(
                'nhom_hang'
            ).filter(ma_hang=sku).first()

            if goods:
                if (
                    goods.nhom_hang.loai_hang != category
                    or goods.ten_hang != name
                    or goods.mau_sac != color
                    or goods.kich_co != size
                ):
                    raise ValidationError(
                        f'Mã {sku} đã có thông tin khác Excel.'
                    )

                old_stock = {
                    x.vi_tri.ma_vi_tri: x.so_luong_ton
                    for x in TonKho.objects.filter(
                        hang_hoa=goods
                    ).select_related('vi_tri')
                }

                if (
                    old_stock
                    and old_stock != quantity_by_position
                ):
                    raise ValidationError(
                        f'Mã {sku} đã có tồn kho khác Excel. '
                        'Không ghi đè tồn cũ; hãy sao lưu và '
                        'xử lý dữ liệu demo trước khi import.'
                    )

                result['existing_goods'] += 1

                if old_stock:
                    continue

            else:
                unit, _ = DonViTinh.objects.get_or_create(
                    ten_don_vi_tinh=unit_name
                )

                goods = HangHoa.objects.create(
                    ma_hang=sku,
                    ten_hang=name,
                    mau_sac=color,
                    kich_co=size,
                    nhom_hang=group,
                    don_vi_tinh=unit
                )

                result['new_goods'] += 1

            for pos_code, qty in quantity_by_position.items():
                TonKho.objects.create(
                    hang_hoa=goods,
                    vi_tri=position_objects[pos_code],
                    so_luong_ton=qty
                )

                result['opening_lines'] += 1

            total = sum(
                quantity_by_position.values(),
                Decimal('0')
            )

            NguongTonAnToan.objects.get_or_create(
                hang_hoa=goods,
                kho=warehouse,
                defaults={
                    'muc_ton_an_toan': (
                        total * Decimal('0.20')
                    ).quantize(Decimal('0.01')),
                    'nguoi_cap_nhat': account,
                }
            )

    return result
