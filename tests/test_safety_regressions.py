"""Regression coverage for observed identity, retry and concurrency failures."""
import hashlib
import json
import sys
import threading
import time
import types
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_app import app_module, client, bootstrap, admin_login


def headers(csrf, key=None):
    return {"X-CSRF-Token": csrf, "Idempotency-Key": key or uuid.uuid4().hex}


def order_body(guest):
    return {"guest_id": guest, "items": [{"id": "crayfish-medium-kg", "quantity": 1}],
            "name": "Test User", "phone": "+79990000000", "consent": True, "delivery_mode": "pickup"}


def test_unsigned_max_identity_and_existing_browser_profile_are_rejected(client, app_module):
    assert client.get("/api/bootstrap?guest_id=max_123").status_code == 403
    guest = "existing-browser-identity-12345"
    bootstrap(client, guest)
    other = app_module.app.test_client()
    response = other.get("/api/bootstrap", query_string={"guest_id": guest})
    assert response.status_code == 403
    assert response.json["error"] == "visitor_identity_unproven"
    assert client.get("/api/game/profile", query_string={"guest_id": guest}).status_code == 200


def test_duplicate_sku_cannot_bypass_stock(client, app_module):
    with app_module.connect_db() as c:
        c.execute("UPDATE products SET stock=1 WHERE id='crayfish-medium-kg'")
    response = client.post("/api/checkout/quote", json={"items": [
        {"id": "crayfish-medium-kg", "quantity": 1},
        {"id": "crayfish-medium-kg", "quantity": 1}], "delivery_mode": "pickup"})
    assert response.status_code == 400
    assert response.json["message"] == "duplicate_cart_item"


@pytest.mark.parametrize("path", ["/api/orders", "/api/game/spin"])
def test_critical_requests_require_explicit_key(client, path):
    guest = "missing-key-browser-12345"
    csrf = bootstrap(client, guest)
    response = client.post(path, headers={"X-CSRF-Token": csrf}, json=order_body(guest))
    assert response.status_code == 428
    assert response.json["error"] == "idempotency_key_required"


def test_order_replay_returns_same_receipt_without_double_promo(client, app_module):
    guest = "idempotent-order-browser-12345"
    csrf = bootstrap(client, guest)
    body = dict(order_body(guest), promo_code="WELCOME10")
    key = uuid.uuid4().hex
    first = client.post("/api/orders", headers=headers(csrf, key), json=body)
    retry = client.post("/api/orders", headers=headers(csrf, key), json=body)
    conflict = client.post("/api/orders", headers=headers(csrf, key), json=dict(body, delivery_mode="delivery"))
    assert first.status_code == retry.status_code == 201
    assert retry.json == first.json
    assert conflict.status_code == 409
    assert conflict.json["error"] == "idempotency_payload_conflict"
    with app_module.connect_db() as c:
        assert c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert c.execute("SELECT uses FROM promotions WHERE code='WELCOME10'").fetchone()[0] == 1
        receipt = dict(c.execute("SELECT * FROM operation_receipts").fetchone())
        assert body["phone"] not in json.dumps(receipt)
        assert body["name"] not in json.dumps(receipt)


def test_spin_replay_has_one_effect_and_matching_server_sector(client, app_module):
    guest = "idempotent-spin-browser-12345"
    csrf = bootstrap(client, guest)
    key = uuid.uuid4().hex
    first = client.post("/api/game/spin", headers=headers(csrf, key), json={"guest_id": guest})
    second = client.post("/api/game/spin", headers=headers(csrf, key), json={"guest_id": guest})
    assert first.status_code == second.status_code == 200
    assert first.json == second.json
    assert first.json["sectors"][first.json["sector_index"]]["id"] == first.json["prize"]["id"]
    assert first.json["tickets"] == 2
    with app_module.connect_db() as c:
        assert c.execute("SELECT COUNT(*) FROM spins").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM ticket_ledger WHERE source_type='spin'").fetchone()[0] == 1


def test_oversized_legacy_prize_pool_cannot_consume_ticket(client, app_module):
    guest = "oversized-prize-pool-12345"
    csrf = bootstrap(client, guest)
    with app_module.connect_db() as c:
        for number in range(28):
            c.execute("INSERT INTO prizes(id,title,kind,stock,weight,active) VALUES(?,?,'gift',10,1,1)",
                      (f"legacy-extra-{number}", f"Legacy demo prize {number}"))
    data = client.get("/api/bootstrap", query_string={"guest_id": guest}).json
    assert len(data["wheel_sectors"]) == 33
    assert data["wheel_configuration_error"] == "too_many_sectors"
    response = client.post("/api/game/spin", headers=headers(csrf), json={"guest_id": guest})
    assert response.status_code == 409 and response.json["error"] == "wheel_configuration_invalid"
    with app_module.connect_db() as c:
        assert c.execute("SELECT tickets FROM visitors WHERE guest_id=?", (guest,)).fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM spins").fetchone()[0] == 0


def test_prize_create_and_reactivation_enforce_renderer_limit(client, app_module):
    csrf = admin_login(client)
    with app_module.connect_db() as c:
        for number in range(28):
            c.execute("INSERT INTO prizes(id,title,kind,stock,weight,active) VALUES(?,?,'gift',10,1,?)",
                      (f"prize-extra-{number}", f"Demo prize {number}", 0 if number == 27 else 1))
    response = client.post("/api/admin/prizes", headers=headers(csrf), json={"title": "One more", "stock": 10, "weight": 1, "kind": "gift"})
    assert response.status_code == 409
    response = client.patch("/api/admin/prizes/prize-extra-27", headers=headers(csrf), json={"active": 1})
    assert response.status_code == 409
    assert client.patch("/api/admin/prizes/prize-extra-0", headers=headers(csrf), json={"active": 0}).status_code == 200
    assert client.patch("/api/admin/prizes/prize-extra-27", headers=headers(csrf), json={"active": 1}).status_code == 200


def parallel_clients(app, cookie, actions):
    barrier = threading.Barrier(len(actions))
    def run(action):
        with app.test_client() as worker:
            worker.set_cookie("session", cookie)
            barrier.wait(timeout=15)
            return action(worker)
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def test_concurrent_spins_cannot_overspend_three_tickets(client, app_module):
    guest = "concurrent-spin-browser-12345"
    csrf = bootstrap(client, guest)
    cookie = client.get_cookie("session").value
    actions = [lambda worker: worker.post("/api/game/spin", headers=headers(csrf), json={"guest_id": guest}) for _ in range(4)]
    responses = parallel_clients(app_module.app, cookie, actions)
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 409]
    with app_module.connect_db() as c:
        assert c.execute("SELECT tickets FROM visitors WHERE guest_id=?", (guest,)).fetchone()[0] == 0
        assert c.execute("SELECT SUM(delta) FROM ticket_ledger WHERE guest_id=?", (guest,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM spins WHERE guest_id=?", (guest,)).fetchone()[0] == 3


def test_concurrent_same_key_returns_one_spin(client, app_module):
    guest = "concurrent-same-key-browser-12345"
    csrf = bootstrap(client, guest)
    key, cookie = uuid.uuid4().hex, client.get_cookie("session").value
    actions = [lambda worker: worker.post("/api/game/spin", headers=headers(csrf, key), json={"guest_id": guest}) for _ in range(2)]
    responses = parallel_clients(app_module.app, cookie, actions)
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json == responses[1].json
    assert responses[0].json["tickets"] == 2


def test_cancel_after_preparation_reverses_original_award_and_logs_history(client):
    guest = "cancel-after-prepare-12345"
    csrf = bootstrap(client, guest)
    order = client.post("/api/orders", headers=headers(csrf), json=order_body(guest)).json["order_id"]
    admin_csrf = admin_login(client)
    for status in ("paid", "preparing", "ready"):
        assert client.patch(f"/api/admin/orders/{order}", headers=headers(admin_csrf), json={"status": status}).status_code == 200
    cancel = client.patch(f"/api/admin/orders/{order}", headers=headers(admin_csrf), json={"status": "cancelled"})
    assert cancel.json["tickets_reversed"] == 3
    assert client.get("/api/game/profile", query_string={"guest_id": guest}).json["tickets"] == 3
    repeat = client.patch(f"/api/admin/orders/{order}", headers=headers(admin_csrf), json={"status": "cancelled"})
    assert repeat.json["tickets_reversed"] == 0
    forbidden = client.patch(f"/api/admin/orders/{order}", headers=headers(admin_csrf), json={"status": "preparing"})
    assert forbidden.status_code == 409
    history = client.get(f"/api/admin/orders/{order}/history").json
    assert [row["new_status"] for row in history] == ["demo_received", "paid", "preparing", "ready", "cancelled"]
    assert all(row["actor"].startswith("staff:") for row in history[1:])


def test_end_day_is_inclusive_and_concurrent_draw_selects_once(client, app_module):
    guest = "contest-deadline-browser-12345"
    csrf = bootstrap(client, guest)
    with app_module.connect_db() as c:
        c.execute("UPDATE contests SET ends_at=? WHERE id='sea-evening'", (app_module.TODAY(),))
    assert client.post("/api/contests/sea-evening/entries", headers=headers(csrf), json={"guest_id": guest, "alias": "Demo", "answer": "A test answer"}).status_code == 201
    csrf = admin_login(client)
    assert client.post("/api/admin/contests/sea-evening/draw", headers=headers(csrf), json={"winners": 1}).status_code == 409
    with app_module.connect_db() as c:
        yesterday = (app_module.dt.date.fromisoformat(app_module.TODAY()) - app_module.dt.timedelta(days=1)).isoformat()
        c.execute("UPDATE contests SET ends_at=? WHERE id='sea-evening'", (yesterday,))
    cookie = client.get_cookie("session").value
    actions = [lambda worker: worker.post("/api/admin/contests/sea-evening/draw", headers=headers(csrf), json={"winners": 1}) for _ in range(2)]
    responses = parallel_clients(app_module.app, cookie, actions)
    assert sorted(r.status_code for r in responses) == [200, 409]
    with app_module.connect_db() as c:
        assert c.execute("SELECT COUNT(*) FROM contest_winners").fetchone()[0] == 1


def test_published_status_requires_provider_result(client):
    csrf = admin_login(client)
    created = client.post("/api/admin/content", headers=headers(csrf), json={"title": "Demo", "body": "Demo draft", "channels": ["vk"]})
    response = client.patch(f"/api/admin/content/{created.json['id']}", headers=headers(csrf), json={"status": "published"})
    assert response.status_code == 400
    assert client.get("/api/admin/content").json[0]["status"] == "draft"


def test_crashed_webhook_is_retried_and_only_processed_event_is_acked(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_WEBHOOK_SECRET", "synthetic-webhook-secret")
    update = {"update_type": "message_created", "timestamp": 1234567}
    fingerprint = hashlib.sha256(json.dumps(update, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with app_module.connect_db() as c:
        c.execute("INSERT INTO max_webhook_events(event_hash,received_at) VALUES(?,?)", (fingerprint, app_module.NOW()))
        c.execute("INSERT INTO max_webhook_leases(event_hash,lease_token,lease_until) VALUES(?,?,?)", (fingerprint, "expired-lease", int(time.time()) - 1))
    calls = []
    monkeypatch.setitem(sys.modules, "max_bot", types.SimpleNamespace(handle_update=lambda *args: calls.append(args)))
    first = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "synthetic-webhook-secret"}, json=update)
    again = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "synthetic-webhook-secret"}, json=update)
    assert first.status_code == again.status_code == 200
    assert first.json["status"] == "ok" and again.json["status"] == "duplicate"
    assert len(calls) == 1


def test_active_webhook_lease_is_retryable_not_success(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_WEBHOOK_SECRET", "synthetic-webhook-secret")
    update = {"update_type": "message_created", "timestamp": 7654321}
    fingerprint = hashlib.sha256(json.dumps(update, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with app_module.connect_db() as c:
        c.execute("INSERT INTO max_webhook_events(event_hash,received_at) VALUES(?,?)", (fingerprint, app_module.NOW()))
        c.execute("INSERT INTO max_webhook_leases(event_hash,lease_token,lease_until) VALUES(?,?,?)", (fingerprint, "active-lease", int(time.time()) + 60))
    response = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "synthetic-webhook-secret"}, json=update)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
