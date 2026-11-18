from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from wms_core.models import TaiKhoan, VaiTro, Quyen, VaiTroQuyen

ROLES = {
 'Quản lý kho': ['duyet_phieu','duyet_dieu_chinh','quan_ly_nguong','xem_bao_cao','xem_nhat_ky','quan_ly_tai_khoan','lap_phieu','kiem_dem'],
 'Nhân viên kho NVL': ['lap_phieu','kiem_dem'],
 'Nhân viên kho thành phẩm': ['lap_phieu','kiem_dem'],
}
class Command(BaseCommand):
 help='Khởi tạo vai trò và liên kết tài khoản Django có sẵn, không thay mật khẩu.'
 def add_arguments(self,parser):
  parser.add_argument('--manager', help='Tên đăng nhập Django được cấp vai trò quản lý kho')
  parser.add_argument('--staff-nvl', help='Tên đăng nhập Django làm nhân viên kho NVL')
  parser.add_argument('--staff-tp', help='Tên đăng nhập Django làm nhân viên kho thành phẩm')
 @transaction.atomic
 def handle(self,*args,**opts):
  for title, permissions in ROLES.items():
   role,_=VaiTro.objects.get_or_create(ten_vai_tro=title)
   for code in permissions:
    permission,_=Quyen.objects.get_or_create(ma_quyen=code,defaults={'ten_quyen':code.replace('_',' ').title()})
    VaiTroQuyen.objects.get_or_create(vai_tro=role,quyen=permission)
  for arg,role in [('manager','Quản lý kho'),('staff_nvl','Nhân viên kho NVL'),('staff_tp','Nhân viên kho thành phẩm')]:
   username=opts.get(arg)
   if not username:continue
   user=User.objects.filter(username=username,is_active=True).first()
   if not user:raise CommandError(f'Không có Django User đang hoạt động: {username}. Tạo bằng Admin trước.')
   row,created=TaiKhoan.objects.get_or_create(user=user,defaults={'ho_ten':user.get_full_name() or username,'vai_tro':VaiTro.objects.get(ten_vai_tro=role)})
   if not created:
    row.vai_tro=VaiTro.objects.get(ten_vai_tro=role);row.trang_thai=True;row.save(update_fields=['vai_tro','trang_thai'])
   self.stdout.write(self.style.SUCCESS(f'Đã cấp {role} cho {username}'))
  self.stdout.write('Đã tạo/kiểm tra vai trò và quyền, không thay đổi mật khẩu.')
