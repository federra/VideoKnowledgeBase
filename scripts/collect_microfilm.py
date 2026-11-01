"""Explicit free microfilm video-search collection. No other channels or AI."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.collection.microfilm import run
from app.core.database import application_engine
from app.security.local import owner_identity
from app.security.sessions import MemberPrincipal

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--authorized-one-retry',action='store_true',help='One-off user-approved scoped search exception, at most two failed attempts')
a=p.parse_args();engine=application_engine()
with engine.begin() as c:
 m=owner_identity(c)
 principal=MemberPrincipal(m.org_id,m.id)
print(json.dumps(run(engine,principal,one_off_retry=a.authorized_one_retry),ensure_ascii=False),flush=True)
