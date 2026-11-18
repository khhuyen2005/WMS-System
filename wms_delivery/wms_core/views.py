from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Sum,Count,Q
from .models import Kho,HangHoa,TonKho,NguongTonAnToan,PhieuNhap,PhieuXuat,NhatKyGiaoDich

@login_required
def dashboard(request):
    stocks=TonKho.objects.select_related('hang_hoa__nhom_hang','vi_tri__ke__khu_vuc__kho')
    balances={}
    for entry in stocks:
        key=(entry.hang_hoa_id,entry.vi_tri.kho.id)
        balances[key]=balances.get(key,0)+entry.so_luong_ton
    warnings=[]
    for threshold in NguongTonAnToan.objects.select_related('hang_hoa','kho'):
        qty=balances.get((threshold.hang_hoa_id,threshold.kho_id),0)
        if qty<=threshold.muc_ton_an_toan: warnings.append((threshold,qty))
    return render(request,'wms_core/dashboard.html',{
        'kho_count':Kho.objects.count(),'hang_count':HangHoa.objects.count(),
        'total_positions':stocks.count(),'warnings':warnings,
        'stocks':stocks.order_by('hang_hoa__ma_hang')[:100],
        'pending_in':PhieuNhap.objects.filter(trang_thai__in=['nhap','cho_duyet']).count(),
        'pending_out':PhieuXuat.objects.filter(trang_thai__in=['nhap','cho_duyet']).count(),
        'logs':NhatKyGiaoDich.objects.select_related('nguoi_thuc_hien')[:10],
    })
