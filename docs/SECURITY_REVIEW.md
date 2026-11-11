# Проверка безопасности P0

Дата: 9 ноября 2026. Проверены исходники, временные synthetic БД, SQLite и настоящий локальный PostgreSQL 17.11. Удалённый Render-сервис не подвергался атакам, пользовательские секреты не извлекались. Это инженерное ревью ограниченного этапа, без заявления об отсутствии всех уязвимостей.

## Исправленные дефекты

Подтверждённые сценарии и regression tests перечислены в [P0_DELIVERY.md](P0_DELIVERY.md). Основные: присвоение MAX identity, повторные заказы/спины, гонки промокода/draw, пропущенное сторнирование, duplicate SKU, ручной fake published, ACK незавершённого webhook. Серверная идентичность и staff authority теперь проверяются отдельно. Изменяемые SQL-столбцы выбираются из статических allowlists; значения параметризованы.

## Зависимости

`pip-audit 2.10.1 -r requirements.txt` обнаружил две различные уязвимости (каждая продублирована источниками):

| Пакет до | Advisory | Изменение |
|---|---|---|
| Flask 3.1.1 | CVE-2026-27205 / GHSA-68rp-wp8r-4726 | Flask 3.1.3 |
| python-dotenv 1.1.1 | CVE-2026-28684 / GHSA-mf9w-mj56-hr94 | python-dotenv 1.2.4 |

Повторный аудит исправленного production requirements: **No known vulnerabilities found**. Это проверка базы известных advisories, не доказательство отсутствия неизвестных ошибок. psycopg[binary] 3.3.8: официальный PyPI, LGPL; Flask/python-dotenv BSD-3-Clause, Gunicorn MIT. Новые frontend runtime-библиотеки не добавлялись: SVG, CSS/Web Animations, WebAudio и Web Crypto нативные.

Первичные источники: [Flask releases](https://github.com/pallets/flask/releases), [Flask advisory](https://github.com/pallets/flask/security/advisories/GHSA-68rp-wp8r-4726), [python-dotenv advisory](https://github.com/theskumar/python-dotenv/security/advisories/GHSA-mf9w-mj56-hr94), [psycopg PyPI](https://pypi.org/project/psycopg/). Версии и metadata проверены через официальный PyPI JSON; advisory IDs получены из фактически выполненного pip-audit.

## SAST

Выполнен Bandit 1.9.4 для app.py, storage.py, staff_auth.py, commerce_safety.py, MAX модулей, prepare/start и scripts. Исходные результаты сохранены в отчёте проверки. Проверены классы предупреждений:

| Правило | Обоснование по текущим путям |
|---|---|
| B608, динамическое построение SQL | В admin updates имена столбцов берутся из фиксированных tuples/ветвей, значения placeholders. В importer имена таблиц — фиксированный TABLES; source columns дополнительно проходят regex и сверку target schema |
| B310, urlopen | MAX host задан константой HTTPS, пути задают внутренние функции; readiness использует фиксированный localhost. Пользовательского backend fetch произвольного URL нет |
| B104, 0.0.0.0 | Штатное bind dev/server; Flask debug отключён, production путь — Gunicorn |
| B404/B603/B607, subprocess | Команды передаются массивами, shell не используется; admin HTTP input не может выбирать исполняемые команды. Dev/maintenance инструменты требуют локального исполнения оператором |
| B101, asserts | В offline validator; не используются как HTTP authorization или production data validation |

Сигналы не были массово подавлены `nosec`. SAST не заменяет проверку продакшн-конфигурации и отзывов доступа. Эксплуатируемые SQLi, XSS или SSRF в просмотренных путях не подтверждены; CSRF, IDOR и конкурентные операции проверяются regression tests.

## Оставшиеся ограничения перед production

1. TOTP seeds хранятся в БД без application-layer encryption; нужны шифрование/управление ключами, recovery и операционная процедура восстановления. Не включать обязательную MFA до проверенного enrollment.
2. Браузерный guest ID — анонимная сессия, не проверенный клиент. Нет телефонного login/промышленного антифрода и защиты от создания множества новых анонимных профилей. Бесплатные demo-билеты не годятся для коммерческой акции.
3. Общая транзакционная блокировка PostgreSQL — переходная мера корректности, не финальная модель нагрузки. Public in-memory rate buckets не распределены между процессами; staff login/reauth guards хранятся в БД.
4. MAX lease не гарантирует exactly-once внешнюю отправку после crash. Нужны outbox, подтверждённая политика retries и приёмка реального provider.
5. Реальные файлы, платежи, личные данные, касса, доставки и publisher workers не включены. Сначала нужны соответствующие P1–P3 сервисы, retention, consent/legal документы и эксплуатационная приёмка.
6. Rights/актуальность фото, меню, контактов и юридические требования в этом engineering этапе не подтверждены.
7. Восстановление проверено на disposable PostgreSQL; резервные копии реального Render и восстановление production не выполнялись.

Новая инфраструктура не создавалась, тарифы и данные Render не менялись. Для release нужен review PR, проверка CI/браузеров, отдельный staging и затем согласованный production-релиз.
