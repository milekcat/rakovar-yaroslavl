# Интеграции: готовность и зависимости

| Интеграция | Сейчас | Для рабочего подключения |
|---|---|---|
| MAX Bot API | Клиент, команды /start /catalog /club /referral /id /help, Long Polling, уведомления, heartbeat и MAX Mini App HMAC-auth реализованы | Токен в `.env`, запуск `max_bot.py`, HTTPS URL в настройках MAX; для постоянной работы — Webhook |
| MAX Mini App | `window.WebApp.initData` проверяется backend; ID MAX связан с клубным балансом | Публичный HTTPS URL через временный Quick Tunnel; сохранение URL в MAX Bot settings |
| VK | Контент-план и очередь/статусы в админке | Токен сообщества, ID сообщества, scopes, тестовый метод, обработка rate limits и модерации |
| Telegram | Контент-план/концепция | Bot token, канал/чат ID, разрешения администратора, webhook или polling |
| Оплата | UI/quote и демонстрационная заявка | Договор с провайдером, merchant credentials, подпись webhook, идемпотентность, возвраты, сверка и тестовый контур |
| PostgreSQL | SQLite preview | Render Postgres или внешний managed PostgreSQL, миграции, backup/restore, connection pooling |
| Доставка и карты | Предварительные поля и сценарии | Утверждённые зоны/тарифы, адресный сервис, геокодирование, курьерский workflow |
| CRM / учёт | Архитектурные точки и экспорт | Выбрать реальную систему компании (1С, МойСклад, CRM или таблицы), согласовать master-data и webhook/API |
| Email / SMS | Точки подключения | Провайдер, sender ID, шаблоны, согласие и unsubscribe |
| AI-помощник | Концепция и места интеграции | Выбор модели/провайдера, ключи в secrets, ограничения, журналирование и human approval |

**Важно:** статус «Ключи заданы» не означает, что интеграция работает. Для MAX есть runtime heartbeat от локального bot process; для остальных сервисов UI показывает состояние конфигурации, пока не будет реализован реальный health check.
