# IT Admin Runbook

Owner: Ian Brooks, IT Administrator. For IT staff and the backup admins only. Every admin action in Okta and Kandji is logged; record the ticket number in the change reason.

## Okta administration

Okta is our identity provider for all employees and contractors. Admin roles:

- **Super admin:** Ian Brooks and Erin Walsh (break-glass only). Super admin is never used for day-to-day work.
- **Org admin:** Ian Brooks and the backup IT contractor in Lisbon.
- **Help desk admin:** used for password resets and MFA resets.

Common procedures:

1. **New joiner:** HiBob triggers the joiner workflow 10 working days before the start date. Check the user's department and group assignments (e.g. `engineering`, `finance`, `managers`) and that contractors are placed in the `contractors` group with the `-ext` suffix. Enrol a YubiKey as the required factor.
2. **MFA reset:** only after verifying the person on a video call with their camera on and confirming their identity against the HiBob photo. Never reset MFA based on a Slack message or email alone.
3. **Group changes:** changes to `leadership`, `finance`, `hr` and `legal` groups require written approval from the group owner, recorded in the ticket.

## Offboarding

Access must be removed **within 4 hours of termination**, and immediately for involuntary terminations (coordinate timing with the People team so access is cut during the termination meeting).

Checklist:
- Suspend the Okta account (this ends sessions in all SSO apps).
- Revoke GitHub organisation membership and remove personal access tokens.
- Remove the user from Teleport roles and rotate any shared credentials they had access to in 1Password.
- Transfer Google Drive ownership to the manager; set an email auto-reply and forward to the manager for 30 days.
- Lock the laptop through Kandji and arrange the return of the device and YubiKey.
- Disable the Kisi badge.
Record the completion time in the ticket; auditors sample these.

## Device management with Kandji

All company Macs are enrolled in **Kandji** through Apple Business Manager, so devices enrol automatically on first boot. The standard blueprint enforces FileVault, the firewall, a screen lock after 5 minutes, automatic OS updates within 7 days, and installs the endpoint protection agent. Windows laptops (four in Finance) are managed separately with Intune. Lost or stolen devices: lock immediately, wipe after 24 hours if not recovered.

## Quarterly access reviews

Every quarter (in January, April, July and October), IT exports access lists for Okta groups, GitHub, AWS, Teleport, NetSuite, Salesforce and HiBob. Each system owner reviews their list within 10 working days and confirms or removes access. IT completes removals within 2 working days and stores the evidence in the SOC 2 evidence folder. The October 2026 review starts on 12 October.
