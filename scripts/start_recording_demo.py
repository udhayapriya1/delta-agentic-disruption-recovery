"""Start real cloud-backed product APIs and private presenter console.

Creates a new P001-only 90-minute token, fresh ledgers and temporary tunnel.
Requires the existing authorized Salesforce org. No fixture fallback is used.
"""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time

import jwt
import uvicorn
from fastapi import FastAPI

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
run=ROOT/'tmp/recording';run.mkdir(parents=True,exist_ok=True)
if (run/'happy.sqlite3').exists():
    raise SystemExit('Recording ledger exists. Archive tmp/recording before starting a new run; never overwrite execution evidence.')
cloudflared=str(ROOT/'tools/cloudflared') if (ROOT/'tools/cloudflared').exists() else shutil.which('cloudflared')
if not cloudflared:raise SystemExit('Install cloudflared before starting the recording demo')
secret=secrets.token_urlsafe(48);issued=int(time.time())
token=jwt.encode({'sub':'P001','role':'passenger','iat':issued,'exp':issued+5400,'iss':'delta-demo','aud':'delta-api'},secret,algorithm='HS256')
runtime={'secret':secret,'token':token,'expires_at':issued+5400,'subject':'P001'}
p=run/'runtime.json';p.write_text(json.dumps(runtime));p.chmod(0o600)
os.environ.update(DELTA_JWT_SECRET=secret,DELTA_CONTEXT_MODE='data360_federation',DELTA_SALESFORCE_SYNC='true',DELTA_DATA360_REST_GRAPH='true',DELTA_DATA360_UNIFIED_GRAPH='true',DELTA_ENABLE_FAULTS='true',DELTA_AUDIT=str(run/'audit.jsonl'))
from delta_demo.app import create_app
product=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
product.mount('/failure',create_app(str(run/'failure.sqlite3')))
product.mount('/',create_app(str(run/'happy.sqlite3')))
threading.Thread(target=lambda:uvicorn.run(product,host='127.0.0.1',port=8000,access_log=False),daemon=True).start()
tunnel=subprocess.Popen([cloudflared,'tunnel','--url','http://127.0.0.1:8000','--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
try:
    for line in tunnel.stdout:
        match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
        if match:
            runtime['url']=match.group(0);p.write_text(json.dumps(runtime));p.chmod(0o600);break
    else: raise RuntimeError('Temporary tunnel failed')
    from demo.server import configure_endpoint,sf
    configure_endpoint()
    import tempfile
    body={'externalCredential':'Delta_External','principalName':'DemoPassenger','principalType':'NamedPrincipal','credentials':{'DeltaToken':{'value':token,'encrypted':True}}}
    with tempfile.TemporaryDirectory(dir=run) as folder:
        b=Path(folder)/'credential.json';b.write_text(json.dumps(body));b.chmod(0o600)
        result=sf('api','request','rest','/services/data/v68.0/named-credentials/credential','--method','PUT','--body','@'+str(b))
        if result.get('statusCode') not in (200,201,204):raise RuntimeError('Credential configuration failed')
    print('Real demo ready: http://127.0.0.1:8765 (private console); synthetic API tunnel active',flush=True)
    from demo.server import app
    uvicorn.run(app,host='127.0.0.1',port=8765,access_log=False)
finally:
    try:
        if 'configure_endpoint' in globals():
            configure_endpoint(False)
    finally:
        tunnel.terminate()
