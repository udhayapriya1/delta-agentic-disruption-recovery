from scripts.generate_data import passengers
from delta_demo.identity import match,resolve,reverse_merge


def test_duplicate_and_survivor_with_reversal():
    rows=passengers();result=resolve(rows)
    assert len(result['profiles'])==13
    merged=next(p for p in result['profiles'] if len(p['sources'])==2)
    assert merged['profile']['email']=='passenger1@example.invalid'
    assert result['merge_audit'][0]['rule']=='exact_skymiles'
    assert reverse_merge(merged)==rows[:2]


def test_ambiguous_and_conflicting_loyalty_not_merged():
    a=passengers()[0];b={**a,'source_id':'OTHER','skymiles':'DIFFERENT'}
    assert match(a,b) is None
    assert len(resolve([a,b])['profiles'])==2
    b={**a,'source_id':'OTHER','skymiles':None,'pnr':'OTHER','email':'other@example.invalid'}
    assert match(a,b) is None


def test_transitive_conflict_and_shared_group():
    a=passengers()[0];b={**a,'source_id':'B','skymiles':None};c={**a,'source_id':'C','skymiles':'OTHER'}
    assert len(resolve([a,b,c])['profiles'])==2
    assert match({**a,'skymiles':None,'special':'group'},{**b,'special':'group','email_verified':False}) is None


def test_latest_revocation_wins():
    a=passengers()[0];b={**a,'source_id':'B','updated_at':'2026-11-16','consent':False}
    assert resolve([a,b])['profiles'][0]['profile']['consent'] is False
