import sys
import os
import threading
import json
import subprocess
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify, redirect, url_for
from database import (
    init_database, add_product, delete_product, get_all_products,
    get_product_count, get_active_products, get_alert_products,
    update_ebay_price, update_product_prices, get_products_missing_prices,
    get_exchange_rate, save_setting, get_setting, apply_sedori_listing,
    bootstrap_sedori_webhook_secret,
)
from monitor import MonitorManager
from profit_monitor import ProfitMonitor
from sheets_sync import SheetsSyncManager
from notifier import send_profit_alerts
from logger import log_info, log_error
from ebay_controller import check_ebay_api_status
from sedori_integration import (
    validate_listing_payload,
    verify_bearer_token,
    get_expected_webhook_secret,
    log_validation_failure,
)
from config import (
    MAX_PRODUCTS, WEB_HOST, WEB_PORT,
    TEMPLATES_DIR, STATIC_DIR
)

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR
)
app.secret_key = os.urandom(24)

init_database()
_auto_sedori = bootstrap_sedori_webhook_secret()
if _auto_sedori:
    log_info(
        "セドリ連携: 共有秘密を自動発行しました。"
        "セドリアプリの HTTP ヘッダ Authorization: Bearer に、次の行と同じ値を設定してください。"
    )
    log_info(f"SEDORI_BEARER_TOKEN={_auto_sedori}")
log_info("=== Webアプリケーション初期化 ===")

monitor = None
profit_mon = None
sheets_sync = None

def get_monitor():
    global monitor
    if monitor is None:
        monitor = MonitorManager()
    return monitor

def get_profit_monitor():
    global profit_mon
    if profit_mon is None:
        profit_mon = ProfitMonitor(
            alert_callback=lambda alerts: send_profit_alerts(alerts)
        )
        profit_mon.load_settings()
    return profit_mon

def get_sheets_sync():
    global sheets_sync
    if sheets_sync is None:
        sheets_sync = SheetsSyncManager()
    return sheets_sync


def _auto_start_services():
    import time
    time.sleep(2)

    pm = get_profit_monitor()
    pm.fetch_exchange_rate()

    sheet_id = get_setting("sheet_id", "")
    if sheet_id:
        sync = get_sheets_sync()
        creds_path = get_setting("creds_path", "")
        interval = int(get_setting("sync_interval", "2") or "2")
        sync.set_config(sheet_id, creds_path, interval)
        sync.start_auto_sync()
        log_info("スプレッドシート自動同期を開始しました")

threading.Thread(target=_auto_start_services, daemon=True).start()


@app.route("/")
def index():
    products = get_all_products()
    count = get_product_count()
    mon = get_monitor()
    sync = get_sheets_sync()
    rate_data = get_exchange_rate("USD_JPY")
    sheet_id = get_setting("sheet_id", "")

    sheet_url = ""
    if sheet_id:
        if sheet_id.startswith("http"):
            sheet_url = sheet_id
        else:
            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"

    return render_template(
        "index.html",
        products=products,
        product_count=count,
        max_products=MAX_PRODUCTS,
        monitor_running=mon.is_running,
        sync_running=sync.is_running,
        last_sync=sync.last_sync,
        last_sync_error=sync.last_error,
        exchange_rate=rate_data["rate"] if rate_data else None,
        rate_updated=rate_data["updated_at"] if rate_data else None,
        sheet_url=sheet_url,
        sheet_configured=bool(sheet_id)
    )

@app.route("/profit")
def profit_page():
    products = get_all_products()
    alert_products = get_alert_products()
    pm = get_profit_monitor()
    rate_data = get_exchange_rate("USD_JPY")
    return render_template(
        "profit.html",
        products=products,
        alert_products=alert_products,
        exchange_rate=rate_data["rate"] if rate_data else None,
        rate_updated=rate_data["updated_at"] if rate_data else None,
        profit_running=pm.is_running
    )

@app.route("/settings")
def settings_page():
    sync = get_sheets_sync()

    from sheets_connector import _is_replit_env
    is_replit = _is_replit_env()

    return render_template(
        "settings.html",
        sync_running=sync.is_running,
        last_sync=sync.last_sync,
        last_sync_error=sync.last_error,
        line_token=get_setting("line_token", ""),
        alert_threshold=get_setting("alert_threshold", "10"),
        warning_threshold=get_setting("warning_threshold", "15"),
        auto_stop_threshold=get_setting("auto_stop_threshold", "5"),
        auto_stop_enabled=get_setting("auto_stop_enabled", "true"),
        ebay_fee=get_setting("ebay_fee", "10"),
        shipping_usd=get_setting("shipping_usd", "15"),
        other_expenses=get_setting("other_expenses", "0"),
        sheet_id=get_setting("sheet_id", ""),
        creds_path=get_setting("creds_path", ""),
        sync_interval=get_setting("sync_interval", "2"),
        ebay_client_id=get_setting("ebay_client_id", ""),
        ebay_client_secret=get_setting("ebay_client_secret", ""),
        ebay_oauth_token=get_setting("ebay_oauth_token", ""),
        ebay_runame=EBAY_RUNAME,
        ebay_callback_url=f"{PRODUCTION_URL}/ebay/callback",
        is_replit=is_replit,
        ebay_token_status=check_ebay_api_status(),
        sedori_webhook_configured=bool(get_expected_webhook_secret(get_setting)),
    )

@app.route("/api/products", methods=["GET"])
def api_get_products():
    products = get_all_products()
    return jsonify({"products": products, "count": len(products)})

@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def api_delete_product(product_id):
    success = delete_product(product_id)
    return jsonify({"success": success})

@app.route("/api/admin/reset_ebay_pending", methods=["POST"])
def api_reset_ebay_pending():
    import sqlite3
    from config import DATABASE_PATH
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    try:
        conn.execute("UPDATE products SET ebay_updated=0 WHERE status='active'")
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM products WHERE status='active'").fetchone()[0]
    finally:
        conn.close()
    return jsonify({"success": True, "reset_count": count})

@app.route("/api/monitor/start", methods=["POST"])
def api_start_monitor():
    mon = get_monitor()
    if not mon.is_running:
        mon.start()
    return jsonify({"success": True, "running": True})

@app.route("/api/monitor/stop", methods=["POST"])
def api_stop_monitor():
    mon = get_monitor()
    if mon.is_running:
        mon.stop()
    return jsonify({"success": True, "running": False})

@app.route("/api/monitor/status", methods=["GET"])
def api_monitor_status():
    mon = get_monitor()
    return jsonify({"running": mon.is_running})

@app.route("/api/profit/check", methods=["POST"])
def api_profit_check():
    pm = get_profit_monitor()
    result = pm.check_all_products()
    return jsonify({"success": True, "result": result})

@app.route("/api/profit/start", methods=["POST"])
def api_start_profit_monitor():
    pm = get_profit_monitor()
    if not pm.is_running:
        pm.start()
    return jsonify({"success": True, "running": True})

@app.route("/api/profit/stop", methods=["POST"])
def api_stop_profit_monitor():
    pm = get_profit_monitor()
    if pm.is_running:
        pm.stop()
    return jsonify({"success": True, "running": False})

@app.route("/api/exchange_rate/update", methods=["POST"])
def api_update_exchange_rate():
    pm = get_profit_monitor()
    rate = pm.fetch_exchange_rate()
    if rate:
        return jsonify({"success": True, "rate": rate})
    return jsonify({"success": False, "error": "為替レート取得失敗"}), 500

@app.route("/api/exchange_rate", methods=["GET"])
def api_get_exchange_rate():
    rate_data = get_exchange_rate("USD_JPY")
    if rate_data:
        return jsonify({"success": True, "rate": rate_data["rate"], "updated_at": rate_data["updated_at"]})
    return jsonify({"success": False, "rate": None})

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "リクエストが不正です"}), 400

        for key, value in data.items():
            save_setting(key, str(value))

        pm = get_profit_monitor()
        try:
            pm.set_config(
                ebay_fee_percent=float(data.get("ebay_fee", 10)),
                shipping_usd=float(data.get("shipping_usd", 15)),
                other_expenses=float(data.get("other_expenses", 0)),
                alert_threshold=float(data.get("alert_threshold", 10)),
                warning_threshold=float(data.get("warning_threshold", 15)),
                auto_stop_threshold=float(data.get("auto_stop_threshold", 5)),
                auto_stop_enabled=data.get("auto_stop_enabled", "true") == "true"
            )
        except (ValueError, TypeError):
            pass

        if "sheet_id" in data:
            sync = get_sheets_sync()
            sheet_id = data.get("sheet_id", "")
            creds_path = data.get("creds_path", "")
            interval = int(data.get("sync_interval", "2") or "2")
            sync.set_config(sheet_id, creds_path, interval)

            if sheet_id and not sync.is_running:
                sync.start_auto_sync()

        return jsonify({"success": True})
    except Exception as e:
        log_error(f"設定保存APIエラー: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/sheets/sync", methods=["POST"])
def api_sheets_sync():
    sheet_id = get_setting("sheet_id", "")
    if not sheet_id:
        return jsonify({"success": False, "error": "スプレッドシートURLを設定画面で入力してください"}), 400

    sync = get_sheets_sync()
    if not sync._spreadsheet_id:
        creds_path = get_setting("creds_path", "")
        interval = int(get_setting("sync_interval", "2") or "2")
        sync.set_config(sheet_id, creds_path, interval)

    def do_sync():
        sync.sync_once()

    threading.Thread(target=do_sync, daemon=True).start()
    return jsonify({"success": True, "message": "同期を開始しました"})


def _trigger_sheet_sync_if_configured():
    sheet_id = get_setting("sheet_id", "")
    if not sheet_id:
        return False

    sync = get_sheets_sync()
    if not sync._spreadsheet_id:
        creds_path = get_setting("creds_path", "")
        interval = int(get_setting("sync_interval", "2") or "2")
        sync.set_config(sheet_id, creds_path, interval)

    def do_sync():
        try:
            sync.sync_once()
        except Exception as e:
            log_error(f"Cron同期エラー: {e}")

    threading.Thread(target=do_sync, daemon=True).start()
    return True


@app.route("/api/cron/sync", methods=["GET", "POST"])
def api_cron_sync():
    """
    cron-job.org 用の軽量エンドポイント。
    本文レスポンスを返さず 204 で終了することで
    "output too large" を回避する。
    """
    _trigger_sheet_sync_if_configured()
    return ("", 204)

@app.route("/api/sheets/status", methods=["GET"])
def api_sheets_status():
    sync = get_sheets_sync()
    return jsonify({
        "running": sync.is_running,
        "last_sync": sync.last_sync,
        "last_error": sync.last_error
    })

@app.route("/api/sheets/start", methods=["POST"])
def api_start_sheets_sync():
    sheet_id = get_setting("sheet_id", "")
    if not sheet_id:
        return jsonify({"success": False, "error": "スプレッドシートURLを設定してください"}), 400

    sync = get_sheets_sync()
    if not sync.is_running:
        creds_path = get_setting("creds_path", "")
        interval = int(get_setting("sync_interval", "2") or "2")
        sync.set_config(sheet_id, creds_path, interval)
        sync.start_auto_sync()
    return jsonify({"success": True, "running": True})

@app.route("/api/sheets/stop", methods=["POST"])
def api_stop_sheets_sync():
    sync = get_sheets_sync()
    if sync.is_running:
        sync.stop_auto_sync()
    return jsonify({"success": True, "running": False})

@app.route("/api/alerts", methods=["GET"])
def api_get_alerts():
    alerts = get_alert_products()
    return jsonify({"alerts": alerts})


@app.route("/api/v1/sedori/health", methods=["GET"])
def api_sedori_health():
    configured = bool(get_expected_webhook_secret(get_setting))
    return jsonify(
        {
            "ok": True,
            "service": "ebay_stock_manager",
            "sedori_webhook_secret_configured": configured,
        }
    )


def _schedule_sheets_sync_after_sedori_import():
    sheet_id = get_setting("sheet_id", "")
    if not sheet_id:
        return
    sync = get_sheets_sync()
    if not sync._spreadsheet_id:
        creds_path = get_setting("creds_path", "")
        interval = int(get_setting("sync_interval", "2") or "2")
        sync.set_config(sheet_id, creds_path, interval)

    def do_sync():
        try:
            sync.sync_once()
        except Exception as e:
            log_error(f"セドリ連携後のシート同期エラー: {e}")

    threading.Thread(target=do_sync, daemon=True).start()


@app.route("/api/v1/sedori/listings", methods=["POST"])
def api_sedori_listings():
    """
    セドリアプリからの出品確定を取り込む本番用API。
    Authorization: Bearer <SEDORI_WEBHOOK_SECRET または設定の sedori_webhook_secret>
    Body: { event_id, external_id, mercari_url, ebay_url [, purchase_price, profit_rate, title, listed_at] }
    """
    secret = get_expected_webhook_secret(get_setting)
    if not secret:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "サーバに共有秘密がありません。起動ログの SEDORI_BEARER_TOKEN= を確認するか、環境変数 SEDORI_WEBHOOK_SECRET を設定してください。",
                    "code": "NOT_CONFIGURED",
                }
            ),
            503,
        )

    if not verify_bearer_token(request.headers.get("Authorization", ""), secret):
        return (
            jsonify({"success": False, "error": "認証に失敗しました", "code": "UNAUTHORIZED"}),
            401,
        )

    data = request.get_json(silent=True)
    cleaned, err = validate_listing_payload(data)
    if err:
        log_validation_failure(err)
        return jsonify({"success": False, "error": err, "code": "VALIDATION"}), 400

    result = apply_sedori_listing(cleaned)
    if not result.get("success"):
        code = result.get("code", "ERROR")
        status = 409 if code == "INTEGRITY" else 500 if code == "INTERNAL" else 400
        if code == "LIMIT":
            status = 429
        return (
            jsonify(
                {
                    "success": False,
                    "error": result.get("error", "処理に失敗しました"),
                    "code": code,
                }
            ),
            status,
        )

    res_type = result.get("result")
    if res_type in ("created", "updated"):
        _schedule_sheets_sync_after_sedori_import()

    return jsonify(
        {
            "success": True,
            "result": res_type,
            "product_id": result.get("product_id"),
        }
    )


EBAY_RUNAME = "NORIKO_WATANABE-NORIKOWA-Ssyste-ybzhuimzt"
EBAY_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
])


PRODUCTION_URL = "https://mercari-ebay-sync.replit.app"

def _get_callback_url():
    return f"{PRODUCTION_URL}/ebay/callback"


@app.route("/ebay/connect")
def ebay_connect():
    client_id = get_setting("ebay_client_id", "")
    if not client_id:
        return "<h2>先にClient IDを設定ページで保存してください</h2>", 400

    auth_url = (
        "https://auth.ebay.com/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={EBAY_RUNAME}"
        "&response_type=code"
        f"&scope={urllib.parse.quote(EBAY_SCOPES)}"
    )
    return redirect(auth_url)


@app.route("/ebay/callback")
def ebay_callback():
    code = request.args.get("code", "")
    error = request.args.get("error", "")

    if error or not code:
        desc = request.args.get("error_description", "キャンセルされました")
        return render_template("ebay_callback.html", success=False, message=desc)

    client_id = get_setting("ebay_client_id", "")
    client_secret = get_setting("ebay_client_secret", "")
    if not client_id or not client_secret:
        return render_template("ebay_callback.html", success=False, message="Client IDまたはClient Secretが未設定です")

    import base64
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "20",
                "-X", "POST",
                "-H", f"Authorization: Basic {credentials}",
                "-H", "Content-Type: application/x-www-form-urlencoded",
                "-d", f"grant_type=authorization_code&code={urllib.parse.quote(code)}&redirect_uri={EBAY_RUNAME}",
                "https://api.ebay.com/identity/v1/oauth2/token"
            ],
            capture_output=True, text=True, timeout=25
        )

        data = json.loads(result.stdout)

        if "access_token" in data:
            import time as _time
            save_setting("ebay_oauth_token", data["access_token"])
            expires_in = data.get("expires_in", 7200)
            expires_at = _time.time() + expires_in
            save_setting("ebay_token_expires_at", str(expires_at))
            if "refresh_token" in data:
                save_setting("ebay_refresh_token", data["refresh_token"])
            log_info("eBay User Auth Token取得・保存成功")
            return render_template("ebay_callback.html", success=True, message="eBay連携が完了しました！在庫の自動停止が有効になります。")
        else:
            err = data.get("error_description", data.get("error", "不明なエラー"))
            log_error(f"eBay token exchange失敗: {err}")
            return render_template("ebay_callback.html", success=False, message=f"トークン取得失敗: {err}")

    except Exception as e:
        log_error(f"eBay callback例外: {e}")
        return render_template("ebay_callback.html", success=False, message=f"エラー: {e}")


def start_web_app():
    init_database()
    log_info("=== Webアプリケーション起動 ===")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)

if __name__ == "__main__":
    start_web_app()
