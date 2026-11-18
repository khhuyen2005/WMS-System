
import re
import unicodedata
from collections import defaultdict

from django.db import transaction
from django.db.models import Sum

from wms_core.models import HangHoa, Ke, TonKho


def normalize(value):
    value = str(value or '').lower().replace('đ', 'd')
    value = unicodedata.normalize('NFD', value)
    value = ''.join(
        c for c in value
        if unicodedata.category(c) != 'Mn'
    )
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', value)).strip()


# Tu khoa san pham -> Tu khoa ten ke
RULES = [
    (['chi may'], ['chi may']),
    (['khoa', 'nut', 'khuy'], ['khoa', 'nut']),
    (['vai hoa'], ['vai hoa']),
    (['kaki', 'denim'], ['kaki', 'denim']),
    (['vai len'], ['vai len']),
    (['lua', 'voan', 'gam'], ['lua', 'voan']),
    (['vai thun', 'thun cotton'], ['vai thun']),
    (['muc in'], ['muc in']),
    (['cardigan'], ['cardigan']),
    (['so mi'], ['so mi']),
]


def rack_from_name(item, racks):
    name = normalize(item.ten_hang)

    for product_words, rack_words in RULES:
        if not any(word in name for word in product_words):
            continue

        matched = [
            rack for rack in racks
            if any(
                word in normalize(rack.ten_ke)
                for word in rack_words
            )
        ]

        if len(matched) == 1:
            return matched[0]

    return None


# Lay danh sach ke theo loai kho
racks_by_kind = {
    'NVL': list(
        Ke.objects.filter(
            khu_vuc__kho__loai_kho='NVL'
        ).select_related('khu_vuc__kho')
    ),
    'TP': list(
        Ke.objects.filter(
            khu_vuc__kho__loai_kho='TP'
        ).select_related('khu_vuc__kho')
    ),
}

# Tong ton cua tung hang hoa tai tung ke
stock_by_good = defaultdict(list)

stock_data = (
    TonKho.objects.filter(so_luong_ton__gt=0)
    .values('hang_hoa_id', 'vi_tri__ke_id')
    .annotate(total=Sum('so_luong_ton'))
)

for row in stock_data:
    stock_by_good[row['hang_hoa_id']].append(
        (row['vi_tri__ke_id'], row['total'])
    )


updated = []
kept = []
unmatched = []

with transaction.atomic():

    for item in HangHoa.objects.select_related('nhom_hang', 'ke_mac_dinh'):

        kind = item.nhom_hang.loai_hang
        racks = racks_by_kind.get(kind, [])
        valid_rack_ids = {rack.pk for rack in racks}

        # Giu nguyen ke da gan dung loai kho
        if item.ke_mac_dinh_id in valid_rack_ids:
            kept.append(item.ma_hang)
            continue

        chosen = None

        # 1. Uu tien ke dang chua ton thuc te
        existing_stock = [
            (rack_id, quantity)
            for rack_id, quantity in stock_by_good.get(item.pk, [])
            if rack_id in valid_rack_ids
        ]

        if existing_stock:
            existing_stock.sort(
                key=lambda pair: pair[1],
                reverse=True
            )

            # Neu ke co ton lon nhat la duy nhat
            if (
                len(existing_stock) == 1
                or existing_stock[0][1] > existing_stock[1][1]
            ):
                chosen = next(
                    rack for rack in racks
                    if rack.pk == existing_stock[0][0]
                )

            # Neu dong hang co ton bang nhau o nhieu ke
            # thi uu tien ke phu hop ten san pham
            else:
                name_match = rack_from_name(item, racks)
                if name_match and any(
                    rack_id == name_match.pk
                    for rack_id, _ in existing_stock
                ):
                    chosen = name_match

        # 2. Hang chua co ton: thu khop ten san pham
        else:
            chosen = rack_from_name(item, racks)

        if chosen is None:
            unmatched.append(
                f'{item.ma_hang} - {item.ten_hang} ({kind})'
            )
            continue

        HangHoa.objects.filter(pk=item.pk).update(
            ke_mac_dinh=chosen
        )

        updated.append(
            f'{item.ma_hang} - {item.ten_hang} -> {chosen.ten_ke}'
        )


print('\n=== KET QUA GAN KE ===')

print('\nDA GAN MOI:', len(updated))
for row in updated:
    print(' +', row)

print('\nDA CO KE HOP LE:', len(kept))

print('\nCHUA XAC DINH DUOC KE:', len(unmatched))
for row in unmatched:
    print(' !', row)

print(
    '\nTONG HANG HOA:',
    HangHoa.objects.count()
)

print(
    'TONG HANG DA GAN KE:',
    HangHoa.objects.filter(
        ke_mac_dinh__isnull=False
    ).count()
)
