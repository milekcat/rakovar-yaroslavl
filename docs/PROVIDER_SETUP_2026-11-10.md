# Подключение VK, MAX и Telegram

Проверено 10.11.2026 по официальным источникам. Исследование не использовало токены компании и не отправляло сообщений. Документ задаёт контракт адаптеров; успешного подключения реального аккаунта пока нет.

## Состояния интеграции

`not_configured` → `configured_unverified` → `token_valid` → `destination_valid` → `webhook_verified` → `enabled`. Проверка токена подтверждает личность бота, а не права публикации. В интерфейсе показывать эти проверки раздельно. Сетевой тайм-аут означает `unknown`, а не неверный токен. Ни сохранение ключа, ни «проверить соединение» не отправляют сообщения и не заменяют webhook другой системы.

## MAX — актуальный контракт подтверждён

База: `https://platform-api2.max.ru`. Старый `platform-api.max.ru` заменён с 19.07.2026. Авторизация: `Authorization: <token>`, без `Bearer`; токен в query больше не поддерживается. TLS проверять, сертификат Минцифры добавлять в доверенные по официальной инструкции, не применять `verify=False`.

- Проверка: `GET /me`, без тела. Ожидаются `user_id`, `is_bot=true`, название/username; `401` — ошибка авторизации.
- Отправка: `POST /messages?chat_id=<int64>` для чата/канала **или** `?user_id=<int64>` для диалога; JSON `{"text":"…"}`. Не добавлять `parse_mode` Telegram; MAX имеет собственное поле `format`. Подтверждённый результат содержит `message.body.mid`; HTTP200 без валидного ID не считать доказанной публикацией. Обычный текст — до 4000 символов; не больше двух сообщений/секунду в одну цель.
- Бот должен быть добавлен в целевой чат/канал и иметь нужные права. Для постов в канал проверять `write` и `read_all_messages`; их значение подтверждено [справочником прав](https://dev.max.ru/docs-api/methods/POST/chats/-chatId-/members/admins/). `GET /chats` удалён с июня 2026. ID нужно получить из событий, а не обещать автоматическое перечисление всех чатов. Проверять конкретное членство через `GET /chats/{chatId}/members/me`.
- Подписка: `POST /subscriptions`, JSON `{"url":"https://host/api/webhooks/max","update_types":["bot_started","message_created"],"secret":"<generated>"}`. Читать существующие подписки можно через `GET /subscriptions`.
- Приём: сверять `X-Max-Bot-Api-Secret` постоянным по времени сравнением; secret: `^[a-zA-Z0-9_-]{5,256}$`. Ответ — HTTP200 за 30 секунд после надёжного сохранения события. HTTPS443 с доверенной полной цепочкой; HTTP и самоподписанные сертификаты не подходят. Long Polling не работает при активном webhook и не рекомендован для production.

Источники: [обзор](https://dev.max.ru/docs-api), [изменения](https://dev.max.ru/docs-api/changelog-api), [GET /me](https://dev.max.ru/docs-api/methods/GET/me), [сообщения](https://dev.max.ru/docs-api/methods/POST/messages), [подписка](https://dev.max.ru/docs-api/methods/POST/subscriptions), [членство](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-/members/me), [получение ID](https://dev.max.ru/docs-api/use-cases/getting-chat-id/).

## Telegram — обычный Bot API подтверждён

База `https://api.telegram.org/bot<token>/`. `GET getMe` без параметров проверяет токен; успех — `ok=true`, данные в `result`. Обычная отправка: `POST sendMessage`, JSON `{"chat_id":"<ID-or-@channel>","text":"…"}`; текст 1–4096 символов. Не включать платные рассылки. Для уведомлений человек сначала обращается к боту; для канала нужны членство и разрешение публикации. Дополнительная проверка цели — `getChat`, прав бота — `getChatMember`.

`POST setWebhook` получает `url`, `secret_token`, `allowed_updates`; входящий `Update` проверяется по `X-Telegram-Bot-Api-Secret-Token`. Secret — 1–256 символов `A-Z a-z 0-9 _ -`. `getWebhookInfo` читает состояние. `getUpdates` несовместим с активным webhook. Не выставлять `drop_pending_updates=true` автоматически. Нужны HTTPS, доступный endpoint и защищённое хранение ключа; токен входит в URL API, поэтому HTTP-логи должны его редактировать.

Источники: [Bot API](https://core.telegram.org/bots/api), [getMe](https://core.telegram.org/bots/api#getme), [sendMessage](https://core.telegram.org/bots/api#sendmessage), [setWebhook](https://core.telegram.org/bots/api#setwebhook), [Bot FAQ](https://core.telegram.org/bots/faq), [создание бота](https://core.telegram.org/bots).

## VK — контракт схемы 5.199 проверен; live-подключение NOT_VERIFIED

Официальные страницы `dev.vk.com` недоступны среде (`Site Unavailable` вместо документации). По отдельному указанию проверен официальный репозиторий **VKCOM/vk-api-schema**, commit `333481bd082ad747d4873ef4a77f9247097eeef0` от 14.04.2025: README явно указывает API **5.199**, пакет имеет версию 5.199.99. Это проверенная база совместимости, а не утверждение, что 5.199 — самая новая версия сервиса в ноябре2026.

База: `https://api.vk.com/method/`. Использовать HTTPS POST, `application/x-www-form-urlencoded`, `access_token` в теле, `v=5.199`. JSON `error` обрабатывать даже при HTTP200.

| Действие | Метод/параметры | Проверенный контракт |
|---|---|---|
| Проверить community token | `groups.getTokenPermissions`; только `access_token`, `v` | Только токен типа `group`; `response.mask` integer и `response.permissions[]` с `name`, `setting` |
| Проверить user token | `account.getAppPermissions`; только токен и версию | Только `user`; возвращаемую маску прав не считать подтверждённым правом публикации без необходимого scope |
| Прочитать сообщество | `groups.getById`; `group_id=<positive-id-or-screen-name>` или `group_ids` | `user`, `group`, `service`; ответ 5.199 — `response.groups[]`, не старый плоский `response[]` |
| Опубликовать текст | `wall.post`; `owner_id=-<positive_group_id>`, `from_group=1`, `message`, опционально стабильный `guid` | **Только `user` token**; успех `response.post_id` integer |
| Послать уведомление | `messages.send`; `peer_id`, стабильный integer `random_id`, `message` | `user`/`group`; текст до 9000 символов; peer чата = 2000000000+chat_id |

**Community-token для сообщений не подходит для `wall.post`.** Админка должна различать ключ сообщества и пользовательский ключ публикации. Нужны отдельные проверки прав приложения и роли пользователя в целевом сообществе. Не делать публичный пробный пост при нажатии «проверить ключ».

Для Callback API схема подтверждает:

- `groups.addCallbackServer`: user/group token, обязательные `group_id`, `url`, `title` (до 14 символов), опциональный `secret_key` до 50 символов; результат `response.server_id`.
- `groups.getCallbackConfirmationCode`: user/group, `group_id`; результат `response.code`.
- `groups.setCallbackSettings`: user/group, `group_id`, `server_id`, `api_version`, флаги вроде `message_new`, `wall_post_new`.
- Событие содержит `type`, `group_id`, `event_id`, `v`, опционально `secret`. Повторный `event_id` нужно игнорировать. Тип `confirmation` предусмотрен схемой.
- Возврат confirmation-кода и plain-text `ok` для обычного события — известный протокол обработчика; правила подтверждения сервера не представлены целиком JSON-схемой и требуют окончательной проверки в кабинете VK. Не регистрировать/заменять чужой callback автоматически при сохранении токена.

Источники (immutable commit): [README/API version](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/README.md), [groups methods](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/groups/methods.json), [groups responses](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/groups/responses.json), [wall methods](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/wall/methods.json), [wall responses](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/wall/responses.json), [messages methods](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/messages/methods.json), [account methods](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/account/methods.json), [callback objects](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/callback/objects.json).

## Что нельзя включить одним API-ключом

Для ботов требуются созданный/допущенный бот, целевой chat/user/group ID, членство и нужные права. Для входящих событий — HTTPS-endpoint, secret и регистрация webhook; замена существующей подписки должна быть отдельным явным действием. VK wall.post требует пользовательского токена, отдельно от ключа сообщений сообщества. Платежи дополнительно требуют договора, кабинета провайдера, продавца/кассы и отдельных проверок, а не ключей социальных сетей.

Сервер хранит ключи зашифрованными, возвращает только признаки наличия и статусы проверки. В журнале — провайдер, действие, результат и ID запроса без ключей/полных URL Telegram. Сохранение ключа не включает рассылки. Публикация происходит отдельным действием администратора; статус `published` разрешён только после подтверждённого ответа провайдера с ID результата. При неоднозначном сетевом сбое не отправлять повторно автоматически: требуется сверка, чтобы не создать дубликат. Живое end-to-end подключение проверяется только с ключами и разрешениями владельца.
