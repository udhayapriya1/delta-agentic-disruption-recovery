"""Run only after account authorization. Save query IDs, never credentials."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from delta_demo.cloud import connect
from scripts.generate_data import passengers

p = argparse.ArgumentParser()
p.add_argument('--apply', action='store_true')
p.add_argument('--grant-current-user', action='store_true')
args = p.parse_args()
conn = connect(role='ACCOUNTADMIN' if args.apply else None)
evidence = []

def execute(sql, values=None):
    with conn.cursor() as c:
        c.execute(sql, values)
        records = c.fetchall()
        evidence.append({'query_id': c.sfqid, 'operation': sql.split()[0], 'rows': ([list(records[0][:3])+['[MASKED]']] if 'CURRENT_USER()' in sql else records)})
        Path('evidence').mkdir(exist_ok=True)
        Path('evidence/snowflake-query-progress.json').write_text(json.dumps({'queries': evidence}, default=str, indent=2)+'\n')
        return records

identity = execute('SELECT CURRENT_ACCOUNT(), CURRENT_REGION(), CURRENT_ROLE(), CURRENT_USER(), CURRENT_ORGANIZATION_NAME(), CURRENT_ACCOUNT_NAME()')[0]
if (identity[4].upper(),identity[5].upper()) != ('DRJMZEF','SU04270'):
    raise RuntimeError('Account safety gate: expected organization/account DRJMZEF-SU04270; no resource changes performed')
if args.apply:
    with open('snowflake/001_bootstrap.sql') as stream:
        for c in conn.execute_stream(stream, remove_comments=True):
            evidence.append({'query_id': c.sfqid, 'operation': 'bootstrap', 'rows': c.fetchall()})
            Path('evidence/snowflake-query-progress.json').write_text(json.dumps({'queries': evidence}, default=str, indent=2)+'\n')
    if args.grant_current_user:
        for role in ['DELTA_DEMO_APP', 'DELTA_DEMO_LOADER']:
            quoted_user = '"' + identity[3].replace('"','""') + '"'
            execute(f'GRANT ROLE {role} TO USER {quoted_user}')
    execute('USE ROLE DELTA_DEMO_LOADER')
    execute('USE WAREHOUSE DELTA_DEMO_WH')
    for r in passengers():
        values = tuple(r[k] for k in ['source_id','passenger_id','surname','email','email_verified','skymiles','tier','pnr','consent','cabin','special','updated_at'])
        execute('MERGE INTO DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES t USING (SELECT %s SOURCE_ID,%s PASSENGER_ID,%s SURNAME,%s EMAIL,%s EMAIL_VERIFIED,%s SKYMILES,%s TIER,%s PNR,%s CONSENT,%s CABIN,%s SPECIAL,%s::TIMESTAMP_TZ UPDATED_AT) s ON t.SOURCE_ID=s.SOURCE_ID WHEN NOT MATCHED THEN INSERT (SOURCE_ID,PASSENGER_ID,SURNAME,EMAIL,EMAIL_VERIFIED,SKYMILES,TIER,PNR,CONSENT,CABIN,SPECIAL,UPDATED_AT) VALUES (s.SOURCE_ID,s.PASSENGER_ID,s.SURNAME,s.EMAIL,s.EMAIL_VERIFIED,s.SKYMILES,s.TIER,s.PNR,s.CONSENT,s.CABIN,s.SPECIAL,s.UPDATED_AT)', values)
    execute("MERGE INTO DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES t USING (SELECT DISTINCT PASSENGER_ID,TIER FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES) s ON t.PASSENGER_ID=s.PASSENGER_ID WHEN NOT MATCHED THEN INSERT VALUES(s.PASSENGER_ID,s.TIER,42000,CURRENT_TIMESTAMP())")
    execute("MERGE INTO DELTA_DEMO.CUSTOMER_360.TRAVEL_HISTORY t USING (SELECT DISTINCT 'TR-'||PASSENGER_ID TRAVEL_ID,PASSENGER_ID FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES) s ON t.TRAVEL_ID=s.TRAVEL_ID WHEN NOT MATCHED THEN INSERT VALUES(s.TRAVEL_ID,s.PASSENGER_ID,'ATL-JFK','2026-10-01')")
    execute("MERGE INTO DELTA_DEMO.FLIGHT_OPERATIONS.DISRUPTION_EVENTS t USING (SELECT DISTINCT 'EV-'||PNR EVENT_ID,PNR FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES) s ON t.EVENT_ID=s.EVENT_ID WHEN NOT MATCHED THEN INSERT VALUES(s.EVENT_ID,s.PNR,'CANCELLED','Synthetic weather event',CURRENT_TIMESTAMP())")
    execute("MERGE INTO DELTA_DEMO.CUSTOMER_360.CONSENT t USING (SELECT PASSENGER_ID,BOOLAND_AGG(CONSENT) ALLOWED FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES GROUP BY PASSENGER_ID) s ON t.PASSENGER_ID=s.PASSENGER_ID AND t.PURPOSE='disruption_service' WHEN MATCHED THEN UPDATE SET ALLOWED=s.ALLOWED,SOURCE_TIMESTAMP=CURRENT_TIMESTAMP() WHEN NOT MATCHED THEN INSERT VALUES(s.PASSENGER_ID,'disruption_service',s.ALLOWED,CURRENT_TIMESTAMP())")
    execute("MERGE INTO DELTA_DEMO.FLIGHT_OPERATIONS.FLIGHTS t USING (SELECT 'DL-SYN0' FLIGHT_ID) s ON t.FLIGHT_ID=s.FLIGHT_ID WHEN NOT MATCHED THEN INSERT VALUES(s.FLIGHT_ID,'ATL-JFK','ECONOMY',DATEADD(hour,3,CURRENT_TIMESTAMP()),'CANCELLED')")
    execute("MERGE INTO DELTA_DEMO.FLIGHT_OPERATIONS.BOOKING_SNAPSHOTS t USING (SELECT DISTINCT PNR,PASSENGER_ID FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES) s ON t.PNR=s.PNR AND t.PASSENGER_ID=s.PASSENGER_ID WHEN NOT MATCHED THEN INSERT VALUES(s.PNR,s.PASSENGER_ID,'DL-SYN0',CURRENT_TIMESTAMP())")
    counts = execute('SELECT COUNT(*),COUNT(DISTINCT PASSENGER_ID) FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES')[0]
    assert counts[0] >= 12 and counts[1] >= 11, 'Synthetic load count gate failed'
Path('evidence').mkdir(exist_ok=True)
Path('evidence/snowflake-execution.json').write_text(json.dumps({'executed_at': datetime.now(timezone.utc).isoformat(), 'queries': evidence}, default=str, indent=2)+'\n')
print('Authenticated Snowflake queries:', len(evidence), 'Evidence: evidence/snowflake-execution.json')
conn.close()
