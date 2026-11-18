from decimal import Decimal, InvalidOperation
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Sum, Q
from django.http import HttpResponseForbidden, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import *
from . import services


def account_for(user):
    return TaiKhoan.objects.select_related('vai_tro').filter(user=user, trang_thai=True).first()

def authorized(view):
    @login_required
    @wraps(view)
    def inner(request,*args,**kwargs):
        account=account_for(request.user)
        if account is None: return HttpResponseForbidden('Tài khoản chưa được phân quyền WMS. Nhờ quản trị viên cấp vai trò tại /admin/.')
        request.wms_account=account
        request.wms_manager=request.user.is_superuser or account.vai_tro.ten_vai_tro=='Quản lý kho'
        request.wms_kind= 'NVL' if account.vai_tro.ten_vai_tro=='Nhân viên kho NVL' else ('TP' if account.vai_tro.ten_vai_tro=='Nhân viên kho thành phẩm' else None)
        if request.wms_kind and kwargs.get('kind') and kwargs['kind']!=request.wms_kind: return HttpResponseForbidden('Không có quyền truy cập kho này.')
        return view(request,*args,**kwargs)
    return inner

def base(request, **extra):
    d={'is_manager':request.wms_manager,'role_name':request.wms_account.vai_tro.ten_vai_tro,'allowed_kind':request.wms_kind,'warehouse_options':Kho.objects.filter(loai_kho=request.wms_kind) if request.wms_kind else Kho.objects.all()}
    d.update(extra);return d

def restricted(qs,request,field):
    if request.wms_kind:return qs.filter(**{field:request.wms_kind})
    return qs

def decimal_pos(raw):
    try:
        num=Decimal(raw)
        if not num.is_finite() or num<=0:raise InvalidOperation
        return num
    except (InvalidOperation,TypeError,ValueError):raise ValidationError('Số lượng phải là số dương hợp lệ.')

def manager_only(request):
    if not request.wms_manager:raise PermissionDenied('Chỉ quản lý kho được thao tác.')

def manager_action(request, fn):
    manager_only(request)
    try:
        fn();messages.success(request,'Đã xử lý thành công và ghi nhận trên hệ thống.')
    except (ValidationError,ValueError) as e:
        messages.error(request,'Không thể xử lý: '+str(e))

@authorized
def dashboard(request):
    stocks=restricted(TonKho.objects.select_related('hang_hoa__nhom_hang','vi_tri__ke__khu_vuc__kho'),request,'vi_tri__ke__khu_vuc__kho__loai_kho')
    totals={}
    for entry in stocks:
        key=(entry.hang_hoa_id,entry.vi_tri.kho.id)
        totals[key]=totals.get(key,Decimal('0'))+entry.so_luong_ton
    thresholds=restricted(NguongTonAnToan.objects.select_related('hang_hoa','kho'),request,'kho__loai_kho')
    alerts=[{'item':t,'quantity':totals.get((t.hang_hoa_id,t.kho_id),Decimal(0))} for t in thresholds if totals.get((t.hang_hoa_id,t.kho_id),Decimal(0))<=t.muc_ton_an_toan]
    return render(request,'wms_core/dashboard.html',base(request,section='dashboard',stocks=stocks[:40],alerts=alerts,
        sku_count=restricted(HangHoa.objects.all(),request,'nhom_hang__loai_hang').count(),
        warehouse_count=restricted(Kho.objects.all(),request,'loai_kho').count(),
        pending_in=restricted(PhieuNhap.objects.filter(trang_thai='cho_duyet'),request,'kho__loai_kho').count(),
        pending_out=restricted(PhieuXuat.objects.filter(trang_thai='cho_duyet'),request,'kho__loai_kho').count(),
        transactions=restricted(NhatKyGiaoDich.objects.select_related('hang_hoa','nguoi_thuc_hien'),request,'hang_hoa__nhom_hang__loai_hang')[:8]))

@authorized
def goods(request,kind):
    qs=HangHoa.objects.filter(nhom_hang__loai_hang=kind).select_related('don_vi_tinh','nhom_hang').order_by('ma_hang')
    search=request.GET.get('q','').strip()
    if search:qs=qs.filter(Q(ma_hang__icontains=search)|Q(ten_hang__icontains=search))
    amounts=dict(TonKho.objects.filter(hang_hoa__in=qs).values_list('hang_hoa_id').annotate(total=Sum('so_luong_ton')))
    rows=[{'item':p,'qty':amounts.get(p.pk,0)} for p in qs[:300]]
    return render(request,'wms_core/goods.html',base(request,rows=rows,kind=kind,section='goods',search=search))

@authorized
def partners(request):
    return render(request,'wms_core/partners.html',base(request,rows=DoiTac.objects.order_by('ma_doi_tac'),section='partners'))

@authorized
def positions(request):
    qs=restricted(ViTriLuuTru.objects.select_related('ke__khu_vuc__kho').all(),request,'ke__khu_vuc__kho__loai_kho')
    return render(request,'wms_core/positions.html',base(request,rows=qs,section='positions'))

@authorized
def inventory(request):
    qs=restricted(TonKho.objects.select_related('hang_hoa__don_vi_tinh','vi_tri__ke__khu_vuc__kho').all(),request,'vi_tri__ke__khu_vuc__kho__loai_kho')
    kind=request.GET.get('kind')
    if kind in ('NVL','TP'):qs=qs.filter(vi_tri__ke__khu_vuc__kho__loai_kho=kind)
    return render(request,'wms_core/inventory.html',base(request,rows=qs.order_by('hang_hoa__ma_hang'),section='inventory',kind=kind))

@authorized
def documents(request,direction):
    if direction not in ('nhap','xuat'):raise Http404()
    cls=PhieuNhap if direction=='nhap' else PhieuXuat
    rows=restricted(cls.objects.select_related('kho','doi_tac','nguoi_lap','nguoi_phe_duyet'),request,'kho__loai_kho')
    kind=request.GET.get('kind')
    if kind in ('NVL','TP'):rows=rows.filter(kho__loai_kho=kind)
    return render(request,'wms_core/documents.html',base(request,rows=rows.order_by('-thoi_gian_lap')[:200],direction=direction,kind=kind,section=direction))

@authorized
def new_document(request,direction):
    if direction not in ('nhap','xuat'):
        raise Http404('Loại phiếu không hợp lệ')
    cls=PhieuNhap if direction=='nhap' else PhieuXuat
    if request.method=='POST':
        try:
            with transaction.atomic():
                kho=get_object_or_404(Kho,pk=request.POST.get('kho'))
                if request.wms_kind and kho.loai_kho!=request.wms_kind:raise ValidationError('Kho không thuộc quyền của bạn.')
                partner=get_object_or_404(DoiTac,pk=request.POST.get('doi_tac'),trang_thai=True)
                if direction=='nhap' and partner.loai_doi_tac=='CHINHANH':raise ValidationError('Chi nhánh không phải nguồn nhập hàng.')
                if direction=='xuat' and partner.loai_doi_tac=='NCC':raise ValidationError('Chọn xưởng hoặc chi nhánh nhận hàng.')
                goods_ids=request.POST.getlist('hang_hoa')
                pos_ids=request.POST.getlist('vi_tri')
                qty_values=request.POST.getlist('so_luong')
                if not goods_ids or not (len(goods_ids)==len(pos_ids)==len(qty_values)):
                    raise ValidationError('Phiếu phải có ít nhất một dòng đầy đủ.')
                if len(goods_ids)>100:raise ValidationError('Một phiếu tối đa 100 dòng hàng.')
                lines=[]
                for gid,pid,rawqty in zip(goods_ids,pos_ids,qty_values):
                    item=get_object_or_404(HangHoa.objects.select_related('nhom_hang'),pk=gid)
                    pos=get_object_or_404(ViTriLuuTru.objects.select_related('ke__khu_vuc__kho'),pk=pid)
                    if item.nhom_hang.loai_hang!=kho.loai_kho or pos.kho.pk!=kho.pk:
                        raise ValidationError('Hàng hóa hoặc vị trí không thuộc kho được chọn.')
                    lines.append((item,pos,decimal_pos(rawqty)))
                code=request.POST.get('ma_phieu','').strip()
                if not code:raise ValidationError('Bạn cần nhập mã phiếu.')
                doc=cls.objects.create(kho=kho,doi_tac=partner,nguoi_lap=request.wms_account,
                    ghi_chu=request.POST.get('ghi_chu',''),**({'ma_phieu_nhap':code} if direction=='nhap' else {'ma_phieu_xuat':code}))
                for item,pos,number in lines:
                    line=(ChiTietPhieuNhap(phieu_nhap=doc,hang_hoa=item,vi_tri=pos,so_luong_nhap=number) if direction=='nhap'
                      else ChiTietPhieuXuat(phieu_xuat=doc,hang_hoa=item,vi_tri=pos,so_luong_xuat=number))
                    line.full_clean();line.save()
            messages.success(request,f'Đã lưu phiếu nháp với {len(lines)} dòng. Tồn kho chưa thay đổi.')
            return redirect('wms_documents',direction=direction)
        except (ValidationError,ValueError,IntegrityError) as exc:messages.error(request,'Không thể tạo phiếu: '+str(exc))
    warehouses=restricted(Kho.objects.all(),request,'loai_kho')
    goods=restricted(HangHoa.objects.select_related('nhom_hang'),request,'nhom_hang__loai_hang')
    locations=restricted(ViTriLuuTru.objects.select_related('ke__khu_vuc__kho'),request,'ke__khu_vuc__kho__loai_kho')
    return render(request,'wms_core/new_document.html',base(request,direction=direction,warehouses=warehouses,
         goods=goods,locations=locations,partners=DoiTac.objects.filter(trang_thai=True),section=direction))

@authorized
@require_POST
def document_action(request,direction,pk,action):
    if direction not in ('nhap','xuat'):raise Http404()
    cls=PhieuNhap if direction=='nhap' else PhieuXuat
    doc=get_object_or_404(cls,pk=pk)
    if request.wms_kind and doc.kho.loai_kho!=request.wms_kind:return HttpResponseForbidden('Không có quyền kho này.')
    if action=='send':
        if doc.trang_thai!='nhap':messages.error(request,'Chỉ phiếu nháp mới được gửi duyệt.')
        elif not request.wms_manager and doc.nguoi_lap_id!=request.wms_account.pk:messages.error(request,'Chỉ người lập phiếu được gửi duyệt.')
        elif not doc.chi_tiet.exists():messages.error(request,'Phiếu chưa có dòng hàng.')
        else:
            doc.trang_thai='cho_duyet';doc.save(update_fields=['trang_thai']);messages.success(request,'Đã gửi phiếu chờ quản lý phê duyệt.')
    elif action=='approve':
        def do():
            if doc.trang_thai!='cho_duyet':raise ValidationError('Phiếu phải ở trạng thái chờ duyệt.')
            services.approve_receipt(pk,request.user,direction)
        manager_action(request,do)
    elif action=='reject':
        def do():
            if doc.trang_thai!='cho_duyet':raise ValidationError('Chỉ từ chối phiếu đang chờ duyệt')
            with transaction.atomic():
                checked=cls.objects.select_for_update().get(pk=pk)
                if checked.trang_thai!='cho_duyet':raise ValidationError('Phiếu không còn chờ duyệt')
                checked.trang_thai='da_huy';checked.save(update_fields=['trang_thai'])
                NhatKyGiaoDich.objects.create(nguoi_thuc_hien=request.wms_account,
                    phieu_nhap=checked if direction=='nhap' else None,phieu_xuat=checked if direction=='xuat' else None,
                    loai_giao_dich=direction,hanh_dong='TU_CHOI',noi_dung_thay_doi='Quản lý từ chối phiếu chờ duyệt')
        manager_action(request,do)
    return redirect('wms_documents',direction=direction)

@authorized
def stock_counts(request):
    qs=restricted(DotKiemKe.objects.select_related('kho','nguoi_lap'),request,'kho__loai_kho')
    return render(request,'wms_core/counts.html',base(request,rows=qs.order_by('-id'),section='counts'))

@authorized
@require_POST
def new_count(request):
    manager_only(request)
    warehouse=get_object_or_404(Kho,pk=request.POST.get('kho'))
    code=request.POST.get('ma_dot','').strip()
    if not code:messages.error(request,'Cần có mã đợt kiểm kê.');return redirect('wms_counts')
    try:
        with transaction.atomic():
            batch=DotKiemKe.objects.create(kho=warehouse,nguoi_lap=request.wms_account,ma_dot=code)
            for pos in ViTriLuuTru.objects.filter(ke__khu_vuc__kho=warehouse):PhamViKiemKe.objects.create(dot_kiem_ke=batch,vi_tri=pos)
        messages.success(request,'Đã tạo đợt kiểm kê nháp và chọn toàn bộ vị trí trong kho.')
    except Exception as e:messages.error(request,str(e))
    return redirect('wms_counts')

@authorized
@require_POST
def count_action(request,pk,action):
    if action=='start':manager_action(request,lambda:services.start_count(pk,request.user))
    elif action=='finish':manager_action(request,lambda:services.finish_count(pk,request.user))
    return redirect('wms_counts')

@authorized
def count_detail(request,pk):
    batch=get_object_or_404(DotKiemKe.objects.select_related('kho'),pk=pk)
    if request.wms_kind and batch.kho.loai_kho!=request.wms_kind:return HttpResponseForbidden('Không có quyền kho này.')
    rows=ChiTietKiemKe.objects.filter(pham_vi__dot_kiem_ke=batch).select_related('hang_hoa','pham_vi__vi_tri')
    return render(request,'wms_core/count_detail.html',base(request,batch=batch,rows=rows,section='counts'))

@authorized
@require_POST
def record_count(request,pk):
    line=get_object_or_404(ChiTietKiemKe.objects.select_related('pham_vi__dot_kiem_ke__kho'),pk=pk)
    if request.wms_kind and line.pham_vi.dot_kiem_ke.kho.loai_kho!=request.wms_kind:return HttpResponseForbidden('Không có quyền kho này.')
    if line.pham_vi.dot_kiem_ke.trang_thai!='dang_kiem':messages.error(request,'Đợt chưa bắt đầu hoặc đã kết thúc.')
    else:
        try:
            qty=Decimal(request.POST.get('so_luong_thuc_te',''))
            if not qty.is_finite() or qty<0:raise ValueError()
            if DieuChinhTonKho.objects.filter(chi_tiet_kiem_ke=line).exists():raise ValidationError('Đã lập đề nghị điều chỉnh, không thể sửa kiểm đếm.')
            line.so_luong_thuc_te=qty;line.chenh_lech=qty-line.so_luong_he_thong;line.nguoi_kiem_dem=request.wms_account
            line.save(update_fields=['so_luong_thuc_te','chenh_lech','nguoi_kiem_dem'])
            if line.chenh_lech!=0:DieuChinhTonKho.objects.create(chi_tiet_kiem_ke=line,nguoi_de_nghi=request.wms_account,so_luong_dieu_chinh=line.chenh_lech,ly_do=request.POST.get('ly_do','Sai lệch kiểm kê'))
            messages.success(request,'Đã ghi nhận số lượng kiểm đếm.')
        except (ValueError,InvalidOperation,ValidationError) as e:messages.error(request,'Số lượng không hợp lệ: '+str(e))
    return redirect('wms_count_detail',pk=line.pham_vi.dot_kiem_ke_id)

@authorized
def adjustments(request):
    manager_only(request)
    rows=DieuChinhTonKho.objects.select_related('chi_tiet_kiem_ke__hang_hoa','chi_tiet_kiem_ke__pham_vi__vi_tri').order_by('-id')
    return render(request,'wms_core/adjustments.html',base(request,rows=rows,section='adjustments'))

@authorized
@require_POST
def adjustment_action(request,pk,action):
    manager_only(request)
    if action=='approve':manager_action(request,lambda:services.approve_adjustment(pk,request.user))
    elif action=='reject':
        def do():
            a=get_object_or_404(DieuChinhTonKho,pk=pk)
            if a.trang_thai!='cho_duyet':raise ValidationError('Đề nghị không còn chờ duyệt')
            a.trang_thai='tu_choi';a.save(update_fields=['trang_thai'])
        manager_action(request,do)
    return redirect('wms_adjustments')

@authorized
def thresholds(request):
    qs=restricted(NguongTonAnToan.objects.select_related('hang_hoa','kho'),request,'kho__loai_kho')
    return render(request,'wms_core/thresholds.html',base(request,rows=qs,section='thresholds'))

@authorized
@require_POST
def update_threshold(request,pk):
    manager_only(request)
    obj=get_object_or_404(NguongTonAnToan,pk=pk)
    try:
        qty=Decimal(request.POST['muc_ton_an_toan'])
        if not qty.is_finite() or qty<0:raise ValueError()
        obj.muc_ton_an_toan=qty;obj.nguoi_cap_nhat=request.wms_account;obj.save()
        messages.success(request,'Đã cập nhật ngưỡng tồn an toàn.')
    except (ValueError,InvalidOperation):messages.error(request,'Ngưỡng tồn phải là số không âm.')
    return redirect('wms_thresholds')

@authorized
def activity(request):
    manager_only(request)
    return render(request,'wms_core/activity.html',base(request,rows=NhatKyGiaoDich.objects.select_related('hang_hoa','vi_tri','nguoi_thuc_hien').all()[:300],section='activity'))

@authorized
def report(request):
    manager_only(request)
    wh=Kho.objects.all()
    data=[]
    for k in wh:
        stocks=TonKho.objects.filter(vi_tri__ke__khu_vuc__kho=k)
        data.append({'kho':k,'total':stocks.aggregate(total=Sum('so_luong_ton'))['total'] or 0,'sku':stocks.values('hang_hoa').distinct().count(),
                     'receipts':PhieuNhap.objects.filter(kho=k,trang_thai='da_duyet').count(), 'issues':PhieuXuat.objects.filter(kho=k,trang_thai='da_duyet').count()})
    return render(request,'wms_core/report.html',base(request,data=data,section='report'))

@authorized
def users(request):
    manager_only(request)
    return render(request,'wms_core/users.html',base(request,rows=TaiKhoan.objects.select_related('user','vai_tro'),section='users'))


@authorized
def correction_requests(request):
    qs=YeuCauXuLyPhieu.objects.select_related('phieu_nhap','phieu_xuat','nguoi_yeu_cau','nguoi_phe_duyet').order_by('-id')
    if request.wms_kind:
        qs=qs.filter(Q(phieu_nhap__kho__loai_kho=request.wms_kind)|Q(phieu_xuat__kho__loai_kho=request.wms_kind))
    return render(request,'wms_core/corrections.html',base(request,rows=qs[:150],section='corrections'))

@authorized
@require_POST
def request_correction(request,direction,pk):
    if direction not in ('nhap','xuat'):raise Http404()
    cls=PhieuNhap if direction=='nhap' else PhieuXuat
    doc=get_object_or_404(cls.objects.select_related('kho'),pk=pk)
    if request.wms_kind and doc.kho.loai_kho!=request.wms_kind:
        return HttpResponseForbidden('Không thuộc phạm vi kho được phân công')
    if doc.trang_thai!='da_duyet':messages.error(request,'Chỉ tạo yêu cầu cho phiếu đã duyệt.')
    else:
        try:
            reason=request.POST.get('ly_do','').strip()
            if not reason:raise ValidationError('Cần ghi rõ lý do hủy phiếu.')
            with transaction.atomic():
                if YeuCauXuLyPhieu.objects.filter(trang_thai='cho_duyet',**({'phieu_nhap':doc} if direction=='nhap' else {'phieu_xuat':doc})).exists():
                    raise ValidationError('Phiếu đang có yêu cầu xử lý chờ phê duyệt.')
                YeuCauXuLyPhieu.objects.create(nguoi_yeu_cau=request.wms_account,loai_yeu_cau='huy',ly_do=reason,
                    noi_dung_de_nghi='Đề nghị hủy phiếu đã xác nhận',**({'phieu_nhap':doc} if direction=='nhap' else {'phieu_xuat':doc}))
            messages.success(request,'Đã gửi yêu cầu hủy để quản lý xem xét. Tồn kho chưa thay đổi.')
        except (ValidationError,IntegrityError) as e:messages.error(request,str(e))
    return redirect('wms_corrections')

@authorized
@require_POST
def correction_action(request,pk,action):
    manager_only(request)
    if action=='approve':manager_action(request,lambda:services.approve_cancellation(pk,request.user))
    elif action=='reject':
        def reject():
            with transaction.atomic():
                req=YeuCauXuLyPhieu.objects.select_for_update().get(pk=pk)
                if req.trang_thai!='cho_duyet':raise ValidationError('Yêu cầu không còn chờ duyệt')
                req.trang_thai='tu_choi';req.nguoi_phe_duyet=request.wms_account
                req.thoi_gian_phe_duyet=timezone.now();req.noi_dung_xu_ly=request.POST.get('ghi_chu','Từ chối')
                req.save(update_fields=['trang_thai','nguoi_phe_duyet','thoi_gian_phe_duyet','noi_dung_xu_ly'])
        manager_action(request,reject)
    return redirect('wms_corrections')

@authorized
def import_excel(request):
    """Import opening master data from XONXEN workbook without overwriting live stock."""
    manager_only(request)
    summary=None
    if request.method=='POST':
        try:
            from .excel_import import import_workbook
            source=request.FILES.get('excel')
            if source is None:raise ValidationError('Vui lòng chọn tệp Excel .xlsx')
            if not source.name.lower().endswith('.xlsx') or source.size>5*1024*1024:
                raise ValidationError('Chỉ nhận tệp .xlsx tối đa 5 MB')
            summary=import_workbook(source,request.wms_account)
            messages.success(request,'Đã kiểm tra và nhập danh mục mới. Tồn hiện hữu không bị ghi đè.')
        except (ValidationError, ValueError, IntegrityError) as exc:
            messages.error(request,str(exc))
    return render(request,'wms_core/import_excel.html',base(request,section='import_excel',summary=summary))

@authorized
def export_inventory_csv(request):
    """Current stock by SKU and physical location; avoids summing unlike units."""
    manager_only(request)
    import csv
    from django.http import HttpResponse
    qs=TonKho.objects.select_related('hang_hoa__don_vi_tinh','vi_tri__ke__khu_vuc__kho').order_by('vi_tri__ke__khu_vuc__kho__ten_kho','hang_hoa__ma_hang')
    response=HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition']='attachment; filename="xonxen_ton_kho_hien_tai.csv"'
    response.write('\\ufeff'.encode('utf-8'))
    writer=csv.writer(response)
    writer.writerow(['Kho','Mã hàng','Tên hàng','Đơn vị tính','Vị trí','Số lượng tồn','Cập nhật lúc'])
    for row in qs.iterator():
        writer.writerow([row.vi_tri.kho.ten_kho,row.hang_hoa.ma_hang,row.hang_hoa.ten_hang,
             row.hang_hoa.don_vi_tinh.ten_don_vi_tinh,row.vi_tri.ma_vi_tri,str(row.so_luong_ton),
             timezone.localtime(row.thoi_gian_cap_nhat).strftime('%d/%m/%Y %H:%M')])
    return response
