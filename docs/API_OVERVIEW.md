# API РАКОВАРЪ — контракты P0

Состояние: 9 ноября 2026. Все денежные величины существующего preview выражены целыми рублями. Коммерческие заказы и платежи отключены. API работает с cookie-сессией; мутации требуют `X-CSRF-Token` из bootstrap или административного входа. CSRF для MAX webhook заменён проверкой `X-Max-Bot-Api-Secret`, MAX auth проверяет подписанный initData.

## Критические операции

| Метод и маршрут | Назначение | Доступ |
|---|---|---|
| GET `/api/bootstrap?guest_id=...` | Каталог, настройки, visitor, CSRF, `wheel_sectors` | Новый анонимный ID или подписанная существующая сессия |
| POST `/api/checkout/quote` | Серверный расчёт корзины | Публичный read-only расчёт |
| POST `/api/orders` | Synthetic demo заказ | Cookie, public CSRF, обязательный Idempotency-Key |
| POST `/api/game/spin` | Списание билета и серверный приз | Cookie, public CSRF, обязательный Idempotency-Key |
| GET `/api/game/profile?guest_id=...` | Баланс текущего профиля | Подтверждённая сессия своего ID |
| GET `/api/game/history?guest_id=...` | Свои результаты | Подтверждённая сессия своего ID |
| GET `/api/referrals/profile?guest_id=...` | Своя ссылка/статистика | Подтверждённая сессия своего ID |
| POST `/api/referrals/attach` | Закрепление приглашения | Cookie и CSRF |
| POST `/api/max/auth` | Проверка MAX initData | Серверная HMAC и срок подписанных данных |
| POST `/api/max/webhook` | Доставка события бота | Секрет webhook; pending lease даёт retryable 503 |
| GET `/api/live` | Жив ли процесс | Без обращения к БД |
| GET `/api/health`, `/api/ready` | Быстрая проверка БД | Не доказывает готовность коммерческого магазина |

Новый браузер не может получить чужую личность, передав известный `guest_id`; ответ — `403 visitor_identity_unproven`. Namespace `max_` доступен только через verified MAX session. Signed shopper identity сохраняется при ротации административной сессии. Потерянная анонимная cookie не восстанавливается по публичному UUID; UI начинает новый гостевой профиль.

### Изменение контракта Idempotency-Key

Для `/api/orders` и `/api/game/spin` обязателен ключ длиной 8–128 символов: `[A-Za-z0-9][A-Za-z0-9._:-]{7,127}`. Подходит `crypto.randomUUID()`.

- Отсутствие ключа: `428 idempotency_key_required`.
- Неверный формат: `400` с `message=invalid_idempotency_key`.
- Одинаковые identity, operation, key и JSON-поля: тот же результат и HTTP-статус, без повторного эффекта.
- Повтор ключа с изменёнными значениями полей: `409 idempotency_payload_conflict`.
- Два разных ключа означают две отдельные операции.
- После потери ответа, 429 или 5xx нужно повторить исходный ключ и тело. Frontend хранит только ключ и хеш тела; имя/телефон в browser storage не сохраняются.

Receipt и заказ/вращение коммитятся одной транзакцией. Fingerprint в БД — HMAC JSON-представления с секретом приложения, без исходного тела. Нужен стабильный `FLASK_SECRET_KEY`; смена ключа инвалидирует signed cookies и не сохраняет retry-прозрачность старых клиентов. Удаление receipts без согласованного срока повторов может снова разрешить старую операцию; автоматическая очистка пока не включена.

### Spin response

Сохраняются `status`, `prize`, `redemption_code`, `tickets`, `points`, `message`. Добавлены:

```json
{
  "spin_id": 1,
  "sectors": [{"id": "prize-5", "title": "Скидка 5% на заказ", "kind": "coupon", "artwork": "shrimp"}],
  "sector_index": 0
}
```

Это пример структуры. Фактические сектора возвращаются снимком конкретной серверной операции; `sectors[sector_index].id == prize.id`. JavaScript анимирует этот сектор и не выбирает приз. Размеры секторов равны для графики, веса выигрышей могут различаться; пояснение размещено рядом с колесом.

Максимум — 32 активных сектора. Добавление/активация сверх лимита даёт `409 prize_limit_reached`. Для существующей некорректной БД bootstrap содержит `wheel_configuration_error=too_many_sectors`, а spin даёт `409 wheel_configuration_invalid` без списания билета.

## Административные API

Все существующие `/api/admin/*` проходят серверный RBAC. Неизвестный endpoint по умолчанию запрещён даже владельцу, пока не классифицирован. Подробная матрица и staff payloads: [STAFF_ACCESS.md](STAFF_ACCESS.md).

| Маршрут | Permission |
|---|---|
| GET `/api/admin/orders` | orders.read |
| PATCH `/api/admin/orders/<id>` | orders.write |
| GET `/api/admin/orders/<id>/history` | orders.read |
| GET/POST/PATCH `/api/admin/products` | catalog.read / catalog.write |
| GET/POST/PATCH `/api/admin/content` | content.read / content.write |
| GET `/api/admin/analytics` | analytics.read |
| GET `/api/admin/audit` | audit.read |
| GET/POST/PATCH `/api/admin/staff` | staff.manage и дополнительные owner ограничения |
| GET `/api/admin/security/me` | собственная staff session |
| GET/DELETE `/api/admin/security/sessions` | только свои session records |
| POST `/api/admin/security/password` | повторная проверка текущего пароля; bootstrap меняется через env |
| POST `/api/admin/security/mfa/enroll`, `/confirm` | повторная проверка, CSRF, throttling |

PATCH заказа принимает `{"status":"paid"}` и возвращает `tickets_awarded`, `tickets_reversed`. Матрица demo переходов:

| Из | В |
|---|---|
| demo_received | confirmed, paid, cancelled |
| confirmed | paid, cancelled |
| paid | preparing, ready, completed, cancelled |
| preparing | ready, completed, cancelled |
| ready | completed, cancelled |
| completed | cancelled |
| cancelled | только повтор своего статуса, без эффекта |

Недопустимый переход: `409 invalid_order_transition` с `previous_status`, `allowed_statuses`. Сторнирование использует исходные ledger суммы. Если билеты уже потрачены, баланс может стать отрицательным долгом; новые вращения недоступны до восстановления баланса. Возврат реального платежа, частичные возвраты и cash-on-delivery этим demo статусом не реализованы.

Контент допускает ручные статусы `draft`, `planned`, `approved`. `published`/`failed` должны назначаться будущим publisher adapter; `/publish` возвращает 409/501, пока нет проверенного адаптера. Credentials presence не считается успешной публикацией.

## Ошибки и ограничения

API HTTP ошибки возвращают JSON и сохраняют исходный HTTP статус/служебные заголовки. `400` исторически имеет `error=bad_request`, подробный машинный код в `message`; остальные HTTP коды используют `error` для явного машинного кода. Потребители не должны считать любой 200 от health доказательством подключения MAX, оплаты или маркетинга.

MAX inbox имеет lease 120 секунд. Повтор законченного события ACK как duplicate; активная обработка возвращает 503 с Retry-After; аварийно оставленная lease может быть занята после истечения. Без provider-side idempotency невозможно гарантировать exactly-once внешнее сообщение при crash между отправкой и записью processed_at. Входящие payloads/контакты не сохраняются; повтор зависит от redelivery MAX. Проверка этой политики на реальном MAX — отдельная приёмка.
