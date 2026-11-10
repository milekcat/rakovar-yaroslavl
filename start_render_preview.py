"""Run the preview web app and optional development MAX Long Polling bot."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = os.getenv("PORT", "10000")
web = None
bot = None


def stop(_signum=None, _frame=None):
    for proc in (bot, web):
        if proc and proc.poll() is None:
            proc.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

web = subprocess.Popen(
    [
        sys.executable, "-m", "gunicorn", "app:app",
        "--bind", f"0.0.0.0:{PORT}", "--workers", "1",
        "--threads", "4", "--timeout", "60",
    ],
    cwd=ROOT,
)

try:
    ready = False
    last_error = "not checked"
    # Check both health and the actual storefront. A health-only check allowed
    # a broken deployment (missing Jinja templates) to be marked healthy.
    for _ in range(60):
        if web.poll() is not None:
            raise SystemExit(web.returncode)
        try:
            for path in ("/api/health", "/"):
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=3) as response:
                    if response.status != 200:
                        raise RuntimeError(f"{path} returned HTTP {response.status}")
            ready = True
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if ready:
            break
        time.sleep(1)

    if not ready:
        raise SystemExit(f"web service failed storefront readiness check: {last_error}")

    if os.getenv("MAX_BOT_TOKEN", "").strip() and os.getenv("MAX_BOT_MODE", "webhook") == "polling":
        bot = subprocess.Popen([sys.executable, os.path.join(ROOT, "max_bot.py")], cwd=ROOT)
    else:
        print("Web app ready; MAX webhook is configured explicitly in the admin panel.", flush=True)

    code = web.wait()
finally:
    stop()
    for proc in (bot, web):
        if proc and proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

sys.exit(code if "code" in locals() else 1)
