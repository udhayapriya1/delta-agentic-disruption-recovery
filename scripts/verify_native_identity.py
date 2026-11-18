"""Native source-to-unified verification; configuration success alone never passes."""
import json,subprocess,time,argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--attempts',type=int,default=1);a=p.parse_args()
source=json.loads(Path('evidence/deployments/passenger-canonical-contact-load.json').read_text())['result']['records']['successfulResults']
ids={x['Source_Id__c']:x['sf__Id'] for x in source}
for attempt in range(a.attempts):
 subprocess.run(['.venv/bin/python','scripts/sf_rest.py','/services/data/v68.0/ssot/queryv2','--method','POST','--body','salesforce/data360/native-link-verification-query.json','--output','evidence/data360-unified-links.json'],capture_output=True,text=True,timeout=90)
 d=json.loads(Path('evidence/data360-unified-links.json').read_text());body=d.get('result',{}).get('body',{});links={x[0]:x[1] for x in body.get('data',[])}
 duplicates=all(ids[x] in links for x in ['SRC001','SRC002']) and links.get(ids['SRC001'])==links.get(ids['SRC002'])
 distinct=all(ids[x] in links for x in ['SRC013','SRC014']) and links.get(ids['SRC013'])!=links.get(ids['SRC014'])
 report={'duplicate_sources':['SRC001','SRC002'],'duplicate_source_record_ids':[ids['SRC001'],ids['SRC002']],'duplicate_unified_ids':[links.get(ids['SRC001']),links.get(ids['SRC002'])],'duplicate_merged':duplicates,'conflicting_loyalty_sources':['SRC013','SRC014'],'conflicting_loyalty_kept_distinct':distinct,'native_link_rows':len(links),'unique_native_profiles':len(set(links.values())),'query_id':body.get('queryId'),'passed':bool(duplicates and distinct),'source':'actual Data 360 query; local preprocessing is not substituted'}
 Path('evidence/data360-native-identity-verification.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'attempt':attempt+1,'passed':report['passed'],'profiles':report['unique_native_profiles']}),flush=True)
 if report['passed']:break
 if attempt+1<a.attempts:time.sleep(30)
raise SystemExit(0 if report['passed'] else 1)
