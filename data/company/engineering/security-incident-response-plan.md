# Security Incident Response Plan

Owners: Erin Walsh (VP Engineering) and Ian Brooks (IT Administrator). Legal adviser: Grace Liu, General Counsel. Reviewed annually and after every SEV-S1 incident; last tabletop exercise held 10 June 2026.

## What counts as a security incident

Any event that threatens the confidentiality, integrity or availability of Fernhill or customer data. Examples: a compromised employee account, malware on a laptop, a leaked API key or credential, unauthorised access to production, a misconfigured S3 bucket, a lost unencrypted device, or a vendor reporting a breach that involves our data.

If you are unsure, report it. Reporting something that turns out to be harmless costs us nothing.

## Severity levels

| Level | Description | Examples |
|-------|-------------|----------|
| SEV-S1 | Confirmed or likely access to customer personal data or production systems by an unauthorised party | Database exfiltration, compromised admin account |
| SEV-S2 | Security control failure with potential data exposure, no evidence of access yet | Public S3 bucket with internal files, leaked AWS key revoked within minutes |
| SEV-S3 | Limited, contained event | A single phishing click with no credential entry, lost laptop with full-disk encryption |

## Who to page

1. Page the **security on-call** in PagerDuty (service "Security"), or post in #security-incident if you cannot use PagerDuty.
2. For SEV-S1 and SEV-S2, the security on-call pages Erin Walsh and Ian Brooks, and opens a private incident channel. Erin informs Grace Liu and Hana Sato.
3. For incidents involving employee devices or accounts, Ian Brooks leads containment (disable the Okta account, lock or wipe the device through Kandji, rotate credentials in 1Password).

Do not discuss suspected security incidents in public channels.

## Regulatory notification

Under the GDPR, a personal data breach that is likely to result in a risk to individuals must be reported to the supervisory authority (for us, the Portuguese CNPD) **within 72 hours** of becoming aware of it. Because many customers are controllers and we are their processor, our customer DPAs also require us to notify affected customers "without undue delay"; our internal target is within 48 hours of confirmation. Grace Liu decides on notifications, and the clock starts when the incident commander confirms a breach is likely, so record that time precisely. US state breach notification laws are assessed in parallel for US data subjects.

## Communication

- Internal updates every 2 hours for SEV-S1, every 4 hours for SEV-S2, in the private incident channel.
- Customer communication is drafted by Legal and Customer Success; no one else contacts customers about a security incident.
- Media enquiries go to Hana Sato only.
- After the incident, a postmortem within 10 working days, with action items tracked in Linear.
