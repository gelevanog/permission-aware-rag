# Production Access Runbook

Owner: Platform team, with IT (Ian Brooks) for identity. Contractors are never granted production access under this runbook.

## Principles

Nobody has standing access to production. All access to production Kubernetes clusters, databases and AWS consoles is just-in-time, time-limited, approved and recorded. This protects customer data and gives us the audit evidence we need for SOC 2.

## Access through Teleport

All production access goes through **Teleport**, which is connected to Okta.

1. Run `tsh login --proxy=teleport.fernhill.test` and authenticate with Okta and your YubiKey.
2. Request a role: `tsh request create --roles=prod-readonly --reason="INC-xxxx or ticket link"`. Available roles are `prod-readonly` (kubectl get/logs, read replica of PostgreSQL), `prod-operator` (restart deployments, scale, run approved jobs) and `prod-db-write` (write access to the primary database).
3. Once approved, run `tsh kube login` or `tsh db connect` as needed. Sessions are recorded and kept for one year.

## Approvals

| Role | Approvers | Maximum duration |
|------|-----------|------------------|
| `prod-readonly` | Any L4+ engineer on the same team | 8 hours |
| `prod-operator` | Engineering manager or on-call incident commander | 4 hours |
| `prod-db-write` | Two approvers, one of whom must be Erin Walsh or a Staff Engineer | 2 hours |

You cannot approve your own request. During an active SEV1 or SEV2, the incident commander can approve `prod-operator` for anyone working the incident.

## Break-glass procedure

Break-glass is only for situations where Teleport or Okta itself is unavailable and production is down or customer data is at risk.

1. Two engineers from the on-call rotation must agree that break-glass is needed. Announce it in #incident-active and page Erin Walsh.
2. Retrieve the emergency credentials from HashiCorp Vault at `secret/prod/breakglass-7731`. Vault requires two of the five unseal-key holders (Erin Walsh, Ian Brooks and three Staff Engineers) to approve the read.
3. Use the credentials only for the actions needed to restore service. Keep a written log of every command in the incident channel.
4. When the incident is over, IT rotates the break-glass credentials within 24 hours and the event is reviewed in the postmortem.

Any use of break-glass without a SEV1 or SEV2 incident is treated as a security incident.

## Periodic review

IT reviews Teleport role assignments and access logs quarterly together with Engineering managers. Unused roles are removed. Findings go into the access review evidence folder used for the SOC 2 audit.
