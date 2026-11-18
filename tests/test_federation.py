"""Unit fixtures validate rejection behavior; live proof is saved separately."""
import json
from types import SimpleNamespace
import pytest
from delta_demo import federation


def response(rows=None, done=True):
    return {'body':{'done':done,'data':rows if rows is not None else [['P001','GOLD','42000.000','2026-11-15']],
                    'metadata':{k:{'placeInOrder':i} for i,k in enumerate(['passenger_id','tier','miles','source_timestamp'])},'queryId':'UNIT-QUERY'},'request_id':'UNIT-REQUEST'}


def test_subject_and_consent_predicates(monkeypatch):
    seen=[]
    monkeypatch.setattr(federation,'query_data360',lambda sql:(seen.append(sql),response())[1])
    result=federation.Data360SnowflakeContext().lookup('P001')
    assert result['miles']==42000
    assert result['access_mode']=='DIRECT_ACCESS'
    assert "c.purpose__c='disruption_service' AND c.allowed__c=TRUE" in seen[0]
    for subject in ["P001' OR 1=1 --",'p001','P001\n',None]:
        with pytest.raises(ValueError):federation.Data360SnowflakeContext().lookup(subject)
    assert len(seen)==1


@pytest.mark.parametrize('rows',[[['P002','GOLD','42','now']], [['P001','GOLD','-1','now']], [['P001','GOLD','1.5','now']], [['P001','GOLD','NaN','now']], [['P001','GOLD','42','now']]*2])
def test_invalid_or_ambiguous_context_blocked(monkeypatch,rows):
    monkeypatch.setattr(federation,'query_data360',lambda sql:response(rows))
    with pytest.raises(ValueError):federation.Data360SnowflakeContext().lookup('P001')


def test_denied_consent_has_no_fabricated_context(monkeypatch):
    monkeypatch.setattr(federation,'query_data360',lambda sql:response([]))
    assert federation.Data360SnowflakeContext().lookup('P007') is None


def test_failed_or_incomplete_cloud_query_has_no_fallback(monkeypatch):
    monkeypatch.setattr(federation.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout='unavailable'))
    with pytest.raises(RuntimeError):federation.query_data360('SELECT 1')
    monkeypatch.setattr(federation.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'statusCode':201,'body':{'done':False,'queryId':'partial'}}})))
    with pytest.raises(RuntimeError):federation.query_data360('SELECT 1')
