# Security and demo boundaries

- Never commit `.env`, API credentials, customer data, payment payloads, private tokens or admin passwords.
- If any credential was present in an earlier shared archive or repository history, rotate it at the provider; removing it from the current tree does not remove it from Git history.
- `DEMO_MODE=true` is mandatory for public preview. Checkout stores synthetic order labels only; the submitted name and phone are validated then discarded. No customer contact details are persisted or forwarded.
- The demo prize wheel uses free test tickets, a server-side random selection and a stock counter. Prizes are samples, not promises of delivery. Do not sell chances or introduce cash stakes.
- Demo analytics and orders are synthetic. SQLite at `/tmp` is ephemeral on Render and must not be used for business records.
- Admin access requires a strong `ADMIN_PASSWORD_HASH` and a stable random `FLASK_SECRET_KEY` set as deployment secrets. Do not expose demo admin credentials in a public repository.
- Social API environment variables are only presence checks. Publishing adapters are not implemented; the application must not claim that a post was published.
- Payment, delivery, CRM, MAX, VK and Telegram integrations are not connected until official owner credentials, contracts, API scopes and end-to-end tests are completed.
- Do not switch `DEMO_MODE=false` until PostgreSQL migrations, persistent storage, rate limits, privacy/consent flows, payment webhook verification, idempotency, stock reservation, backups, recovery and production acceptance tests are implemented.
- Before real contests or prize draws, obtain legal review of rules, eligibility, selection, publication of winners, prize delivery, advertising and personal-data processing.
- Use HTTPS, secure cookies, least-privilege roles, MFA, audit logs, secret rotation and monitoring in production.
