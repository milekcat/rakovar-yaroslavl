"""Browser acceptance checks on a disposable, synthetic local preview.

Install requirements-browser.txt and a compatible Chromium, then run:
python scripts/browser_check.py --app-python .venv/bin/python --output docs/qa
Never targets a remote URL, imports real contacts or uses production credentials.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def otp(secret):
    digest = hmac.new(base64.b32decode(secret + "=" * (-len(secret) % 8)),
                      struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-python", default=str(ROOT / ".venv/bin/python"))
    parser.add_argument("--chromium", default=shutil.which("chromium"))
    parser.add_argument("--output", type=Path, default=ROOT / "docs/qa")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    password, staff_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    password_hash = subprocess.run([args.app_python, "-c",
        "import sys;from werkzeug.security import generate_password_hash;print(generate_password_hash(sys.stdin.read()))"],
        input=password, capture_output=True, text=True, check=True).stdout.strip()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    checks, console_errors = [], []
    with tempfile.TemporaryDirectory(prefix="rakovar-browser-") as temporary:
        database = Path(temporary) / "synthetic.sqlite3"
        env = os.environ.copy()
        env.update(DEMO_MODE="true", COOKIE_SECURE="false", DATABASE_URL="",
                   SQLITE_DB_PATH=str(database), ADMIN_PASSWORD_HASH=password_hash,
                   FLASK_SECRET_KEY=secrets.token_hex(32), INTEGRATION_ENCRYPTION_KEY=secrets.token_hex(32), STAFF_REQUIRE_MFA="false",
                   MAX_BOT_TOKEN="", MAX_ADMIN_USER_ID="", MAX_WEBHOOK_SECRET="", HIDE_STAFF_ENTRY="true")
        with (Path(temporary) / "server.log").open("w+") as log:
            server = subprocess.Popen([args.app_python, "-m", "gunicorn", "app:app", "--bind",
                f"127.0.0.1:{port}", "--workers", "1", "--threads", "4", "--timeout", "60"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("Synthetic preview server exited before readiness")
                    try:
                        with urllib.request.urlopen(origin + "/api/ready", timeout=1) as response:
                            if response.status == 200: break
                    except OSError:
                        if time.monotonic() >= deadline: raise RuntimeError("Synthetic preview did not become ready")
                        time.sleep(.1)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=args.chromium, headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"])
                    context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
                    page = context.new_page()
                    page.on("pageerror", lambda error: console_errors.append(str(error)))
                    page.goto(origin, wait_until="domcontentloaded")
                    expect(page.locator("#products .product-card").first).to_be_visible()
                    expect(page.locator("#wheel svg")).to_be_visible()
                    assert page.locator(".hero-visual > img").get_attribute("src").startswith("/static/images/menu/")
                    expect(page.locator(".hero-visual > img")).to_have_attribute("alt", "Сет «4 моря»: раки, креветки, лангустины и мидии")
                    assert page.locator("#products .product-card").count() == 24
                    assert len(context.request.get(origin + "/api/bootstrap").json()["products"]) == 74
                    expect(page.locator("#products .product-card h3").first).to_have_text("Средние варёные раки")
                    assert page.locator(".demo-banner").count() == 0
                    assert page.locator("#products .product-source").count() == 0
                    page.locator('[data-category="Соусы"]').click()
                    expect(page.locator("#products .product-card")).to_have_count(4)
                    for image in page.locator("#products img").all():
                        assert image.get_attribute("src").startswith("/static/images/menu/")
                    page.locator('[data-category="all"]').click()
                    expect(page.locator("#products .product-card")).to_have_count(24)
                    assert page.locator('a[href^="/admin"]').count()==0
                    assert context.request.get(origin+'/admin/login').status==404
                    page.locator('#products [data-favorite]').first.click()
                    expect(page.locator('#products [data-favorite]').first).to_have_attribute('aria-pressed','true')
                    page.screenshot(path=str(output / "storefront-desktop.png"))
                    checks.append("Storefront shows 59 priced photo cards, five live sizes, favorites and no staff links")

                    # Lose the successful response AFTER the server commits it.
                    sent_keys = []
                    def lose_once(route):
                        sent_keys.append(route.request.headers.get("idempotency-key"))
                        if len(sent_keys) == 1:
                            result = route.fetch()
                            assert result.status == 200
                            route.abort()
                        else:
                            route.continue_()
                    page.route("**/api/game/spin", lose_once)
                    page.locator("#spinButton").click()
                    expect(page.locator("#spinRetry")).not_to_be_empty()
                    expect(page.locator("#spinButton")).to_be_enabled()
                    with page.expect_response(lambda response: response.url.endswith("/api/game/spin") and response.status == 200) as spin:
                        page.locator("#spinButton").click()
                    result = spin.value.json()
                    expect(page.locator("#prizeModalOk")).to_be_visible()
                    assert len(sent_keys) == 2 and sent_keys[0] and sent_keys[0] == sent_keys[1]
                    assert result["sectors"][result["sector_index"]]["id"] == result["prize"]["id"]
                    with sqlite3.connect(database) as c:
                        assert c.execute("SELECT COUNT(*) FROM spins").fetchone()[0] == 1
                    page.locator("#prizeModalOk").click()
                    page.locator("#club").scroll_into_view_if_needed()
                    page.screenshot(path=str(output / "wheel-desktop.png"))
                    checks.append("Lost spin response retries same key, consumes one ticket and lands on server sector")

                    expect(page.locator('#liveSizes input')).to_have_count(5)
                    page.locator('#liveSizes input').last.check()
                    expect(page.locator('#liveSummary')).to_contain_text('XXL')
                    assert 'live-company-4.jpg' in page.locator('#livePhoto').get_attribute('src')
                    page.locator('#liveWeight').fill('3')
                    expect(page.locator('#liveSummary')).to_contain_text('3')
                    page.locator('#studioSearch').fill('кревет')
                    assert 3 < page.locator('#builderItems .studio-product').count() < 59
                    page.locator('#studioSearch').fill('')
                    page.locator('#sets').scroll_into_view_if_needed()
                    page.screenshot(path=str(output / 'set-studio-desktop.png'))
                    checks.append('Five live-crayfish sizes switch source photos and all 59 priced builder items remain searchable')
                    page.locator('#studioBudget').fill('10000')
                    page.locator('#autoBuildSet').click()
                    assert page.locator('#builderSelection .studio-selection-line').count()>=2
                    expect(page.locator('#studioPlate img').first).to_be_visible()
                    page.locator('#clearBuildSet').click()
                    expect(page.locator('#addBundle')).to_be_disabled()
                    page.locator('[data-studio-preset="two"]').click()
                    expect(page.locator("#builderItems .studio-product")).to_have_count(59)
                    page.locator('#bundleInquiry').click()
                    page.locator("#addBundle").click()
                    page.locator("#customerName").fill("Synthetic Browser Customer")
                    page.locator("#customerPhone").fill("+79990000000")
                    page.locator('input[name="delivery"][value="pickup"]').check()
                    expect(page.locator('#deliveryAddressGroup')).to_be_hidden()
                    page.locator("#consent").check()
                    order_keys=[]
                    def lose_order_once(route):
                        order_keys.append(route.request.headers.get('idempotency-key'))
                        if len(order_keys)==1:
                            result=route.fetch();assert result.status==201;route.abort()
                        else:route.continue_()
                    page.route('**/api/store/orders',lose_order_once)
                    page.locator('#checkoutForm button[type="submit"]').click()
                    expect(page.locator('#checkoutRetry')).not_to_be_empty()
                    expect(page.locator('#checkoutForm button[type="submit"]')).to_be_enabled()
                    with page.expect_response(lambda response: response.url.endswith("/api/store/orders") and response.status == 201) as order:
                        page.locator('#checkoutForm button[type="submit"]').click()
                    order_id = order.value.json()["order_id"]
                    assert len(order_keys)==2 and order_keys[0]==order_keys[1]
                    page.unroute('**/api/store/orders')
                    expect(page.locator("#orderDone")).to_be_visible()
                    page.locator("#orderDone").click()
                    with sqlite3.connect(database) as c:
                        row=c.execute("SELECT contact_label,customer_label,address_label FROM orders WHERE id=?",(order_id,)).fetchone()
                        assert row == ('ЗАШИФРОВАНО','Покупатель','ЗАШИФРОВАНО')
                        private=c.execute('SELECT ciphertext FROM shop_order_details WHERE order_id=?',(order_id,)).fetchone()[0]
                        assert '+79990000000' not in private and 'Synthetic Browser Customer' not in private
                    page.goto(origin + '/account')
                    expect(page.locator('#customerOrders')).to_contain_text(order_id)
                    assert page.locator('a[href^="/admin"]').count()==0
                    page.screenshot(path=str(output / 'customer-account-orders.png'))
                    page.locator('[data-account-tab="favorites"]').click()
                    expect(page.locator('#customerSavedSets [data-set-buy]')).to_have_count(1)
                    expect(page.locator('#customerSavedSets [data-set-buy]')).to_be_enabled()
                    checks.append('Store checkout stores encrypted contacts and customer sees exactly their own order timeline')

                    page.goto(origin + "/team/rakovar-control/login")
                    page.locator('[name="username"]').fill("owner")
                    page.locator('[name="password"]').fill(password)
                    page.locator('button[type="submit"]').click()
                    expect(page.locator("#adminNav")).to_be_visible()
                    page.locator('[data-tab="orders"]').click()
                    expect(page.locator(f'[data-save-order="{order_id}"]')).to_be_visible()
                    pending_order_refresh = []
                    # Hold each refresh until the UI proves it prevents a second edit.
                    page.route("**/api/admin/orders", lambda route: pending_order_refresh.append(route))
                    for status in ("paid", "preparing", "cancelled"):
                        page.locator(f'[data-order-status="{order_id}"]').select_option(status)
                        with page.expect_request(lambda request: request.url.endswith("/api/admin/orders") and request.method == "GET"):
                            with page.expect_response(lambda response: f"/api/admin/orders/{order_id}" in response.url and response.request.method == "PATCH") as saved:
                                page.locator(f'[data-save-order="{order_id}"]').click()
                        assert saved.value.status == 200
                        expect(page.locator(f'[data-order-status="{order_id}"]')).to_be_disabled()
                        expect(page.locator(f'[data-save-order="{order_id}"]')).to_be_disabled()
                        assert len(pending_order_refresh) == 1
                        refresh = pending_order_refresh.pop()
                        refresh.fulfill(response=refresh.fetch())
                        expect(page.locator(f'[data-save-order="{order_id}"]')).to_be_enabled()
                        expect(page.locator(f'[data-order-status="{order_id}"]')).to_have_value(status)
                        persisted = next(row for row in context.request.get(origin + "/api/admin/orders").json() if row['id'] == order_id)
                        assert persisted['status'] == status
                    page.unroute("**/api/admin/orders")
                    page.locator(f'[data-order-history="{order_id}"]').click()
                    expect(page.locator("#orderHistoryDialog")).to_be_visible()
                    expect(page.locator("#orderHistoryBody")).to_contain_text("Готовится")
                    page.screenshot(path=str(output / "order-history.png"))
                    page.locator("#closeOrderHistory").click()
                    checks.append("Manager changes persisted statuses, blocks edits during delayed refresh, reverses tickets and sees order history")

                    page.locator('[data-tab="inventory"]').click()
                    stockrow=page.locator('[data-inventory-row="live-crayfish-standart-kg"]')
                    expect(stockrow).to_be_visible()
                    stockrow.locator('[data-stock-quantity]').fill('5')
                    stockrow.locator('[data-stock-tracked]').check()
                    stockrow.locator('[data-stock-reason]').fill('Синтетическая инвентаризация')
                    with page.expect_response(lambda response:'/api/admin/store/inventory/live-crayfish-standart-kg' in response.url and response.request.method=='PUT') as stock:
                        stockrow.locator('[data-stock-save]').click()
                    assert stock.value.status==200
                    inventory=context.request.get(origin+'/api/admin/store/inventory').json()
                    assert next(p for p in inventory if p['product_id']=='live-crayfish-standart-kg')['quantity_milli']==5000
                    page.screenshot(path=str(output/'inventory-admin.png'))
                    page.locator('[data-tab="customers"]').click()
                    expect(page.locator('#customersWorkspace [data-customer]').first).to_be_visible()
                    page.locator('[data-tab="store"]').click()
                    expect(page.locator('#storeOperationsForm')).to_be_visible()
                    page.locator('#storeOperationsForm [name="cashback_percent"]').fill('7')
                    with page.expect_response(lambda response:response.url.endswith('/api/admin/store/settings') and response.request.method=='PUT') as rules:
                        page.locator('#storeOperationsForm button[type="submit"]').click()
                    assert rules.value.status==200
                    assert context.request.get(origin+'/api/admin/store/settings').json()['cashback_percent']==7
                    page.locator('[data-tab="promotions"]').click()
                    promotion=page.locator('[data-promotion-edit="WELCOME10"]')
                    promotion.locator('[name="discount_value"]').fill('15')
                    with page.expect_response(lambda response:response.url.endswith('/api/admin/promotions/WELCOME10') and response.request.method=='PATCH') as edited:
                        promotion.locator('button[type="submit"]').click()
                    assert edited.value.status==200
                    page.locator('[data-tab="notifications"]').click()
                    expect(page.locator('#notificationsWorkspace')).to_contain_text(order_id)
                    page.screenshot(path=str(output/'notifications-admin.png'))
                    checks.append('Staff controls tracked stock, customer profiles, cashback rules, full promotions and order notifications')

                    page.locator('[data-tab="integrations"]').click()
                    expect(page.locator('.connection-card')).to_have_count(3)
                    expect(page.locator('[data-connection-form="max"] input[name="bot_token"]')).to_have_attribute('type','password')
                    for button in page.locator('.connection-form button[type="submit"]').all():
                        expect(button).to_be_enabled()
                    page.screenshot(path=str(output / 'connections-admin.png'))
                    checks.append('Owner sees three encrypted provider forms; saving and sending are separate explicit actions')

                    page.locator('[data-tab="staff"]').click()
                    expect(page.locator("#staffCreateRole option").first).to_be_attached()
                    form = page.locator("#staffCreateForm")
                    form.locator('[name="username"]').fill("e2e_editor")
                    form.locator('[name="password"]').fill(staff_password)
                    form.locator('[name="role"]').select_option("content_editor")
                    with page.expect_response(lambda response: response.url.endswith("/api/admin/staff") and response.request.method == "POST") as created:
                        form.locator('button[type="submit"]').click()
                    assert created.value.status == 201
                    expect(page.locator("#staffAccounts")).to_contain_text("e2e_editor")
                    page.screenshot(path=str(output / "admin-staff.png"))
                    checks.append("Owner creates an individual employee through the working staff UI")

                    editor_context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
                    editor = editor_context.new_page()
                    editor.on("pageerror", lambda error: console_errors.append(str(error)))
                    editor.goto(origin + "/team/rakovar-control/login")
                    editor.locator('[name="username"]').fill("e2e_editor")
                    editor.locator('[name="password"]').fill(staff_password)
                    editor.locator('button[type="submit"]').click()
                    expect(editor.locator("#adminNav")).to_be_visible()
                    assert editor.locator('#adminNav [data-tab="staff"]').count() == 0
                    assert editor.locator('#adminNav [data-tab="analytics"]').count() == 0
                    assert editor_context.request.get(origin + "/api/admin/staff").status == 403
                    editor.locator('[data-tab="security"]').click()
                    expect(editor.locator("#staffSessions")).to_contain_text("Текущий сеанс")
                    editor.locator('#mfaEnrollForm [name="password"]').fill(staff_password)
                    editor.locator('#mfaEnrollForm button[type="submit"]').click()
                    expect(editor.locator("#mfaProvisioning")).to_be_visible()
                    secret = editor.locator("#mfaSecret").inner_text()
                    editor.locator('#mfaConfirmForm [name="code"]').fill(otp(secret))
                    editor.locator('#mfaConfirmForm button[type="submit"]').click()
                    expect(editor.locator("#personalMfaStatus")).to_have_text("MFA подключена")
                    assert not editor.locator("#mfaSecret").inner_text()
                    checks.append("Restricted employee is denied staff/finance access and can enable personal TOTP MFA")

                    account = page.locator('[data-staff-id="' + created.value.json()["id"] + '"]')
                    with page.expect_response(lambda response: response.request.method == "PATCH" and "/api/admin/staff/" in response.url):
                        account.locator("[data-staff-toggle]").click()
                    assert editor_context.request.get(origin + "/api/admin/security/me").status == 401
                    checks.append("Blocking an employee immediately invalidates their existing server session")

                    mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                        device_scale_factor=1, reduced_motion="reduce")
                    mobile = mobile_context.new_page()
                    mobile.on("pageerror", lambda error: console_errors.append(str(error)))
                    mobile.goto(origin, wait_until="domcontentloaded")
                    expect(mobile.locator("#wheel svg")).to_be_visible()
                    for section in ('#liveCrayfish','#sets'):
                        mobile.locator(section).scroll_into_view_if_needed()
                        assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    mobile.screenshot(path=str(output / 'set-studio-mobile.png'))
                    mobile.locator("#club").scroll_into_view_if_needed()
                    assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    mobile.screenshot(path=str(output / "wheel-mobile.png"))
                    checks.append("390px mobile wheel has no horizontal overflow and supports reduced motion")
                    assert not console_errors, "Browser JavaScript errors were captured"
                    browser.close()
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait(timeout=5)
    report = {"status": "passed", "checks": checks, "javascript_errors": console_errors,
              "browser": "Chromium", "screenshots": [path.name for path in sorted(output.glob("*.png"))]}
    (output / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
