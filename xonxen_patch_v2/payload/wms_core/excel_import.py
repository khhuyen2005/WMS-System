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
