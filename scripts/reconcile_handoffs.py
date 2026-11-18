"""Run one durable handoff retry pass using the existing authorized SF CLI."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from delta_demo.salesforce import reconcile_handoffs
p=argparse.ArgumentParser();p.add_argument('--db',required=True);a=p.parse_args()
print(json.dumps({'results':reconcile_handoffs(a.db),'human_acknowledgement_claimed':False},indent=2))
