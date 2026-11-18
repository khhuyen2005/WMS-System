from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wms_core', '0005_phieu_nhap_xuat_kiem_kho'),
    ]

    operations = [
        migrations.AddField(
            model_name='phieukiemkho',
            name='loai_kiem_ke',
            field=models.CharField(
                choices=[('mot_phan', 'Một phần'), ('toan_bo', 'Toàn bộ')],
                default='mot_phan',
                max_length=12,
                verbose_name='Loại kiểm kê',
            ),
        ),
    ]
