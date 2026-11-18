"""Validate recorded execution facts without replacing or simulating responses."""
import json
from pathlib import Path
import sqlite3

run=Path('tmp/recording')
events=json.loads((run/'execution.json').read_text())
latest={event['action']:event for event in events}
checks={}
def check(label,condition):
    checks[label]=bool(condition)
    if not condition:raise AssertionError(label)
for name in ['event','identity','status','options','book','voucher','conflict']:
    check(name+' completed',latest[name]['success'])
check('Native event produced independently queried Case',bool(latest['event']['cases'][0]['CaseNumber']))
check('Outbound message remains explicitly false',latest['event']['outbound_message_sent'] is False)
identity=latest['identity'];check('14 sources resolve to 13 profiles',identity['sources']==14 and identity['profiles']==13 and identity['duplicate_merged'])
context=latest['status']['context'];check('Native federated Graph context',context['status']==200 and context['body']['access_mode']=='DIRECT_ACCESS' and context['body']['data360_context']['native_unified_merge_verified'])
check('Contact masked',context['body']['contact']=='masked')
check('Cancellation from actual product API',latest['status']['flight_status']['body']['status']=='CANCELLED')
check('Two real options offered',len(latest['options']['inventory']['body']['options'])==2)
book=latest['book'];check('Exactly one confirmed Option 1 booking',len(book['bookings'])==1 and book['bookings'][0]['option_id']=='OPT-1')
case=book['case_outbox'][0];check('Real Salesforce Case synchronized',case['status']=='SYNCED' and json.loads(case['result_json'])['verified'])
voucher=latest['voucher'];check('250 dollar approval proposal exists',len(voucher['voucher_requests'])==1 and float(voucher['voucher_requests'][0]['amount'])==250)
check('Human-review Case synchronized',len(voucher['handoff'])==1 and voucher['handoff'][0]['status']=='SYNCED')
handoff=json.loads(voucher['handoff'][0]['context_json']);check('Context package complete',all(k in handoff for k in ['identity_context','loyalty_context','booking','voucher_requests','audit_references']))
check('Human receipt not invented',handoff['human_acknowledged'] is False and handoff['omni_channel_verified'] is False)
with sqlite3.connect(run/'happy.sqlite3') as c:
    responses=[json.loads(row[0]) for row in c.execute('SELECT response FROM ledger')]
check('No voucher issued',not any(r.get('status')=='ISSUED' for r in responses))
conflict=latest['conflict'];check('Actual POST rebook rejected with 409',conflict['rebook']['status']==409)
check('No conflict booking',conflict['bookings']==[])
check('Only second option remains', [r['id'] for r in conflict['fresh_options']['body']['options']]==['OPT-2'])
messages=conflict['conversation'];check('Agent actually answered recovery follow-up',isinstance(messages,list) and len(messages)>=2 and all(m['messages'] for m in messages))
text=' '.join(m.get('message','') for item in messages for m in item['messages'])
check('Agent names the remaining real option','DL-SYN2' in text)
report={'passed':all(checks.values()),'checks':checks,'booking':book['bookings'][0]['id'],'case':json.loads(case['result_json'])['case_number'],'scope':'actual recorded synthetic run; not production certification'}
(run/'execution-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
