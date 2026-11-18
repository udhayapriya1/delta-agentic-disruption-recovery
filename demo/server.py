"""Loopback-only presenter console. Agent replies and API traces are actual calls.

Run with scripts/start_recording_demo.py, never expose port 8765 publicly.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import time
import uuid

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'tmp/recording'
RUN.mkdir(parents=True, exist_ok=True)
STATE = RUN / 'runtime.json'
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
nonce = secrets.token_urlsafe(32)
state = {'session': None, 'failure_session': None, 'events': [], 'busy': False}
if (RUN / 'execution.json').exists():
    state['events'] = json.loads((RUN / 'execution.json').read_text())
    for event in state['events']:
        conversation = event.get('conversation')
        if isinstance(conversation, dict) and conversation.get('session_id'):
            state['failure_session' if event['action'].startswith('conflict') else 'session'] = conversation['session_id']
        if event['action'] == 'conflict-prepare':
            state['failure_acceptance'] = event['acceptance']['body']['acceptance_id']
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
job = None


def sf(*args):
    result = subprocess.run(['sf', *args, '--target-org', os.getenv('DELTA_SALESFORCE_ORG', 'delta-dev'), '--json'], capture_output=True, text=True, timeout=160)
    if result.returncode:
        raise RuntimeError('Salesforce command failed; inspect private operator logs')
    data = json.loads(result.stdout)
    if data.get('status', 0) != 0:
        raise RuntimeError('Salesforce returned unsuccessful execution')
    return data['result']


def rest(route, body):
    with tempfile.TemporaryDirectory(dir=RUN) as folder:
        p = Path(folder) / 'body.json'
        p.write_text(json.dumps(body)); p.chmod(0o600)
        result = sf('api', 'request', 'rest', route, '--method', 'POST', '--body', '@' + str(p))
    if result.get('statusCode') not in (200, 201, 202):
        raise RuntimeError('Salesforce REST operation failed')
    return result['body']


def api(path, body=None, failure=False, operator=False):
    runtime = json.loads(STATE.read_text())
    token = runtime['token']
    if operator:
        token = jwt.encode({'sub': 'demo-operator', 'role': 'operator', 'iat': int(time.time()), 'exp': int(time.time()) + 600, 'iss': 'delta-demo', 'aud': 'delta-api'}, runtime['secret'], algorithm='HS256')
    with httpx.Client(timeout=150) as client:
        response = client.request('POST' if body is not None else 'GET', 'http://127.0.0.1:8000' + ('/failure' if failure else '') + path, headers={'Authorization': 'Bearer ' + token}, json=body)
    return {'method': 'POST' if body is not None else 'GET', 'endpoint': path, 'status': response.status_code, 'trace_id': response.headers.get('X-Trace-ID'), 'body': response.json()}


def agent(prompt, failure=False):
    key = 'failure_session' if failure else 'session'
    if not state[key]:
        state[key] = sf('agent', 'preview', 'start', '--api-name', 'Delta_Medallion_Recovery')['sessionId']
    result = sf('agent', 'preview', 'send', '--api-name', 'Delta_Medallion_Recovery', '--session-id', state[key], '--utterance', prompt)
    return {'prompt': prompt, 'messages': result.get('messages', []), 'session_id': state[key]}


def rows(db, query):
    with sqlite3.connect(RUN / db) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(r) for r in connection.execute(query)]


def configure_endpoint(failure=False):
    import xml.etree.ElementTree as ET
    ns = {'m': 'http://soap.sforce.com/2006/04/metadata'}
    source = ROOT / 'salesforce/force-app/main/default/namedCredentials/Delta_Integration.namedCredential-meta.xml'
    tree = ET.fromstring(source.read_text())
    url = json.loads(STATE.read_text())['url'] + ('/failure' if failure else '')
    for p in tree.findall('m:namedCredentialParameters', ns):
        if p.find('m:parameterName', ns).text == 'DefaultEndpoint':
            p.find('m:parameterValue', ns).text = url
    ET.register_namespace('', ns['m'])
    directory = RUN / 'deploy/namedCredentials'; directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    ET.ElementTree(tree).write(target, encoding='utf-8', xml_declaration=True)
    sf('project', 'deploy', 'start', '--source-dir', str(directory), '--wait', '5')
    return {'named_credential': 'Delta_Integration', 'ledger': 'isolated failure' if failure else 'happy path', 'configured': True}


def execute(action):
    started = time.time()
    result = {'action': action, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'actual_execution': True}
    try:
        if action == 'event':
            key = 'DEMO-' + uuid.uuid4().hex[:16].upper()
            event = rest('/services/data/v68.0/sobjects/Delta_Disruption_Event__e', {'Event_Key__c': key, 'Passenger_Ref__c': 'P001', 'Flight_Ref__c': 'DL-SYN0', 'Event_Type__c': 'CANCELLED'})
            found = []
            for attempt in range(8):
                found = sf('data', 'query', '--query', "SELECT Id,CaseNumber,Status,Description FROM Case WHERE Delta_Transaction_Id__c='EVT-" + key + "'")['records']
                if found: break
                time.sleep(1)
            if not found: raise RuntimeError('Event published; Case creation not yet verified')
            result.update(event=event, cases=found, outbound_message_sent=False, note='Native platform event created this Case. Outbound messaging and event-driven Data 360 refresh are not implemented.')
        elif action == 'identity':
            from delta_demo.federation import query_data360
            body = query_data360(json.loads((ROOT / 'salesforce/data360/native-link-verification-query.json').read_text())['sql'])['body']
            links = {row[0]: row[1] for row in body['data']}
            ids = ['a00bm00003QTT4XAAX', 'a00bm00003QTT4YAAX']
            rules = json.loads((ROOT / 'salesforce/data360/identity-rules.json').read_text())
            result.update(source_records=ids, unified_ids=[links.get(x) for x in ids], duplicate_merged=all(x in links for x in ids) and links[ids[0]] == links[ids[1]], sources=len(links), profiles=len(set(links.values())), query_id=body['queryId'], rules=rules, reversal='Raw source records and preprocessing lineage are retained. Native unmerge has not been exercised.')
            if not result['duplicate_merged']: raise RuntimeError('Native merge verification failed')
        elif action == 'status':
            result['conversation'] = agent('My synthetic booking is D00001. My flight was cancelled. Retrieve my verified customer context using the customer context action and check the current flight status using the status action. Report source timestamps. Do not book anything.')
            result['context'] = api('/customer-context')
            result['flight_status'] = api('/flight-status?pnr=D00001')
        elif action == 'options':
            result['conversation'] = agent('Please retrieve current same-cabin rebooking options for D00001. Show both flights and times from the live API. Do not book anything yet.')
            result['inventory'] = api('/rebook-options?pnr=D00001')
        elif action == 'book':
            messages = []
            for prompt in ['I choose Option 1, flight DL-SYN1 in Economy, for D00001. I explicitly authorize this rebooking. Record my selection acceptance.', 'Yes, record my acceptance for Option 1 and complete the rebooking now using my recorded acceptance. Report only the confirmation returned by the service.']:
                messages.append(agent(prompt))
            booking = rows('happy.sqlite3', 'SELECT * FROM bookings')
            if not booking:
                messages.append(agent('Yes, complete the rebooking now using the recorded acceptance.'))
                booking = rows('happy.sqlite3', 'SELECT * FROM bookings')
            result.update(conversation=messages, bookings=booking, case_outbox=rows('happy.sqlite3', 'SELECT confirmation,result_json,status FROM case_outbox'))
            if not booking: raise RuntimeError('Agent did not complete a booking; no success is claimed')
            if not result['case_outbox'] or result['case_outbox'][0]['status'] != 'SYNCED': raise RuntimeError('Booking committed but Salesforce Case synchronization is not verified')
        elif action == 'voucher':
            messages = []
            for prompt in ['Please request a 250 USD voucher for this disruption. Enforce the 200 USD autonomous cap. Submit it for human approval without issuing it.', 'Yes, submit the 250 USD proposal for human approval, without issuing it. Then create a human review handoff with verified context. Do not claim human acknowledgement unless verified.']:
                messages.append(agent(prompt))
            if not rows('happy.sqlite3', 'SELECT * FROM requests'):
                messages.append(agent('Yes, submit the voucher request now. Do not issue or approve it.'))
            messages.append(agent('Yes, create the human review handoff now. Report only the actual Salesforce Case update and acknowledgement facts.'))
            result.update(conversation=messages, voucher_requests=rows('happy.sqlite3', 'SELECT id,amount,case_ref FROM requests'), handoff=rows('happy.sqlite3', 'SELECT salesforce_case_id,context_json,status FROM handoff_outbox'))
            if not result['voucher_requests'] or not result['handoff'] or result['handoff'][0]['status'] != 'SYNCED': raise RuntimeError('Voucher proposal or human-review Case update not verified')
        elif action == 'conflict-prepare':
            result['configuration'] = configure_endpoint(True)
            result['conversation'] = agent('My synthetic booking is D00001. Please retrieve current same-cabin rebooking options. Do not book yet.', True)
            result['inventory'] = api('/rebook-options?pnr=D00001', failure=True)
            result['acceptance'] = api('/acceptance', {'pnr': 'D00001', 'option_id': 'OPT-1'}, failure=True)
            state['failure_acceptance'] = result['acceptance']['body']['acceptance_id']
        elif action == 'conflict':
            result['remove_seat'] = api('/admin/remove-seat', {'pnr': 'D00001', 'option_id': 'OPT-1'}, failure=True, operator=True)
            result['rebook'] = api('/rebook', {'pnr': 'D00001', 'option_id': 'OPT-1', 'passenger_ref': 'P001', 'acceptance_id': state['failure_acceptance'], 'idempotency_key': 'recording-conflict-' + uuid.uuid4().hex}, failure=True)
            result['conversation'] = [agent('Yes, proceed now with recording my selection of Option 1, DL-SYN1, and attempt the rebooking. I explicitly confirm. If unavailable, retrieve fresh options and ask for renewed acceptance.', True)]
            result['conversation'].append(agent('Retrieve the currently available same-cabin rebooking options for D00001 now. Show only options returned by the reservation service. Do not book anything or assume any availability.', True))
            result['fresh_options'] = api('/rebook-options?pnr=D00001', failure=True)
            result['bookings'] = rows('failure.sqlite3', 'SELECT * FROM bookings')
            if result['rebook']['status'] != 409 or result['bookings']: raise RuntimeError('Expected conflict without booking was not verified')
        else:
            raise ValueError('Unknown action')
        result['success'] = True
    except Exception as error:
        result['success'] = False
        result['error'] = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
    result['duration_seconds'] = round(time.time() - started, 2)
    state['events'].append(result)
    (RUN / 'execution.json').write_text(json.dumps(state['events'], indent=2))
    return result


@app.get('/', response_class=HTMLResponse)
def index():
    return (ROOT / 'demo/index.html').read_text().replace('__NONCE__', nonce)


@app.get('/state')
def snapshot():
    traces = []
    p = RUN / 'audit.jsonl'
    if p.exists():
        traces = [json.loads(x) for x in p.read_text().splitlines()[-18:]]
    return {'events': state['events'], 'busy': job is not None and not job.done(), 'traces': traces}


@app.post('/action/{action}')
def action(action: str, request: Request):
    global job
    if request.headers.get('X-Demo-Nonce') != nonce:
        raise HTTPException(403)
    if action not in {'event','identity','status','options','book','voucher','conflict-prepare','conflict'}:
        raise HTTPException(404)
    if job is not None and not job.done():
        raise HTTPException(409, 'Action in progress')
    job = executor.submit(execute, action)
    return {'started': action}
