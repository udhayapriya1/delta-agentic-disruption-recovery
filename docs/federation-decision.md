# Native Data 360–Snowflake federation: implemented and verified

The selected native path is **zero-copy DIRECT_ACCESS**, not scheduled ingestion. On November 15, 2026 (Pacific), Salesforce authenticated to the real Snowflake trial using the approved `DELTA_DEMO_CONTEXT_SERVICE` key-pair identity. Connection `Delta_Snowflake_Context` (`9cgbm000001DVTdAAO`) is Active. Data unload and acceleration are disabled. Salesforce stores the approved connector credential; local private-key files remain protected and Git-ignored.

| Snowflake source in DELTA_DEMO.CUSTOMER_360 | Native Data 360 external DLO | Key | Category |
|---|---|---|---|
| LOYALTY_PROFILES | Delta_Snowflake_Loyalty__dll | passenger_id | Profile |
| CONSENT | Delta_Snowflake_Consent__dll | passenger_id + purpose | Other |
| TRAVEL_HISTORY | Delta_Snowflake_Travel__dll | travel_id | Other |

All three streams are Active, `dataStreamType=EXTERNAL`, `dataAccessMode=DIRECT_ACCESS`, and `isAccelerationEnabled=false`. Each exposes 13 source rows. Native source-to-DLO fields are lowercase with `__c` query suffixes: loyalty passenger_id/tier/miles/source_timestamp; consent passenger_id/purpose/allowed/source_timestamp; travel travel_id/passenger_id/route/travel_date. Source names, field types, keys, stream IDs and warehouse/source lineage are captured in `evidence/native-snowflake-data-streams.json` and `evidence/native-snowflake-source-preflight.json`.

## Executed proof

`evidence/native-snowflake-federated-counts.json` contains a successful Data 360 Query API response and query ID for all three counts. `evidence/native-snowflake-federated-context.json` contains a successful native loyalty/consent join for P001. `evidence/native-federation-verification.json` reconciles native/source counts, tests P007 denied consent, changes P012 miles in Snowflake and observes the change through Data 360 without ingestion, revokes P012 consent and observes no eligible context, then restores and verifies the original source state. Mutations use the bootstrap identity; the connector identity retains SELECT-only access. Evidence distinguishes Data 360 query IDs from Snowflake query IDs.

The application selects this path explicitly with `DELTA_CONTEXT_MODE=data360_federation`. `delta_demo/federation.py` uses the authorized Salesforce CLI OAuth session to call `/ssot/queryv2`. Strict synthetic subject validation precedes SQL construction, consent purpose and allowed=true are required, ambiguity/subject mismatch/incomplete queries fail closed, and no direct SQL or fixture fallback occurs. `DELTA_CONTEXT_MODE=snowflake_python` preserves the previous explicitly selected Python connector path. This is a local developer OAuth bridge; hosted deployment needs a service OAuth identity, connection pooling, measured timeouts and operational circuit breaking.

## Why federation

Actual native capability and freshness tests support direct access for this small demonstration. Scheduled ingestion would introduce a second copy, stale-consent risk and reconciliation/delete jobs. Acceleration could help repeated analytic queries but adds a caching interval and credit consumption; it remains disabled. Source query costs use `DELTA_DEMO_WH` (X-Small, auto-suspend 60 seconds). Production SLAs, quotas, trial expiry, Snowflake query costs and region/residency approval still require an owner decision. The Snowflake region is AWS_US_EAST_2; this does not establish end-to-end EU residency.

## Boundaries and remaining work

These are real native external DLOs, not newly mapped custom DMOs or added Graph relationships. Their `mappings` arrays are empty. Existing CRM identity resolution and unified Graph remain separately deployed and verified; the application combines that verified pilot identity with a subject-filtered federated lookup. Do not claim a single Graph automatically traverses native Snowflake loyalty/travel relationships. Broader native Graph enrichment, business authority for P001-to-SkyMiles binding, platform data classification and lifecycle deletion remain future work.

Consent is enforced by the application/native SQL join, not a claimed Snowflake row-access policy or Data 360 administrator restriction. Authorized Data 360 administrators can query synthetic external DLOs directly. No new grants were added: the service role can read only the approved three customer tables, with database/schema/warehouse usage; raw passenger sources and ACCOUNTADMIN remain denied. Credential rotation/revocation and production secret management need an operations runbook.

The older PowerPoint/video and original Agentforce end-to-end trace predate native federation and document the earlier Python connector path. The new native API verification is separate evidence; do not relabel the historical Agentforce session as having used federation.

## Repeat verification

Authenticate the existing `delta-dev` Salesforce alias and the existing Snowflake bootstrap Keychain connection, then run:

```sh
.venv/bin/python scripts/verify_native_federation.py
.venv/bin/python -m pytest tests -q --junitxml=evidence/backend-tests.xml
```

The live verification temporarily changes only synthetic P012 miles and consent, restores them in a finally block, and records query IDs without credentials. An interrupted machine/process still requires checking restoration. Connector setup used Private Key Pair, the existing service user, account URL `drjmzef-su04270.snowflakecomputing.com`, and `DELTA_DEMO_WH`. This UI requires the base64 PKCS8 body without PEM delimiters; the first wrapper-format rejection is documented, not a credential or entitlement failure.
