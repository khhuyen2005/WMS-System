"""Regression tests for critical WMS business rules. Run: python manage.py test wms_core"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from .models import (Kho,KhuVuc,Ke,ViTriLuuTru,NhomHang,DonViTinh,HangHoa,DoiTac,VaiTro,TaiKhoan,
                     PhieuNhap,PhieuXuat,ChiTietPhieuNhap,ChiTietPhieuXuat,TonKho,
                     YeuCauXuLyPhieu,NhatKyGiaoDich)
from .services import approve_receipt,approve_cancellation

class CoreBusinessRulesTests(TestCase):
    def setUp(self):
        self.manager_user=User.objects.create_user('manager',password='test-password-please-change')
        self.staff_user=User.objects.create_user('staff',password='test-password-please-change')
        manager=VaiTro.objects.create(ten_vai_tro='Quản lý kho')
        staff=VaiTro.objects.create(ten_vai_tro='Nhân viên kho NVL')
        self.manager=TaiKhoan.objects.create(user=self.manager_user,vai_tro=manager,ho_ten='Manager')
        self.staff=TaiKhoan.objects.create(user=self.staff_user,vai_tro=staff,ho_ten='Staff')
        self.warehouse=Kho.objects.create(ten_kho='Kho thử',loai_kho='NVL')
        zone=KhuVuc.objects.create(kho=self.warehouse,ten_khu_vuc='Khu A')
        shelf=Ke.objects.create(khu_vuc=zone,ten_ke='Kệ A')
        self.position=ViTriLuuTru.objects.create(ke=shelf,ma_vi_tri='TEST-A-01',ten_vi_tri='Ô 1')
        unit=DonViTinh.objects.create(ten_don_vi_tinh='Mét')
        group=NhomHang.objects.create(ten_nhom='Vải',loai_hang='NVL')
        self.goods=HangHoa.objects.create(ma_hang='TEST-NVL-001',ten_hang='Vải thử',nhom_hang=group,don_vi_tinh=unit)
        self.supplier=DoiTac.objects.create(ma_doi_tac='TEST-NCC-001',ten_doi_tac='NCC',loai_doi_tac='NCC')
        self.workshop=DoiTac.objects.create(ma_doi_tac='TEST-XUONG-001',ten_doi_tac='Xưởng',loai_doi_tac='XUONG')
    def make_receipt(self,qty='10'):
        doc=PhieuNhap.objects.create(kho=self.warehouse,doi_tac=self.supplier,nguoi_lap=self.staff,
                                      ma_phieu_nhap='PN-TEST-001',trang_thai='cho_duyet')
        ChiTietPhieuNhap.objects.create(phieu_nhap=doc,hang_hoa=self.goods,vi_tri=self.position,so_luong_nhap=Decimal(qty))
        return doc
    def make_issue(self,qty='2'):
        doc=PhieuXuat.objects.create(kho=self.warehouse,doi_tac=self.workshop,nguoi_lap=self.staff,
                                     ma_phieu_xuat='PX-TEST-001',trang_thai='cho_duyet')
        ChiTietPhieuXuat.objects.create(phieu_xuat=doc,hang_hoa=self.goods,vi_tri=self.position,so_luong_xuat=Decimal(qty))
        return doc
    def test_receipt_only_credited_after_approval_and_cannot_approve_twice(self):
        receipt=self.make_receipt()
        self.assertEqual(TonKho.objects.count(),0)
        with self.assertRaises(PermissionDenied):approve_receipt(receipt.pk,self.staff_user,'nhap')
        approve_receipt(receipt.pk,self.manager_user,'nhap')
        self.assertEqual(TonKho.objects.get().so_luong_ton,Decimal('10'))
        with self.assertRaises(ValidationError):approve_receipt(receipt.pk,self.manager_user,'nhap')
        self.assertEqual(TonKho.objects.get().so_luong_ton,Decimal('10'))
    def test_cannot_issue_beyond_available_stock(self):
        self.make_receipt();approve_receipt(PhieuNhap.objects.get().pk,self.manager_user,'nhap')
        issue=self.make_issue('11')
        with self.assertRaises(ValidationError):approve_receipt(issue.pk,self.manager_user,'xuat')
        self.assertEqual(TonKho.objects.get().so_luong_ton,Decimal('10'))
    def test_cancel_receipt_requires_stock_and_audits(self):
        receipt=self.make_receipt();approve_receipt(receipt.pk,self.manager_user,'nhap')
        issue=self.make_issue('8');approve_receipt(issue.pk,self.manager_user,'xuat')
        req=YeuCauXuLyPhieu.objects.create(phieu_nhap=receipt,nguoi_yeu_cau=self.staff,loai_yeu_cau='huy',ly_do='Đề nghị hủy')
        with self.assertRaises(ValidationError):approve_cancellation(req.pk,self.manager_user)
        self.assertEqual(TonKho.objects.get().so_luong_ton,Decimal('2'))
        # Cancel outgoing transaction first: stock can now be restored and receipt reversed.
        req_issue=YeuCauXuLyPhieu.objects.create(phieu_xuat=issue,nguoi_yeu_cau=self.staff,loai_yeu_cau='huy',ly_do='Hủy xuất')
        approve_cancellation(req_issue.pk,self.manager_user)
        approve_cancellation(req.pk,self.manager_user)
        self.assertEqual(TonKho.objects.get().so_luong_ton,Decimal('0'))
        self.assertTrue(NhatKyGiaoDich.objects.filter(hanh_dong='HOAN_TAC').exists())
        with self.assertRaises(ValidationError):approve_cancellation(req.pk,self.manager_user)

class ExcelAndAccessTests(TestCase):
    def setUp(self):
        self.manager=User.objects.create_user('chief',password='long-test-only-password')
        self.employee=User.objects.create_user('worker',password='long-test-only-password')
        lead=VaiTro.objects.create(ten_vai_tro='Quản lý kho')
        staff=VaiTro.objects.create(ten_vai_tro='Nhân viên kho NVL')
        self.wms_manager=TaiKhoan.objects.create(user=self.manager,vai_tro=lead,ho_ten='Quản lý')
        TaiKhoan.objects.create(user=self.employee,vai_tro=staff,ho_ten='Nhân viên')
        for kind in ('NVL','TP'):
            wh=Kho.objects.create(ten_kho=f'Kho {kind}',loai_kho=kind)
            zone=KhuVuc.objects.create(kho=wh,ten_khu_vuc='Khu 1')
            shelf=Ke.objects.create(khu_vuc=zone,ten_ke='Kệ 1')
            ViTriLuuTru.objects.create(ke=shelf,ma_vi_tri=f'{kind}-TEST-01',ten_vi_tri='Ô 1')
    def test_staff_cannot_import_excel(self):
        self.client.force_login(self.employee)
        response=self.client.get('/wms/nhap-excel/')
        self.assertEqual(response.status_code,403)
    def test_import_is_idempotent_for_existing_items(self):
        from io import BytesIO
        from openpyxl import Workbook
        from .excel_import import import_workbook
        wb=Workbook()
        a=wb.active;a.title='NguyenVatLieu';a.append(['ID Vải','Tên Vải','Màu sắc','Số lượng','ĐVT']);a.append(['NEW-001','Vải thử','Đỏ',Decimal('10'),'Mét'])
        b=wb.create_sheet('ThanhPham');b.append(['ID Thành Phẩm','Tên Thành Phẩm','Màu sắc','Size','Số lượng']);b.append(['NEW-TP-001','Áo thử','Xanh','M',7])
        c=wb.create_sheet('NhaCungCap');c.append(['ID NCC Vải','Tên NCC Vải']);c.append(['NCC-TEST-01','Nhà cung cấp thử'])
        stream=BytesIO();wb.save(stream);stream.seek(0)
        first=import_workbook(stream,self.wms_manager)
        self.assertEqual(first['new_goods'],2)
        self.assertEqual(TonKho.objects.count(),2)
        stream.seek(0)
        second=import_workbook(stream,self.wms_manager)
        self.assertEqual(second['new_goods'],0)
        self.assertEqual(second['existing_goods'],2)
        self.assertEqual(TonKho.objects.count(),2)
