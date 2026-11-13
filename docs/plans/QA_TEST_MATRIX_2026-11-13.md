# РАКОВАРЪ 2.0 — матрица приёмки, регрессии, безопасности и визуального контроля

**Дата:** 13.11.2026 · **Статус:** проектный quality gate · **Исполнение:** обязательная проверка перед каждым release candidate.

## 1. Статусы результатов

`TESTED` — тест действительно выполнен с командой, окружением, commit и доказательством, `PASS` или `FAIL`. `IMPLEMENTED` — код существует, но мог быть не проверен. `NOT_VERIFIED` — не проверено. `BLOCKED` — внешняя зависимость. Не смешивать эти состояния; пустой файл теста и вручную отмеченное галочкой «рабочий» не считаются доказательством.

Запреты релиза:
- checkout способен принять деньги, но не создать заказ/чек;
- третье лицо видит чужие заказы/сертификаты/контакты;
- дубли заказов/списаний/сертификатов при повторных сообщениях;
- публичная витрина показывает внутренние `preview`/`guest_id`/`NaN`/`API`/traceback, неподтверждённые цены или ложные призы;
- кнопка оформляет не то действие, что написано на ней;
- новый интерфейс нарушает работающие legacy orders/bonus ledger.

## 2. Страница, состояние, пользовательское действие

| Test ID | Зона | Положительный и негативный сценарии | Тип |
|---|---|---|---|
| UI-001 | / | Уникальный brand hero, категории, хиты, соцссылки, реальные репутационные карточки; нет AI и tech мусора | Visual/browser |
| UI-002 | Глобальный header/footer | Реальные пути, мобильная навигация, обязательные legal ссылки, sticky/safe-area, 320px, клавиатура | Browser/a11y |
| UI-003 | /catalog | Поиск по названию, опечатки, facets, сортировки, пустая категория, ошибка API, paging | Browser/integration |
| UI-004 | /catalog/<slug> | Категория имеет корректные данные, нет чужих товаров/дублей, восстановление фильтра по Back | Browser |
| UI-005 | /product/<slug> | Фото exact SKU, варианты, единицы/аллергены, веса, цена сервера, отсутствие 1 г/ценовой ошибки | Browser/integration |
| UI-006 | Gallery & media | 1/10 фото, unavailable exact photo, alt, keyboard zoom, slow load/404 | Browser/a11y |
| UI-007 | /sets | Сет на 2/8/20 гостей, состав, продукты недоступны, бюджет, сохранение/повтор | Browser |
| UI-008 | /cart | Add/remove/qty, stock decrease, price change, promo incompatible, retain after reload | Browser/api |
| UI-009 | /checkout | Delivery/pickup/address/slot, contact, consent, 2 payment methods, timeout, retry | Browser/api |
| UI-010 | /orders/id | Статус, события, чат, документы, real paid vs pending, чужой order 403/404 | Browser/security |
| UI-011 | /account | Orders/balances/identity links, empty state, review write, sign out | Browser/security |
| UI-012 | /gifts/certificates | Nominal, gift preview, payment success/pending, redemption, partial balance, refund | Browser/integration |
| UI-013 | /club/wheel | Entry tickets, draw server side, partner prize issued once, empty/out-of-stock campaign | Integration/security |
| UI-014 | /reviews | Real per-provider ratings as_of, verified own-order reviews, negative preserved, link source | Browser/content |
| UI-015 | /about, /contacts | 9+ years only as brand claim after approval; current address, real schedule, clear contact | Content/manual |
| UI-016 | /journal /business | Actual articles or appropriate empty state, working inquiry form with case ID | Browser |
| UI-017 | /legal/* | Offer/PDP/returns/certificate/club terms, valid version snapshot, contact and date | Browser/legal |
| UI-018 | All links | Crawl same-origin anchors, 200/301/404 as expected, no broken `href="#"`, no dead CTAs | Automated |
| UI-019 | Consent and cookies | Marketing separate consent; default unchecked; stored version, revoke & export behavior | Security/browser |
| UI-020 | Empty network | Slow/timeout/500, retry, no eternal loading; no fake «заказ готов» | Browser |
| UI-021 | Localization | Russian copy, thousand separators, ₽, phone/E.164, time/date/timezone, pluralization | Unit/manual |
| UI-022 | No tech text | Scan rendered public DOM for preview/mock/AI/UUID/undefined/NaN/stacktrace; human review | Automated/manual |
| UI-023 | Mobile overlay | 320/375/390/430 plus soft keyboard, safe area, horizontal scroll, bottom actions | Visual |
| UI-024 | Navigation memory | Search/facet/cart persisted across routing, back/forward/reload works | Browser |
| UI-025 | Bad input | Form errors inline, focus field, long name/address, accessible announcement | Browser/a11y |
| UI-026 | Theme | Contrast WCAG AA, motion, font scaling, image focus, no clipped content | Visual/a11y |
| UI-027 | Honest availability | Draft/no-stock/preorder cannot be bought incorrectly; no fabricated order estimate | Integration |
| UI-028 | Review source integrity | Old/new Yandex business cards separated; other city excluded; no fake aggregate score | Unit/content |

## 3. Авторизация, сессии и данные

| Test ID | Сценарий | Expected |
|---|---|---|
| AUTH-001 | Первый заказ, новый номер, OTP valid | Один `customer_id`, заказ привязан, one-time password revealed только после проверки |
| AUTH-002 | Чужой номер/некорректный OTP | Не раскрыт ни заказ, ни баланс, ни временный пароль; нет account takeover |
| AUTH-003 | Два параллельных запроса на регистрацию одного телефона | Одна identity, нет потерянных заказов |
| AUTH-004 | Существующий email в новом заказе | Без доказательства владения не сливать аккаунты |
| AUTH-005 | Смена phone/email | Требование независимой повторной проверки |
| AUTH-006 | VK ID callback invalid state/PKCE or injected identity | Отказ; нет сессии |
| AUTH-007 | MAX initData old/tampered/missing signature | Отказ; нет сессии |
| AUTH-008 | Yandex OAuth invalid state/nonce/claims | Отказ; нет привязки |
| AUTH-009 | One provider bound to second account | Conflict + controlled merge; no silent overwrite |
| AUTH-010 | Guest → linked identity | Сохранились заказы и бонусный ledger, нет дубликатов |
| AUTH-011 | Восстановление при звонке с caller ID без step-up | Нельзя сбросить пароль |
| AUTH-012 | После восстановления | Старые sessions revoked; reset token single-use / TTL |
| AUTH-013 | Удаление последнего login method | Без безопасного fallback запрещено |
| AUTH-014 | Consent revoked after login | Реклама прекращена во всех соответствующих каналах |
| AUTH-015 | Public auth/OTP abuse | Rate limits, no account enumeration, no leak |
| AUTH-016 | Legacy email login on migration | Принятая compatibility policy; lost account prevention |

## 4. Commerce, деньги, склад, сертификаты

| Test ID | Сценарий | Expected |
|---|---|---|
| ORD-001 | Дважды тот же idempotency key | Один заказ, один складской резерв |
| ORD-002 | Concurrent checkout на последний остаток | Не продаётся больше подтверждённого stock |
| ORD-003 | Server quote differs from UI price | Итог подтверждён сервером и показан клиенту |
| ORD-004 | Кг, шаг 0.5, выбор 1.5 | В заказ попал правильный вариант/вес, единица |
| ORD-005 | Price change after selection | Информирование/согласование, без скрытой доплаты |
| ORD-006 | Cancel/refund partial order | Stock/bonus/gift/payment compensating entries correct |
| ORD-007 | Delivery slot unavailable after quote | Не обещать недоступную дату, checkout корректно восстанавливается |
| ORD-008 | Customer chat + attachment | Сохранение, permissions, staff-only note невидима |
| ORD-009 | Courier assigned vs unassigned | Only own assigned order, no customer funds visibility |
| ORD-010 | Cash collected | Audit, correct cash receipt state and reconciliation |
| PAY-001 | Yoo payment created, redirected but webhook absent | `pending`, не `paid` |
| PAY-002 | Two webhook delivered/reordered | One `paid`, one credit, one receipt trigger |
| PAY-003 | Provider outage after success ambiguous | Explicit reconciliation/manual review, no blind resend |
| PAY-004 | Fake webhook / wrong payment ID/amount | Reject/flag |
| PAY-005 | Partial refund + new payment | Ledger sums and refund references consistent |
| PAY-006 | Cash/transfer not actually received | Payment cannot be set `paid` automatically |
| FIN-001 | Bonus vs gift prepaid vs promo credit | Separate ledgers, no automatic conversion |
| FIN-002 | 2x redeem same certificate | Exactly one activation/credit |
| FIN-003 | Stolen certificate/public number | Cannot redeem without secret and verified identity |
| FIN-004 | Certificate value used in 2 simultaneous orders | No double spend or negative unauthorized balance |
| FIN-005 | Return unused certificate balance | Rights and refund workflow/accounting correct |
| FIN-006 | Chargeback/reversal of purchased certificate | State reconciliation, no unbacked prepaid |
| FIN-007 | Promo code asks to spend other customer's money | Denied |
| INV-001 | Live inventory on/off | No fake `99` as physical quantity |
| INV-002 | Import with unknown SKU/external IDs | Human approval, no silent publish |
| INV-003 | Duplicate catalog sources | One normalized product with source variants |
| INV-004 | Photo missing or rights not confirmed | Correct draft status/placeholder not shown as exact photo |

## 5. CMS, медиа, персонал, маркетинг

| Test ID | Сценарий | Expected |
|---|---|---|
| CMS-001 | Editor creates page and preview | No publication until approval; stable URL |
| CMS-002 | Rollback page v3 to v2 | Correct content/menu/banner, no corruption |
| CMS-003 | Schedule banner start/end, link broken | Not published until valid link/content |
| CMS-004 | Upload bulk photos from device | File validation, resize and persistent storage after restart |
| CMS-005 | Malicious SVG/ZIP/oversized image/EXIF | Rejected/sanitized and quotas enforced |
| CMS-006 | Remove media referenced by product | Safe reference checks, no broken image |
| CMS-007 | Storefront editor tries refund | 403 server side |
| CMS-008 | Social editor tries change integration token | 403 server side |
| CMS-009 | Courier tries admin catalogue | 403 server side |
| CMS-010 | Owner updates legal page | Effective version, audit, regulatory review |
| MKT-001 | VK/MAX transaction notice with permissions | Sent idempotently or clear failure |
| MKT-002 | No VK subscription / MAX not started | Not sent; no false provider success |
| MKT-003 | Revoked marketing consent | No promotional send, even with active social login |
| MKT-004 | Failed scheduled publication | Retry with idempotency and owner-visible error |
| MKT-005 | Partner gift reserved/fulfilled | One fulfillment, stock and budget consistent |
| MKT-006 | Wheel changes weight while campaign active | Published rule version audit |
| MKT-007 | Review imported via API errors | Public section links remain; no broken HTML |
| MKT-008 | Internal review contains PII/bad text | Moderation and privacy requests properly handled |

## 6. Проверки окружения, миграций и защиты

- Python syntax/unit tests, pytest existing suite, temporary PostgreSQL migration integration, SQLite local fallback, node JS syntax, static checks, `git diff --check`.
- Browser E2E with **synthetic** names/addresses/phones only; no requests to real merchants/clients; network mock for external provider errors.
- Migration from current `shop_accounts` and `guest_id`, `max_guest_id`, `shop_bonus_ledger`, `orders`; verify row counts, integrity constraints, rollback. Check `migrations/0001..0007` order, no destructive columns without safe path.
- Security negative suite for IDOR/XSS/CSRF/session fixation/role escalation/SQL injection/file traversal/SSRF/upload bombs/webhook forgery/promo enumeration/replay/account merge.
- CSP/security headers (no unaudited inline third-party scripts), redaction PII in logs, safe CSRF, no public staff login link.
- Offline/slow mobile; 4G 400ms RTT simulation; avoid duplicate checkout on retry.
- Contrast, keyboard/tab order, screen reader, touch target min/visible focus, `prefers-reduced-motion`.
- Validate source-of-truth facts and legal seller before live. Verify that free PostgreSQL expiration 10.12.2026 is addressed with owner-approved resources.

## 7. Definition of Done for each implementation PR

A PR is **not completed** until:
1. Names and IDs of backlog tasks noted in PR description.
2. Source changes reviewed, no secrets, no unnecessary full rewrite or legacy deletion.
3. Tests executed and exact commands + counts in PR.
4. Changed migrations/requirements explicitly named; schema state and rollback recorded.
5. Browser screenshots for changed responsive UI from **actual running build**; no static invented screenshot as test evidence.
6. Copy/content reviewed in Russian; no AI text, contradictory terms, errors, empty section without purpose.
7. Risky integrations default OFF behind feature flag until legal/merchant approval.
8. Manual acceptance of UX-critical workflows and no blocking accessibility regression.
9. Work status correctly marked IMPLEMENTED / TESTED / BLOCKED, no fabricated success.
10. No auto-merge into main or prod deploy without separate permission.

## 8. Release criteria

**Release candidate** can be cut only when all blockers resolved and P0 complete; stability metrics measured rather than guessed. Any regression in legacy cash checkout, order history, inventory reservations, customer access, staff auth or PDF certificates is BLOCKER. If a dependency is missing (seller, fees, images, provider credentials, client rights), keep that feature closed and document BLOCKED; do not mark the entire commercial platform complete.

**Audit output format:** CSV `test_id,area,scenario,environment,commit,command_or_manual_procedure,result,evidence_url,notes,executed_at`. Do not commit real PII or credentials.

**Related:** [CONTENT_UX_QUALITY_GATE_2026-11-13.md](CONTENT_UX_QUALITY_GATE_2026-11-13.md), [EXECUTION_PLAN_2026-11-13.md](EXECUTION_PLAN_2026-11-13.md).
