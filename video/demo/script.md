# Four-minute demonstration — spoken script

This is the demonstration segment intended for minutes 14–18 of the panel session. Exact narration and chapter timings are in [narration.json](narration.json). The video records actual execution in the private presenter console, including published Agentforce live actions. It uses synthetic speech and shortens cloud waiting time, with an on-screen disclosure.

| Segment | Time | On-screen action |
| --- | --- | --- |
| Disruption | 0:00–0:35 | Publish the native cancellation event; independently query the new Salesforce Case. Show that outbound notification is false. |
| Identity | 0:35–1:10 | Live-query the source/unified links; inspect both source IDs and the deployed exact-match rule. |
| Grounding | 1:10–1:45 | Ask actual Agentforce for context/status; inspect Graph proof, DIRECT_ACCESS facts and masked contact. |
| Options | 1:45–2:30 | Ask Agentforce for current options; follow live API traces and inspect both returned flights. |
| Booking | 2:30–3:00 | Accept Option 1; inspect the committed reservation, authoritative confirmation and synchronized Salesforce Case. |
| Trust | 3:00–3:35 | Request $250 against the $200 cap; inspect the approval proposal and human-review context. |
| Failure | 3:35–4:00 | Use a separate fresh ledger; remove Option 1; show the actual POST /rebook 409 and Agentforce's refreshed options. |

Corrections to the requested script: the event does not send an outbound message or update Data 360; native matching uses an AND rule rather than sequential SkyMiles-first matching; native unmerge is not demonstrated; payment fields are not returned; Case synchronization is distinct from human receipt. The 409 probe is an explicit operator API request; the subsequent agent conversation uses the same lost-seat inventory.
