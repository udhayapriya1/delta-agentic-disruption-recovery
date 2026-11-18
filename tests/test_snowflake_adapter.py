from unittest.mock import MagicMock
from delta_demo import cloud


def fixture(monkeypatch,row):
    cursor=MagicMock();cursor.__enter__.return_value=cursor;cursor.fetchone.return_value=row;cursor.sfqid='unit-fixture-query-id'
    connection=MagicMock();connection.is_closed.return_value=False;connection.cursor.return_value=cursor
    monkeypatch.setattr(cloud,'connect',lambda:connection)
    return cloud.SnowflakeContext(),cursor


def test_parameters_and_platform_source(monkeypatch):
    adapter,cursor=fixture(monkeypatch,('P001','GOLD',42000,'2026-11-15'))
    result=adapter.lookup("P001' OR 1=1 --")
    sql,args=cursor.execute.call_args.args
    assert "P001' OR 1=1 --" not in sql
    assert args==("P001' OR 1=1 --",'disruption_service')
    assert result['query_id']=='unit-fixture-query-id'
    assert result['source']=='DELTA_DEMO.CUSTOMER_360.LOYALTY_PROFILES'


def test_no_context_is_not_fabricated(monkeypatch):
    adapter,_=fixture(monkeypatch,None)
    assert adapter.lookup('P007') is None


def test_service_key_avoids_password_and_bootstrap_role(monkeypatch,tmp_path):
    config=tmp_path/'config.toml'
    config.write_text('[connections.delta-demo]\naccount="test-account"\nuser="bootstrap-user"\nauthenticator="username_password_mfa"\n')
    monkeypatch.setenv('SNOWFLAKE_CONFIG_FILE',str(config))
    monkeypatch.setenv('SNOWFLAKE_SERVICE_KEY_FILE',str(tmp_path/'ignored-key.p8'))
    monkeypatch.delenv('SNOWFLAKE_ROLE',raising=False)
    monkeypatch.setattr(cloud.subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Keychain password must not be read for service auth')))
    connector=MagicMock();monkeypatch.setattr(cloud.snowflake.connector,'connect',connector)
    cloud.connect()
    args=connector.call_args.kwargs
    assert args['user']=='DELTA_DEMO_CONTEXT_SERVICE'
    assert args['role']=='DELTA_DEMO_CONTEXT'
    assert args['authenticator']=='SNOWFLAKE_JWT'
    assert 'password' not in args
