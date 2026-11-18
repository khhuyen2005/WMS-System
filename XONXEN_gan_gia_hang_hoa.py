# Chay sau khi da them cot don_gia va migrate:
# python manage.py shell -c "exec(open('XONXEN_gan_gia_hang_hoa.py', encoding='utf-8').read())"
# Gia minh hoa cho he thong WMS XONXEN SHOP, khong phai gia giao dich thuc te.
# Chinh sua don gia danh muc theo ma SKU, khong thay doi ton kho hay phieu nhap/xuat.

from decimal import Decimal
from django.db import transaction
from wms_core.models import HangHoa

GIA_THEO_SKU = {
    # Nguyen vat lieu: VND/met, VND/cuon, VND/cai hoac VND/hop theo DVT san co.
    'NVL001': 58000,   # Vai thun cotton
    'NVL002': 65000,   # Vai hoa nhi
    'NVL003': 79000,   # Vai kaki
    'NVL004': 92000,   # Vai denim
    'NVL005': 115000,  # Vai lua
    'NVL006': 52000,   # Vai voan
    'NVL007': 98000,   # Vai len det kim
    'NVL008': 8000,    # Chi may trang
    'NVL009': 8000,    # Chi may den
    'NVL010': 6000,    # Khoa keo
    'NVL011': 1200,    # Nut ao
    'NVL012': 85000,   # Muc in vai
    # Thanh pham: VND/san pham.
    'TP001': 149000,   # Ao thun Baby Tee - S
    'TP002': 149000,   # Ao thun Baby Tee - M
    'TP003': 269000,   # Dam hoa nhi vintage
    'TP004': 219000,   # Chan vay chu A - S
    'TP005': 219000,   # Chan vay chu A - M
    'TP006': 329000,   # Quan Jean ong rong - S
    'TP007': 329000,   # Quan Jean ong rong - M
    'TP008': 299000,   # Ao so mi lua
    'TP009': 199000,   # Ao tre vai voan beo
    'TP010': 279000,   # Ao khoac Cardigan
}

# Tu dong ngan chay sai thu tu buoc.
HangHoa._meta.get_field('don_gia')

so_cap_nhat = 0
khong_tim_thay = []
with transaction.atomic():
    for ma_hang, gia in GIA_THEO_SKU.items():
        so_dong = HangHoa.objects.filter(ma_hang=ma_hang).update(
            don_gia=Decimal(gia)
        )
        if so_dong:
            so_cap_nhat += so_dong
        else:
            khong_tim_thay.append(ma_hang)

print(f'Da gan gia cho {so_cap_nhat}/{len(GIA_THEO_SKU)} ma hang.')
if khong_tim_thay:
    print('Ma SKU khong ton tai tren database:', ', '.join(khong_tim_thay))
print('Da giu nguyen ton kho va cac phieu nhap/xuat.')
