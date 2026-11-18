"""Authorized scoped bootstrap: dedicated read-only key-pair service identity, no passwords."""
import json,os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from delta_demo.cloud import connect
keypath=Path('tmp/secrets/snowflake-context-service.p8');keypath.parent.mkdir(parents=True,exist_ok=True);keypath.parent.chmod(0o700)
if keypath.exists():key=serialization.load_pem_private_key(keypath.read_bytes(),password=None)
else:
 key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
 keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));keypath.chmod(0o600)
public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
import base64
public=base64.b64encode(public).decode()
conn=connect(role='ACCOUNTADMIN');evidence=[]
with conn.cursor() as c:
 c.execute('SELECT CURRENT_ORGANIZATION_NAME(),CURRENT_ACCOUNT_NAME()');assert c.fetchone()==('DRJMZEF','SU04270')
 statements=["CREATE ROLE IF NOT EXISTS DELTA_DEMO_CONTEXT","GRANT USAGE ON WAREHOUSE DELTA_DEMO_WH TO ROLE DELTA_DEMO_CONTEXT","GRANT USAGE ON DATABASE DELTA_DEMO TO ROLE DELTA_DEMO_CONTEXT","GRANT USAGE ON SCHEMA DELTA_DEMO.CUSTOMER_360 TO ROLE DELTA_DEMO_CONTEXT"]
 statements += ['GRANT SELECT ON TABLE DELTA_DEMO.CUSTOMER_360.'+name+' TO ROLE DELTA_DEMO_CONTEXT' for name in ['LOYALTY_PROFILES','CONSENT','TRAVEL_HISTORY']]
 statements += ["CREATE USER IF NOT EXISTS DELTA_DEMO_CONTEXT_SERVICE TYPE=SERVICE DEFAULT_ROLE=DELTA_DEMO_CONTEXT DEFAULT_WAREHOUSE=DELTA_DEMO_WH",f"ALTER USER DELTA_DEMO_CONTEXT_SERVICE SET RSA_PUBLIC_KEY='{public}'","GRANT ROLE DELTA_DEMO_CONTEXT TO USER DELTA_DEMO_CONTEXT_SERVICE"]
 for sql in statements:
  c.execute(sql);evidence.append({'operation':sql.split()[0],'query_id':c.sfqid,'executed':True})
conn.close();os.environ['SNOWFLAKE_SERVICE_KEY_FILE']=str(keypath.resolve());os.environ['SNOWFLAKE_ROLE']='DELTA_DEMO_CONTEXT'
conn=connect();checks=[]
with conn.cursor() as c:
 c.execute('SELECT CURRENT_ROLE(),CURRENT_USER()');identity=c.fetchone();checks.append({'check':'dedicated service identity and context role','passed':identity==('DELTA_DEMO_CONTEXT','DELTA_DEMO_CONTEXT_SERVICE'),'query_id':c.sfqid})
 c.execute('SELECT COUNT(*) FROM DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES');checks.append({'check':'context read permitted','passed':c.fetchone()[0]==13,'query_id':c.sfqid})
 for sql,label in [('USE ROLE ACCOUNTADMIN','cannot assume bootstrap role'),('SELECT COUNT(*) FROM DELTA_DEMO.CUSTOMER_360.PASSENGER_SOURCES','raw contact source inaccessible')]:
  try:c.execute(sql);checks.append({'check':label,'passed':False})
  except Exception as ex:checks.append({'check':label,'passed':True,'error_code':getattr(ex,'errno',None)})
conn.close();report={'bootstrap':evidence,'checks':checks,'passed':all(x['passed'] for x in checks),'credentials':'private key retained only in ignored mode-600 local secret file; no password or key in evidence'}
Path('evidence/snowflake-service-identity-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'checks':checks}))
