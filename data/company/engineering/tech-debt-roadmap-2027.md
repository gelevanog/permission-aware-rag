# Tech Debt Roadmap 2027

Owner: Erin Walsh, VP Engineering, with the Staff Engineers group. Status: agreed in the engineering leads meeting on 24 September 2026; capacity confirmed subject to the 2027 budget.

## Why now

Platform reliability is one of the three company priorities for 2027. The August routing outage (INC-2291) showed that some of our foundations were built for 50 customers, not 300. We are committing roughly **25% of engineering capacity** in 2027 to the items below, tracked as a single Linear initiative with a monthly review.

## 1. Migrate from Kafka to Redpanda (Q2 2027)

We run Amazon MSK today. Redpanda is API-compatible with Kafka, so most consumers will not change, and it should cut streaming costs by an estimated 35–40% while giving us lower tail latency and simpler operations (no ZooKeeper, built-in schema registry).

Plan:
- Q1: run Redpanda in staging alongside MSK; mirror production topics with MirrorMaker 2 and compare.
- **Q2 2027: migrate production topics** tenant group by tenant group, starting with internal and low-volume tenants; decommission MSK by the end of June.
- Owner: Data platform team.

## 2. Deprecate API v1 (by 30 June 2027)

About 14% of API traffic still uses v1. We will announce the deprecation in October 2026, add `Deprecation` and `Sunset` headers, and contact every customer still on v1 through Customer Success. **API v1 will be switched off on 30 June 2027.** Migration guides for the five most-used v1 endpoints are due by December 2026.

## 3. Other items

| Item | Target | Notes |
|------|--------|-------|
| Poison-message handling and dead-letter queues in all consumers | Q4 2026 | Follow-up from INC-2291 |
| Upgrade PostgreSQL 15 to 17 on RDS | Q1 2027 | Blue/green deployment |
| Split the `fleet-insights` monolith into query and aggregation services | Q2–Q3 2027 | Reduces deploy risk |
| Active-active failover for the planning service across eu-west-1 and us-east-2 (non-personal data only) | Q3 2027 | Must respect EU data residency |
| Replace hand-written Terraform modules with a shared module library | Ongoing | Platform team |
| Remove Python 3.9 from the `carbon` service | Q1 2027 | End of life |

## How we measure success

- 99.95% monthly uptime for core planning, every month of 2027.
- Mean time to recovery for SEV1 incidents under 60 minutes.
- Streaming infrastructure cost down at least 30% by Q3 2027.
- Zero customers on API v1 after 30 June 2027.
