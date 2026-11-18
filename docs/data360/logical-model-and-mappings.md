# Data 360 logical model and mapping coverage

## Implemented source and standard models

`Passenger_Source__c` is the synthetic CRM source. `Source_Id__c` is its stable upsert key, `Passenger_Ref__c` is the demonstration subject reference, and the Salesforce record ID is the DLO primary key. `Raw_Email__c` retains the original contact variant. `Email__c` and `Identity_Email__c` contain the verified canonical contact selected by deterministic, conflicting-loyalty-veto preprocessing; unverified group contacts are blank for matching. Source records and raw variants remain available in the original dataset and CRM. `scripts/prepare_salesforce_data.py` reproduces the preparation and merge-lineage record.

| Source → target | Implemented fields | Purpose |
|---|---|---|
| CRM → Delta_Passenger_Source__dll | Source ID, Salesforce ID, surname, loyalty, PNR, contact, tier, consent, special case, verified contact and timestamps | Actual 14-row CRM ingestion; canonical-contact propagation verified separately |
| DLO → ssot__Individual__dlm | Id → ssot__Id__c; Name → LastName; SkyMiles → ExternalRecordId; modification time | Stable source-level service profile |
| DLO → ssot__ContactPointEmail__dlm | Id → Id and PartyId; Email → EmailAddress | Actual active mapping; canonical email is prepared before ingestion |
| DLO → ssot__PartyIdentification__dlm | Id → Id and PartyId; SkyMiles → IdentificationNumber | Source loyalty identifier; missing identification type/name originally prevented its use as the native match key |
| Native ruleset → UnifiedssotIndividualDlt / UnifiedLinkssotIndividualDlt | Exact canonical email AND loyalty AND surname | Actual ruleset and link tables; native duplicate merge and conflicting-loyalty separation are verified in current query evidence |

The logical relationship is Individual 1:N Email / Phone / PartyIdentification / Booking / TravelHistory / Case / Consent. Native Email and PartyIdentification mappings exist. Phone, custom Booking, TravelHistory, Loyalty, Disruption and consent-specific DMOs remain logical design elements, not deployed Data 360 custom-object claims. Those facts are implemented in CRM source fields, Snowflake tables or the external transaction ledger as described below.

| Logical entity | Current authoritative implementation | Intended production integration |
|---|---|---|
| Loyalty and historical travel | Real Snowflake CUSTOMER_360 tables | Three verified native DIRECT_ACCESS external DLOs; see docs/federation-decision.md (custom DMO/Graph relationships remain undeployed) |
| Consent | CRM source flag and real Snowflake purpose filter; API checks before use | Purpose-specific consent DMO, enforcement, revocation and retention workflows |
| Booking / live inventory | External FastAPI SQLite transaction ledger | Authoritative reservation API, never stale profile inventory |
| Disruption | Synthetic flight ledger and Snowflake disruption events | Versioned event/API with authoritative timestamps |
| Case | Actual Salesforce Case and unique transaction external ID | Staffed Service Console/Omni-Channel after delivery tests |
| Phone | No synthetic phone collection required by this pilot | Verified E.164 contact point mapping if phone matching is authorized |

## Graph and calculated insight

`Passenger_Disruption_Context` is an actual Data 360 source-profile Graph projecting Individual ID, surname and loyalty external ID. Its REST result is verified against fixed synthetic P001 before Snowflake context is returned. The additional `Delta_Unified_Disruption` Graph is now rooted in the actual native unified Individual and used at runtime after a fresh source-link verification. Native Apex Graph methods returned null; the labeled real REST adapter uses authorized local Salesforce CLI authentication. Hosted deployment must replace that developer bridge with dedicated OAuth.

`Delta_Profile_Evidence__cio` groups the synthetic loyalty key and counts source Individual IDs. An actual query returned SYN0000001 / 2. This proves duplicate source multiplicity, not eligibility or a completed identity merge. See `evidence/data360-calculated-insight-result.json`.

## Identity and governance acceptance

Local exact-match order is loyalty, then PNR+surname for non-group sources, then verified email/phone. Conflicting loyalty always vetoes a fallback. Survivor contact must be verified; raw values are retained; latest explicit consent wins. Fuzzy matching is not enabled for automatic merging. Native rules are a stricter subset, with exact verified canonical email, loyalty and surname. The native acceptance script checks the duplicate pair shares one unified ID and conflicting-loyalty group records remain distinct. A published ruleset, accepted job or nonempty link table alone does not satisfy that test.

Current record lifecycle is demonstration retention with local protected runtime files. Production retention periods, legal purpose, classification tags, deletion propagation, subject access, backup deletion and regional processing require owner-approved policy and tests. No production retention control or full platform PII-classification deployment is claimed.
