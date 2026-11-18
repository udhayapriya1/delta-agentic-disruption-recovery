"""Select the working demo for Git without deleting local historical artifacts.

Default is a preview. --apply updates only the Git index and .gitignore.
"""
import argparse
from pathlib import Path
import subprocess

p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
keep_scripts=set('setup.sh run-api.sh run-tests.sh deploy_salesforce.sh generate_data.py issue_test_token.py prepare_salesforce_data.py cloud_bootstrap.py provision_snowflake_service.py sf_rest.py verify_native_identity.py verify_native_federation.py reconcile_handoffs.py start_recording_demo.py record_demo.mjs render_demo.py prepare_demo_checkin.py verify_recording.py'.split())
keep_docs=set('deployment-guide.md federation-decision.md live-agentforce-conversation.md security-design.md'.split())
keep_evidence=set('data360-native-identity-verification.json data360-calculated-insight-result.json native-snowflake-data-streams.json native-snowflake-source-preflight.json native-federation-verification.json snowflake-service-identity-verification.json identity-preprocessing-lineage.json backend-tests.xml'.split())
keep_bodies=set('identity-rules.json individual-mapping.json email-mapping.json party-identification-mapping.json passenger-stream.json verified-contact-stream.json passenger-data-graph.json unified-passenger-data-graph.json profile-evidence-insight.json profile-evidence-query.json native-link-verification-query.json synthetic-record-count-query.json unified-link-query.json native-individual-verification-query.json native-email-verification-query.json source-contact-verification-query.json unified-profile-schema-query.json'.split())

def keep(name):
    q=Path(name)
    if name in ['Dockerfile','docker-compose.yml','data/identity-preprocessing-evidence.json']:return False
    if any(name.startswith(prefix) for prefix in ['legacy/','databricks/','reference/','presentation/','dashboard/']):return False
    if q.name=='.gitkeep':return False
    if name.startswith('architecture/'):
        return name in ['architecture/presentation/delta-recovery-architecture.png','architecture/presentation/delta-recovery-architecture.svg']
    if name.startswith('video/'):return name.startswith('video/demo/')
    if name.startswith('scripts/'):return q.name in keep_scripts
    if name.startswith('docs/'):return name=='docs/data360/logical-model-and-mappings.md' or (q.parent==Path('docs') and q.name in keep_docs)
    if name.startswith('evidence/'):
        return (q.parent==Path('evidence') and q.name in keep_evidence) or name=='evidence/deployments/passenger-canonical-contact-load.json'
    if name.startswith('salesforce/data360/'):return q.name in keep_bodies
    if any(name.startswith('salesforce/force-app/main/default/'+x+'/') for x in ['aiAuthoringBundles','aiAgents','genAiPlannerBundles']):return False
    return True

tracked=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
remove=[x for x in tracked if x and not keep(x)]
ignore=['# Historical work is preserved locally, excluded from the demo repository.','legacy/','databricks/','reference/','presentation/','dashboard/','**/.gitkeep','demo/node_modules/','demo/package-lock.json','Dockerfile','docker-compose.yml','data/identity-preprocessing-evidence.json','architecture/*','!architecture/presentation/','architecture/presentation/*','!architecture/presentation/delta-recovery-architecture.png','!architecture/presentation/delta-recovery-architecture.svg','video/*','!video/demo/','scripts/*']+['!scripts/'+x for x in sorted(keep_scripts)]+['docs/*','!docs/data360/']+['!docs/'+x for x in sorted(keep_docs)]+['evidence/*']+['!evidence/'+x for x in sorted(keep_evidence)]+['!evidence/deployments/','evidence/deployments/*','!evidence/deployments/passenger-canonical-contact-load.json','salesforce/data360/*']+['!salesforce/data360/'+x for x in sorted(keep_bodies)]+['salesforce/force-app/main/default/aiAuthoringBundles/','salesforce/force-app/main/default/aiAgents/','salesforce/force-app/main/default/genAiPlannerBundles/']
if args.apply:
    if remove:subprocess.run(['git','rm','--cached','--ignore-unmatch','--',*remove],check=True,stdout=subprocess.DEVNULL)
    path=Path('.gitignore');base=path.read_text().split('# Historical work is preserved locally')[0].rstrip()
    path.write_text(base+'\n\n'+'\n'.join(ignore)+'\n')
print(f'{len(remove)} historical or unnecessary tracked files '+('excluded; local copies preserved' if args.apply else 'would be excluded'))
if not args.apply:print('\n'.join(remove))
