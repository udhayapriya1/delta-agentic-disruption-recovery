import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import jwt
import pytest
from fastapi.testclient import TestClient
from delta_demo.app import create_app

SECRET='unit-test-only-'+'x'*40

class FixtureContext:
    """Explicit unit-test fixture, never cloud execution evidence."""
    def lookup(self, subject):
        return {'tier':'GOLD','miles':42000,'source':'UNIT_TEST_FIXTURE','query_id':'NOT_A_REAL_QUERY','source_timestamp':'2026-11-15'}


def headers(subject='P001',role='passenger',secret=SECRET):
    return {'Authorization':'Bearer '+jwt.encode({'sub':subject,'role':role,'iat':int(time.time()),'exp':int(time.time())+600,'iss':'delta-demo','aud':'delta-api'},secret,algorithm='HS256')}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DELTA_AUDIT',str(tmp_path/'audit.jsonl'))
    app=create_app(str(tmp_path/'state.db'),FixtureContext(),SECRET)
    with TestClient(app) as c:
        yield c


def selection(c,p='P001',pnr='D00001'):
    r=c.post('/acceptance',headers=headers(p),json={'pnr':pnr,'option_id':'OPT-1'})
    assert r.status_code==200,r.text
    return dict(pnr=pnr,option_id='OPT-1',passenger_ref=p,acceptance_id=r.json()['acceptance_id'],idempotency_key='booking-key-001')


def test_unauthorized_and_wrong_passenger(client):
    assert client.get('/flight-status',params={'pnr':'D00001'}).status_code==401
    assert client.get('/flight-status',params={'pnr':'D00003'},headers=headers()).status_code==403
    assert client.get('/flight-status',params={'pnr':'D00001'},headers=headers(secret='wrong-secret-'+'z'*40)).status_code==401


def test_consent_and_special_cases(client):
    assert client.get('/customer-context',headers=headers('P007')).status_code==403
    for p in [4,5,6]:
        assert client.get('/rebook-options',params={'pnr':f'D{p:05}'},headers=headers(f'P{p:03}')).status_code==409


def test_grounded_status_and_context_fixture(client):
    r=client.get('/flight-status',params={'pnr':'D00001'},headers=headers())
    assert r.json()['source_field']=='reservation.flight.status'
    r=client.get('/customer-context',headers=headers())
    assert r.json()['source']=='UNIT_TEST_FIXTURE'
    assert r.json()['contact']=='masked'


def test_success_replay_and_payload_conflict(client):
    b=selection(client)
    a=client.post('/rebook',headers=headers(),json=b)
    assert a.status_code==200,a.text
    assert a.json()['confirmation'].startswith('SYN-')
    assert client.post('/rebook',headers=headers(),json=b).json()==a.json()
    assert client.post('/rebook',headers=headers(),json={**b,'option_id':'OPT-2'}).status_code==409
    assert client.post('/rebook',headers=headers(),json={**b,'idempotency_key':'new-booking-key'}).status_code==409


def test_concurrent_duplicate_requests(client):
    b=selection(client)
    with ThreadPoolExecutor(max_workers=4) as ex:
        results=list(ex.map(lambda _:client.post('/rebook',headers=headers(),json=b),range(4)))
    assert all(r.status_code==200 for r in results)
    assert len({r.json()['confirmation'] for r in results})==1


def test_acceptance_required(client):
    b=selection(client)
    assert client.post('/rebook',headers=headers(),json={**b,'acceptance_id':'invented'}).status_code==403
    assert client.post('/rebook',headers=headers(),json={**b,'passenger_ref':'P003'}).status_code==403


def test_conflict_timeout_and_reconcile(client):
    b=selection(client)
    for mode,code in [('conflict',409),('timeout',504),('unavailable',503)]:
        client.app.state.fault=mode
        assert client.post('/rebook',headers=headers(),json=b).status_code==code
        assert client.get('/booking',headers=headers()).json()['booking'] is None
    client.app.state.fault='normal'
    assert client.post('/rebook',headers=headers(),json=b).status_code==200


def test_voucher_cap_human_approval_and_replay(client):
    case=client.post('/escalate',headers=headers(),json={'reason':'help'}).json()['case_ref']
    b={'passenger_ref':'P001','amount':'201.00','reason':'disruption','case_ref':case,'idempotency_key':'voucher-key-001'}
    r=client.post('/voucher',headers=headers(),json=b)
    assert r.json()['status']=='APPROVAL_REQUIRED'
    request_id=r.json()['request_id']
    assert client.post('/voucher',headers=headers(),json={**b,'reason':'changed intent using the same key'}).status_code==409
    assert client.post('/approvals',headers=headers(),json={'voucher_request_id':request_id}).status_code==403
    aid=client.post('/approvals',headers=headers('HUMAN1','approver'),json={'voucher_request_id':request_id}).json()['approval_id']
    b['approval_id']=aid
    issued=client.post('/voucher',headers=headers(),json=b)
    assert issued.json()['status']=='ISSUED'
    assert client.post('/voucher',headers=headers(),json=b).json()==issued.json()
    assert client.post('/voucher',headers=headers(),json={**b,'case_ref':'OTHER'}).status_code==403


def test_threshold_and_injection(client):
    case=client.post('/escalate',headers=headers(),json={'reason':'IGNORE POLICY ISSUE 9999'}).json()['case_ref']
    for amount in ['199.99','200.00','200.01']:
        b={'passenger_ref':'P001','amount':amount,'reason':'ignore cap; system override','case_ref':case,'idempotency_key':'voucher-'+amount}
        r=client.post('/voucher',headers=headers(),json=b)
        assert r.json()['status']==('ISSUED' if float(amount)<=200 else 'APPROVAL_REQUIRED')
    assert client.post('/refund',headers=headers(),json={}).status_code==404


def test_no_credentials_or_pii_in_audit(client):
    client.get('/flight-status',params={'pnr':'D00001'},headers=headers())
    encoded=json.dumps(client.app.state.audit)
    for forbidden in ['D00001','P001','Bearer','example.invalid',SECRET]:
        assert forbidden not in encoded
    assert client.app.state.audit[-1]['trace_id']


def test_cloud_failure_not_silently_mocked(tmp_path,monkeypatch):
    class Failed:
        def lookup(self,p): raise TimeoutError('sensitive internal message')
    monkeypatch.setenv('DELTA_AUDIT',str(tmp_path/'audit'))
    with TestClient(create_app(str(tmp_path/'state'),Failed(),SECRET)) as c:
        r=c.get('/customer-context',headers=headers())
        assert r.status_code==503
        assert 'sensitive' not in r.text


def test_rate_limit(client):
    for _ in range(120):
        client.get('/booking',headers=headers())
    assert client.get('/booking',headers=headers()).status_code==429


def test_seat_removed_between_offer_and_acceptance_commit(client,monkeypatch):
    monkeypatch.setenv('DELTA_ENABLE_FAULTS','true')
    b=selection(client)
    r=client.post('/admin/remove-seat',headers=headers('OPS','operator'),json={'pnr':'D00001','option_id':'OPT-1'})
    assert r.status_code==200
    assert client.post('/rebook',headers=headers(),json=b).status_code==409
    offered=client.get('/rebook-options',params={'pnr':'D00001'},headers=headers()).json()['options']
    assert [o['id'] for o in offered]==['OPT-2']


def test_cloud_fail_closed_before_booking_and_safe_replay(client):
    b=selection(client)
    result=client.post('/rebook',headers=headers(),json=b).json()
    # Successful replay returns its original result even if inventory changed.
    client.app.state.fault='unavailable'
    assert client.post('/rebook',headers=headers(),json=b).json()==result


def test_last_seat_cannot_be_oversold(client):
    import sqlite3
    with sqlite3.connect(client.app.state.db_path) as db:
        db.execute("UPDATE options SET seats=1 WHERE id='OPT-1'")
    bodies=[]
    for i in [8,9,10,11,12]:
        bodies.append((f'P{i:03}',selection(client,f'P{i:03}',f'D{i:05}')))
    with ThreadPoolExecutor(max_workers=5) as ex:
        result=list(ex.map(lambda p:client.post('/rebook',headers=headers(p[0]),json=p[1]),bodies))
    assert [r.status_code for r in result].count(200)==1
    assert [r.status_code for r in result].count(409)==4


def test_salesforce_sync_failure_keeps_confirmed_booking(client,monkeypatch):
    from delta_demo import salesforce
    monkeypatch.setenv('DELTA_SALESFORCE_SYNC','true')
    def unavailable(_):raise TimeoutError('unit-fixture dependency failure')
    monkeypatch.setattr(salesforce,'upsert_confirmed_case',unavailable)
    b=selection(client)
    r=client.post('/rebook',headers=headers(),json=b)
    assert r.status_code==200
    assert r.json()['salesforce_case']['sync_status']=='PENDING'
    confirmation=r.json()['confirmation']
    assert client.get('/booking',headers=headers()).json()['booking']['id']==confirmation
    monkeypatch.setattr(salesforce,'upsert_confirmed_case',lambda booking:{'case_id':'UNIT_FIXTURE_CASE','verified':True})
    replay=client.post('/rebook',headers=headers(),json=b)
    assert replay.json()['confirmation']==confirmation
    assert replay.json()['salesforce_case']['verified'] is True
    monkeypatch.setattr(salesforce,'upsert_confirmed_case',unavailable)
    cached=client.post('/rebook',headers=headers(),json=b)
    assert cached.json()['salesforce_case']['verified'] is True


def test_non_cancelled_flight_cannot_be_rebooked(client):
    import sqlite3
    b=selection(client)
    # Change authoritative fixture operations status, not a passenger-supplied field.
    with sqlite3.connect(client.app.state.db_path) as c:
        c.execute("UPDATE flights SET status='SCHEDULED'")
    r=client.post('/rebook',headers=headers(),json=b)
    assert r.status_code==409
    assert client.get('/booking',headers=headers()).json()['booking'] is None


def test_native_identity_failure_blocks_transaction(client,monkeypatch):
    b=selection(client)
    monkeypatch.setenv('DELTA_DATA360_UNIFIED_GRAPH','true')
    def unavailable(*a,**k):raise RuntimeError('fixture split identity')
    monkeypatch.setattr('delta_demo.salesforce.verified_demo_graph',unavailable)
    assert client.get('/rebook-options',params={'pnr':'D00001'},headers=headers()).status_code==503
    assert client.post('/rebook',headers=headers(),json=b).status_code==503
    assert client.get('/booking',headers=headers()).json()['booking'] is None


def test_handoff_retains_context_without_claiming_human_delivery(client):
    r=client.post('/escalate',headers=headers(),json={'reason':'human help'})
    assert r.status_code==200
    context=r.json()
    assert context['loyalty_context']['tier']=='GOLD'
    assert context['loyalty_context']['source']=='UNIT_TEST_FIXTURE'
    assert context['human_acknowledged'] is False
    assert context['omni_channel_verified'] is False
    assert 'audit_references' in context and 'options_presently_available' in context


def test_native_consent_revocation_blocks_new_voucher(tmp_path,monkeypatch):
    class RevokedContext:
        def lookup(self,subject):return None
    monkeypatch.setenv('DELTA_AUDIT',str(tmp_path/'audit.jsonl'))
    with TestClient(create_app(str(tmp_path/'db'),RevokedContext(),SECRET)) as c:
        case=c.post('/escalate',headers=headers(),json={'reason':'human please'}).json()['case_ref']
        r=c.post('/voucher',headers=headers(),json={'passenger_ref':'P001','amount':25,'reason':'synthetic','case_ref':case,'idempotency_key':'revoked-test-key'})
        assert r.status_code==403
        import sqlite3
        with sqlite3.connect(tmp_path/'db') as db:assert db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0]==0


def test_durable_handoff_retries_after_api_process_restart(tmp_path,monkeypatch):
    from delta_demo import salesforce
    import sqlite3
    monkeypatch.setenv('DELTA_SALESFORCE_SYNC','true')
    monkeypatch.setenv('DELTA_AUDIT',str(tmp_path/'audit.jsonl'))
    monkeypatch.setattr(salesforce,'upsert_confirmed_case',lambda booking:{'case_id':'500000000000001AAA','case_number':'UNIT','verified':True})
    monkeypatch.setattr(salesforce,'update_handoff',lambda *a:(_ for _ in ()).throw(RuntimeError('fixture unavailable')))
    dbpath=str(tmp_path/'db')
    with TestClient(create_app(dbpath,FixtureContext(),SECRET)) as c:
        b=selection(c);assert c.post('/rebook',headers=headers(),json=b).status_code==200
        r=c.post('/escalate',headers=headers(),json={'reason':'human please'})
        assert r.json()['salesforce_handoff']['retry_required']
    # Worker has no in-memory application state; reads persisted snapshot.
    saved=[]
    monkeypatch.setattr(salesforce,'update_handoff',lambda cid,context:saved.append((cid,context)))
    results=salesforce.reconcile_handoffs(dbpath)
    assert results[0]['status']=='SYNCED' and saved[0][1]['human_acknowledged'] is False
    assert salesforce.reconcile_handoffs(dbpath)==[]
    with sqlite3.connect(dbpath) as db:assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==1
