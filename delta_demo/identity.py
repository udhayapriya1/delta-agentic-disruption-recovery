"""Local preprocessing safeguards, not a claim of native Data 360 deployment."""
import uuid
from datetime import datetime, timezone


def match(a, b):
    if a.get('skymiles') and b.get('skymiles') and a['skymiles'] != b['skymiles']:
        return None
    if a.get('skymiles') and a['skymiles'] == b.get('skymiles'):
        return 'exact_skymiles'
    # Group/shared PNR surname alone is insufficient to safely collapse people.
    if a.get('special') != 'group' and b.get('special') != 'group' and a.get('pnr') and (a['pnr'],a['surname']) == (b.get('pnr'),b.get('surname')):
        return 'pnr_surname'
    if a.get('email_verified') and b.get('email_verified') and a.get('email') and a['email'].casefold() == b.get('email','').casefold():
        return 'verified_email'
    if a.get('phone_verified') and b.get('phone_verified') and a.get('phone') and a['phone'] == b.get('phone'):
        return 'verified_phone'
    return None


def resolve(records):
    """Conservative complete-link groups avoid transitive conflicting-ID merges."""
    groups = []
    audit = []
    for record in records:
        candidates = [g for g in groups if all(match(record,r) for r in g)]
        if len(candidates) != 1:
            groups.append([record.copy()])
            continue
        group=candidates[0]
        rule=match(record,group[0])
        audit.append({'merge_id':uuid.uuid4().hex,'rule':rule,'sources':[r['source_id'] for r in group]+[record['source_id']],
                      'timestamp':datetime.now(timezone.utc).isoformat(),'evidence':'deterministic exact keys; no fuzzy auto-merge','reversible':True})
        group.append(record.copy())
    profiles=[]
    for group in groups:
        ordered=sorted(group,key=lambda r:r.get('updated_at',''),reverse=True)
        survivor=ordered[0].copy()
        verified=next((r for r in ordered if r.get('email_verified')),None)
        if verified:
            survivor['email']=verified['email'];survivor['email_verified']=True
        # Latest explicit consent record wins; revocation is not overwritten by older grants.
        survivor['consent']=ordered[0].get('consent',False)
        profiles.append({'profile':survivor,'sources':[r.copy() for r in group]})
    return {'profiles':profiles,'merge_audit':audit,'implementation':'local preprocessing; Data 360 native rules unverified'}


def reverse_merge(profile):
    return [r.copy() for r in profile['sources']]
