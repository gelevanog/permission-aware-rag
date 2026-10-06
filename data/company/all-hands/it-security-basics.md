# IT Security Basics

Everyone at Fernhill Labs, including contractors, handles information that customers have trusted us with. These are the minimum security practices we expect from you. The IT team (Ian Brooks) and the security group are happy to help if any of this is unclear.

## Accounts and authentication

- Every account uses single sign-on through Okta with multi-factor authentication (MFA).
- Your primary second factor is the **YubiKey** you received on day one. Keep it on your keyring, not in your laptop bag. A backup YubiKey is available on request.
- SMS codes are not allowed as a second factor for any company system.
- Never share your account or approve an MFA prompt you did not start. If you get an unexpected prompt, deny it and tell IT.

## Passwords

All passwords that are not covered by SSO live in **1Password**. Use the generator; 20+ characters is the default. Shared credentials for teams belong in a shared vault, never in Slack, Notion or a spreadsheet. Your 1Password master password should be unique and never reused anywhere else.

## Phishing

Attackers increasingly target logistics software vendors because of the customer data behind them. Be suspicious of urgent messages about invoices, payroll changes or shared documents. If something looks off:

1. Do not click links or open attachments.
2. Forward the email as an attachment to **security@fernhill.test**, or use the "Report phishing" button in Gmail.
3. Delete it from your inbox.

Reporting a phish you clicked by mistake is always the right move. You will not get in trouble for it.

## Devices

- Company laptops are managed and have full-disk encryption (FileVault on macOS, BitLocker on Windows) turned on by default. Do not disable it.
- Screens must lock automatically after 5 minutes of inactivity. Lock manually (Ctrl+Cmd+Q on a Mac) whenever you step away.
- Keep your operating system and browser up to date; the management agent will nag you after 7 days.

## Customer data

Customer data must never be stored on personal devices, personal cloud storage or personal email. This includes exports, CSV files, screenshots of dashboards with customer names, and route data samples. If you need customer data for debugging or analysis, use the approved environments described by your team, and delete local copies when you are done.
