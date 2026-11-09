# Security and demo boundaries

Current engineering review and verified boundaries: `docs/SECURITY_REVIEW.md` and `docs/P0_DELIVERY.md` (2026-11-09). Individual staff identities, RBAC, TOTP and revocable sessions are implemented. This remains a guarded preview, with commercial checkout disabled.

- Never commit `.env`, API credentials, customer data, payment payloads, private tokens or admin passwords.
- If any credential was present in an earlier shared archive or repository history, rotate it at the provider; removing it from the current tree does not remove it from Git history.
- `DEMO_MODE=true` is mandatory for public preview. Checkout stores synthetic order labels only; the submitted name and phone are validated then discarded. No customer contact details are persisted or forwarded.
- The demo prize wheel uses free test tickets, a server-side random selection and a stock counter. Prizes are samples, not promises of delivery. Do not sell chances or introduce cash stakes.
- Demo analytics and orders are synthetic. SQLite at `/tmp` is ephemeral on Render and must not be used for business records.
- Bootstrap owner access requires a strong `ADMIN_PASSWORD_HASH` and a stable random `FLASK_SECRET_KEY` set as deployment secrets. Staff accounts use individual password hashes and server session records; all admin endpoints enforce explicit permissions. Do not expose deployment credentials in a public repository.
- `Idempotency-Key` is mandatory for `/api/orders` and `/api/game/spin`. Receipts and effects share one database transaction; retries must reuse both the key and the exact payload.
- Browser visitor IDs cannot claim an existing profile without the signed session. The `max_` identity namespace is accepted only after verified MAX authentication.
- TOTP seeds currently require database-level protection: application-layer encryption and self-service recovery are not implemented. Enroll and confirm MFA privately before requiring it; production startup always requires privileged MFA.
- PostgreSQL uses a transitional application-wide transaction lock. Validate throughput before commercial traffic; do not present serialization as a final scalability solution.
- Social API environment variables are only presence checks. Publishing adapters are not implemented; the application must not claim that a post was published.
- Payment, delivery, CRM, MAX, VK and Telegram integrations are not connected until official owner credentials, contracts, API scopes and end-to-end tests are completed.
- Do not switch `DEMO_MODE=false` until PostgreSQL migrations, persistent storage, rate limits, privacy/consent flows, payment webhook verification, idempotency, stock reservation, backups, recovery and production acceptance tests are implemented.
- Before real contests or prize draws, obtain legal review of rules, eligibility, selection, publication of winners, prize delivery, advertising and personal-data processing.
- Use HTTPS, secure cookies, least-privilege roles, MFA, audit logs, secret rotation and monitoring in production.
