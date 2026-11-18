"""CLI-authenticated REST helper that strips cookie/credential headers from saved evidence."""
import argparse,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('url');p.add_argument('--method',default='GET');p.add_argument('--body');p.add_argument('--output',required=True);a=p.parse_args()
cmd=['sf','api','request','rest',a.url,'--method',a.method,'--target-org','delta-dev','--json']
if a.body:cmd+=['--body','@'+a.body]
r=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
d=json.loads(r.stdout);result=d.get('result',{})
if isinstance(result,dict) and 'headers' in result:result['headers']={k:v for k,v in result['headers'].items() if k in ['x-request-id','content-type','sforce-limit-info']}
Path(a.output).write_text(json.dumps(d,indent=2)+'\n');print(json.dumps({'file':a.output,'success':r.returncode==0,'statusCode':result.get('statusCode') if isinstance(result,dict) else None,'error':result.get('body') if r.returncode else None}))
raise SystemExit(r.returncode)
