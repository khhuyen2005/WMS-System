import json
from pathlib import Path
from decimal import Decimal
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth.models import User
from django.db import transaction
from wms_core.models import *

class Command(BaseCommand):
    help='Nhập Excel mẫu (đã trích xuất) và thiết lập vị trí giả lập phục vụ demo, chỉ tạo dữ liệu nếu chưa có.'
    @transaction.atomic
    def handle(self,*args,**kwargs):
        user=User.objects.filter(is_superuser=True).first()
        if not user:raise CommandError('Cần chạy python manage.py createsuperuser trước.')
        manager,_=VaiTro.objects.get_or_create(ten_vai_tro='Quản lý kho')
        VaiTro.objects.get_or_create(ten_vai_tro='Nhân viên kho NVL')
        VaiTro.objects.get_or_create(ten_vai_tro='Nhân viên kho thành phẩm')
        account,_=TaiKhoan.objects.get_or_create(user=user,defaults={'ho_ten':user.username,'vai_tro':manager})
        nvl,_=Kho.objects.get_or_create(ten_kho='Kho nguyên vật liệu XONXEN (demo)',defaults={'loai_kho':'NVL'})
        tp,_=Kho.objects.get_or_create(ten_kho='Kho thành phẩm XONXEN (demo)',defaults={'loai_kho':'TP'})
        locations={}
        for warehouse,zone_name,code in [(nvl,'Khu vải và phụ liệu','NVL'),(tp,'Khu thời trang thành phẩm','TP')]:
            zone,_=KhuVuc.objects.get_or_create(kho=warehouse,ten_khu_vuc=zone_name)
            locs=[]
            for shelf in range(1,3):
                rack,_=Ke.objects.get_or_create(khu_vuc=zone,ten_ke=f'Kệ {shelf:02d}')
                for cell in range(1,4):
                    code_pos=f'{code}-K{shelf:02d}-O{cell:02d}'
                    pos,_=ViTriLuuTru.objects.get_or_create(ma_vi_tri=code_pos,defaults={'ke':rack,'ten_vi_tri':f'Ô {cell:02d}'})
                    locs.append(pos)
            locations[code]=locs
        payload=json.loads((Path(__file__).resolve().parents[2]/'seed_data.json').read_text(encoding='utf-8'))
        for row in payload['NhaCungCap']:
            code=str(row['ID NCC Vải'])
            name=row['Tên NCC Vải']
            typ='XUONG' if 'xưởng' in name.lower() else 'NCC'
            contact=' | '.join(str(row[k]) for k in ('SĐT','Địa chỉ','Facebook','Website') if row.get(k))
            DoiTac.objects.get_or_create(ma_doi_tac=code,defaults={'ten_doi_tac':name,'loai_doi_tac':typ,'thong_tin_lien_he':contact})
        for ix,(code,name) in enumerate([('CN001','XONXEN SHOP - 299 Phan Châu Trinh'),('CN002','XONXEN SHOP - 23 Lê Duẩn')]):
            DoiTac.objects.get_or_create(ma_doi_tac=code,defaults={'ten_doi_tac':name,'loai_doi_tac':'CHINHANH'})
        group_nvl,_=NhomHang.objects.get_or_create(ten_nhom='Vải và nguyên phụ liệu',loai_hang='NVL')
        group_tp,_=NhomHang.objects.get_or_create(ten_nhom='Thời trang thành phẩm',loai_hang='TP')
        for kind,rows,wh,group in [('NVL',payload['NguyenVatLieu'],nvl,group_nvl),('TP',payload['ThanhPham'],tp,group_tp)]:
            for i,row in enumerate(rows):
                if kind=='NVL':
                    code=row['ID Vải'];name=row['Tên Vải'];color=row.get('Màu sắc') or '';size='';unit=row.get('ĐVT') or 'Mét';qty=row.get('Số lượng') or 0
                else:
                    code=row['ID Thành Phẩm'];name=row['Tên Thành Phẩm'];color=row.get('Màu sắc') or '';size=row.get('Size') or '';unit='Cái';qty=row.get('Số lượng') or 0
                dvt,_=DonViTinh.objects.get_or_create(ten_don_vi_tinh=unit)
                good,_=HangHoa.objects.get_or_create(ma_hang=code,defaults={'ten_hang':name,'mau_sac':color,'kich_co':size,'don_vi_tinh':dvt,'nhom_hang':group})
                location=locations[kind][i%len(locations[kind])]
                # Opening balance is imported once; re-running this command never overwrites transaction history.
                TonKho.objects.get_or_create(hang_hoa=good,vi_tri=location,defaults={'so_luong_ton':Decimal(str(qty))})
                threshold=Decimal(str(qty))*Decimal('0.20')
                NguongTonAnToan.objects.get_or_create(hang_hoa=good,kho=wh,defaults={'muc_ton_an_toan':threshold.quantize(Decimal('0.01')),'nguoi_cap_nhat':account})
        self.stdout.write(self.style.SUCCESS('Đã khởi tạo 2 kho, 12 vị trí, dữ liệu Excel và ngưỡng tồn demo (20% tồn đầu kỳ).'))
