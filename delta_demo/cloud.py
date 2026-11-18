"""No mock fallback: a failed cloud query is unavailable, never fabricated context."""
import os
from pathlib import Path
import tomllib
import threading
import subprocess
import snowflake.connector


def connect(role=None):
    name = os.getenv('SNOWFLAKE_CONNECTION_NAME', 'delta-demo')
    config = os.getenv('SNOWFLAKE_CONFIG_FILE')
    default_config = Path.home()/'.snowflake/config.toml'
    if not config and default_config.exists():
        config = str(default_config)
    kwargs = {}
    if config:
        document = tomllib.loads(Path(config).expanduser().read_text())
        profiles = document.get('connections', document)
        if name not in profiles:
            raise RuntimeError('Named Snowflake profile absent from selected config')
        kwargs.update(profiles[name])
    else:
        kwargs['connection_name'] = name
    service_key = os.getenv('SNOWFLAKE_SERVICE_KEY_FILE') if role != 'ACCOUNTADMIN' else None
    if service_key:
        kwargs.pop('password',None)
        kwargs.update(user='DELTA_DEMO_CONTEXT_SERVICE',authenticator='SNOWFLAKE_JWT',
                      private_key_file=str(Path(service_key).expanduser()))
    elif kwargs.get('authenticator','').lower() in ['username_password_mfa','snowflake']:
        password = os.getenv('SNOWFLAKE_PASSWORD')
        if not password:
            keychain = subprocess.run(['security','find-generic-password','-s','delta-demo-snowflake','-a','delta-demo','-w'],capture_output=True,text=True,timeout=30)
            if keychain.returncode == 0:
                password = keychain.stdout.rstrip('\n')
        if not password:
            raise RuntimeError('Snowflake credential unavailable in environment or approved Keychain entry')
        kwargs['password'] = password
    if os.getenv('SNOWFLAKE_ACCOUNT'):
        kwargs['account'] = os.environ['SNOWFLAKE_ACCOUNT']
    kwargs.update(role=role or os.getenv('SNOWFLAKE_ROLE', 'DELTA_DEMO_CONTEXT' if service_key else 'DELTA_DEMO_APP'),
                  warehouse=os.getenv('SNOWFLAKE_WAREHOUSE', 'DELTA_DEMO_WH'),
                  login_timeout=30, network_timeout=20,
                  session_parameters={'QUERY_TAG': 'DELTA_SYNTHETIC_DEMO', 'STATEMENT_TIMEOUT_IN_SECONDS': 15})
    return snowflake.connector.connect(**kwargs)


class SnowflakeContext:
    def __init__(self):
        self.connection = None
        self.lock = threading.Lock()

    def lookup(self, passenger_id):
        with self.lock:
            if self.connection is None or self.connection.is_closed():
                self.connection = connect()
            with self.connection.cursor() as c:
                c.execute('SELECT l.PASSENGER_ID, l.TIER, l.MILES, l.SOURCE_TIMESTAMP FROM DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES l JOIN DELTA_DEMO.CUSTOMER_360.CONSENT c ON c.PASSENGER_ID=l.PASSENGER_ID WHERE l.PASSENGER_ID=%s AND c.PURPOSE=%s AND c.ALLOWED=TRUE', (passenger_id, 'disruption_service'))
                row = c.fetchone()
                query_id = c.sfqid
            if not row:
                return None
            return {'passenger_id': row[0], 'tier': row[1], 'miles': int(row[2]),
                    'source_timestamp': str(row[3]), 'query_id': query_id,
                    'source': 'DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES'}
