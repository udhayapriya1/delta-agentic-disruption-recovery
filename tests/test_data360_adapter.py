"""Adapter contract tests use explicit fixtures; real verification is in evidence/."""
import json
from types import SimpleNamespace
import pytest
from delta_demo.salesforce import verified_demo_graph


def result(key='SYN0000001'):
    return SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'statusCode':200,'body':{'data':[{'json_blob__c':json.dumps({'ssot__ExternalRecordId__c':key})}]}}}))


def test_fixed_subject_and_profile_binding(monkeypatch):
    monkeypatch.setattr('delta_demo.salesforce.subprocess.run',lambda *a,**k:result())
    assert verified_demo_graph('P001')['profile_binding_verified'] is True
    with pytest.raises(ValueError):verified_demo_graph('P002')
    monkeypatch.setattr('delta_demo.salesforce.subprocess.run',lambda *a,**k:result('OTHER'))
    with pytest.raises(ValueError):verified_demo_graph('P001')


def test_no_profile_or_failed_api_does_not_pass(monkeypatch):
    monkeypatch.setattr('delta_demo.salesforce.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=''))
    with pytest.raises(RuntimeError):verified_demo_graph('P001')


def test_native_unified_lookup_rejects_split_identity(monkeypatch):
    rows=[['a00bm00003QTT4XAAX','a'*32],['a00bm00003QTT4YAAX','b'*32]]
    response=SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'body':{'data':rows,'queryId':'fixture-only'}}}))
    monkeypatch.setattr('delta_demo.salesforce.subprocess.run',lambda *a,**k:response)
    with pytest.raises(ValueError,match='not unified'):verified_demo_graph('P001',unified=True)


def test_native_unified_lookup_and_graph_both_required(monkeypatch):
    rows=[['a00bm00003QTT4XAAX','a'*32],['a00bm00003QTT4YAAX','a'*32]]
    links=SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'body':{'data':rows,'queryId':'fixture-only'}}}))
    responses=iter([links,result()])
    monkeypatch.setattr('delta_demo.salesforce.subprocess.run',lambda *a,**k:next(responses))
    assert verified_demo_graph('P001',unified=True)['native_unified_merge_verified'] is True
