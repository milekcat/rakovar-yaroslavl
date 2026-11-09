"""Run the Python preview with the host/port supplied by a preview supervisor.

The optional --strictPort flag is accepted for supervisors that also support
Vite apps. Gunicorn fails on a busy port and does not select a different one.
Authentication and data location use the project's ignored local .env file.
"""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    parser.add_argument("--strictPort", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    os.chdir(Path(__file__).resolve().parents[1])
    os.execv(sys.executable, [sys.executable, "-m", "gunicorn", "app:app", "--bind",
        f"{args.host}:{args.port}", "--workers", "1", "--threads", "4", "--timeout", "60"])


if __name__ == "__main__":
    main()
