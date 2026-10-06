# Deployment Process

How code gets from a merged pull request to customers. Applies to all services in the RouteIQ platform. Owner: Platform team.

## Overview

We use GitOps. Every service has its own repository with a GitHub Actions pipeline that builds a container image, runs tests and pushes the image to Amazon ECR. Deployments happen when the image tag is updated in the `deploy-manifests` repository; **ArgoCD** watches that repository and syncs the change to the EKS clusters in eu-west-1 and us-east-2.

Environments: `dev` (every merge to main, automatic), `staging` (automatic after dev passes smoke tests), `production` (via the release train below).

## Release train

Production releases go out on the **release train every Tuesday and Thursday**:

1. **09:00 Lisbon time:** the release bot opens a release PR in `deploy-manifests` listing every change that has been in staging for at least 24 hours with green end-to-end tests.
2. **Until 11:00:** service owners review their changes and can pull them from the train by commenting `/hold`.
3. **11:30:** the release captain (rotating among L3+ engineers) merges the PR. ArgoCD rolls out to eu-west-1 first.
4. **12:15:** after 45 minutes of healthy metrics (error rate, p95 latency, solver success rate), the same release is promoted to us-east-2.
5. The release captain posts a summary in #releases.

Hotfixes for SEV1 or SEV2 incidents can be deployed outside the train with approval from the incident commander and one reviewer.

## Progressive delivery

`api-gateway`, `route-planner` and `web-app` use Argo Rollouts canaries: 10% of traffic for 15 minutes, then 50%, then 100%. A canary is aborted automatically if the error rate exceeds the baseline by 0.5 percentage points. Risky changes should also sit behind a LaunchDarkly feature flag.

## Change freeze windows

No production releases (other than incident fixes) during:

- **Winter shutdown:** 21 December 2026 to 4 January 2027 (we freeze a few days either side of the company shutdown).
- **US Thanksgiving week:** 23–27 November 2026, because many customers run peak volumes.
- The **48 hours before** any major customer go-live flagged by Customer Success in #releases.

## Rollback

If a release causes problems in production:

1. In ArgoCD, select the application and use **History and Rollback** to return to the previous synced revision, or revert the release PR in `deploy-manifests` (preferred, because it keeps Git as the source of truth).
2. Confirm the rollback in Grafana: error rates and latency should recover within 10 minutes.
3. Database migrations must be backward compatible with the previous release (expand–contract pattern) so that a rollback never needs a schema change.
4. Open an incident if customers were affected, and add the cause to the release PR.
