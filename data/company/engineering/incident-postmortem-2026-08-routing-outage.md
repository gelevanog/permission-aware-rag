# Postmortem: INC-2291 Routing Outage, 14 August 2026

Severity: SEV1. Incident commander: Dan Kim. Author: Dan Kim, reviewed by Erin Walsh.
Status: Action items in progress. This is a blameless postmortem.

## Summary

On Friday 14 August 2026, the route-planner service in eu-west-1 stopped producing new route plans for **3 hours 12 minutes**, from 05:41 to 08:53 Lisbon time. During this window, customers in Europe could not create or re-optimise routes, and live ETA updates were delayed. North American tenants in us-east-2 were not affected.

## Timeline (Lisbon time)

- **05:30** A routine `ingest` deploy, held over from the Thursday train, is promoted by an automated retry.
- **05:41** Solver job failures begin; the `route-planner` worker pool starts crash-looping.
- **05:52** PagerDuty pages the Core primary on-call. Acknowledged at 05:55.
- **06:20** SEV1 declared, Dan Kim takes incident commander. Status page updated at 06:31.
- **07:05** Root cause suspected in malformed messages on the `orders.v3` Kafka topic.
- **07:40** Rollback of `ingest` completed, but workers keep failing on messages already in the topic.
- **08:25** Engineers deploy a patched consumer that skips and quarantines invalid messages.
- **08:53** Solver success rate back above 99.5%. Incident resolved at 09:30 after monitoring.

## Root cause

The `ingest` release included a change to how optional delivery-window fields are serialised. For orders without a time window, the new code wrote an empty object instead of `null`. The `route-planner` consumer did not validate messages against the schema and panicked on the empty object. Because the consumer committed offsets only after successful processing, every worker that restarted read the same poisoned messages and crashed again. Canary analysis only looked at `ingest` metrics, so it missed the downstream failure.

Contributing factors: no schema registry compatibility check on the `orders.v3` topic; the automated retry of a held release; and alert thresholds on solver failures that took 11 minutes to fire.

## Action items

| Action | Owner | Due | Status |
|--------|-------|-----|--------|
| Enforce schema registry compatibility checks for all Kafka topics | Platform | 30 Sep | Done |
| Dead-letter queue and poison-message handling in all consumers | Dan Kim | 15 Oct | In progress |
| Disable automated retries of held releases | Release tooling | 31 Aug | Done |
| Add downstream consumer health to canary analysis | Platform | 31 Oct | In progress |
| Lower solver failure alert threshold to fire within 3 minutes | Core team | 31 Aug | Done |

## Customer impact and service credits

Under the uptime commitments in our Enterprise and Growth contracts, Customer Success and Finance reviewed affected accounts. Leadership approved service credits totaling $86,300 to 23 customers, applied to their next invoices, plus a goodwill call from Hana Sato to the five most affected enterprise accounts. Legal confirmed that no customer contract required formal breach notification. A customer-facing RCA was sent on 21 August.
