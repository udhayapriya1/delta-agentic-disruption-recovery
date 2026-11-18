"""Issue a short-lived local test token only; not an OAuth server."""
import argparse, os, time
import jwt
p=argparse.ArgumentParser();p.add_argument('--subject',default='P001');p.add_argument('--role',choices=['passenger','approver','operator'],default='passenger');a=p.parse_args()
s=os.environ['DELTA_JWT_SECRET']
if len(s)<32:raise SystemExit('Secret must have at least 32 random characters')
print(jwt.encode(dict(sub=a.subject,role=a.role,iat=int(time.time()),exp=int(time.time())+900,iss='delta-demo',aud='delta-api'),s,algorithm='HS256'))
