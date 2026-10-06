# On-Call Handbook

Owner: Platform team. Applies to all engineers in the production on-call rotations. Contractors do not take part in on-call.

## Rotations

We run three weekly rotations, each with a primary and a secondary:

- **Core** (`route-planner`, `api-gateway`, PostgreSQL)
- **Data** (`ingest`, Kafka, `fleet-insights`, `carbon`)
- **Web** (`web-app`, `notifier`)

Shifts start **Monday at 10:00 Lisbon time** and last one week. Because we have engineers in Lisbon and Austin, the rotation follows the sun where possible: Lisbon engineers cover 07:00–19:00 Lisbon time and Austin engineers cover the rest, so nobody is paged in the middle of their night on a normal week. Engineers join the rotation after their first 8 weeks and after shadowing one full shift.

Schedules, overrides and swaps live in **PagerDuty**. If you need a swap, arrange it with a colleague and record it in PagerDuty yourself; post it in #oncall.

## Severity levels

| Severity | Definition | Response |
|----------|------------|----------|
| SEV1 | Core planning or the API unavailable or giving wrong routes for many customers; data breach suspected | Acknowledge within 5 minutes, incident channel and incident commander immediately, status page within 15 minutes |
| SEV2 | Major feature degraded for many customers, or full outage for a single enterprise customer | Acknowledge within 15 minutes; status page if customer-visible for over 30 minutes |
| SEV3 | Minor degradation, workaround available, or internal tooling broken | Handle in working hours; ticket in Linear |

When in doubt, declare the higher severity. Downgrading later is cheap.

## Escalation

1. The primary on-call is paged first. If they do not acknowledge within 10 minutes, PagerDuty escalates to the secondary.
2. After a further 10 minutes, the engineering manager on duty is paged.
3. For any SEV1, the incident commander pages Erin Walsh (VP Engineering), who decides whether to involve leadership, Support and Legal.
4. Suspected security incidents follow the Security Incident Response Plan; page the security on-call in addition.

Use `/incident declare` in Slack to open an incident channel and start the timeline automatically.

## Compensation and wellbeing

- On-call engineers receive an **on-call stipend of $350 per week** for each primary week (or the euro equivalent through Portuguese payroll). Secondary weeks are paid at half.
- If you are paged outside working hours for more than one hour, take the equivalent time off the next working day. You do not need to ask.
- Nobody should be on primary more than one week in five. Raise it with your manager if the rotation gets thinner than that.

## After an incident

Every SEV1 and SEV2 gets a blameless postmortem within 5 working days, using the template in Notion. Action items are tracked in Linear with the `postmortem` label and reviewed in the weekly reliability meeting.
