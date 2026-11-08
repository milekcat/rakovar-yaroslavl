"""Development-only MAX long-polling bot for local preview.

MAX documents Long Polling as a development/testing mechanism, not production.
Production should switch to HTTPS Webhook subscriptions.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv()

from max_client import MaxAPIError, get_me, get_updates, send_message, set_commands
from app import DEMO_MODE, connect_db, get_loyalty_rate, get_visitor, get_or_create_referral_code, loyalty_tier, referral_setting

STOP = False


def _record_health(status: str, detail: str = ""):
    try:
        with connect_db() as c:
            c.execute("INSERT INTO integration_health(provider,status,last_checked,detail) VALUES('MAX Bot API',?,?,?) "
                      "ON CONFLICT(provider) DO UPDATE SET status=excluded.status,last_checked=excluded.last_checked,detail=excluded.detail",
                      (status, NOW_UTC(), detail[:160]))
    except Exception as exc:
        print(f"MAX health write failed: {type(exc).__name__}", file=sys.stderr)


def NOW_UTC():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stop(*_args):
    global STOP
    STOP = True


def _guest_id(user_id: int | str) -> str:
    return f"max_{int(user_id)}"


def _buttons(username: str | None) -> list | None:
    # Do not show a Mini App button until an HTTPS URL is registered in MAX settings.
    miniapp_url = os.getenv("MAX_MINIAPP_URL", "").strip()
    username = (username or os.getenv("MAX_BOT_USERNAME", "")).strip().lstrip("@")
    if not username or not miniapp_url.startswith("https://"):
        return None
    link = f"https://max.ru/{quote(username)}?startapp=shop"
    return [[{"type": "link", "text": "Открыть РАКОВАРЪ", "url": link}]]


def _send_user(user_id: int, text: str, username: str | None = None):
    return send_message(user_id=user_id, text=text, buttons=_buttons(username))


def _catalog_text() -> str:
    with connect_db() as c:
        rows = c.execute("SELECT title,price,unit,price_verified FROM products WHERE active=1 ORDER BY category,title LIMIT 12").fetchall()
    if not rows:
        return "Каталог пока загружается. Напишите менеджеру — поможем с выбором."
    lines = ["🦞 РАКОВАРЪ · несколько позиций из каталога"]
    for row in rows:
        mark = "" if row["price_verified"] else " · цена предварительная"
        lines.append(f"• {row['title']} — {row['price']} ₽ {row['unit']}{mark}")
    lines.append("\nАктуальные наличие, состав и цену подтвердит менеджер.")
    return "\n".join(lines)[:3900]


def _ticket_state(user_id: int) -> tuple[int, int]:
    guest_id = _guest_id(user_id)
    with connect_db() as c:
        return int(get_visitor(c, guest_id)["tickets"]), get_loyalty_rate(c)


def handle_update(update: dict, bot_username: str | None = None):
    kind = update.get("update_type")
    if kind == "bot_started":
        user = update.get("user") or update.get("sender") or {}
        user_id = user.get("user_id")
        if user_id:
            _send_user(int(user_id), "Добро пожаловать в РАКОВАРЪ! 🦞\n\nЗдесь можно посмотреть каталог, узнать о клубе и игровых билетах.\n\nКоманды: /catalog, /club, /referral, /help", bot_username)
        return
    if kind != "message_created":
        return
    message = update.get("message") or {}
    sender = message.get("sender") or update.get("sender") or {}
    user_id = sender.get("user_id")
    if not user_id or sender.get("is_bot"):
        return
    body = message.get("body") or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return
    command = text.split()[0].split("@", 1)[0].lower()
    if command in {"/start", "start", "начать"}:
        answer = ("Добро пожаловать в РАКОВАРЪ! 🦞\n\n"
                  "Морские и речные деликатесы, авторские сеты и подарочные композиции.\n\n"
                  "Команды:\n/catalog — каталог\n/club — билеты и клуб\n/id — ваш MAX ID\n/help — помощь")
    elif command in {"/catalog", "каталог", "меню"}:
        answer = _catalog_text()
    elif command in {"/club", "клуб", "/tickets", "билеты"}:
        balance, loyalty_rate = _ticket_state(int(user_id))
        answer = (f"🎟 Ваш баланс клуба РАКОВАРЪ: {balance} билет(ов).\n\n"
                  f"Билеты начисляются за подтверждённые покупки: 1 билет за каждые {loyalty_rate} ₽, "
                  "а также за участие в специальных акциях и конкурсах, если это указано в их правилах.\n"
                  "Билет можно потратить в игровой зоне. Денежных ставок и покупки шансов нет.")
    elif command in {"/referral", "пригласить", "реферал"}:
        guest_id = _guest_id(int(user_id))
        with connect_db() as c:
            code = get_or_create_referral_code(c, guest_id)
            inviter_reward = referral_setting(c, "referral_inviter_tickets", 10, 0, 100)
            friend_reward = referral_setting(c, "referral_friend_tickets", 5, 0, 100)
            minimum = referral_setting(c, "referral_min_order_rub", 1500, 0, 1000000)
        link = f"https://max.ru/{(bot_username or os.getenv('MAX_BOT_USERNAME','')).lstrip('@')}?startapp=ref_{code}"
        answer = (f"🦞 Ваш код приглашения: {code}\n\n"
                  f"Друг получает {friend_reward} клубных билетов, а вы — {inviter_reward}, когда друг совершит первую подтверждённую покупку от {minimum} ₽.\n\n"
                  f"Поделиться: {link}\n\n"
                  "Бонусы не имеют денежного эквивалента и используются в игровой зоне клуба.")
    elif command in {"/id", "id"}:
        answer = f"Ваш MAX user_id: {user_id}\nИспользуйте его для настройки уведомлений владельцу."
    elif command in {"/help", "помощь", "поддержка"}:
        answer = "Помогу с каталогом и клубом.\n/catalog — каталог\n/club — билеты\n/referral — пригласить друга\n/id — ваш ID\nПо составу, наличию и доставке обратитесь к менеджеру РАКОВАРЪ."
    else:
        answer = "Я помогу найти морские деликатесы 🦞\nНапишите /catalog для меню или /club для информации о билетах."
    _send_user(int(user_id), answer, bot_username)


def main():
    if not os.getenv("MAX_BOT_TOKEN", "").strip():
        print("BLOCKED: set MAX_BOT_TOKEN in .env (do not paste it into source code).", file=sys.stderr)
        return 2
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        me = get_me()
    except MaxAPIError as exc:
        _record_health("error", f"auth_failed:{exc.status or 'network'}")
        print(f"MAX bot auth failed: {exc}", file=sys.stderr)
        return 1
    username = me.get("username") or os.getenv("MAX_BOT_USERNAME")
    try:
        set_commands()
        print("MAX bot commands registered.")
    except MaxAPIError as exc:
        print(f"MAX command registration failed: {exc}", file=sys.stderr)
    _record_health("connected", f"@{username or 'username-not-returned'}; long-polling-dev")
    print(f"MAX bot connected: @{username or 'username-not-returned'}; mode=long-polling (development only)")
    marker = None
    while not STOP:
        try:
            response = get_updates(marker=marker, timeout=30, limit=100)
            _record_health("connected", "long-polling-ok")
            if response.get("marker") is not None:
                marker = response["marker"]
            for update in response.get("updates", []):
                try:
                    handle_update(update, username)
                except MaxAPIError as exc:
                    print(f"MAX reply failed: {exc}", file=sys.stderr)
                except Exception as exc:
                    print(f"Update handler failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        except MaxAPIError as exc:
            _record_health("degraded", f"poll_error:{exc.status or 'network'}")
            print(f"MAX polling error: {exc}", file=sys.stderr)
            time.sleep(5)
        except KeyboardInterrupt:
            break
    _record_health("stopped", "polling_stopped")
    print("MAX bot stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
