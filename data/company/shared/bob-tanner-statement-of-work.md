# Statement of Work: Bob Tanner, Backend Engineering Services

This Statement of Work (SOW 2026-07) is entered into under the Contractor Agreement dated 24 June 2026 between Fernhill Labs, Inc. ("Fernhill") and Bob Tanner, an independent contractor ("Contractor"). Engagement is administered through Deel.

## Parties and term

- **Client contact:** Erin Walsh, VP Engineering, who approves timesheets and deliverables.
- **Day-to-day lead:** the Data platform team's engineering manager.
- **Term:** 1 July 2026 to 31 December 2026, unless extended in writing by both parties or terminated earlier with 14 days' written notice by either party.

## Scope of services

Contractor will work as a backend engineer embedded in Fernhill's Engineering team, primarily on the `ingest` service and streaming infrastructure. Contractor works in development and staging environments only and will not be granted production access or access to customer production data. Contractor will not take part in on-call rotations.

## Deliverables

1. **Dead-letter queue framework** for all Kafka consumers, including poison-message quarantine, replay tooling and documentation — due 15 October 2026.
2. **Schema validation library** for Python services, integrated with the schema registry, adopted in `ingest`, `fleet-insights` and `carbon` — due 15 November 2026.
3. **Redpanda compatibility test suite** that runs all consumer integration tests against both MSK and Redpanda in staging — due 15 December 2026.
4. Handover documentation and two recorded knowledge-transfer sessions before the end of the term.

Each deliverable is accepted when merged to main with review from a Fernhill engineer and confirmed by Erin Walsh in writing.

## Fees and hours

- **Rate:** $95 per hour, billed monthly in arrears through Deel.
- **Hours cap:** a maximum of **30 hours per week**. Hours above the cap are not billable unless approved by Erin Walsh in writing before the work is done.
- Timesheets are submitted in Deel by the 3rd business day of the following month. Fernhill pays approved invoices within 15 days.
- No expenses are reimbursable unless pre-approved; approved travel follows Fernhill's Travel Policy.

## Other terms

All work product, including code and documentation, is owned by Fernhill on creation, as set out in the Contractor Agreement. Contractor remains bound by the NDA and Fernhill's IT security requirements, uses a Fernhill-managed YubiKey and 1Password account, and must return all equipment and delete all Fernhill data at the end of the term.

Signed: Erin Walsh for Fernhill Labs, Inc., 26 June 2026. Bob Tanner, 26 June 2026.
