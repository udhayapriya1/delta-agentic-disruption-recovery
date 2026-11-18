"""Real Data 360 SQL over native Snowflake DIRECT_ACCESS objects.

Local developer OAuth is owned by Salesforce CLI. No fixture or direct-Snowflake
fallback is used when this adapter is selected.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from decimal import Decimal


def query_data360(sql):
    with tempfile.TemporaryDirectory(prefix='delta-federation-') as folder:
        body = Path(folder) / 'query.json'
        body.write_text(json.dumps({'sql': sql}))
        body.chmod(0o600)
        result = subprocess.run(
            ['sf', 'api', 'request', 'rest', '/services/data/v68.0/ssot/queryv2',
             '--method', 'POST', '--body', '@' + str(body), '--target-org',
             os.getenv('DELTA_SALESFORCE_ORG', 'delta-dev'), '--json'],
            capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Native Data 360 federation query unavailable')
    response = json.loads(result.stdout)['result']
    body = response.get('body', {})
    if response.get('statusCode') not in (200, 201) or body.get('done') is not True or not body.get('queryId'):
        raise RuntimeError('Native federation query incomplete or invalid')
    return {'body': body, 'request_id': response.get('headers', {}).get('x-request-id')}


class Data360SnowflakeContext:
    def lookup(self, passenger_id):
        # Query API has no bind arguments. Strict synthetic identifier validation
        # occurs before constructing SQL; callers cannot submit arbitrary SQL.
        if not isinstance(passenger_id, str) or not re.fullmatch(r'P[0-9]{3}', passenger_id):
            raise ValueError('Valid synthetic passenger identifier required')
        sql = f"""SELECT l.passenger_id__c AS passenger_id, l.tier__c AS tier,
            l.miles__c AS miles, l.source_timestamp__c AS source_timestamp
            FROM Delta_Snowflake_Loyalty__dll l
            JOIN Delta_Snowflake_Consent__dll c ON c.passenger_id__c=l.passenger_id__c
            WHERE l.passenger_id__c='{passenger_id}'
            AND c.purpose__c='disruption_service' AND c.allowed__c=TRUE"""
        response = query_data360(sql)
        body = response['body']
        rows = body.get('data', [])
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError('Ambiguous native context; autonomous eligibility blocked')
        metadata = body['metadata']
        row = {key: rows[0][metadata[key]['placeInOrder']]
               for key in ('passenger_id', 'tier', 'miles', 'source_timestamp')}
        if row['passenger_id'] != passenger_id:
            raise ValueError('Federated subject binding mismatch')
        miles = Decimal(str(row['miles']))
        if not miles.is_finite() or miles < 0 or miles != miles.to_integral_value():
            raise ValueError('Invalid native loyalty balance')
        return {**row, 'miles': int(miles), 'query_id': body['queryId'],
                'request_id': response['request_id'],
                'source': 'Delta_Snowflake_Loyalty__dll',
                'source_system': 'DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES',
                'access_mode': 'DIRECT_ACCESS', 'adapter': 'native_data360_snowflake',
                'consent_source': 'Delta_Snowflake_Consent__dll'}
