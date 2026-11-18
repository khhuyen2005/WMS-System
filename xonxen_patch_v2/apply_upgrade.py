"""Install XONXEN business logic upgrade into EXISTING Django project safely.
Run in a terminal from the directory containing manage.py:
    python xonxen_patch_v2/apply_upgrade.py
Does NOT delete or update db.sqlite3, migrations, old apps, nor credentials.
"""
from pathlib import Path
from datetime import datetime
import shutil
import sys

HERE=Path(__file__).resolve().parent
PROJECT=Path.cwd().resolve()
if not (PROJECT/'manage.py').is_file() or not (PROJECT/'WMS'/'settings.py').is_file():
    sys.exit('LOI: Ban phai mo Terminal tai thu muc co manage.py va WMS/settings.py. Khong co file nao duoc sua.')
if not (PROJECT/'wms_core'/'models.py').is_file():
    sys.exit('LOI: Khong tim thay wms_core/models.py. Chua dung phien ban du an co ERD 25 bang.')
payload=HERE/'payload'
if not (payload/'wms_core'/'views.py').is_file():
    sys.exit('LOI: Khong thay goi payload. Hay giai nen nguyen thu muc xonxen_patch_v2.')
files=[f for f in payload.rglob('*') if f.is_file()]
backup=PROJECT/('BACKUP_CODE_BEFORE_WMS_V2_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
# First back up all files that would be replaced. No database is modified.
for src in files:
    rel=src.relative_to(payload)
    dst=PROJECT/rel
    if dst.exists():
        destination=backup/rel
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(dst,destination)
# Then apply the new files, retaining every other existing file and directory.
for src in files:
    rel=src.relative_to(payload)
    target=PROJECT/rel
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,target)
print('DA CAP NHAT CODE: '+str(len(files))+' tep. Khong xoa DB, migration hay hai app cu.')
print('Backup code cu: '+str(backup))
print('CHAY LAN LUOT:')
print('  python manage.py check')
print('  python manage.py makemigrations --check --dry-run')
print('  python manage.py migrate')
print('  python manage.py setup_wms_roles --manager nhom36')
print('  python manage.py test wms_core')
print('  python manage.py runserver')
