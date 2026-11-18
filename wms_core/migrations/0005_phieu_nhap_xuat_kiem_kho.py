# Add one-to-one provenance for stock count balancing vouchers.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('wms_core', '0004_phieukiemkho_chitietphieukiemkho'),
    ]

    operations = [
        migrations.AlterField(
            model_name='phieunhap',
            name='doi_tac',
            field=models.ForeignKey(
                to='wms_core.doitac', on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True,
            ),
        ),
        migrations.AlterField(
            model_name='phieuxuat',
            name='doi_tac',
            field=models.ForeignKey(
                to='wms_core.doitac', on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True,
            ),
        ),
        migrations.AddField(
            model_name='phieunhap',
            name='kiem_kho',
            field=models.OneToOneField(
                to='wms_core.phieukiemkho',
                on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True, related_name='phieu_nhap_can_bang',
            ),
        ),
        migrations.AddField(
            model_name='phieuxuat',
            name='kiem_kho',
            field=models.OneToOneField(
                to='wms_core.phieukiemkho',
                on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True, related_name='phieu_xuat_can_bang',
            ),
        ),
    ]
