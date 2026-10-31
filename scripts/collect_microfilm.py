"""Explicit free microfilm video-search collection. No other channels or AI."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.collection.microfilm import run
from app.core.database import application_engine
from app.security.sessions import MemberPrincipal

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--authorized-one-retry',action='store_true',help='One-off user-approved scoped search exception, at most two failed attempts')
a=p.parse_args();engine=application_engine()
with engine.begin() as c:
 m=c.exec_driver_sql("SELECT m.org_id,m.id FROM members m JOIN organizations o ON o.id=m.org_id WHERE o.name='本地单人工作区' AND m.login_name='__local_owner__' AND m.disabled_at IS NULL").one()
 principal=MemberPrincipal(m.org_id,m.id)
print(json.dumps(run(engine,principal,one_off_retry=a.authorized_one_retry),ensure_ascii=False),flush=True)
