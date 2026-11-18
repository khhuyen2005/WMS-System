from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q

class Kho(models.Model):
    ten_kho = models.CharField(max_length=150)
    loai_kho = models.CharField(max_length=20, choices=[('NVL','Nguyên vật liệu'),('TP','Thành phẩm')])
    def __str__(self): return self.ten_kho

class KhuVuc(models.Model):
    kho = models.ForeignKey(Kho,on_delete=models.PROTECT)
    ten_khu_vuc = models.CharField(max_length=120)
    class Meta: constraints=[models.UniqueConstraint(fields=['kho','ten_khu_vuc'],name='unique_khu_vuc')]
    def __str__(self): return f'{self.kho} / {self.ten_khu_vuc}'

class Ke(models.Model):
    khu_vuc = models.ForeignKey(KhuVuc,on_delete=models.PROTECT)
    ten_ke = models.CharField(max_length=100)
    class Meta: constraints=[models.UniqueConstraint(fields=['khu_vuc','ten_ke'],name='unique_ke')]
    def __str__(self): return f'{self.khu_vuc} / {self.ten_ke}'

class ViTriLuuTru(models.Model):
    ke = models.ForeignKey(Ke,on_delete=models.PROTECT)
    ma_vi_tri = models.CharField(max_length=40,unique=True)
    ten_vi_tri = models.CharField(max_length=120)
    @property
    def kho(self): return self.ke.khu_vuc.kho
    def __str__(self): return self.ma_vi_tri

class NhomHang(models.Model):
    ten_nhom = models.CharField(max_length=100)
    loai_hang = models.CharField(max_length=20,choices=[('NVL','Nguyên vật liệu'),('TP','Thành phẩm')])
    def __str__(self): return self.ten_nhom

class DonViTinh(models.Model):
    ten_don_vi_tinh = models.CharField(max_length=30,unique=True)
    def __str__(self): return self.ten_don_vi_tinh

class HangHoa(models.Model):
    nhom_hang = models.ForeignKey(NhomHang,on_delete=models.PROTECT)
    don_vi_tinh = models.ForeignKey(DonViTinh,on_delete=models.PROTECT)
    ma_hang = models.CharField(max_length=40,unique=True)
    ten_hang = models.CharField(max_length=220)
    mau_ma = models.CharField(max_length=100,blank=True)
    mau_sac = models.CharField(max_length=80,blank=True)
    kich_co = models.CharField(max_length=30,blank=True)
    trang_thai = models.CharField(max_length=20,default='hoat_dong',choices=[('hoat_dong','Hoạt động'),('ngung','Ngừng')])
    def __str__(self): return f'{self.ma_hang} - {self.ten_hang}'

class DoiTac(models.Model):
    ma_doi_tac = models.CharField(max_length=40,unique=True)
    ten_doi_tac = models.CharField(max_length=220)
    loai_doi_tac = models.CharField(max_length=30, choices=[('NCC','Nhà cung cấp'),('XUONG','Xưởng gia công'),('CHINHANH','Chi nhánh nhận hàng')])
    thong_tin_lien_he = models.TextField(blank=True)
    trang_thai = models.BooleanField(default=True)
    def __str__(self): return self.ten_doi_tac

class VaiTro(models.Model):
    ten_vai_tro = models.CharField(max_length=100,unique=True)
    def __str__(self): return self.ten_vai_tro

class Quyen(models.Model):
    ma_quyen = models.CharField(max_length=80,unique=True)
    ten_quyen = models.CharField(max_length=160)
    def __str__(self): return self.ma_quyen

class VaiTroQuyen(models.Model):
    vai_tro = models.ForeignKey(VaiTro,on_delete=models.CASCADE)
    quyen = models.ForeignKey(Quyen,on_delete=models.CASCADE)
    class Meta: constraints=[models.UniqueConstraint(fields=['vai_tro','quyen'],name='unique_vai_tro_quyen')]

class TaiKhoan(models.Model):
    # Password hashes are managed by Django's built-in User table (never plaintext).
    user = models.OneToOneField(User,on_delete=models.PROTECT)
    vai_tro = models.ForeignKey(VaiTro,on_delete=models.PROTECT)
    ho_ten = models.CharField(max_length=150)
    trang_thai = models.BooleanField(default=True)
    @property
    def ten_dang_nhap(self): return self.user.username
    def __str__(self): return self.ho_ten

STATUS=[('nhap','Nháp'),('cho_duyet','Chờ duyệt'),('da_duyet','Đã duyệt'),('da_huy','Đã hủy')]
class PhieuNhap(models.Model):
    kho = models.ForeignKey(Kho,on_delete=models.PROTECT)
    doi_tac = models.ForeignKey(DoiTac,on_delete=models.PROTECT)
    nguoi_lap = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,related_name='phieu_nhap_lap')
    nguoi_phe_duyet = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True,related_name='phieu_nhap_duyet')
    ma_phieu_nhap = models.CharField(max_length=50,unique=True)
    thoi_gian_lap = models.DateTimeField(auto_now_add=True)
    thoi_gian_phe_duyet = models.DateTimeField(null=True,blank=True)
    trang_thai = models.CharField(max_length=20,choices=STATUS,default='nhap')
    ghi_chu = models.TextField(blank=True)
    def __str__(self): return self.ma_phieu_nhap

class PhieuXuat(models.Model):
    kho = models.ForeignKey(Kho,on_delete=models.PROTECT)
    doi_tac = models.ForeignKey(DoiTac,on_delete=models.PROTECT)
    nguoi_lap = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,related_name='phieu_xuat_lap')
    nguoi_phe_duyet = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True,related_name='phieu_xuat_duyet')
    ma_phieu_xuat = models.CharField(max_length=50,unique=True)
    thoi_gian_lap = models.DateTimeField(auto_now_add=True)
    thoi_gian_phe_duyet = models.DateTimeField(null=True,blank=True)
    trang_thai = models.CharField(max_length=20,choices=STATUS,default='nhap')
    ghi_chu = models.TextField(blank=True)
    def __str__(self): return self.ma_phieu_xuat

class ChiTietPhieuNhap(models.Model):
    phieu_nhap = models.ForeignKey(PhieuNhap,on_delete=models.PROTECT,related_name='chi_tiet')
    hang_hoa = models.ForeignKey(HangHoa,on_delete=models.PROTECT)
    vi_tri = models.ForeignKey(ViTriLuuTru,on_delete=models.PROTECT)
    so_luong_nhap = models.DecimalField(max_digits=14,decimal_places=2)
    def clean(self):
        if self.so_luong_nhap is not None and self.so_luong_nhap <= 0: raise ValidationError('Số lượng nhập phải > 0')
        if self.vi_tri_id and self.phieu_nhap_id and self.vi_tri.kho.id != self.phieu_nhap.kho_id: raise ValidationError('Vị trí không thuộc kho trên phiếu')
    def __str__(self): return f'{self.phieu_nhap} / {self.hang_hoa.ma_hang}'

class ChiTietPhieuXuat(models.Model):
    phieu_xuat = models.ForeignKey(PhieuXuat,on_delete=models.PROTECT,related_name='chi_tiet')
    hang_hoa = models.ForeignKey(HangHoa,on_delete=models.PROTECT)
    vi_tri = models.ForeignKey(ViTriLuuTru,on_delete=models.PROTECT)
    so_luong_xuat = models.DecimalField(max_digits=14,decimal_places=2)
    def clean(self):
        if self.so_luong_xuat is not None and self.so_luong_xuat <= 0: raise ValidationError('Số lượng xuất phải > 0')
        if self.vi_tri_id and self.phieu_xuat_id and self.vi_tri.kho.id != self.phieu_xuat.kho_id: raise ValidationError('Vị trí không thuộc kho trên phiếu')
    def __str__(self): return f'{self.phieu_xuat} / {self.hang_hoa.ma_hang}'

class YeuCauXuLyPhieu(models.Model):
    phieu_nhap = models.ForeignKey(PhieuNhap,on_delete=models.PROTECT,null=True,blank=True)
    phieu_xuat = models.ForeignKey(PhieuXuat,on_delete=models.PROTECT,null=True,blank=True)
    nguoi_yeu_cau = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,related_name='xu_ly_yeu_cau')
    nguoi_phe_duyet = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True,related_name='xu_ly_phe_duyet')
    loai_yeu_cau = models.CharField(max_length=20,choices=[('huy','Hủy phiếu'),('dieu_chinh','Điều chỉnh')])
    ly_do = models.TextField()
    noi_dung_de_nghi = models.TextField(blank=True)
    noi_dung_xu_ly = models.TextField(blank=True)
    thoi_gian_yeu_cau = models.DateTimeField(auto_now_add=True)
    thoi_gian_phe_duyet = models.DateTimeField(null=True,blank=True)
    trang_thai = models.CharField(max_length=20,default='cho_duyet',choices=[('cho_duyet','Chờ duyệt'),('da_duyet','Đã duyệt'),('tu_choi','Từ chối')])
    def clean(self):
        if bool(self.phieu_nhap_id) == bool(self.phieu_xuat_id): raise ValidationError('Chỉ chọn một trong hai loại phiếu')

class ChiTietYeuCauXuLyPhieu(models.Model):
    yeu_cau = models.ForeignKey(YeuCauXuLyPhieu,on_delete=models.PROTECT,related_name='chi_tiet')
    chi_tiet_phieu_nhap = models.ForeignKey(ChiTietPhieuNhap,on_delete=models.PROTECT,null=True,blank=True)
    chi_tiet_phieu_xuat = models.ForeignKey(ChiTietPhieuXuat,on_delete=models.PROTECT,null=True,blank=True)
    so_luong_truoc = models.DecimalField(max_digits=14,decimal_places=2)
    so_luong_de_nghi = models.DecimalField(max_digits=14,decimal_places=2)
    ly_do_chi_tiet = models.TextField(blank=True)
    def clean(self):
        if bool(self.chi_tiet_phieu_nhap_id) == bool(self.chi_tiet_phieu_xuat_id): raise ValidationError('Chọn đúng một dòng phiếu')

class TonKho(models.Model):
    hang_hoa = models.ForeignKey(HangHoa,on_delete=models.PROTECT)
    vi_tri = models.ForeignKey(ViTriLuuTru,on_delete=models.PROTECT)
    so_luong_ton = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    thoi_gian_cap_nhat = models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['hang_hoa','vi_tri'],name='unique_ton_kho_vi_tri'),models.CheckConstraint(condition=Q(so_luong_ton__gte=0),name='ton_kho_khong_am')]
    def __str__(self): return f'{self.hang_hoa.ma_hang} @ {self.vi_tri}'

class NguongTonAnToan(models.Model):
    hang_hoa = models.ForeignKey(HangHoa,on_delete=models.PROTECT)
    kho = models.ForeignKey(Kho,on_delete=models.PROTECT)
    nguoi_cap_nhat = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True)
    muc_ton_an_toan = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    thoi_gian_cap_nhat = models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['hang_hoa','kho'],name='unique_nguong_theo_kho')]

class DotKiemKe(models.Model):
    kho = models.ForeignKey(Kho,on_delete=models.PROTECT)
    nguoi_lap = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT)
    ma_dot = models.CharField(max_length=50,unique=True)
    thoi_gian_bat_dau = models.DateTimeField(null=True,blank=True)
    thoi_gian_ket_thuc = models.DateTimeField(null=True,blank=True)
    trang_thai = models.CharField(max_length=20,default='nhap',choices=[('nhap','Nháp'),('dang_kiem','Đang kiểm'),('hoan_tat','Hoàn tất')])
    def __str__(self): return self.ma_dot

class PhamViKiemKe(models.Model):
    dot_kiem_ke = models.ForeignKey(DotKiemKe,on_delete=models.PROTECT,related_name='pham_vi')
    vi_tri = models.ForeignKey(ViTriLuuTru,on_delete=models.PROTECT)
    nguoi_xac_nhan_mo_khoa = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True)
    thoi_gian_khoa = models.DateTimeField(null=True,blank=True)
    thoi_gian_mo_khoa = models.DateTimeField(null=True,blank=True)
    trang_thai_khoa = models.BooleanField(default=False)
    class Meta: constraints=[models.UniqueConstraint(fields=['dot_kiem_ke','vi_tri'],name='unique_kiem_ke_vi_tri')]

class ChiTietKiemKe(models.Model):
    pham_vi = models.ForeignKey(PhamViKiemKe,on_delete=models.PROTECT,related_name='chi_tiet')
    hang_hoa = models.ForeignKey(HangHoa,on_delete=models.PROTECT)
    nguoi_kiem_dem = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True)
    so_luong_he_thong = models.DecimalField(max_digits=14,decimal_places=2)
    so_luong_thuc_te = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)
    chenh_lech = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    ly_do = models.TextField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['pham_vi','hang_hoa'],name='unique_kiem_ke_hang_hoa')]

class DieuChinhTonKho(models.Model):
    chi_tiet_kiem_ke = models.OneToOneField(ChiTietKiemKe,on_delete=models.PROTECT)
    nguoi_de_nghi = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,related_name='de_nghi_dieu_chinh')
    nguoi_phe_duyet = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT,null=True,blank=True,related_name='phe_duyet_dieu_chinh')
    so_luong_dieu_chinh = models.DecimalField(max_digits=14,decimal_places=2)
    ly_do = models.TextField()
    trang_thai = models.CharField(max_length=20,default='cho_duyet',choices=[('cho_duyet','Chờ duyệt'),('da_duyet','Đã duyệt'),('tu_choi','Từ chối')])
    thoi_gian_phe_duyet = models.DateTimeField(null=True,blank=True)

class NhatKyGiaoDich(models.Model):
    nguoi_thuc_hien = models.ForeignKey(TaiKhoan,on_delete=models.PROTECT)
    phieu_nhap = models.ForeignKey(PhieuNhap,on_delete=models.PROTECT,null=True,blank=True)
    phieu_xuat = models.ForeignKey(PhieuXuat,on_delete=models.PROTECT,null=True,blank=True)
    yeu_cau = models.ForeignKey(YeuCauXuLyPhieu,on_delete=models.PROTECT,null=True,blank=True)
    dot_kiem_ke = models.ForeignKey(DotKiemKe,on_delete=models.PROTECT,null=True,blank=True)
    dieu_chinh = models.ForeignKey(DieuChinhTonKho,on_delete=models.PROTECT,null=True,blank=True)
    hang_hoa = models.ForeignKey(HangHoa,on_delete=models.PROTECT,null=True,blank=True)
    vi_tri = models.ForeignKey(ViTriLuuTru,on_delete=models.PROTECT,null=True,blank=True)
    loai_giao_dich = models.CharField(max_length=50)
    thoi_gian = models.DateTimeField(auto_now_add=True)
    hanh_dong = models.CharField(max_length=80)
    noi_dung_thay_doi = models.TextField(blank=True)
    so_luong_truoc = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)
    so_luong_sau = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True)
    class Meta: ordering=['-thoi_gian']
