"""Actual native federation verification, including reversible synthetic mutations.

Run with authorized Salesforce CLI and Snowflake bootstrap Keychain credentials.
No tokens, passwords or private keys are written to evidence.
"""
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from delta_demo.cloud import connect
from delta_demo.federation import Data360SnowflakeContext, query_data360

out={'executed_at':datetime.now(timezone.utc).isoformat(),'simulation':False,'checks':[],'queries':[],'mutations':[]}
def check(name, value):
    out['checks'].append({'name':name,'passed':bool(value)})
    if not value:
        Path('evidence/native-federation-verification.json').write_text(json.dumps(out,indent=2,default=str)+'\n')
        raise AssertionError(name)
def query(label,sql):
    r=query_data360(sql);out['queries'].append({'label':label,'sql':sql,**r});return r['body']['data']
def lookup(label,subject):
    r=Data360SnowflakeContext().lookup(subject);out['queries'].append({'label':label,'context':r});return r

c=None
original=None
try:
    meta=json.loads(Path('evidence/native-snowflake-data-streams.json').read_text())['result']['body']['dataStreams']
    check('Three active native external streams with acceleration disabled',len(meta)==3 and all(s['dataAccessMode']=='DIRECT_ACCESS' and s['status']=='ACTIVE' and not s['refreshConfig']['isAccelerationEnabled'] for s in meta))
    c=connect(role='ACCOUNTADMIN')
    with c.cursor() as cur:
        cur.execute("SELECT l.MILES, c.ALLOWED FROM DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES l JOIN DELTA_DEMO.CUSTOMER_360.CONSENT c ON l.PASSENGER_ID=c.PASSENGER_ID WHERE l.PASSENGER_ID='P012' AND c.PURPOSE='disruption_service'")
        original=cur.fetchone();check('Synthetic mutation target uniquely found',original is not None)
        for table,dlo in [('LOYALTY_PROFILES','Loyalty'),('CONSENT','Consent'),('TRAVEL_HISTORY','Travel')]:
            cur.execute('SELECT COUNT(*) FROM DELTA_DEMO.CUSTOMER_360.'+table);source_count=cur.fetchone()[0]
            rows=query(table+' count','SELECT COUNT(*) FROM Delta_Snowflake_'+dlo+'__dll')
            check(table+' source/native counts reconcile',rows==[[source_count]])
    p001=lookup('P001 consent-granted profile','P001');check('P001 actual native context',p001['tier']=='GOLD' and p001['miles']==42000)
    check('P007 consent denied yields no native context',lookup('P007 consent-negative','P007') is None)
    baseline=lookup('P012 baseline','P012');check('P012 native baseline matches source',baseline['miles']==int(original[0]))
    with c.cursor() as cur:
        cur.execute("UPDATE DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES SET MILES=%s WHERE PASSENGER_ID='P012'",(int(original[0])+424,));out['mutations'].append({'action':'temporary synthetic mileage update','query_id':cur.sfqid})
    changed=lookup('P012 immediately after source update','P012');check('Uncached native query sees source update without ingestion',changed['miles']==int(original[0])+424)
    with c.cursor() as cur:
        cur.execute("UPDATE DELTA_DEMO.CUSTOMER_360.CONSENT SET ALLOWED=FALSE WHERE PASSENGER_ID='P012' AND PURPOSE='disruption_service'");out['mutations'].append({'action':'temporary synthetic consent revocation','query_id':cur.sfqid})
    check('Native consent revocation immediately blocks context',lookup('P012 revoked consent','P012') is None)
finally:
    if c is not None and original is not None:
        with c.cursor() as cur:
            cur.execute("UPDATE DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES SET MILES=%s WHERE PASSENGER_ID='P012'",(original[0],));out['mutations'].append({'action':'restore original synthetic miles','query_id':cur.sfqid})
            cur.execute("UPDATE DELTA_DEMO.CUSTOMER_360.CONSENT SET ALLOWED=%s WHERE PASSENGER_ID='P012' AND PURPOSE='disruption_service'",(original[1],));out['mutations'].append({'action':'restore original synthetic consent','query_id':cur.sfqid})
        restored=lookup('P012 restored source state','P012');check('Source and native context restored',restored is not None and restored['miles']==int(original[0]))
    Path('evidence/native-federation-verification.json').write_text(json.dumps(out,indent=2,default=str)+'\n')

# Exercise actual native context through the application boundary, in-process.
# This bearer exists only inside this test process; no tunnel transmission.
import jwt
from fastapi.testclient import TestClient
from delta_demo.app import create_app
secret=secrets.token_urlsafe(48)
os.environ.update(DELTA_CONTEXT_MODE='data360_federation',DELTA_DATA360_UNIFIED_GRAPH='true',DELTA_AUDIT='tmp/native-federation-api-audit.jsonl')
now=int(time.time());token=jwt.encode({'sub':'P001','role':'passenger','iat':now,'exp':now+120,'iss':'delta-demo','aud':'delta-api'},secret,algorithm='HS256')
with TestClient(create_app('tmp/native-federation-verification.sqlite3',secret=secret)) as client:
    r=client.get('/customer-context',headers={'Authorization':'Bearer '+token})
    out['api']={'transport':'in-process ASGI; actual Salesforce/native Snowflake calls','status':r.status_code,'body':r.json()}
    check('FastAPI native federated context succeeds with verified unified identity',r.status_code==200 and r.json()['adapter']=='native_data360_snowflake' and r.json()['data360_context']['native_unified_merge_verified'])

# Corroborate Salesforce-issued source SQL from the actual Snowflake query history.
with c.cursor() as cur:
    cur.execute("SELECT QUERY_ID, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, QUERY_TEXT, EXECUTION_STATUS, START_TIME FROM TABLE(DELTA_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(USER_NAME=>'DELTA_DEMO_CONTEXT_SERVICE',RESULT_LIMIT=>100)) WHERE START_TIME >= DATEADD('minute',-30,CURRENT_TIMESTAMP()) AND QUERY_TEXT ILIKE '%LOYALTY_PROFILES%' ORDER BY START_TIME DESC")
    names=[d[0].lower() for d in cur.description];out['snowflake_query_history']=[dict(zip(names,row)) for row in cur.fetchall()]
    check('Snowflake history proves Salesforce-issued native source queries',any(all(part in row['query_text'] for part in ['cast_PASSENGER_ID', 'CONSENT', 'LOYALTY_PROFILES', 'disruption_service']) and row['execution_status']=='SUCCESS' and row['role_name']=='DELTA_DEMO_CONTEXT' for row in out['snowflake_query_history']))
c.close()
out['passed']=all(x['passed'] for x in out['checks'])
Path('evidence/native-federation-verification.json').write_text(json.dumps(out,indent=2,default=str)+'\n')
print(json.dumps({'passed':out['passed'],'checks':len(out['checks']),'file':'evidence/native-federation-verification.json'}))
