# Engineering Onboarding

Welcome to Fernhill Labs Engineering. This guide gets you from a fresh laptop to your first production change. It applies to new employees and embedded contractors alike; where something differs for contractors, it is called out.

## Your buddy

Every new engineer is paired with a **buddy** from their team for the first 6 weeks. Your buddy is not your manager: they are the person you can ask the "obvious" questions. Expect a daily 15-minute check-in in week one and twice a week after that. Buddies pair with you on your first pull request and your first release train.

## Dev environment setup

1. Make sure your laptop is enrolled in Kandji (employees) or meets the contractor device requirements, and that your YubiKey works with Okta.
2. Install Homebrew, then run `brew bundle` in the `dev-setup` repository. It installs Go 1.22, Python 3.12 with uv, Node 20, Docker Desktop, kubectl, the ArgoCD CLI and pre-commit.
3. Clone the repositories you need with `./clone-all.sh --team <your-team>`.
4. Run `make dev-up` in the `local-stack` repository. This starts PostgreSQL, Kafka (via Redpanda in local mode), Redis and a seeded tenant called "Demo Freight Co." using synthetic data.
5. Log into the staging environment with `aws sso login --profile staging`.

Setup should take about half a day. If it takes longer, tell your buddy; that is a bug in our docs.

## Key repositories

| Repository | What it is |
|------------|-----------|
| `route-planner` | Go optimisation engine |
| `ingest` | Python ingestion service |
| `api-gateway` | Public API |
| `web-app` | React front end |
| `deploy-manifests` | ArgoCD application definitions |
| `api-spec` | OpenAPI specification |
| `dev-setup`, `local-stack` | Tooling for local development |

## First-week tasks

- Day 1: laptop, accounts, meet your buddy and manager, read the Architecture Overview.
- Day 2: finish local setup; run the test suite of your team's main service.
- Day 3: pick up a `good-first-issue` ticket in Linear and open a pull request.
- Day 4: attend a release train with your buddy; read the Deployment Process and API Design Guidelines.
- Day 5: ship your first change to staging and write a short note in #eng-intros about what surprised you.

## Weeks 2 to 8

Employees shadow one on-call shift and join the rotation after 8 weeks. Contractors do not join on-call and do not receive production access; they work entirely in dev and staging. Everyone attends at least two internal tech talks and has a 30-day check-in with their manager.
