# Delta Agentic Disruption Recovery

**From cancelled to confirmed in minutes — one-minute overview**

https://github.com/user-attachments/assets/46381434-0447-433f-96ca-719390de2c67

[Download the one-minute MP4](https://github.com/udhayapriya1/delta-agentic-disruption-recovery/raw/refs/heads/main/video/demo/delta-rebooking-1min-video.mp4)

**Four-minute product demo — actual execution with narration**

https://github.com/user-attachments/assets/d924ee6a-3e89-45e8-b045-29978297245c

[Download the full demo MP4](https://github.com/udhayapriya1/delta-agentic-disruption-recovery/raw/refs/heads/main/video/demo/delta-recovery-live-demo.mp4) · [Execution evidence](video/demo/execution.json) · [Four-minute script](video/demo/script.md)

A cancelled flight should lead to a verified recovery, with the correct passenger, current inventory and a clear boundary for human approval.

This project demonstrates that journey using **Salesforce Agentforce, Data 360 and Snowflake**, connected to an executable synthetic reservation and voucher service. Salesforce and Snowflake calls are real. Passenger records, flight operations, bookings and voucher policies are synthetic demonstration data; this is not a Delta production system.

## Pilot Targets to Validate — Not Baselines

These are proposed pilot targets to validate, not measured baselines or achieved results.

| Measure | Pilot target | Why it matters |
| --- | --- | --- |
| Median time to rebook | Under 5 minutes for eligible Medallion passengers on a single disrupted route | Speed is the passenger experience during disruption. |
| Routine contact deflection | 30% deflection of routine rebook contacts in the pilot | Frees human agents for complex and vulnerable passengers. |
| Wrong-passenger rebookings | **Zero. This is a hard gate, not a target to trade off.** | One wrong identity merge makes the whole design unsafe. |
| Experience and cost | CSAT and cost per contact tracked throughout the pilot | Speed without trust or value is not success. |

## Passenger Recovery Agent

The published `Delta_Medallion_Recovery` agent verifies passenger context, checks cancellation status, retrieves real options from the mock reservation API, records an explicit selection, and completes a reservation. Above-cap voucher requests require human approval. If a seat disappears, the service rejects the transaction and the agent must retrieve fresh inventory.

### Agent Details

- **Four topics:** disruption status, rebooking, credit vouchers and escalation.
- **Seven actions:** customer context, flight status, rebooking options, acceptance, rebooking, voucher request and handoff.
- **Execution:** Agentforce → Flow → Apex → Named Credential → FastAPI.
- **Identity:** native Data 360 resolution consolidates 14 source records into 13 profiles; conflicting loyalty identities remain separate.
- **Grounding:** a unified Data Graph verifies the fixed P001 pilot identity. The Data 360 Query API separately reads consent-filtered Snowflake context through native zero-copy federation.

### Agent Topics

| Topic | What it does | Boundary |
| --- | --- | --- |
| Disruption Status | Explains what happened using grounded sources only | Read only; no transaction. |
| Rebook | Offers real options and completes an accepted rebooking | Same cabin, pilot route and approved 24-hour recovery window only; explicit passenger acceptance required. |
| Credit / Voucher | Explains eligibility and requests or issues a voucher within the permitted limit | Autonomous up to the $200 pilot cap; human approval above it. |
| Escalate | Prepares a human-review Case with the full available context | Passenger can request escalation at any time; staffed routing and human receipt remain unverified. |

### Agent Actions

The published agent has seven registered actions. The Case workflow below is a supporting capability, separate from those seven actions. External calls use Flow → Apex → Named Credential → API.

| Action | Inputs / Outputs | Tool type | Permission |
| --- | --- | --- | --- |
| Get customer context | Authenticated passenger context in / verified identity, loyalty, consent purpose and source references out | Flow calling the context API; Data Graph and federated Query API grounding | Autonomous read, subject to passenger binding and consent. |
| Get flight status | PNR in / cancellation status, reason and source timestamp out | Flow calling the external status API | Autonomous read. |
| Get rebook options | Authorized PNR and verified passenger context in / currently available same-cabin options out; two options in the happy path | Flow calling the external reservation API | Autonomous read within pilot eligibility rules. |
| Record acceptance | PNR and chosen option in / short-lived acceptance ID out | Flow calling the acceptance API | Requires explicit passenger selection and authorization. |
| Complete rebook | Chosen option, acceptance ID, passenger reference and idempotency key in / reservation confirmation, existing PNR and selected option out | Flow calling the rebooking API | Autonomous execution after acceptance, within pilot rules. |
| Issue / request voucher | Amount, reason, Case reference and idempotency key in / voucher ID or approval-required request out | Flow calling the voucher API | Autonomous up to $200; separate human approval above it. |
| Create / update Case — supporting workflow | Verified transaction ID and summary in / Case record ID out | Flow with guarded Apex upsert; runtime synchronization uses Salesforce REST | Autonomous after authoritative booking confirmation; recovery action permission required for the Flow. |
| Escalate to human | Passenger request and available context package in / durable handoff and Case update status out | Flow calling the escalation API | Autonomous and on demand; no claim of staffed delivery or human acknowledgement. |

### Agent Architecture

![Current Salesforce, Data 360, Snowflake and reservation architecture](architecture/presentation/delta-recovery-architecture.png)

### Component Details

| Component | Responsibility |
| --- | --- |
| Salesforce Agentforce | Conversation, topic selection and fixed action invocation |
| Salesforce Data 360 | CRM ingestion, standard model mappings, native identity resolution, unified Data Graph, profile-count calculated insight and Query API |
| Snowflake | Loyalty, purpose-specific consent and travel history, exposed as three native `DIRECT_ACCESS` external DLOs with acceleration disabled |
| FastAPI reservation service | Authoritative synthetic flight status, inventory, acceptance, atomic rebooking and idempotency |
| Voucher service | $200 autonomous demonstration cap; approval proposal for a $250 request; separate human approver role |
| Salesforce Case | Confirmed booking synchronization and a context-bearing human-review record |

The external Snowflake DLOs are queried separately from the unified Graph; custom federated DMO and Graph relationships are not deployed. Live seat inventory stays in the reservation service.

## Setup and Installation

### Prerequisites

- Python 3.13 and Salesforce CLI (`sf`).
- An authorized Salesforce org with Agentforce and Data 360 enabled. This demo uses alias `delta-dev` and existing deployed synthetic source identifiers.
- For the native path, the existing Snowflake connector and three `DIRECT_ACCESS` streams described in the [federation runbook](docs/federation-decision.md).

### Installation

```bash
git clone https://github.com/udhayapriya1/delta-agentic-disruption-recovery.git
cd delta-agentic-disruption-recovery
./scripts/setup.sh
```

Authenticate the intended Salesforce org:

```bash
sf org login web --alias delta-dev
```

The deployment assets target the existing demo org. A new org requires provisioning the native data resources and agent, then updating the source IDs in `delta_demo/salesforce.py`. See [deployment instructions](docs/deployment-guide.md) and the [Data 360 mappings](docs/data360/logical-model-and-mappings.md).

## Running the Integration Service

```bash
export DELTA_JWT_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DELTA_CONTEXT_MODE=data360_federation
export DELTA_SALESFORCE_ORG=delta-dev
export DELTA_SALESFORCE_SYNC=true
export DELTA_DATA360_REST_GRAPH=true
export DELTA_DATA360_UNIFIED_GRAPH=true
./scripts/run-api.sh
```

Open [the API documentation](http://127.0.0.1:8000/docs). In another terminal with the same secret, issue a short-lived local passenger token:

```bash
.venv/bin/python -m scripts.issue_test_token --subject P001
```

Use it as the bearer credential when calling the API. Keep credentials out of source control, screenshots and logs. `.env.example` lists supported settings; the service expects exported environment variables and does not automatically load `.env`.

### Running the Agent

Open the published **Delta Medallion Recovery** agent in Agentforce Builder and start Preview. Its Named Credential must point to the running service and contain a matching unexpired P001 token. [Conversation prompts](docs/live-agentforce-conversation.md) cover status, context, options, explicit acceptance, booking and voucher approval.

## Validation

```bash
./scripts/run-tests.sh
.venv/bin/python scripts/verify_native_identity.py
.venv/bin/python scripts/verify_native_federation.py
```

Local tests cover authorization, consent, conflicting identity, current acceptance, idempotency, concurrent bookings, voucher approval, source failure and 409 recovery. Unit tests inject explicit fixtures; they do not establish cloud deployment success. Native verification scripts query the connected platform. Federation verification temporarily changes synthetic P012 miles and consent, then restores them.

## Demonstrated Boundaries

- The native disruption event subscriber creates a Case. Proactive outbound messaging and event-driven Data 360 refresh are not implemented.
- Native identity matching requires exact canonical verified email **and** loyalty identifier **and** surname. Native unmerge remains untested.
- Contact data is masked in the context response; payment data is not returned by this API.
- A human-review Case update does not establish staffed Omni-Channel delivery or human acknowledgement.
- Hosted Salesforce OAuth, managed secrets, retention/deletion controls and surge testing remain production work.

## Project Structure

```text
delta_demo/       Integration service, identity and cloud adapters
salesforce/       Active metadata and Data 360 configuration assets
snowflake/        Synthetic source schema and bootstrap SQL
data/             Synthetic passenger records and source mappings
scripts/          Setup, deployment and verification tools
tests/            Automated behavior and adapter tests
architecture/     Current architecture diagram
video/demo/       Product demo videos, captions and execution evidence
docs/             Deployment, data model, federation and security runbooks
```

Earlier architectures, migration plans, raw deployment iterations and presentation drafts are excluded from the demo check-in. The README structure follows the agent overview, architecture, components and setup flow of the [Harmony City Zoo agent example](https://github.com/lynnaloo/harmony-zoo-agent/blob/main/README.md).
