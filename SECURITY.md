# Security boundaries

Current store behavior and operational limitations are documented in `docs/STORE_OPERATIONS_2026-11-11.md`. P0 reports describe the older demo endpoint and are not a claim that the new store discards contact details.

- Never commit `.env`, credentials, customer data, payment payloads, private tokens or passwords. Any historically exposed credential must be rotated privately at the provider.
- `/api/store/orders` stores encrypted customer contacts and real order requests with payment on receipt. `/api/orders` is retained as a demo-only compatibility endpoint and discards contacts. `DEMO_MODE=true` does not make the store endpoint anonymous or synthetic.
- Keep both `FLASK_SECRET_KEY` and the separate `INTEGRATION_ENCRYPTION_KEY` stable and private. The latter protects customer profiles, order details and provider secrets. Losing or rotating it without migration makes existing encrypted records unreadable.
- Use PostgreSQL for persistent records. Local SQLite and temporary Render disks must not hold business records. Uploaded catalog photos are stored in the database.
- Customer accounts use scrypt password hashes, hashed revocable session tokens, signed cookies and CSRF checks. Email ownership verification and self-service password recovery are not implemented. Email must not be represented as verified.
- Customer profile/order ownership comes from the signed session, not request-supplied visitor IDs. Expired or revoked customer sessions cannot fall back to an account's anonymous visitor identity. MAX identities require verified server-side authentication.
- Staff authentication, server-side RBAC, revocable sessions and TOTP remain separate. Contacts require `customers.read`; inventory changes require `inventory.write`. Hiding `/admin` and `/admin/login` is navigation separation, not access control.
- TOTP seeds currently require database-level protection; self-service MFA recovery is not implemented. Enroll and confirm MFA privately before requiring it. Production-mode startup requires privileged MFA.
- Idempotency is required for store orders, legacy orders and spins. Receipts, effects, stock reservation and bonus movements share one transaction. Retry the same key with the same payload; do not create a new key after an ambiguous successful submission.
- Store bonuses have their own ledger. Demo game points cannot be spent as cash. Payment/completion awards and cancellation reversals use unique references. Do not sell chances or introduce cash stakes.
- Inventory uses conditional reservations and expected-balance checks for manual adjustments. Source catalog updates preserve operator overrides. Imported prices and stock are not verified business facts.
- PostgreSQL currently serializes application transactions through a transitional global lock. Validate throughput separately before commercial traffic.
- Provider secrets are encrypted and excluded from APIs/logs. Credential saving/checking does not send messages. Outbound adapters require permissions and confirmed remote message IDs; ambiguous outcomes require manual review. Order alerts exclude contacts and support MAX / Telegram, not public VK posts.
- Online payment processing, payment webhooks and provider money refunds are not implemented. Real provider acceptance requires owner credentials and destination tests.
- Public contests are hidden by default. Obtain approved rules before enabling prize campaigns. Confirm catalog, delivery terms, legal details, privacy/consent text, retention, backups and recovery with the owner before commercial operation.
- Use HTTPS, secure cookies, least-privilege staff roles, MFA, audit logs and monitoring. This document is not a claim of a completed comprehensive security audit.
