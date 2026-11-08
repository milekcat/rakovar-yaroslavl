"""Run a temporary demo web app and optional MAX Long Polling bot in one Render instance."""
from __future__ import annotations
import os, signal, subprocess, sys, time, urllib.request
root=os.path.dirname(os.path.abspath(__file__))
port=os.getenv("PORT","10000")
web=None; bot=None
def stop(_signum=None,_frame=None):
    for proc in (bot,web):
        if proc and proc.poll() is None: proc.terminate()
signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
web=subprocess.Popen([sys.executable,"-m","gunicorn","app:app","--bind",f"0.0.0.0:{port}","--workers","1","--threads","4","--timeout","60"],cwd=root)
try:
    ready=False
    for _ in range(60):
        if web.poll() is not None: raise SystemExit(web.returncode)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=1) as response:
                ready=response.status==200
        except Exception: pass
        if ready: break
        time.sleep(1)
    if not ready: raise SystemExit("web service did not become ready")
    if os.getenv("MAX_BOT_TOKEN","").strip():
        bot=subprocess.Popen([sys.executable,os.path.join(root,"max_bot.py")],cwd=root)
    else:
        print("MAX_BOT_TOKEN not set; preview runs without MAX bot.",flush=True)
    code=web.wait()
finally:
    stop()
    for proc in (bot,web):
        if proc and proc.poll() is None:
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
sys.exit(code if 'code' in locals() else 1)
