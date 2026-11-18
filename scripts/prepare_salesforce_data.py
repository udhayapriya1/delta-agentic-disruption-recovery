"""Preserve source contact and derive canonical verified contact with conflict-veto provenance."""
import csv,json
from pathlib import Path
from scripts.generate_data import passengers
from delta_demo.identity import resolve
result=resolve(passengers());rows=[]
for group in result['profiles']:
 profile=group['profile']
 canonical=profile['email'] if profile.get('email_verified') else ''
 for source in group['sources']:
  rows.append(dict(Name=source['surname'],Source_Id__c=source['source_id'],Passenger_Ref__c=source['passenger_id'],SkyMiles__c=source['skymiles'],PNR__c=source['pnr'],Email__c=canonical,Raw_Email__c=source['email'],Tier__c=source['tier'],Consent__c=str(source['consent']).lower(),Special_Case__c=source['special'],Identity_Email__c=canonical,Identity_Verified__c=str(bool(canonical)).lower()))
with Path('data/salesforce-passenger-sources.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
Path('evidence/identity-preprocessing-lineage.json').write_text(json.dumps(result,indent=2))
print('Prepared 14 synthetic source rows; raw contacts preserved; unverified contacts excluded from matching')
