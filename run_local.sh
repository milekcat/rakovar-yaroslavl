#!/usr/bin/env bash
set -euo pipefail
[[ -f .env ]] || { cp .env.example .env; echo "Created .env. Add MAX_BOT_TOKEN and ADMIN_PASSWORD_HASH, then rerun."; exit 1; }
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
( .venv/bin/python app.py ) & WEB_PID=$!
( .venv/bin/python max_bot.py ) & BOT_PID=$!
trap 'kill "$WEB_PID" "$BOT_PID" 2>/dev/null || true' EXIT INT TERM
wait
