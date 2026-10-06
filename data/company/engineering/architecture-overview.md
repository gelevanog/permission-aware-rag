# RouteIQ Architecture Overview

Audience: all engineers and embedded contractors. Owner: Platform team. Last reviewed: September 2026, after the RouteIQ 3.0 launch.

## High-level picture

RouteIQ is a set of services running on Kubernetes (Amazon EKS), deployed with ArgoCD from the `deploy-manifests` repository. Customer traffic enters through CloudFront and an Application Load Balancer, then reaches the `api-gateway` service, which handles authentication (Okta-backed for internal users, Auth0 for customers), rate limiting and routing to backend services.

## Core services

| Service | Language | Responsibility |
|---------|----------|----------------|
| `api-gateway` | Go | Public REST API (v1 and v2), auth, rate limits |
| `route-planner` | Go | Route optimisation engine; multi-depot solver introduced in 3.0 |
| `ingest` | Python | Orders, telematics and GPS data from customers and 40+ providers |
| `fleet-insights` | Python | Aggregations and dashboards; uses dbt models |
| `carbon` | Python | Emissions calculations (GLEC / ISO 14083) |
| `notifier` | TypeScript | Webhooks, email and live ETA sharing |
| `web-app` | TypeScript (React) | Customer-facing UI |

The `route-planner` is CPU heavy and runs on dedicated Graviton node groups. Large optimisation jobs are split into chunks and processed by a worker pool that scales on queue depth.

## Data stores and messaging

- **PostgreSQL** (Amazon RDS, version 15) is the primary transactional store. Each customer is a tenant identified by `tenant_id`; row-level security is enforced in the database for all customer tables.
- **Kafka** (Amazon MSK) connects services: `ingest` publishes order and telemetry events, which `route-planner`, `fleet-insights` and `carbon` consume. Topics are partitioned by `tenant_id`.
- **Redis** (ElastiCache) for caching distance matrices and session data.
- **S3** for raw telematics archives and exported reports; **ClickHouse** for analytical queries behind Fleet Insights.

## Regions

- **Primary region: AWS eu-west-1 (Ireland).** All EU customer data lives here and never leaves the EU.
- **Secondary region: AWS us-east-2 (Ohio).** Hosts North American tenants who chose US data residency and acts as a warm standby for disaster recovery of shared, non-personal components.

Database backups are taken every 6 hours with point-in-time recovery for 14 days. The recovery time objective for the core planning service is 4 hours.

## Observability

Metrics in Prometheus with Grafana dashboards, logs in OpenSearch, traces through OpenTelemetry into Grafana Tempo. Alerts route to PagerDuty. Every service must expose `/healthz` and `/readyz` endpoints and a standard RED-metrics dashboard before going to production.

## Where to go next

See the Engineering Onboarding guide for local setup, the API Design Guidelines for public interfaces, and the Tech Debt Roadmap 2027 for planned changes to this architecture.
