"""Atomic request receipts and auditable demo order transitions.

Receipts are written in the same transaction as the business effect. A retry
must carry the original key; a different body cannot reuse a completed key.
No customer payload or contact information is stored in the receipt.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from flask import abort, current_app, request


ORDER_TRANSITIONS = {
    "demo_received": {"confirmed", "paid", "cancelled"},
    "confirmed": {"paid", "cancelled"},
    "paid": {"preparing", "ready", "completed", "cancelled"},
    "preparing": {"ready", "completed", "cancelled"},
    "ready": {"completed", "cancelled"},
    "completed": {"cancelled"},
    "cancelled": set(),
}


def init_safety_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS operation_receipts (
        guest_id TEXT NOT NULL, operation TEXT NOT NULL, request_key TEXT NOT NULL,
        request_digest TEXT NOT NULL, response_json TEXT NOT NULL,
        response_status INTEGER NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(guest_id, operation, request_key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_status_history (
        id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
        previous_status TEXT NOT NULL, new_status TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_order_history ON order_status_history(order_id,created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS max_webhook_events (
        event_hash TEXT PRIMARY KEY, received_at TEXT NOT NULL, processed_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS max_webhook_leases (
        event_hash TEXT PRIMARY KEY REFERENCES max_webhook_events(event_hash),
        lease_token TEXT NOT NULL, lease_until INTEGER NOT NULL)""")


def request_receipt(c, guest_id, operation, payload):
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        abort(428, description="idempotency_key_required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", key):
        abort(400, description="invalid_idempotency_key")
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    secret = str(current_app.config["SECRET_KEY"]).encode()
    digest = hmac.new(secret, serialized, hashlib.sha256).hexdigest()
    row = c.execute("""SELECT request_digest,response_json,response_status
        FROM operation_receipts WHERE guest_id=? AND operation=? AND request_key=?""",
        (guest_id, operation, key)).fetchone()
    if row:
        if not hmac.compare_digest(row["request_digest"], digest):
            abort(409, description="idempotency_payload_conflict")
        return (key, digest), (json.loads(row["response_json"]), row["response_status"])
    return (key, digest), None


def save_receipt(c, guest_id, operation, receipt, response, status, created_at):
    key, digest = receipt
    c.execute("""INSERT INTO operation_receipts
        (guest_id,operation,request_key,request_digest,response_json,response_status,created_at)
        VALUES(?,?,?,?,?,?,?)""", (guest_id, operation, key, digest,
        json.dumps(response, ensure_ascii=False, separators=(",", ":")), status, created_at))
