# GitHub → Render: публикация демонстрационной сборки

## Текущая схема

- Один Render web service во Frankfurt.
- Flask/Gunicorn + optional MAX bot Long Polling в одном экземпляре, одна SQLite БД в `/tmp`.
- `DEMO_MODE=true`; контакты клиентов не сохраняются; оплаты не подключены.
- Временный публичный адрес Render `*.onrender.com`; домен не требуется.
- Free service может засыпать, а `/tmp` не является постоянным хранилищем. Это ссылка для демонстрации, не production.

## Подготовить репозиторий

1. Создать отдельный репозиторий `milekcat/rakovar-yaroslavl` (не использовать `prime-ark` или `nikolaich-shop`).
2. Загрузить содержимое этого проекта в корень репозитория; `.env`, `.venv`, `*.sqlite3`, `__pycache__` и токены не загружать.
3. Убедиться, что `render.yaml` лежит в корне `main`.

## Render Blueprint

1. Открыть `https://dashboard.render.com/blueprint/new?repo=https://github.com/milekcat/rakovar-yaroslavl`.
2. Выбрать Blueprint и регион Frankfurt; проверить, что создаётся только `rakovar-preview`.
3. Задать `ADMIN_PASSWORD_HASH` и `MAX_BOT_TOKEN` как секретные переменные. Не помещать их в Git.
4. После первого успешного deploy скопировать `https://<service>.onrender.com` в `MAX_MINIAPP_URL` и сохранить этот же URL в настройках бота MAX в поле Mini App.
5. Проверить `/api/health`, `/`, `/admin/login`, `/api/bootstrap`; затем проверить MAX `/start`, `/catalog`, `/club`, `/referral` и запуск Mini App.

## Ограничения

- На этом preview SQLite хранится в `/tmp`; данные теряются при рестарте/сна/пересоздания. Никаких реальных заказов, платежей, контактов или финансового учёта.
- MAX Long Polling — только демонстрационный контур. Для production нужны Webhook и отдельная PostgreSQL архитектура.
- Перед production требуется PostgreSQL, миграции, backup/restore, роли/MFA, платёжные webhooks, защита от повторной обработки, реальные уведомления, согласия/политики, антифрод и юридическая проверка программы призов.
