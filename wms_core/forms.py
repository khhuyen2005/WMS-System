
import re

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import HangHoa, NhomHang, DonViTinh, Ke


# ==========================================================
# 1. TU DONG SINH MA NVL / TP
# ==========================================================

NVL_CODE_PATTERN = re.compile(
    r'^NVL(\d+)$',
    re.IGNORECASE
)

TP_CODE_PATTERN = re.compile(
    r'^TP(\d+)$',
    re.IGNORECASE
)


def _next_goods_code(prefix, pattern):

    codes = HangHoa.objects.filter(
        ma_hang__istartswith=prefix
    ).values_list(
        'ma_hang',
        flat=True
    )

    max_number = 0

    for code in codes:

        match = pattern.fullmatch(code or '')

        if match:
            max_number = max(
                max_number,
                int(match.group(1))
            )

    return f'{prefix}{max_number + 1:03d}'


def next_nvl_code():

    return _next_goods_code(
        'NVL',
        NVL_CODE_PATTERN
    )


def next_tp_code():

    return _next_goods_code(
        'TP',
        TP_CODE_PATTERN
    )


# ==========================================================
# 2. FORM THEM NVL / THANH PHAM
# ==========================================================

class HangHoaForm(forms.ModelForm):

    class Meta:

        model = HangHoa

        fields = [
            'ten_hang',
            'nhom_hang',
            'don_vi_tinh',
            'mau_ma',
            'mau_sac',
            'kich_co',
            'don_gia',
            'ke_mac_dinh',
            'trang_thai',
        ]

        labels = {
            'ten_hang': 'Tên hàng hóa',
            'nhom_hang': 'Nhóm hàng',
            'don_vi_tinh': 'Đơn vị tính',
            'mau_ma': 'Mẫu mã',
            'mau_sac': 'Màu sắc',
            'kich_co': 'Kích cỡ',
            'don_gia': 'Đơn giá (VNĐ)',
            'ke_mac_dinh': 'Kệ lưu trữ mặc định',
            'trang_thai': 'Trạng thái',
        }

        widgets = {

            'ten_hang': forms.TextInput(
                attrs={
                    'class': 'field',
                    'maxlength': '220',
                }
            ),

            'nhom_hang': forms.Select(
                attrs={'class': 'field'}
            ),

            'don_vi_tinh': forms.Select(
                attrs={'class': 'field'}
            ),

            'mau_ma': forms.TextInput(
                attrs={'class': 'field'}
            ),

            'mau_sac': forms.TextInput(
                attrs={'class': 'field'}
            ),

            'kich_co': forms.TextInput(
                attrs={'class': 'field'}
            ),

            'don_gia': forms.NumberInput(
                attrs={
                    'class': 'field',
                    'min': '0',
                    'step': '0.01',
                    'placeholder': 'Ví dụ: 85000',
                }
            ),

            'ke_mac_dinh': forms.Select(
                attrs={'class': 'field'}
            ),

            'trang_thai': forms.Select(
                attrs={'class': 'field'}
            ),
        }

    # ======================================================
    # 3. KHOI TAO FORM THEO LOAI HANG
    # ======================================================

    def __init__(self, *args, kind=None, **kwargs):

        super().__init__(*args, **kwargs)

        if kind not in ('NVL', 'TP'):
            raise ValueError(
                'Loại hàng không hợp lệ.'
            )

        self.kind = kind

        # Chi hien ke thuoc dung loai kho
        self.fields['ke_mac_dinh'].queryset = (
            Ke.objects.filter(
                khu_vuc__kho__loai_kho=kind
            )
            .select_related('khu_vuc__kho')
            .order_by(
                'khu_vuc__kho__ten_kho',
                'khu_vuc__ten_khu_vuc',
                'ten_ke'
            )
        )

        self.fields['ke_mac_dinh'].required = True

        self.fields['ke_mac_dinh'].empty_label = (
            '-- Chọn kệ lưu trữ --'
        )

        # Don gia bat buoc
        self.fields['don_gia'].required = True
        self.fields['don_gia'].min_value = Decimal('0')

        # ==================================================
        # FORM NGUYEN VAT LIEU
        # ==================================================

        if kind == 'NVL':

            # Giu nguyen cac truong hien co cua NVL
            for name in (
                'nhom_hang',
                'mau_ma',
                'kich_co',
                'trang_thai',
            ):
                self.fields.pop(name, None)

            self.fields['ten_hang'].label = (
                'Tên nguyên vật liệu'
            )

            self.fields['ten_hang'].widget.attrs.update({
                'placeholder': 'Ví dụ: Vải thun cotton',
                'autofocus': 'autofocus',
            })

            self.fields['don_vi_tinh'].empty_label = (
                '-- Chọn đơn vị tính --'
            )

        # ==================================================
        # FORM THANH PHAM
        # BO 4 TRUONG THEO YEU CAU
        # ==================================================

        else:

            for name in (
                'nhom_hang',
                'don_vi_tinh',
                'mau_ma',
                'trang_thai',
            ):
                self.fields.pop(name, None)

            self.fields['ten_hang'].label = (
                'Tên thành phẩm'
            )

            self.fields['ten_hang'].widget.attrs.update({
                'placeholder': 'Ví dụ: Áo sơ mi nữ',
                'autofocus': 'autofocus',
            })

            self.fields['mau_sac'].widget.attrs.update({
                'placeholder': 'Ví dụ: Trắng',
            })

            self.fields['kich_co'].widget.attrs.update({
                'placeholder': 'Ví dụ: S, M, L',
            })

    # ======================================================
    # 4. KIEM TRA TEN HANG
    # ======================================================

    def clean_ten_hang(self):

        name = ' '.join(
            self.cleaned_data['ten_hang'].split()
        )

        if not name:
            raise ValidationError(
                'Vui lòng nhập tên hàng hóa.'
            )

        return name

    # ======================================================
    # 5. KIEM TRA KE MAC DINH
    # ======================================================

    def clean_ke_mac_dinh(self):

        rack = self.cleaned_data.get(
            'ke_mac_dinh'
        )

        if rack is None:
            raise ValidationError(
                'Vui lòng chọn kệ lưu trữ mặc định.'
            )

        if rack.khu_vuc.kho.loai_kho != self.kind:
            raise ValidationError(
                'Kệ lưu trữ không thuộc đúng loại kho.'
            )

        return rack

    # ======================================================
    # 6. KIEM TRA DON GIA
    # ======================================================

    def clean_don_gia(self):

        price = self.cleaned_data.get(
            'don_gia'
        )

        if price is None:
            raise ValidationError(
                'Vui lòng nhập đơn giá.'
            )

        if price < 0:
            raise ValidationError(
                'Đơn giá không được âm.'
            )

        return price

    # ======================================================
    # 7. LUU HANG HOA
    # ======================================================

    def save(self, commit=True):

        obj = super().save(commit=False)

        # Khong cho nhap mau ma, trang thai thu cong
        obj.mau_ma = ''
        obj.trang_thai = 'hoat_dong'

        if self.kind == 'NVL':
            obj.kich_co = ''

        # --------------------------------------------------
        # GAN NHOM HANG TU DONG CHO HANG MOI
        # --------------------------------------------------

        if not obj.pk:

            if self.kind == 'NVL':

                group_name = 'Nguyên vật liệu'

            else:

                group_name = 'Thành phẩm'

            group = NhomHang.objects.filter(
                loai_hang=self.kind,
                ten_nhom__iexact=group_name
            ).order_by('pk').first()

            if group is None:

                group = NhomHang.objects.create(
                    ten_nhom=group_name,
                    loai_hang=self.kind
                )

            obj.nhom_hang = group

            # --------------------------------------------------
            # THANH PHAM: TU DONG DON VI TINH = CAI
            # --------------------------------------------------

            if self.kind == 'TP':

                unit = DonViTinh.objects.filter(
                    ten_don_vi_tinh__iexact='Cái'
                ).order_by('pk').first()

                if unit is None:

                    unit = DonViTinh.objects.create(
                        ten_don_vi_tinh='Cái'
                    )

                obj.don_vi_tinh = unit

        # --------------------------------------------------
        # CAP NHAT HANG CU: GIU NGUYEN MA
        # --------------------------------------------------

        if obj.pk:

            if commit:

                obj.full_clean()
                obj.save()
                self.save_m2m()

            return obj

        # --------------------------------------------------
        # TAO HANG MOI: SINH MA TU DONG
        # --------------------------------------------------

        if not commit:

            obj.ma_hang = (
                next_nvl_code()
                if self.kind == 'NVL'
                else next_tp_code()
            )

            return obj

        for attempt in range(5):

            code = (
                next_nvl_code()
                if self.kind == 'NVL'
                else next_tp_code()
            )

            obj.ma_hang = code
            obj.pk = None

            try:

                with transaction.atomic():

                    obj.full_clean()
                    obj.save(force_insert=True)

                self.save_m2m()

                return obj

            except (IntegrityError, ValidationError):

                # Chi thu lai neu ma vua bi trung
                if HangHoa.objects.filter(
                    ma_hang__iexact=code
                ).exists():
                    continue

                raise

        raise ValidationError(
            'Không thể tạo mã hàng duy nhất. '
            'Vui lòng thử lại.'
        )
