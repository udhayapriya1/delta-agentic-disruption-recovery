"""Executable synthetic operations. Customer history requires real Snowflake by default."""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ConfigDict

from delta_demo.cloud import SnowflakeContext


def now():
    return datetime.now(timezone.utc).isoformat()


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pnr: str = Field(pattern=r'^D\d{5}$')
    option_id: str = Field(pattern=r'^OPT-[12]$')


class Rebook(Selection):
    passenger_ref: str = Field(pattern=r'^P\d{3}$')
    acceptance_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)


class Voucher(BaseModel):
    model_config = ConfigDict(extra='forbid')
    passenger_ref: str = Field(pattern=r'^P\d{3}$')
    amount: Decimal = Field(gt=0, le=5000, decimal_places=2)
    reason: str = Field(min_length=1, max_length=300)
    case_ref: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    approval_id: str | None = None


class Approval(BaseModel):
    voucher_request_id: str


class Escalation(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class Fault(BaseModel):
    mode: Literal['normal', 'conflict', 'timeout', 'unavailable']


def create_app(db_path=None, context=None, secret=None):
    secret = secret or os.environ.get('DELTA_JWT_SECRET', '')
    if len(secret) < 32:
        raise RuntimeError('Set DELTA_JWT_SECRET to at least 32 random characters; no default credential')
    db_path = db_path or os.getenv('DELTA_DB', 'tmp/delta.sqlite3')
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title='Delta Synthetic Disruption Integration', version='0.1.0',
                  description='Executable synthetic reservation/voucher service; real Snowflake customer adapter. Salesforce integration not implied.')
    context_mode = os.getenv('DELTA_CONTEXT_MODE', 'snowflake_python')
    if context is not None:
        cloud = context
    elif context_mode == 'data360_federation':
        from delta_demo.federation import Data360SnowflakeContext
        cloud = Data360SnowflakeContext()
    elif context_mode == 'snowflake_python':
        cloud = SnowflakeContext()
    else:
        raise RuntimeError('Unsupported DELTA_CONTEXT_MODE; no implicit fallback')
    app.state.fault = 'normal'
    app.state.db_path = db_path
    app.state.audit = []
    audit_lock = threading.Lock()
    limits = defaultdict(deque)
    limit_lock = threading.Lock()
    bearer = HTTPBearer(auto_error=False)
    cap = Decimal(os.getenv('DELTA_VOUCHER_CAP', '200'))

    @contextmanager
    def db():
        c = sqlite3.connect(db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS passengers(id TEXT PRIMARY KEY,pnr TEXT,consent INTEGER,special TEXT,cabin TEXT);
        CREATE TABLE IF NOT EXISTS options(id TEXT PRIMARY KEY,flight TEXT,departure TEXT,arrival TEXT,cabin TEXT,seats INTEGER);
        CREATE TABLE IF NOT EXISTS flights(id TEXT PRIMARY KEY,status TEXT,departure TEXT,reason TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS acceptance(id TEXT PRIMARY KEY,passenger TEXT,option_id TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS ledger(key TEXT PRIMARY KEY,digest TEXT,response TEXT);
        CREATE TABLE IF NOT EXISTS case_outbox(confirmation TEXT PRIMARY KEY,booking_json TEXT,result_json TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS handoff_outbox(case_ref TEXT PRIMARY KEY,salesforce_case_id TEXT,context_json TEXT,status TEXT,attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS bookings(id TEXT PRIMARY KEY,passenger TEXT UNIQUE,option_id TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,passenger TEXT UNIQUE,status TEXT,context TEXT);
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,passenger TEXT,amount TEXT,case_ref TEXT);
        CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,approver TEXT,used INTEGER DEFAULT 0);
        ''')
        records = json.loads(Path('data/synthetic-passengers.json').read_text())
        for r in records:
            c.execute('INSERT OR IGNORE INTO passengers VALUES(?,?,?,?,?)', (r['passenger_id'],r['pnr'],r['consent'],r['special'],r['cabin']))
        departure = datetime.now(timezone.utc) + timedelta(hours=3)
        c.execute('INSERT OR IGNORE INTO flights VALUES(?,?,?,?,?)',('DL-SYN0','CANCELLED',departure.isoformat(),'Synthetic weather disruption',now()))
        for i in [1,2]:
            c.execute('INSERT OR IGNORE INTO options VALUES(?,?,?,?,?,?)', (f'OPT-{i}',f'DL-SYN{i}',(departure+timedelta(hours=i)).isoformat(),(departure+timedelta(hours=i+2)).isoformat(),'ECONOMY',5))

    def pseudonym(value):
        import hmac
        return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:16]

    @app.middleware('http')
    async def trace(request: Request, call_next):
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(status_code=500, content={'detail': 'Internal service failure; contact support', 'trace_id': trace_id})
        response.headers['X-Trace-ID'] = trace_id
        entry = dict(trace_id=trace_id, endpoint=request.url.path, method=request.method,
                     status=response.status_code, timestamp=now(), latency_ms=round((time.monotonic()-start)*1000,2))
        # No headers, query strings, request bodies, free text or credentials in traces.
        with audit_lock:
            app.state.audit.append(entry)
            path = Path(os.getenv('DELTA_AUDIT', 'tmp/audit.jsonl'))
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a') as f:
                f.write(json.dumps(entry)+'\n')
        return response

    def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None:
            raise HTTPException(401, 'Bearer token required')
        try:
            claims = jwt.decode(credentials.credentials, secret, algorithms=['HS256'], audience='delta-api', issuer='delta-demo', options={'require': ['exp','iat','sub','role','aud','iss']})
            if claims['role'] not in ['passenger','approver','operator']:
                raise ValueError('role')
        except (jwt.PyJWTError, ValueError):
            raise HTTPException(401, 'Invalid or expired credential')
        with limit_lock:
            bucket = limits[pseudonym(claims['sub'])]
            cutoff = time.monotonic()-60
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= 120:
                raise HTTPException(429, 'Rate limit exceeded')
            bucket.append(time.monotonic())
        return claims

    def passenger(c, claims, pnr=None, consequential=False):
        if claims['role'] != 'passenger':
            raise HTTPException(403, 'Passenger session required')
        r = c.execute('SELECT * FROM passengers WHERE id=?', (claims['sub'],)).fetchone()
        if not r or (pnr and r['pnr'] != pnr):
            raise HTTPException(403, 'Passenger booking not authorized')
        if not r['consent']:
            raise HTTPException(403, 'Service-purpose consent unavailable')
        if consequential and r['special'] != 'routine':
            cid = case(c, r['id'])
            c.execute('UPDATE cases SET status=?,context=? WHERE id=?', ('ESCALATED',json.dumps({'reason':r['special'],'passenger_ref':pseudonym(r['id']),'system':'local case; Salesforce unverified'}),cid))
            # Only the handoff commits here; no consequential write has occurred.
            c.commit()
            raise HTTPException(409, {'reason':'Human assistance required','case_ref':cid,'case_system':'local'})
        return r

    def case(c, subject):
        existing = c.execute('SELECT * FROM cases WHERE passenger=?', (subject,)).fetchone()
        if existing:
            return existing['id']
        case_id='CASE-'+uuid.uuid4().hex[:12]
        c.execute('INSERT INTO cases VALUES(?,?,?,?)',(case_id,subject,'OPEN','{}'))
        return case_id

    def digest(payload):
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def replay(c, claims, kind, key, payload):
        scoped = digest([claims['sub'],kind,key])
        fingerprint = digest(payload)
        r = c.execute('SELECT * FROM ledger WHERE key=?',(scoped,)).fetchone()
        if r:
            if r['digest'] != fingerprint:
                raise HTTPException(409, 'Idempotency key payload mismatch')
            return scoped, fingerprint, json.loads(r['response'])
        return scoped, fingerprint, None

    def save(c, key, fingerprint, response):
        c.execute('INSERT INTO ledger VALUES(?,?,?)',(key,fingerprint,json.dumps(response)))

    def fault():
        if app.state.fault == 'timeout':
            raise HTTPException(504, 'Synthetic dependency timeout; no transaction attempted')
        if app.state.fault == 'unavailable':
            raise HTTPException(503, 'Reservation dependency unavailable')

    @app.get('/health')
    def health():
        return {'status':'ok', 'operations':'synthetic', 'customer_context':'real Snowflake required',
                'context_mode':context_mode,
                'salesforce_sync_configured':os.getenv('DELTA_SALESFORCE_SYNC')=='true',
                'native_unified_graph_required':os.getenv('DELTA_DATA360_UNIFIED_GRAPH')=='true',
                'dependency_readiness':'not probed by health endpoint'}

    @app.get('/customer-context')
    def customer_context(claims=Depends(principal)):
        with db() as c:
            p = passenger(c, claims)
        graph = None
        if os.getenv('DELTA_DATA360_REST_GRAPH') == 'true' or os.getenv('DELTA_DATA360_UNIFIED_GRAPH') == 'true':
            try:
                from delta_demo.salesforce import verified_demo_graph
                graph = verified_demo_graph(p['id'],unified=os.getenv('DELTA_DATA360_UNIFIED_GRAPH')=='true')
            except Exception:
                raise HTTPException(503, 'Data 360 profile binding unavailable; context blocked')
        try:
            result = cloud.lookup(p['id'])
        except Exception:
            raise HTTPException(503, 'Snowflake context unavailable; autonomous eligibility blocked')
        if not result:
            raise HTTPException(404, 'Grounded loyalty context unavailable')
        return {**result, 'passenger_ref':pseudonym(p['id']), 'contact':'masked', 'consent_purpose':'disruption_service', 'data360_context':graph}

    @app.get('/flight-status')
    def status(pnr: str, claims=Depends(principal)):
        with db() as c:
            passenger(c, claims, pnr)
        fault()
        with db() as c:
            r = c.execute('SELECT * FROM flights WHERE id=?', ('DL-SYN0',)).fetchone()
        return {'flight':r['id'],'status':r['status'],'route':'ATL-JFK','reason':r['reason'],'source_timestamp':r['updated_at'],'scheduled_departure':r['departure'],'source_field':'reservation.flight.status'}

    @app.get('/rebook-options')
    def options(pnr: str, claims=Depends(principal)):
        with db() as c:
            p=passenger(c, claims, pnr, True)
        fault()
        context=None
        if os.getenv('DELTA_DATA360_UNIFIED_GRAPH')=='true':
            context=customer_context(claims=claims)
            if context.get('tier') not in ['SILVER','GOLD','PLATINUM','DIAMOND']:
                raise HTTPException(403,'Verified Medallion context required before offering recovery options')
        with db() as c:
            p=passenger(c,claims,pnr,True)
            result={'options':[dict(r) for r in c.execute('SELECT * FROM options WHERE seats>0 AND cabin=? ORDER BY departure',(p['cabin'],))], 'source_timestamp':now(),'source_field':'reservation.inventory'}
        if context:result['eligibility_context']={'data360_context':context['data360_context'],'snowflake_query_id':context['query_id'],'tier':context['tier']}
        return result

    @app.post('/acceptance')
    def accept(body: Selection, claims=Depends(principal)):
        with db() as c:
            p=passenger(c, claims, body.pnr, True)
            option=c.execute('SELECT * FROM options WHERE id=? AND seats>0 AND cabin=?',(body.option_id,p['cabin'])).fetchone()
            if not option:
                raise HTTPException(409, 'Option unavailable')
            acceptance='ACC-'+uuid.uuid4().hex
            c.execute('INSERT INTO acceptance VALUES(?,?,?,?)',(acceptance,p['id'],body.option_id,time.time()+300))
            return {'acceptance_id':acceptance,'expires_in_seconds':300,'option_id':body.option_id}

    def rebook_transaction(body: Rebook, claims=Depends(principal)):
        # Authorization precedes a cloud lookup; token subject, never free text, selects context.
        with db() as c:
            p = passenger(c, claims, body.pnr, True)
            if body.passenger_ref != p['id']:
                raise HTTPException(403, 'Passenger mismatch')
            _, _, previous = replay(c, claims, 'rebook', body.idempotency_key, body.model_dump())
            if previous:
                return previous
        try:
            native_context=None
            if os.getenv('DELTA_DATA360_UNIFIED_GRAPH')=='true':
                from delta_demo.salesforce import verified_demo_graph
                native_context=verified_demo_graph(claims['sub'],unified=True)
            grounded = cloud.lookup(claims['sub'])
        except Exception:
            raise HTTPException(503, 'Verified customer eligibility unavailable; reconcile existing booking before retry')
        if not grounded or grounded.get('tier') not in ['SILVER','GOLD','PLATINUM','DIAMOND']:
            raise HTTPException(403, 'Grounded Medallion eligibility unavailable')
        with db() as c:
            p=passenger(c, claims, body.pnr, True)
            if body.passenger_ref != p['id']:
                raise HTTPException(403,'Passenger mismatch')
            key,fingerprint,previous=replay(c,claims,'rebook',body.idempotency_key,body.model_dump())
            if previous:
                return previous
            fault()
            accepted=c.execute('SELECT * FROM acceptance WHERE id=? AND passenger=? AND option_id=? AND expires>?',(body.acceptance_id,p['id'],body.option_id,time.time())).fetchone()
            if not accepted:
                raise HTTPException(403,'Explicit current selection acceptance required')
            if c.execute('SELECT 1 FROM bookings WHERE passenger=?',(p['id'],)).fetchone():
                raise HTTPException(409,'Passenger already rebooked; reconcile existing transaction')
            if app.state.fault == 'conflict':
                raise HTTPException(409,'Seat lost; retrieve current options and renew acceptance')
            option = c.execute('SELECT * FROM options WHERE id=?', (body.option_id,)).fetchone()
            original = c.execute('SELECT departure,status FROM flights WHERE id=?', ('DL-SYN0',)).fetchone()
            if not original or original['status']!='CANCELLED':
                raise HTTPException(409,'Verified cancellation required before disruption rebooking')
            if not option or not 0 <= (datetime.fromisoformat(option['departure'])-datetime.fromisoformat(original['departure'])).total_seconds() <= 86400:
                raise HTTPException(409, 'Option outside approved 24-hour route window')
            if c.execute('UPDATE options SET seats=seats-1 WHERE id=? AND seats>0 AND cabin=?',(body.option_id,p['cabin'])).rowcount != 1:
                raise HTTPException(409,'Seat unavailable; refresh options')
            confirmation='SYN-'+uuid.uuid4().hex[:12].upper()
            created=now()
            c.execute('INSERT INTO bookings VALUES(?,?,?,?)',(confirmation,p['id'],body.option_id,created))
            case_id=case(c,p['id'])
            response={'confirmation':confirmation,'updated_pnr':p['pnr'],'selected_option':body.option_id,'booked_at':created,'case_ref':case_id,'case_system':'local pending Salesforce integration','context_query_id':grounded['query_id']}
            response['context_source']=grounded.get('source')
            response['context_access_mode']=grounded.get('access_mode','PYTHON_SQL')
            if native_context:response['data360_context']=native_context
            c.execute('UPDATE cases SET context=? WHERE id=?',(json.dumps(response),case_id))
            save(c,key,fingerprint,response)
            return response

    @app.post('/rebook')
    def rebook(body: Rebook, claims=Depends(principal)):
        result=rebook_transaction(body,claims)
        if os.getenv('DELTA_SALESFORCE_SYNC') == 'true':
            from delta_demo.salesforce import upsert_confirmed_case
            confirmation=result['confirmation']
            with db() as c:
                c.execute('INSERT OR IGNORE INTO case_outbox VALUES(?,?,?,?)',(confirmation,json.dumps(result),None,'PENDING'))
                existing=c.execute('SELECT status,result_json FROM case_outbox WHERE confirmation=?',(confirmation,)).fetchone()
                if existing['status']=='SYNCED' and existing['result_json']:
                    # Replaying a booking must not reset a later human-review Case.
                    return {**result,'salesforce_case':json.loads(existing['result_json'])}
            try:
                sf_case=upsert_confirmed_case(result)
                with db() as c:
                    c.execute('UPDATE case_outbox SET result_json=?,status=? WHERE confirmation=?',(json.dumps(sf_case),'SYNCED',confirmation))
                result={**result,'salesforce_case':sf_case}
            except Exception:
                result={**result,'salesforce_case':{'verified':False,'sync_status':'PENDING','recovery':'Replay the same idempotency key or reconcile; do not create a second booking'}}
        return result

    @app.get('/booking')
    def booking(claims=Depends(principal)):
        with db() as c:
            p=passenger(c,claims)
            r=c.execute('SELECT * FROM bookings WHERE passenger=?',(p['id'],)).fetchone()
            return {'booking':dict(r) if r else None}

    @app.post('/escalate')
    def escalate(body: Escalation, claims=Depends(principal)):
        with db() as c:
            p=passenger(c,claims)
            case_id=case(c,p['id'])
            # Free text never changes policy; do not echo it into grounded context.
            context={'passenger_ref':pseudonym(p['id']),'pnr_ref':pseudonym(p['pnr']),'reason':'passenger_requested_human',
                     'booking': [dict(r) for r in c.execute('SELECT * FROM bookings WHERE passenger=?',(p['id'],))],
                     'options_presently_available':[dict(r) for r in c.execute('SELECT * FROM options WHERE seats>0')],
                     'voucher_requests':[dict(r) for r in c.execute('SELECT id,amount FROM requests WHERE passenger=?',(p['id'],))],
                     'audit_references':[r['trace_id'] for r in app.state.audit[-10:]],
                     'loyalty_context':'not retrieved for handoff; requires real Snowflake lookup',
                     'status':'CANCELLED','source':'synthetic reservation','case_ref':case_id,'system':'local durable handoff','human_acknowledged':False,'omni_channel_verified':False}
            c.execute('UPDATE cases SET status=?,context=? WHERE id=?',('ESCALATED',json.dumps(context),case_id))
            outbox=c.execute("SELECT o.result_json,o.booking_json FROM case_outbox o JOIN bookings b ON b.id=o.confirmation WHERE o.status='SYNCED' AND b.passenger=? ORDER BY b.created_at DESC LIMIT 1",(p['id'],)).fetchone()
        if outbox:
            transaction=json.loads(outbox['booking_json'])
            context['identity_context']=transaction.get('data360_context',{'native_unified_merge_verified':False})
            context['booking_context_query_id']=transaction.get('context_query_id')
        try:
            loyalty=cloud.lookup(claims['sub'])
            context['loyalty_context']={k:loyalty[k] for k in ['tier','miles','source','source_timestamp','query_id']} if loyalty else {'status':'unavailable'}
        except Exception:
            context['loyalty_context']={'status':'unavailable','instruction':'human must reverify; no eligibility inferred'}
        with db() as c:
            c.execute('UPDATE cases SET context=? WHERE id=?',(json.dumps(context),case_id))
        if os.getenv('DELTA_SALESFORCE_SYNC')=='true' and outbox:
            sf_case_id=json.loads(outbox['result_json'])['case_id']
            payload=json.dumps(context)
            with db() as c:
                c.execute('INSERT INTO handoff_outbox VALUES(?,?,?,?,0) ON CONFLICT(case_ref) DO UPDATE SET salesforce_case_id=excluded.salesforce_case_id,context_json=excluded.context_json,status=excluded.status,attempts=0',(case_id,sf_case_id,payload,'PENDING'))
            try:
                from delta_demo.salesforce import update_handoff
                context['salesforce_handoff']=update_handoff(sf_case_id,context)
                with db() as c:
                    c.execute("UPDATE handoff_outbox SET status='SYNCED',attempts=attempts+1 WHERE case_ref=? AND context_json=?",(case_id,payload))
            except Exception:
                context['salesforce_handoff']={'case_updated':False,'retry_required':True}
        return context

    @app.post('/voucher')
    def voucher(body: Voucher, claims=Depends(principal)):
        # Recheck current source consent before each new financial operation.
        # Local profile consent may lag a native Snowflake revocation.
        with db() as c:
            p=passenger(c,claims,consequential=True)
            if p['id'] != body.passenger_ref:
                raise HTTPException(403,'Passenger mismatch')
        try:
            eligibility=cloud.lookup(claims['sub'])
        except Exception:
            raise HTTPException(503,'Current voucher eligibility unavailable; no voucher issued')
        if not eligibility:
            raise HTTPException(403,'Current service consent unavailable; no voucher issued')
        with db() as c:
            p=passenger(c,claims,consequential=True)
            if p['id'] != body.passenger_ref:
                raise HTTPException(403,'Passenger mismatch')
            owncase=c.execute('SELECT * FROM cases WHERE id=? AND passenger=?',(body.case_ref,p['id'])).fetchone()
            if not owncase:
                raise HTTPException(403,'Case ownership required')
            intent=body.model_dump(mode='json')
            intent.pop('approval_id',None)
            intent_key,intent_fingerprint,recorded=replay(c,claims,'voucher-intent',body.idempotency_key,intent)
            if not recorded:
                save(c,intent_key,intent_fingerprint,{'status':'INTENT_RECORDED'})
            key,fp,previous=replay(c,claims,'voucher',body.idempotency_key,body.model_dump(mode='json'))
            if previous:
                return previous
            request_id='VR-'+digest([p['id'],body.case_ref,body.idempotency_key])[:20]
            if body.amount > cap:
                c.execute('INSERT OR IGNORE INTO requests VALUES(?,?,?,?)',(request_id,p['id'],str(body.amount),body.case_ref))
                row=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
                if row['amount'] != str(body.amount):
                    raise HTTPException(409,'Voucher request payload mismatch')
                approval=c.execute('SELECT * FROM approvals WHERE id=? AND request_id=? AND used=0',(body.approval_id,request_id)).fetchone()
                if not approval:
                    return {'status':'APPROVAL_REQUIRED','request_id':request_id,'approved_amount':0,'case_ref':body.case_ref}
                c.execute('UPDATE approvals SET used=1 WHERE id=?',(body.approval_id,))
            result={'status':'ISSUED','voucher_id':'V-'+uuid.uuid4().hex[:16],'approved_amount':str(body.amount),'case_ref':body.case_ref}
            save(c,key,fp,result)
            return result

    @app.post('/approvals')
    def approve(body: Approval, claims=Depends(principal)):
        if claims['role'] != 'approver':
            raise HTTPException(403,'Human approver role required')
        with db() as c:
            r=c.execute('SELECT * FROM requests WHERE id=?',(body.voucher_request_id,)).fetchone()
            if not r:
                raise HTTPException(404,'Request unavailable')
            if r['passenger'] == claims['sub']:
                raise HTTPException(403,'Self approval prohibited')
            existing=c.execute('SELECT id FROM approvals WHERE request_id=?',(body.voucher_request_id,)).fetchone()
            if existing:
                return {'approval_id':existing['id']}
            aid='AP-'+uuid.uuid4().hex
            c.execute('INSERT INTO approvals VALUES(?,?,?,0)',(aid,body.voucher_request_id,pseudonym(claims['sub'])))
            return {'approval_id':aid}

    @app.post('/admin/remove-seat')
    def remove_seat(body: Selection, claims=Depends(principal)):
        if claims['role'] != 'operator' or os.getenv('DELTA_ENABLE_FAULTS') != 'true':
            raise HTTPException(403, 'Operator demo mode required')
        with db() as c:
            changed = c.execute('UPDATE options SET seats=0 WHERE id=?', (body.option_id,)).rowcount
            if not changed:
                raise HTTPException(404, 'Option not found')
        return {'option_id':body.option_id,'available':False}

    @app.post('/admin/fault')
    def set_fault(body: Fault, claims=Depends(principal)):
        if claims['role'] != 'operator' or os.getenv('DELTA_ENABLE_FAULTS') != 'true':
            raise HTTPException(403,'Operator demo mode required')
        app.state.fault=body.mode
        return {'mode':body.mode}

    return app
