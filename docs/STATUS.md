# Текущий статус локальной MAX preview-сборки

## IMPLEMENTED

- Витрина: 62 позиции в 13 категориях, поиск, фильтры, сортировка, карточки, корзина, серверный расчёт, промокоды и демонстрационное оформление.
- Позиции без публичной цены: съедобные букеты, живые раки по размеру и замороженные морепродукты — «по запросу», не добавляются в корзину.
- Источники каталога: Eda7, Eda-Dostavka, Chibbis и публичное описание бренда; все цены/наличие требуют подтверждения.
- Клуб: ledger, начисление за оплаченные заказы и промо, билет за участие в конкурсе, ручное начисление, списание за игру, idempotency, сторно при отмене оплаченного заказа и редактируемый порог начисления в админке.
- Игровая зона: серверный weighted draw, остатки призов, призы партнёров, купоны и статусы выдачи.
- Конкурсы: правила, заявки, защита от дублей, начисление билетов, редактирование и серверный выбор победителя.
- Админка: товары и карточки, цены/остатки, подтверждения, заказы, промокоды, ticket rewards, веса/остатки призов, конкурсы, контент-план, интеграции, аналитика, журнал аудита.
- MAX Bot API client: официальный API host, `Authorization` header, TLS verification, команды `/start`, `/catalog`, `/club`, `/tickets`, `/referral`, `/id`, `/help`, регистрация команд, Long Polling для локального preview, сообщения владельцу и heartbeat в admin.
- MAX Mini App: backend HMAC-SHA256 validation для `window.WebApp.initData`, проверка времени и user ID, привязка `max_<user_id>` к тому же клубному балансу, нативный share action для конкурсов.
- Локальный запуск Windows/Unix, `.env.example`, Quick Tunnel инструкции. Нет необходимости в постоянном домене/хостинге для демонстрации.
- Security: CSRF, signed session, admin password hash, rate limits, security headers, no token in source, no real customer data persisted in demo.

## NOT IMPLEMENTED / НЕ ВЫДАВАТЬ ЗА ГОТОВОЕ

- Реальные платежи, платёжные webhooks, касса, возвраты через провайдера.
- Реальная обработка и передача клиентских персональных данных, доставка/курьеры/слоты.
- Автопубликация в VK / MAX / Telegram: есть контент-план, но publisher adapters не подключены.
- MAX production webhook: локальная сборка использует Long Polling.
- PostgreSQL, миграции, backup/restore, роли сотрудников/RBAC, MFA.
- CRM, 1С/МойСклад, SMS/email, карты и AI-provider integration.
- Реальные платежные webhooks, автоматическое подтверждение заказа и социальные действия; юридически утверждённые правила промоакций.

## TESTED

- `python scripts/validate_preview.py` — PASS: Python AST/syntax, JavaScript syntax, SQLite DDL, ticket/referral constraints, каталог и проверка отсутствия hotlinked images.
- `python -m unittest tests.test_preview_core -v` — PASS: 7 тестов MAX HMAC, срок действия, wrapper, API client и catalog invariants.
- `render.yaml` — PyYAML parse PASS; Render CLI Blueprint validation NOT VERIFIED (CLI отсутствует).
- `python -m unittest tests.test_preview_core -v` — PASS: MAX initData HMAC, срок действия, wrapper, малые user IDs, MAX API client headers/host/body, catalog invariants.
- `python -m py_compile app.py max_auth.py max_client.py max_bot.py catalog_seed.py tests/test_app.py tests/test_preview_core.py` — PASS.
- `node --check static/storefront.js` — PASS.
- `node --check static/admin.js` — PASS.

## NOT VERIFIED

- Flask integration suite `tests/test_app.py`: не запускалась в этой среде, так как Flask/Werkzeug не установлены, а установка зависимостей из PyPI недоступна.
- Реальный MAX API: токен на присланном скриншоте замаскирован; фактический `GET /me`, регистрация команд и polling должны быть проверены локально с токеном в `.env`.
- Browser E2E, визуальная проверка Mini App внутри MAX, платежи, publisher adapters и production security/load tests.
- Все цены, составы, граммовки, фото и наличие должны быть подтверждены компанией.

## BLOCKED / СЛЕДУЮЩИЙ ШАГ

Публичный preview URL ещё не создан. GitHub connector не предоставляет действие создания нового репозитория, а Render требует Git remote. Нужен отдельный репозиторий `milekcat/rakovar-yaroslavl`; после его создания можно загрузить сборку и применить `render.yaml`. Для локальной разработки остаётся вариант Flask + MAX bot + HTTPS Quick Tunnel.
