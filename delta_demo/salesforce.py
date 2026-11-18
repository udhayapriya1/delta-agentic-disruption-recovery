"""Local CLI-backed Salesforce adapter. Hosted deployment requires a service OAuth identity."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import html


def verified_demo_graph(passenger_id, unified=False):
    """Real Data 360 REST fallback for this fixed P001-only developer pilot.

    The local Salesforce CLI credential is never returned to the caller.
    Native ConnectApi graph reads were tested and returned null in this org.
    """
    if passenger_id != 'P001':
        raise ValueError('Data Graph pilot is restricted to P001')
    graph_name='Passenger_Disruption_Context'
    record_id='a00bm00003QTT4XAAX'
    link_query_id=None
    if unified:
        sql="SELECT SourceRecordId__c, UnifiedRecordId__c FROM UnifiedLinkssotIndividualDlt__dlm WHERE SourceRecordId__c IN ('a00bm00003QTT4XAAX','a00bm00003QTT4YAAX')"
        with tempfile.TemporaryDirectory(prefix='delta-link-') as folder:
            p=Path(folder)/'query.json';p.write_text(json.dumps({'sql':sql}));p.chmod(0o600)
            query=subprocess.run(['sf','api','request','rest','/services/data/v68.0/ssot/queryv2','--method','POST','--body','@'+str(p),'--target-org',os.getenv('DELTA_SALESFORCE_ORG','delta-dev'),'--json'],capture_output=True,text=True,timeout=15)
        if query.returncode:raise RuntimeError('Native unified identity lookup unavailable')
        body=json.loads(query.stdout)['result']['body']
        links={row[0]:row[1] for row in body.get('data',[])}
        expected={'a00bm00003QTT4XAAX','a00bm00003QTT4YAAX'}
        if set(links)!=expected or len(set(links.values()))!=1:
            raise ValueError('Native duplicate identity not unified; autonomous context blocked')
        record_id=next(iter(links.values()))
        if not re.fullmatch(r'[a-f0-9]{32}',record_id):raise ValueError('Unexpected unified identifier')
        graph_name='Delta_Unified_Disruption';link_query_id=body.get('queryId')
    route=f'/services/data/v68.0/ssot/data-graphs/data/{graph_name}/{record_id}?dataspace=default&live=true'
    r=subprocess.run(['sf','api','request','rest',route,'--target-org',os.getenv('DELTA_SALESFORCE_ORG','delta-dev'),'--json'],capture_output=True,text=True,timeout=15)
    if r.returncode:
        raise RuntimeError('Data 360 REST lookup unavailable')
    result=json.loads(r.stdout)['result']
    if result.get('statusCode') != 200:
        raise RuntimeError('Data 360 REST lookup failed')
    rows=result['body']['data']
    facts=json.loads(html.unescape(rows[0]['json_blob__c']))
    if facts.get('ssot__ExternalRecordId__c') != 'SYN0000001':
        raise ValueError('Data 360 synthetic profile binding mismatch')
    return {'graph':graph_name,'profile_binding_verified':True,
            'adapter':'real Salesforce REST via local authorized CLI; native Apex fallback',
            'source_field':'ssot__ExternalRecordId__c','native_unified_merge_verified':unified,
            'unified_link_query_id':link_query_id,
            'request_id':result.get('headers',{}).get('x-request-id')}


def update_handoff(case_id, context):
    if not re.fullmatch(r'500[A-Za-z0-9]{12,15}',case_id):
        raise ValueError('Verified Case ID required')
    body={'Status':'Working','Description':json.dumps({'human_review_required':True,'handoff':context,'delivery':'Case updated; Omni-Channel routing and human acknowledgement unverified'})}
    with tempfile.TemporaryDirectory(prefix='delta-handoff-') as folder:
        p=Path(folder)/'request.json';p.write_text(json.dumps(body));p.chmod(0o600)
        r=subprocess.run(['sf','api','request','rest','/services/data/v68.0/sobjects/Case/'+case_id,'--method','PATCH','--body','@'+str(p),'--target-org',os.getenv('DELTA_SALESFORCE_ORG','delta-dev'),'--json'],capture_output=True,text=True,timeout=15)
        if r.returncode:raise RuntimeError('Salesforce handoff update unavailable')
    return {'case_id':case_id,'case_updated':True,'human_acknowledged':False,'omni_channel_verified':False}


def upsert_confirmed_case(booking):
    confirmation=booking['confirmation']
    if not re.fullmatch(r'SYN-[A-Z0-9]{12}',confirmation):
        raise ValueError('Authoritative synthetic confirmation format required')
    body={'Subject':'Synthetic disruption recovery '+confirmation,'Status':'New','Origin':'Web',
          'Description':json.dumps({'confirmation':confirmation,'option':booking['selected_option'],'booked_at':booking['booked_at'],'source_query_id':booking.get('context_query_id'),'source':'actual FastAPI reservation transaction; real Snowflake context'})}
    alias=os.getenv('DELTA_SALESFORCE_ORG','delta-dev')
    with tempfile.TemporaryDirectory(prefix='delta-case-') as folder:
        p=Path(folder)/'request.json';p.write_text(json.dumps(body));p.chmod(0o600)
        r=subprocess.run(['sf','api','request','rest',f'/services/data/v68.0/sobjects/Case/Delta_Transaction_Id__c/{confirmation}','--method','PATCH','--body','@'+str(p),'--target-org',alias,'--json'],capture_output=True,text=True,timeout=45)
        if r.returncode:
            raise RuntimeError('Salesforce Case upsert unavailable; confirmation retained for retry')
    query=f"SELECT Id,CaseNumber,Delta_Transaction_Id__c FROM Case WHERE Delta_Transaction_Id__c='{confirmation}' LIMIT 1"
    r=subprocess.run(['sf','data','query','--target-org',alias,'--query',query,'--json'],capture_output=True,text=True,timeout=45)
    if r.returncode:
        raise RuntimeError('Salesforce Case verification unavailable')
    records=json.loads(r.stdout).get('result',{}).get('records',[])
    if len(records)!=1:raise RuntimeError('Salesforce Case verification missing')
    return {'case_id':records[0]['Id'],'case_number':records[0]['CaseNumber'],'transaction_id':records[0]['Delta_Transaction_Id__c'],'verified':True}


def reconcile_handoffs(db_path):
    """Single-worker recovery of durable handoffs; no new booking or notification.

    Repeat PATCH to the same Case is idempotent. Deploy a distributed lease and
    a monotonic revision check at the remote boundary before multiple workers.
    """
    import sqlite3
    report=[]
    with sqlite3.connect(db_path) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("SELECT * FROM handoff_outbox WHERE status='PENDING'").fetchall()
    for row in rows:
        status='PENDING'
        try:
            update_handoff(row['salesforce_case_id'],json.loads(row['context_json']))
            status='SYNCED'
        except Exception:
            pass  # Credential/error details must never enter persisted diagnostics.
        with sqlite3.connect(db_path) as c:
            changed=c.execute('UPDATE handoff_outbox SET status=?,attempts=attempts+1 WHERE case_ref=? AND context_json=?',(status,row['case_ref'],row['context_json'])).rowcount
        report.append({'case_ref':row['case_ref'],'status':status if changed else 'SUPERSEDED','human_acknowledged':False})
    return report
