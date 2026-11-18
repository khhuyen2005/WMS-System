"""Tạo chứng từ ghi nhận cho phiếu kiểm kho cũ đã cân bằng.

An toàn: đối chiếu nhật ký trước khi tạo; KHÔNG cập nhật TonKho.
Dùng: python manage.py tao_chung_tu_kiem_kho --ma KK-2026-001 --thuc-hien
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wms_core.models import NhatKyGiaoDich, PhieuKiemKho
from wms_core.stockcheck import create_balance_vouchers


class Command(BaseCommand):
    help = 'Bổ sung chứng từ nhập/xuất cho phiếu kiểm kho đã duyệt (không cập nhật tồn).'

    def add_arguments(self, parser):
        parser.add_argument('--ma', required=True, help='Ví dụ KK-2026-001')
        parser.add_argument('--thuc-hien', action='store_true', help='Xác nhận ghi DB')

    def handle(self, *args, **options):
        code = options['ma'].strip()
        with transaction.atomic():
            phieu = (
                PhieuKiemKho.objects.select_for_update()
                .select_related('nguoi_phe_duyet').filter(ma_phieu=code).first()
            )
            if not phieu:
                raise CommandError('Không tìm thấy phiếu kiểm kho ' + code)
            if phieu.trang_thai != 'da_duyet' or not phieu.nguoi_phe_duyet_id:
                raise CommandError('Phiếu chưa cân bằng/không có người duyệt.')

            changed = [
                line for line in phieu.chi_tiet.all()
                if line.chenh_lech != 0
            ]
            # Chỉ lập chứng từ quá khứ nếu có log kiểm chứng quá trình
            # cân bằng đã thực sự ghi nhận các số tồn trước/sau.
            for line in changed:
                logs = NhatKyGiaoDich.objects.filter(
                    hanh_dong='CAN_BANG_KHO',
                    hang_hoa_id=line.hang_hoa_id,
                    vi_tri_id=line.vi_tri_id,
                    so_luong_truoc=line.so_luong_he_thong,
                    so_luong_sau=line.so_luong_thuc_te,
                    noi_dung_thay_doi__startswith=(
                        f'Phiếu kiểm kho {phieu.ma_phieu}: tồn hệ thống'
                    ),
                )
                if logs.count() != 1:
                    raise CommandError(
                        'Nhật ký cân bằng chưa khớp ' +
                        f'{line.hang_hoa.ma_hang} / {line.vi_tri.ma_vi_tri}; '
                        'không tự tạo chứng từ để tránh sai dữ liệu.'
                    )

            n_in = sum(line.chenh_lech > 0 for line in changed)
            n_out = sum(line.chenh_lech < 0 for line in changed)
            self.stdout.write(
                f'{code}: {n_in} dòng nhập, {n_out} dòng xuất; '
                'đã đối chiếu nhật ký cân bằng.'
            )
            if not options['thuc_hien']:
                self.stdout.write(
                    self.style.WARNING(
                        'CHỈ KIỂM TRA, CHƯA GHI DB. '
                        'Chạy lại thêm --thuc-hien để tạo chứng từ.'
                    )
                )
                return

            results = create_balance_vouchers(phieu, phieu.nguoi_phe_duyet)
            for direction, doc in results.items():
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{direction.upper()}: '
                        f'{doc.ma_phieu_nhap if direction == "nhap" else doc.ma_phieu_xuat}'
                    )
                )
            if not results:
                self.stdout.write('Không có chênh lệch, không cần tạo chứng từ.')
            self.stdout.write('Xong: KHÔNG tác động số lượng TonKho.')
