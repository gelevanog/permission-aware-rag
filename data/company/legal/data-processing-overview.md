# Data Processing Overview

Owner: Grace Liu, General Counsel, with the Platform team. This overview is for all employees and can be shared with prospects on request. Our full Data Processing Agreement (DPA) and privacy policy remain the binding documents.

## GDPR basics for Fernhill

Fernhill Labs is headquartered in Portugal, so the GDPR applies to everything we do, and our lead supervisory authority is the Portuguese CNPD.

- **For customer data in RouteIQ** — orders, delivery addresses, recipient names and phone numbers, driver names and GPS positions — our customers are the **controllers** and Fernhill is the **processor**. We only process this data on our customers' documented instructions, as set out in the DPA.
- **For our own employees, candidates and website visitors**, Fernhill is the controller.
- We minimise personal data: GPS traces are kept for 13 months by default, recipient phone numbers are deleted 90 days after delivery, and customers can configure shorter periods.
- Data subject requests that reach us about customer data are forwarded to the relevant customer within 2 business days.

## EU data residency

All customer data for EU and UK customers is stored and processed in **AWS eu-west-1 (Ireland)**. Backups for these customers are also kept in eu-west-1. North American customers can choose data residency in AWS us-east-2 (Ohio). Support engineers in Austin can access EU customer data only through approved tooling, under the EU Standard Contractual Clauses and our transfer impact assessment, and only when needed to resolve a ticket.

## Sub-processors

| Sub-processor | Purpose | Location |
|---------------|---------|----------|
| Amazon Web Services | Hosting, storage, backups | Ireland (EU customers), USA (US customers) |
| Auth0 (Okta) | Customer login and authentication | EU region |
| Twilio | SMS for live ETA notifications | USA, with SCCs |
| SendGrid | Transactional email | USA, with SCCs |
| Zendesk | Customer support tickets | EU region |
| Google Maps Platform | Geocoding and traffic data | Global, with SCCs |

Customers are notified at least **30 days** before we add a new sub-processor, and they may object under the DPA.

## Security measures

Encryption in transit (TLS 1.2+) and at rest (AES-256), tenant isolation using row-level security, just-in-time production access with session recording, annual penetration testing, and a SOC 2 Type II audit in progress. Personal data breaches are handled under our incident response plan, including notification to the CNPD within 72 hours where required.

## Who to ask

Privacy questions go to privacy@fernhill.test. Customer requests for the DPA, sub-processor list or security questionnaire answers go through the #legal-requests form.
