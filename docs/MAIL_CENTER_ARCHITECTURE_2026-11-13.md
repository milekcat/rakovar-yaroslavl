# Почтовый центр РАКОВАРЪ и разделение окружений

Дата решения: 13 ноября 2026 года  
Статус: архитектурное решение / подготовка к реализации. Тестовый домен закреплён; основной production-домен, почтовый провайдер и регион хранения пока не выбраны.

## 1. Принятые решения

1. Основной интерфейс работы с деловой почтой — встроенный Mail Center в служебной ERP-панели.
2. Отдельный Google-аккаунт РАКОВАРЪ будет владельцем Google-ресурсов проекта: Firebase/FCM, Analytics, Search Console, Play Console, Drive и OAuth-приложений. Он не считается почтовым хостингом для адресов рабочего домена.
3. `стильный-квадрат.рф` — временный тестовый домен РАКОВАРЪ. Он будет использоваться как основной адрес STAGING для сквозной проверки сайта и интеграций. Домен уже добавлен в Cloudflare, и Cloudflare сообщает, что зона активирована/защищена. Это не подтверждает, что origin уже направлен на локальный ПК: подключение Cloudflare Tunnel и проверка маршрута остаются отдельными шагами. Текущий Render preview можно оставить как вспомогательный резервный preview до завершения перехода.
4. Будущий production-домен будет отдельным рабочим доменом компании. Предполагаемое имя `rakovar76.рф` пока не зарегистрировано; не использовать его в production-конфигурации до регистрации и подтверждения владения.
5. Регион хранения персональных данных пока не выбран. До решения не подключать внешний почтовый хостинг к реальным данным покупателей и не переключать MX.
6. Архитектура почты должна быть provider-neutral: бизнес-логика ERP не должна зависеть от Zoho, Google, Cloudflare или другого конкретного поставщика.
7. В staging разрешены только синтетические адреса и тестовая доставка (sink/allowlist). Реальные письма покупателям из staging запрещены.
8. Тестовый домен не становится доменом компании после переноса: его можно оставить для регрессионных проверок, а production перевести на отдельный зарегистрированный домен.

## 2. Что подтверждено в текущем репозитории

- Основная ветка: main, базовый commit на момент подготовки документа: 1709109a838bd49e06d256073aa2e7feb27e0df8.
- Публичный preview: https://rakovar-preview-0psh.onrender.com.
- render-store.yaml содержит PUBLIC_BASE_URL для preview, но app.py пока не читает эту переменную. Следовательно, одного изменения Render env недостаточно для гарантированного переключения абсолютных ссылок, canonical URL, OAuth callback и ссылок из писем.
- app.py показывает SMTP_HOST/SMTP_USER только в диагностическом списке интеграций. Полноценный модуль отправки и приёма почты в текущей main не обнаружен. Наличие SMTP-переменных не означает, что email-интеграция реализована.
- В README зафиксировано, что подтверждение email и самостоятельное восстановление пароля ещё не реализованы.
- PostgreSQL выбирается через DATABASE_URL; SQLite предназначена для локальной проверки. Staging и production должны использовать разные базы.
- В проекте уже есть staff RBAC, аудит и внутренняя система уведомлений. Почтовый модуль должен использовать эти механизмы, а не вводить второй механизм прав или уведомлений.

## 3. Окружения и домены

### 3.1 Development

- Локальный запуск на ПК.
- Только синтетическая БД и тестовые учётные записи.
- MAIL_MODE=disabled по умолчанию; при интеграционных тестах — sink.
- Не отправлять письма покупателям.
- Отдельные секреты и отдельная БД от preview и production.

### 3.2 Staging / Preview

- Канонический тестовый адрес: `https://стильный-квадрат.рф` (корень домена, с единым redirect для `www`, если он будет включён).
- Origin для основного staging-контура: приложение на ПК владельца, опубликованное через Cloudflare Tunnel. Не открывать входящие порты роутера и не публиковать Docker-порт напрямую в интернет; Tunnel должен вести только на локальный origin приложения.
- Cloudflare zone уже активирована по последнему скриншоту владельца, но подключение Tunnel, hostname route и фактическая доступность приложения ещё не подтверждены.
- Официальная инструкция Cloudflare Tunnel: https://developers.cloudflare.com/tunnel/get-started/; локальная конфигурация: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/; схема DNS CNAME: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/.
- По ранее показанному DNS-снимку A/AAAA-записи домена и служебных имён указывали на `31.31.196.17`; перед настройкой Tunnel нужно повторно сверить текущую зону, сохранить экспорт и только затем заменить конфликтующие web-записи. Не удалять почтовые/verification TXT и иные неизвестные записи без проверки.
- Render preview URL можно оставить как дополнительную среду для резервной проверки, но он не является каноническим staging origin после завершения настройки тестового домена.
- Отдельная PostgreSQL БД staging, не содержащая копию реальных контактов.
- Отдельные OAuth redirect URI, cookie namespace и ключи.
- PUBLIC_BASE_URL=`https://стильный-квадрат.рф`.
- MAIL_MODE=sink или provider sandbox; получатели ограничены MAIL_ALLOWED_RECIPIENTS.
- Push/FCM, если подключены, используют тестовый Firebase project или отдельные тестовые приложения.
- Для staging использовать sandbox API и тестовые OAuth clients; не копировать production secrets.
- `MAIL_MODE=sink`; MX и реальные почтовые ящики тестового домена пока не настраивать, пока не выбран провайдер и не подтверждены ограничения его тарифа.

### 3.3 Production

- Только будущий отдельный зарегистрированный рабочий домен компании. Значение пока не задано; `стильный-квадрат.рф` остаётся тестовым и не переносится в production.
- Отдельный Render/иной production service и отдельная PostgreSQL БД.
- Отдельные секреты, OAuth credentials, VAPID/FCM credentials и storage.
- PUBLIC_BASE_URL — канонический HTTPS origin рабочего домена.
- MAIL_MODE=provider только после проверки домена, MX, SPF, DKIM, DMARC и тестовой доставки.
- Нельзя использовать preview DB или staging secrets в production.

### 3.4 Конфигурационный контракт

Целевые переменные (не добавлять реальные значения в Git):

| Переменная | Назначение |
|---|---|
| APP_ENV | development / staging / production |
| PUBLIC_BASE_URL | Единственный канонический origin текущего окружения |
| ALLOWED_HOSTS | Разрешённые Host header для приложения |
| DATABASE_URL | PostgreSQL URL конкретного окружения |
| SESSION_COOKIE_NAME | Разные имена cookie для staging и production |
| COOKIE_SECURE | true для HTTPS окружений |
| MAIL_MODE | disabled / sink / provider |
| MAIL_PROVIDER | Идентификатор адаптера провайдера |
| MAIL_API_BASE_URL | Региональный API endpoint, если применимо |
| MAIL_FROM_ADDRESS | Проверенный адрес отправителя |
| MAIL_ALLOWED_RECIPIENTS | Ограничение получателей для staging |
| MAIL_OAUTH_CLIENT_ID | OAuth client ID |
| MAIL_OAUTH_CLIENT_SECRET | OAuth secret в secret store |
| MAIL_REFRESH_TOKEN | Refresh token в secret store |
| MAIL_ENCRYPTION_KEY | Отдельный ключ шифрования почтового содержимого |
| MAIL_RETENTION_DAYS | Срок локального хранения копий писем |
| MAIL_SYNC_INTERVAL_SECONDS | Интервал синхронизации при отсутствии webhook |

Это целевой контракт, а не утверждение, что переменные уже поддерживаются кодом. Перед использованием их необходимо добавить в конфигурационный слой и покрыть тестами.

### 3.5 Требования к доменной независимости

- Не зашивать staging или production hostname в Python, шаблоны, JS, manifest, service worker, Android build config и тексты писем.
- Абсолютные ссылки строить только из PUBLIC_BASE_URL после валидации HTTPS origin.
- Для canonical/OG URL, sitemap, manifest start_url, MAX Mini App URL, OAuth callbacks и ссылок в письмах использовать конфигурацию текущего окружения.
- Host header не считать доверенным источником canonical URL.
- Если используется ProxyFix, доверять только фактическому числу proxy hops от хостинга; не включать широкое доверие к произвольным forwarded headers.
- Разные cookie names, OAuth clients, базы и ключи исключают перенос staging-сессии в production.
- Переключение домена не должно менять customer_id, order_id или содержимое бизнес-таблиц.
- Перед production cutover проверить redirects, canonical, sitemap, robots, CORS/CSRF origins, CSP, service-worker scope, deep links и Android App Links.

### 3.6 Перенос STAGING → PRODUCTION

Перенос выполнять как отдельный контролируемый релиз, а не как замену одной DNS-записи:
1. Зарегистрировать и подтвердить будущий рабочий домен.
2. Создать отдельные production service, БД, секреты, OAuth clients, Firebase/FCM project (если нужен) и storage.
3. Настроить production `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`, cookie namespace, CORS/CSRF origins, CSP и trusted proxy settings.
4. Обновить OAuth redirect URI, платёжные webhook URLs, MAX/VK callbacks, push origins, sitemap/canonical, PWA manifest/service worker scope, Android App Links и deep links.
5. Перенести только согласованные справочники/каталог и необходимые данные по утверждённой миграции; staging-покупатели и тестовые заказы не должны попадать в production.
6. Проверить платежи в sandbox, заказы, роли, уведомления, Android, резервное копирование и восстановление.
7. Отдельно настроить почту и DNS: MX, SPF, DKIM, DMARC — после выбора провайдера и региона хранения.
8. Провести cutover с планом отката; тестовый домен оставить для staging.

Не менять MX, не подключать реальные платёжные ключи и не переводить трафик покупателей на staging. Не публиковать локальный сервер прямым пробросом портов.

## 4. Почтовая модель

### 4.1 Mail Center

Основной интерфейс: служебный раздел «Почта» в существующей ERP.

Целевые функции:
- единый список входящих писем по разрешённым адресам;
- просмотр цепочки и вложений;
- ответ, ответ всем, пересылка и создание письма;
- выбор адреса отправителя при наличии разрешения;
- привязка переписки к customer_id и order_id;
- назначение ответственного сотрудника;
- статусы new / assigned / waiting / resolved / archived;
- внутренние заметки, которые никогда не попадают в письмо покупателю;
- шаблоны ответов и системных писем;
- аудит действий, журнал доставки и ручная обработка неопределённого результата;
- поиск по разрешённым метаданным и содержимому с учётом прав доступа;
- настройки синхронизации, подписей, адресов и retention.

### 4.2 Права доступа

Использовать существующий серверный RBAC. Предлагаемые permissions:
- mail.read — читать разрешённые ящики и переписки;
- mail.send — создавать и отправлять письма;
- mail.assign — назначать ответственных;
- mail.manage — управлять подключениями, адресами и правилами;
- mail.attachments.read — скачивать вложения;
- mail.audit.read — просматривать журнал.

Доступ к заказу не должен автоматически давать доступ ко всей почте. Связь письма с клиентом/заказом — отдельное разрешение и проверка ownership/scope. Внутренние заметки и служебные адреса не доступны покупателю.

### 4.3 Независимая модель данных

Предлагаемые сущности (конкретные имена согласовать с текущими migrations перед реализацией):
- mail_provider_connections — provider, account reference, OAuth scopes, encrypted credentials, status, last_sync_at;
- mailboxes — provider mailbox ID, display name, enabled state;
- mail_addresses — address, mailbox, alias/group role, allowed sender roles;
- mail_threads — provider thread ID, subject metadata, participants fingerprint, customer/order link, status, assignee;
- mail_messages — provider message ID, thread ID, direction, received/sent timestamps, encrypted headers/body, safe preview, delivery state;
- mail_attachments — metadata, encrypted object reference, checksum, scan status, retention;
- mail_sync_state — mailbox cursor/history token, last successful sync, next retry;
- mail_outbox — immutable send request, idempotency key, state, retry count, provider message ID;
- mail_delivery_events — accepted, delivered, bounced, deferred, rejected, unknown;
- mail_templates — versioned templates with locale and purpose;
- mail_audit_log — actor, action, entity, timestamp, safe metadata.

Не создавать эти таблицы, пока не сверены текущие migrations и транзакционные conventions. Не хранить OAuth access/refresh tokens в открытом виде. Не писать body, адреса и вложения в обычные application logs.

### 4.4 События и надёжность

- Входящие события синхронизируются идемпотентно по provider + mailbox + provider_message_id.
- Отправка создаётся в локальном outbox в той же транзакции, что и бизнес-событие, если письмо является частью бизнес-операции.
- Сеть и вызов API выполняются вне транзакции БД.
- Неопределённый результат отправки не повторять вслепую: сначала искать письмо по idempotency/provider reference либо переводить в manual_review.
- Повторные попытки — с exponential backoff и jitter; permanent errors не ретраить.
- Threading соблюдать по Message-ID, In-Reply-To и References, а также provider thread ID.
- Вложения: MIME allowlist, magic bytes, лимит размера, antivirus/quarantine, случайное имя объекта, отсутствие публичного URL по умолчанию.
- HTML письма очищать от scripts, event handlers, remote tracking и опасных URL; внешний контент не загружать автоматически.
- Webhook endpoints проверять по подписи/секрету и replay protection. При отсутствии webhook использовать cursor-based polling с ограничением частоты.

### 4.5 Хранение и приватность

Поскольку регион хранения не выбран:
- не отправлять реальные письма и данные покупателей через EU/US provider до отдельной проверки требований к обработке и трансграничной передаче персональных данных;
- не использовать реальные клиентские данные в staging и в демонстрационных снимках;
- минимизировать локальное хранение: кэшировать только то, что необходимо для работы ERP;
- хранить тела писем и вложения зашифрованными отдельным MAIL_ENCRYPTION_KEY;
- предусмотреть retention, экспорт и удаление по политике владельца и применимому законодательству;
- доступ сотрудников журналировать; MFA обязателен для администраторов и управления подключениями;
- не использовать почту как единственное средство подтверждения финансовой операции.

## 5. Почтовый провайдер: варианты и ограничения

### 5.1 Zoho Mail Free — кандидат, но не окончательный выбор

Официальная сравнительная страница Zoho на дату подготовки документа указывает:
- до 5 пользователей на одном custom domain;
- 5 GB на пользователя;
- бесплатный тариф доступен только в US, EU и India data centers;
- IMAP/POP/ActiveSync в бесплатном тарифе отсутствуют.

Это означает, что Mail Center нельзя строить на предположении о бесплатном IMAP. Для ERP потребуется REST API или webhook/polling provider adapter. До выбора Zoho необходимо на реальном free account подтвердить, что нужные message read/search/send/reply endpoints и OAuth scopes доступны именно этому тарифу. API documentation сама по себе не доказывает доступность каждого endpoint на free plan.

Официальные источники:
- https://www.zoho.com/mail/compare/overview.html
- https://www.zoho.com/mail/help/api/
- https://www.zoho.com/mail/help/api/getting-started-with-api.html
- https://www.zoho.com/mail/help/api/using-oauth-2.html

### 5.2 Google / Gmail

Отдельный бесплатный Google Account подходит для владения Google-сервисами и подключения Gmail API к этому Gmail-ящику по OAuth 2.0. Он не создаёт ящики на собственном домене.

Google Workspace предоставляет Gmail с custom domain в платных Business editions; цену и доступность проверять для страны биллинга на момент покупки:
- https://workspace.google.com/pricing
- https://developers.google.com/workspace/gmail/api/auth/web-server
- https://developers.google.com/workspace/gmail/api/guides/sending

Не использовать личный Gmail владельца как единственный архив деловой переписки компании. Если Gmail API подключается, выдавать минимальные OAuth scopes и предусмотреть отзыв доступа.

### 5.3 Cloudflare Email Routing / Email Service

- Email Routing на Free может принимать и пересылать входящие письма на подтверждённые адреса или в Worker; это не самостоятельный mailbox/webmail.
- Для полноценной отправки произвольным получателям Cloudflare Email Sending требует Workers Paid. Бесплатная отправка ограничена проверенными адресами в аккаунте.
- Cloudflare DNS остаётся DNS-провайдером, но не заменяет почтовый хостинг.

Официальные источники:
- https://developers.cloudflare.com/email-service/
- https://developers.cloudflare.com/email-service/configuration/email-routing-addresses/
- https://developers.cloudflare.com/dns/manage-dns-records/how-to/email-records/

### 5.4 Правило выбора

Выбирать провайдера только после сравнения:
1. дата-центр и допустимость хранения данных;
2. полноценный API read/search/send/reply/thread/attachments;
3. доступность API на бесплатном тарифе;
4. лимиты отправки и антиспам-политика;
5. mailbox storage и количество пользователей;
6. webhook/polling, OAuth, revoke/rotation;
7. возможность экспорта и миграции без потери писем;
8. итоговая стоимость при росте.

Не обещать бесплатную полноценную корпоративную почту до проверки конкретного тарифа и API. Бесплатный forwarding, бесплатный mailbox и бесплатная transactional email delivery — разные функции.

## 6. Адресная схема

Рабочий домен ещё не выбран. До регистрации использовать только логические роли, без создания DNS-записей:

| Роль | Назначение | Предлагаемый тип |
|---|---|---|
| admin@ | Административная переписка | отдельный mailbox |
| support@ | Покупатели и обращения | отдельный mailbox/shared inbox |
| orders@ | Заказы и подтверждения | alias или отдельный mailbox |
| info@ | Общие обращения | alias |
| partners@ | Поставщики и партнёры | alias или отдельный mailbox |
| delivery@ | Логистика | alias |
| notifications@ | Автоматические системные письма | отдельный sender identity, не mailbox для ручной переписки |

Не создавать отдельный платный пользовательский ящик для каждого адреса, если провайдер поддерживает алиасы или группы. Алиас — это адрес доставки в существующий ящик, а не самостоятельная учётная запись. Групповые адреса должны иметь понятного владельца и правила доступа.

## 7. Транзакционные письма и маркетинг

Разделить:
- сервисные письма: заказ принят, изменение статуса, ответ поддержки;
- безопасность: вход/смена пароля/восстановление;
- маркетинг: акции и рекламные кампании.

Для маркетинга отдельно хранить согласие, источник, дату и отписку. Не отправлять массовые рассылки через обычный mailbox API. Сервисные письма должны иметь отдельные шаблоны, ограничение частоты, idempotency и журнал статусов. На первом этапе можно отключить маркетинговые рассылки полностью.

Cloudflare Email Sending не считать бесплатным массовым SMTP: произвольная отправка требует Workers Paid. Любой transactional provider выбирается отдельно и только после проверки региона и тарифа.

## 8. Google Account ownership

Отдельный Google Account создаёт владелец проекта самостоятельно. Требования:
- отдельный аккаунт, не личный аккаунт разработчика;
- уникальный пароль и обязательная 2-Step Verification/passkeys;
- резервные коды хранить вне ПК и не передавать исполнителям;
- recovery email/phone — под контролем владельца;
- добавить отдельного администратора только при необходимости;
- не передавать пароль через чат, GitHub или .env;
- Firebase, Analytics, Search Console, Play Console и Drive выдавать через роли/приглашения, а не общий пароль.

Адрес аккаунта пока не задан. Не создавать фиктивные значения и не добавлять несуществующий адрес в конфигурацию.

## 9. DNS cutover для будущего рабочего домена

До регистрации домена ничего не менять. После регистрации:
1. подтвердить владельца и выбрать DNS provider;
2. выгрузить текущую DNS-зону и сохранить backup;
3. создать и проверить почтовую организацию у выбранного провайдера;
4. добавить TXT verification;
5. получить у провайдера точные MX, SPF, DKIM и DMARC записи;
6. проверить SPF — ровно одна TXT SPF policy на hostname; объединить разрешённых отправителей, не создавать дубли;
7. настроить DKIM selector(s) по точным значениям провайдера;
8. начать с DMARC p=none, собрать отчёты и только затем повышать политику;
9. выполнить тест входящей/исходящей почты, проверку заголовков и доставляемости;
10. только после успешной проверки переключить MX;
11. проверить сайт, TLS, canonical, OAuth, PWA, Android links и все callbacks;
12. оставить staging и production DNS/почту независимыми.

MX и почтовые host records не проксировать через HTTP proxy Cloudflare. Не удалять старые DNS записи до проверки зависимостей. Почтовые записи не менять в REG.RU, если authoritative DNS уже обслуживается Cloudflare; изменения выполняются в фактической authoritative zone.

## 10. Порядок реализации

### Этап A — до выбора провайдера
- проверить текущие migrations и notification/outbox code;
- вынести конфигурацию окружений в единый валидируемый слой;
- сделать PUBLIC_BASE_URL реально используемым для абсолютных ссылок;
- валидировать allowed hosts и trusted proxy headers;
- разделить cookie names, OAuth callback URLs и secret namespaces;
- добавить staging mail sink/allowlist, который физически блокирует произвольных получателей;
- подготовить provider adapter contract и mock provider;
- добавить RBAC permissions и пустой Mail Center shell без фиктивной почты.

### Этап B — после выбора провайдера и региона
- реализовать один реальный adapter;
- OAuth consent и безопасное хранение refresh token;
- sync cursor/webhook, outbox, retries и manual review;
- вложения и антивирусную проверку;
- связи с клиентом/заказом;
- UI входящих/исходящих/цепочек/назначений;
- integration tests на mock и sandbox.

### Этап C — после регистрации рабочего домена
- проверить регион хранения и договор провайдера;
- настроить MX/SPF/DKIM/DMARC;
- провести end-to-end тесты на контролируемых адресах;
- включить реальные сервисные письма;
- затем отдельно решать маркетинг.

## 11. Критерии приёмки

- staging не может отправить письмо произвольному внешнему получателю;
- production не стартует с пустым/невалидным canonical origin или отсутствующими обязательными секретами;
- staging и production не разделяют DB, sessions, OAuth credentials или encryption keys;
- все исходящие письма создаются через outbox и имеют idempotency key;
- потеря ответа провайдера не приводит к слепому повтору;
- входящее письмо не может открыть чужой заказ/профиль через IDOR;
- HTML/вложения безопасно обрабатываются;
- роли проверяются на сервере;
- в логах нет токенов, тел писем, полных адресов и клиентских контактов;
- синхронизация восстанавливается после временной недоступности провайдера;
- отключение почтового провайдера не ломает заказы, внутренние уведомления и кабинет покупателя;
- все письма и связанные данные имеют согласованную retention/export policy.

## 12. Что заблокировано до действий владельца

- выбор юридически допустимого региона хранения;
- выбор и регистрация рабочего домена;
- создание отдельного Google Account;
- регистрация и проверка организации у почтового провайдера;
- согласование реальных почтовых адресов и сотрудников;
- выдача OAuth consent / API credentials;
- переключение MX и включение production email.

Никакие DNS-записи, MX, реальные адреса, OAuth-токены или платные сервисы в рамках этого документа не создаются.  
