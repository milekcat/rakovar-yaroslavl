# РАКОВАРЪ 2.0 — карта внешних интеграций, доступов и действий владельца

**Дата проверки:** 13.11.2026. **Статус:** DESIGNED / NOT_CONNECTED (до предоставления подтверждённых прав). **Контекст:** домен и хостинг будут на REG.RU, владелец самостоятельно регистрирует и оплачивает услуги. Программный код/инфраструктура этим документом не менялись.

**Главный принцип:** собственник сохраняет ownership и биллинг всех сервисов. Исполнитель получает отдельные ограниченные права, scoped API credentials, SSH public-key access либо техническую роль. Никогда не присылать основные пароли, BOT_TOKEN, secretKey, SSH private key, 2FA codes, выписки покупателей или персональные данные в открытые чаты, issues, PR, публичную документацию. Секреты — только в approved secret store / environment с MFA, журналом доступа и ротацией.

## 1. Основные компоненты и достаточные права

| ID | Сервис | Для чего | Что создаёт / подтверждает владелец | Что получает инженер | Критичность |
|---|---|---|---|---|---|
| INF-REG-DOMAIN | REG.RU домен | Основной URL, DKIM/DNS, OAuth callbacks, MAX Mini App | Регистрирует на реального владельца (ИП/ООО), проходит необходимую идентификацию, оплачивает и включает автопродление | Имя домена, ограниченное управление DNS либо утверждённые изменения DNS владельцем, TXT/ACME validation | P0 |
| INF-REG-SERVER | REG.RU VPS/облачный сервер | Python Flask, background jobs/webhooks, HTTPS | Заказывает подходящую услугу **после технического расчёта** с нужным регионом/сервисом, обеспечивает оплату | Отдельный SSH user, SSH **public** key provisioned, нет передачи root password; права деплоя в app namespace, доступ к сервисам logs и firewall в пределах задач | P0 |
| INF-DATABASE | PostgreSQL | Пользователи, заказы, ledger, каталог | Утверждает размещение/подрядчика и retention/backups, права владельца | Отдельный минимальный app DB role и migration role, server-only credentials, backup test environment | P0 |
| INF-MEDIA | Объектное хранилище | Фото товаров, ролики, сертификаты | Утверждает provider, регион, права на фото, лимиты | Bucket-scoped service credentials, private/public distinction, versioning/lifecycle | P1 |
| INF-SSL-DNS | DNS/SSL | HTTPS, callback, письма, поддомены | DNS zone owner, согласование доменных имён | ACME/TLS setup, A/AAAA/CNAME, MX/SPF/DKIM/DMARC и защитные CAA/TXT где требуется; сертификаты обновляются | P0 |
| VK-GROUP | VK группа | Посты, сообщения и товары при наличии API/прав | Подтверждает owner/admin официального сообщества и app/API scope | Group ID, необходимые разрешения сообщества, токен в secret store, разрешённые callback/events, allow-messages consent | P1 |
| VK-ID | VK ID | Вход покупателей | Создаёт и верифицирует приложение под брендом в доступном developer dashboard; утверждает домен и privacy URL | APP_ID, разрешённые origin/redirect URI, server-side app credentials **только если требует выбранный flow**, OAuth 2.1/PKCE, тестовый аккаунт | P1 |
| MAX-BOT | MAX Business бот | Интеграция чата/уведомлений/вход в Mini App | Подтверждает модерацию, принадлежность verified business, ownership бота | Username/ID, bot token только в secret store, права на настройку Mini App URL, публичный HTTPS URL, subscription/webhook config | P1 |
| MAX-MINIAPP | MAX Mini App | Автовход по подписанным данным, магазин внутри MAX | Утверждает ссылку Mini App и кнопку в существующем боте | Серверная проверка `WebApp.initData` по bot token, валидация подписи/срока, тест запуска, обработка `bot_started`/`bot_stopped` | P1 |
| YANDEX-ID | Яндекс ID | Вход покупателей | Создаёт приложение **для авторизации пользователей**, верифицирует его под названием РАКОВАРЪ, задаёт контакты | client_id, client_secret только где необходим, Redirect URI, scope login/email/phone по минимальной необходимости, PKCE/state | P1 |
| YANDEX-EDA | Кабинет Яндекс Еды | Источник реального каталога/заказов, возможная интеграция | Предоставляет **ограниченный доступ к кабинету продавца или экспорт** в согласованном формате; выясняет доступность API/условия | CSV/API только по доступным правам и договору; не путать с Yandex ID; канал-специфичная цена | P1 |
| PAY-YOOKASSA | ЮKassa | Карта/СБП и другие разрешённые способы оплаты, возвраты | Заключает договор на **юридического продавца**, включает тестовый магазин, подтверждает фискализацию | Роль **«Разработчик»** в кабинете, shopId, тестовый/боевой secretKey в secret store, HTTPS webhook URL, события payment/refund; live только по owner approval | P0 до платных заказов |
| FISCAL-KKT | 54-ФЗ, касса/ОФД | Фискальные чеки при онлайн-оплате и наличных/самовывозе | Выбирает и оформляет юридически подходящую ККТ/оператора (например, «Чеки от ЮKassa» при применимости либо стороннюю кассу), подтверждает налоговую схему, ставки и продавца | Интеграционный идентификатор/ключи, webhook/receipt status и доступ к тестовым чекам, требования к офлайн-расчётам и курьеру | P0 |
| MAIL-DOMAIN | Корпоративная почта | Чеки, заказы, support, подтверждение email, уведомления | Создаёт адреса `orders@`, `support@`, `no-reply@` на реальном домене и выбирает email провайдера | SMTP/API credentials отправки через secret store, sender domain verification, SPF/DKIM/DMARC, delivery/bounce logs | P0/P1 |
| SMS-OTP | SMS provider | Проверка номера и восстановление через сотрудника | Оформляет сервис SMS-подтверждений с оплатой и законной обработкой ПДн | API key ограниченных прав, sender id (после модерации), callback доставки, квоты и fraud limits | P1 |
| GEO-MAPS | Геокодирование/карты | Адрес, зона/стоимость доставки, курьер | Утверждает провайдера, бюджет, лицензии и хранение адресов | Browser/server API keys с referrer/IP restriction, quota, геозоны от компании | P1 |
| MSG-MARKETING | Коммуникации | Почта/VK/MAX уведомления и рекламные кампании | Утверждает категории сообщений, рассылочные согласия, privacy/legal | Allowed provider scopes, opt-in ledger per channel, unsubscribe, bounce, suppression | P2 |
| ANALYTICS | Analytics / Search / Webmaster | Ошибки, конверсии, SEO, индексирование | Создаёт/подтверждает site ownership и режим аналитики по 152-ФЗ | Ограниченная роль для Яндекс Метрики/Вебмастера или согласованной аналитики, token site verification | P2 |
| PARTNER | Партнёры и подарки | Промо, розыгрыши, prize fulfillment | Даёт партнёрские договоры, правила кампаний, доказанные права API | Partner/Perfluence identifiers, токены при наличии официального API, список призов и их стоимость/налоги/условия | P2 |
| REVIEWS | Карты/отзывы/соцсети | Проверенные отзывы, ответы, публикации | Подтверждает владение карточками Яндекс Карт / VK и разрешение на собственный контент | Роль отвечающего/ссылки/допустимый API доступ, правила публикации фото пользователей | P2 |
| APP-SIGNING | Android APK | Подписанный клиент и обновления | Утверждает имя приложения, package ID, владельца сертификата/ключа, канал дистрибуции | Доступ к CI signing **без передачи закрытого ключа в Git**, app links/redirect fingerprints, release workflow | P3 |

**Критичность:** P0 — обязательная подготовка инфраструктуры/финансового контура; P1 — перед основной версией; P2 — маркетинг; P3 — APK. Не все P0 API должны быть включены в день первого технического релиза: например, ЮKassa live остается выключенной до договоров/приёмки, действующий наличный checkout сохраняется в рамках законной организации расчётов.

## 2. REG.RU: что именно заказать, чего нельзя делать

**Рекомендуемая архитектура** для нашего Flask/Gunicorn/WSGI + PostgreSQL + очереди фоновых задач + внешних webhooks: VPS/облачный сервер в требуемой правовой юрисдикции, независимая база/backup и object storage. **Не покупать shared host, пока не сверены Python version, процесс-менеджер, SSH, PostgreSQL, scheduler/worker, file persistence, SSL, inbound ports, outbound API, CPU/RAM/диск и тариф.** REG.RU действительно описывает Flask на Linux shared hosting *при использовании ispmanager*, но это не подтверждает поддержку всех требований нашего приложения.

Домен/биллинг остаются владельцу. Для shared hosting REG.RU есть официальное **частичное управление услугой** с другого аккаунта; для VPS/облачных серверов порядок прав уточняется отдельно и лучше выдать SSH user с key-based auth. **Не передавать домен на другой аккаунт** и не предоставлять учётные данные основного владельца. DNS владелец меняет по согласованному чек-листу либо делегирует точечно, если его тариф это позволяет.

- Домен `example.ru` заменить реальным только после регистрации; будущие `shop/`, `api.`, `staging.`, `admin.` не обязательны, выбираются по архитектуре.
- DNS: A/AAAA для сайта, CNAME `www`, TLS/Let's Encrypt/автообновление, TXT проверки владения, MX/SPF/DKIM/DMARC для почты. Сохранить экспорт DNS перед сменой.
- Сервер: Linux LTS, актуальная поддерживаемая Python, ограниченный user, firewall, Fail2ban/SSH hardening по аудитному плану, systemd services/web workers, health endpoint, logs без PII.
- Данные: PostgreSQL, application secrets, миграции, WAL/backup policy, restore drill, object media, отдельная staging среда; не хранить вложения только на ephemeral filesystem.
- **152-ФЗ:** место размещения первичной базы ПД граждан РФ, резервные копии и трансграничные потоки согласовать с компетентным юристом до миграции; тот факт, что услуга куплена у российского регистратора, **сам по себе не гарантирует размещение в РФ** — проверить дата-центр/договор.
- По действующей документации Render free PostgreSQL имеет срок **до 10.12.2026** — выбрать миграцию и реально протестировать backup/restore до этой даты. Не удалять Render и не отключать работающий магазин до подтверждения нового сервера.

**Особенность доменов .ru/.рф/.su на ноябрь 2026:** у REG.RU имеется актуальное уведомление о необходимости идентификации администратора через ЕСИА с 01.09.2026 и специальная услуга переходного администрирования; перед оформлением попросить владельца проверить требования конкретной доменной зоны/своего статуса с REG.RU. Источник: https://help.reg.ru/support/domains/dopolnitelnyye-uslugi-dlya-domena/usluga-tranzitnoe-administrirovanie-domena .

## 3. Секреты и переменные окружения

**Ниже имена — проектные, не подтверждение что они все уже реализованы.** Сверить текущие `.env.example` и `connections.py`/добавить при внедрении.

| Интеграция | Конфигурация | Где хранить |
|---|---|---|
| Flask | `FLASK_SECRET_KEY`, `INTEGRATION_ENCRYPTION_KEY`, `PUBLIC_BASE_URL`, `COOKIE_SECURE=true` | Server secrets |
| PostgreSQL | `DATABASE_URL` и отдельный migration role | Server secrets |
| MAX | существующие `MAX_BOT_TOKEN`, `MAX_BOT_USERNAME`, `MAX_WEBHOOK_SECRET`, `MAX_MINIAPP_URL` | Server secrets |
| VK | `VK_GROUP_ID`, `VK_GROUP_TOKEN`, `VK_ID_APP_ID`, callback / state verifier | Secret store; `APP_ID` может быть public |
| Yandex ID | `YANDEX_OAUTH_CLIENT_ID`, `YANDEX_OAUTH_CLIENT_SECRET` (если применим), redirect URI | Private app config |
| YooKassa | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_URL` | Server secrets + provider settings |
| Email | `EMAIL_FROM`, `SMTP_HOST` / provider API token, `SMTP_TLS` | Server secrets |
| SMS | `SMS_PROVIDER`, `SMS_API_KEY`, sender-ID/quota | Server secrets |
| Media | `MEDIA_BUCKET`, `MEDIA_ENDPOINT`, `MEDIA_ACCESS_KEY`, `MEDIA_SECRET_KEY` | Scoped server secrets |
| Maps | `MAPS_API_KEY`, separate browser/server keys with restrictions | Provider config |
| Analytics | site/project ID; no customer secrets client-side | Separate consent-aware config |

Не коммитить **реальные** значения и не передавать их в текст PR/README; при выдаче доступов проверить least privilege, срок, owner identity, secret rotation/revocation. При смене `INTEGRATION_ENCRYPTION_KEY` старые зашифрованные данные нельзя просто считать доступными — нужна контролируемая ротация.

## 4. ЮKassa / чек и доставка

- Владельцу оформить договор на **правильного продавца**. В публичных материалах РАКОВАРЪ есть конфликтующие ИНН/ОГРНИП — это **блокер** для merchant/account/кассы/оферты до подтверждения.
- ЮKassa разрешает добавить сотрудника с ролью **«Разработчик»**; предпочтительнее передачи главного кабинета. Используются `shopId` + секретный ключ; сначала **тестовые** креденшалы и тестовый магазин.
- HTTP/webhooks — настроить после HTTPS с реальным доменом, статус по серверу; при спорном webhook делать обратный API запрос, не доверять одному redirect.
- Подключение к 54-ФЗ: **«Чеки от ЮKassa»** (при подходящей модели и тарифе) или сторонняя онлайн-касса/ОФД. Сервис «Чеки от ЮKassa» доставляет чек **на email**; не обещать SMS чек от этого сервиса. Для наличных/самовывоза/курьера и зачёта аванса/сертификата отдельно решить чековые сценарии; функциональность «Чеки от ЮKassa» для онлайн-эквайринга не автоматически покрывает каждый офлайн-расчёт.
- Прояснить размеры/условия фискализации и предоплату при переменном весе товара; проверить реальный финальный чек перед включением.

Официальные источники: https://yookassa.ru/developers/using-api/interaction-format , https://yookassa.ru/developers/using-api/webhooks , https://yookassa.ru/developers/payment-acceptance/receipts/54fz/basics , https://yookassa.ru/developers/payment-acceptance/receipts/54fz/yoomoney/basics .

## 5. Авторизация и различие каналов

- **VK Group token** предназначен для разрешённых действий с сообществом; **VK ID App ID** — для OAuth/покупательского входа. Разные полномочия и разные конфигурации. Владение VK-аккаунтом и переход из группы ≠ автоматическое согласие на сообщения/рекламу.
- **MAX Bot token** подписывает initData Mini App и используется для Bot API. Нужны существующий bot username/ID и публичный `https://...` Mini App URL; bot token не публиковать, состав разрешённых events валидировать, выполнять webhook проверку.
- **Yandex ID** отдельное OAuth-приложение для входа и получения согласованных login/email/phone; это **не** доступ к merchant account Яндекс Еды. Получать scope минимально, поднимать consent и безопасность merge identities.
- **Phone login** требует SMS/email services. Временный пароль только после владения подтверждённым номером; операторская процедура сброса требует проверки больше Caller ID.
- Сервис **Яндекс Карт** не равен Яндекс ID: для карты/адреса может потребоваться отдельный Maps API key, реальный адрес/доставка от владельца, referrer/IP restriction; правила конкретного SDK проверять в выбранном тарифе.

Официальные источники: https://github.com/VKCOM/vkid-web-sdk , https://dev.max.ru/docs/chatbots/bots-create/manage/ , https://dev.max.ru/docs/webapps/introduction/ , https://dev.max.ru/docs/webapps/validation , https://yandex.ru/dev/id/doc/ru/register-auth .

## 6. Что владелец обязан предоставить как ДАННЫЕ, не как ключи

1. Название реального домена и реквизиты владельца домена, подтверждённого продавца (ИП/ООО) и оператора ПДн, контакты сотрудника для согласования интеграций.
2. Действующий адрес/график/зоны/тарифы/слоты, реальный ассортимент и direct price/stock; полные выгрузки VK Market, clients.site /kraby, Яндекс Еда; исходные SKU и медиа с разрешением.
3. Корпоративные каналы и контакты: владелец официальной группы VK и бота MAX, способ связи с техподдержкой, email для чеков/заказов, sender/SMS.
4. Система налогообложения, налоговые ставки по продаваемым товарам, оферта, 54-ФЗ и оператор кассы/возвратов, виды сертификатов/предоплаты.
5. Права на фото/логотип, фирменные материалы, согласованная история компании, соцссылки и согласия на публикацию отзывов.
6. Зоны ответственности: кто проверяет цены, кто утверждает акции/юридические тексты, кто принимает заказ, кто отвечает за возврат, кто согласует оплату сторонних тарифов.

## 7. Порядок подключения (без лишних остановок)

1. `PREPARE`: подтвердить продавца/РКН и юридические данные; выбрать хостинг в нужном регионе и утвердить стоимость.
2. `HOSTING`: владелец покупает домен+VPS, инженер получает отдельный доступ; настраивает DNS/HTTPS/DB/storage/backup/health; переносит демо только с резервной копией и миграциями.
3. `AUTH`: зарегистрировать VK ID и Yandex OAuth apps; настроить существующий MAX bot URL/webhook/validation, SMS OTP; связать identity и сформировать безопасную модель customer_id.
4. `COMMERCE`: подключить тестовый YooKassa и фискализацию, email provider, SMS, проверить тестовые чеки, возврат, cash.
5. `CONTENT`: owner-approved catalog/photo import и CMS, интеграции соцсетей, отзывы, карты и контактная информация, отдельные marketing consents.
6. `PRODUCTION`: прогнать полный E2E/regression/IDOR/54-ФЗ тесты, restore drill, UX screen check. Включать реальный платеж/публикацию только по письменному разрешению владельца.

## 8. Критерий приёмки каждой интеграции

- `owner` и `merchant identity` установлены; credential scope минимален, stored safely, expiration/rotation известны.
- Документировано `provider_account_id`, `sandbox` и `production`, callback/redirect URL, per-environment status.
- Подключение прошло **реальный** test call (если провайдер разрешает), retry/error path, webhook duplicate/replay, disconnect/revoke.
- Сохраняется информация **не о значении секретного токена**, а о его доступности, тесте, версии прав, последнем успехе и дате следующей ротации.
- Функция отключена при отзыве доступа; нет ложной отправки/оплаты/заказа.
- Owner сохранил аккаунт, оплачивает сервис, может самостоятельно отозвать любой выданный доступ.

## 8A. Грант REG.Cloud

Если Анатолий планирует получить инфраструктурный грант, cloud account оформляется непосредственно на ИП/ООО-заявителя; сервер и PostgreSQL выбираются по проектной смете. Предполагается передача исключительных имущественных прав компании по **будущему** договору. Перед подачей нужно подтвердить соответствие условию принадлежности проекта заявителю, п. 3.1 программы REG.Cloud. Подробности, условия 30 000–500 000 бонусных рублей и план подготовки: [REGCLOUD_GRANT_APPLICATION_AND_RIGHTS_2026-11-13.md](REGCLOUD_GRANT_APPLICATION_AND_RIGHTS_2026-11-13.md).

## 9. Текущий фактический статус

- REG.RU domain, VPS, delegated access: **NOT_PROVIDED / NOT_VERIFIED** (планы пользователя, не выполненный факт).
- VK group token, VK ID app: **NOT_PROVIDED / NOT_VERIFIED**.
- MAX Business bot: **USER_STATED_REGISTERED**; токен/модерация/возможности реальной отправки **NOT_VERIFIED**.
- Yandex OAuth/Еда, YooKassa merchant/cash, SMS, SMTP, Maps: **NOT_PROVIDED / NOT_VERIFIED**.
- Прежний Render preview Flask/PostgreSQL: подтверждён ранее по документации, перенос не выполнен; production пригодность **BLOCKED** до вопросов 152-ФЗ/юрлица/данных/DB.
- Сами продуктовые интерфейсы и интеграции из master spec: часть legacy кода существует, но реальные провайдеры не подключены/не проверены; не выдавать за внедрение.

**Этот файл предназначен для согласования владельцем; его нельзя заполнять значениями реальных секретов.**
