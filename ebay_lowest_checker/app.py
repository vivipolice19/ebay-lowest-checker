from flask import Flask, jsonify, render_template, request

from checker_service import LowestPriceChecker
from ebay_client import search_min_prices_by_conditions
from config import APP_HOST, APP_PORT, CHECK_INTERVAL_MINUTES
from sheets_gateway import add_watch_item, list_watch_items
from storage import get_recent_logs, init_db

app = Flask(__name__, template_folder="templates")
checker = LowestPriceChecker()


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/api/check/run", methods=["POST"])
def run_check():
    result = checker.run_once()
    return jsonify({"success": True, "result": result})


@app.route("/api/check/start", methods=["POST"])
def start_check():
    checker.start()
    return jsonify({"success": True, "running": checker.is_running, "interval_minutes": CHECK_INTERVAL_MINUTES})


@app.route("/api/check/stop", methods=["POST"])
def stop_check():
    checker.stop()
    return jsonify({"success": True, "running": checker.is_running})


@app.route("/api/check/status", methods=["GET"])
def check_status():
    return jsonify(
        {
            "running": checker.is_running,
            "last_run": checker.last_run,
            "last_error": checker.last_error,
            "last_results": checker.last_results,
        }
    )


@app.route("/api/logs", methods=["GET"])
def recent_logs():
    return jsonify({"logs": get_recent_logs()})


@app.route("/api/watch/list", methods=["GET"])
def watch_list():
    return jsonify({"items": list_watch_items()})


@app.route("/api/watch/add", methods=["POST"])
def watch_add():
    data = request.get_json() or {}
    product_key = (data.get("product_key") or "").strip()
    search_keyword = (data.get("search_keyword") or "").strip()
    target_url = (data.get("target_url") or "").strip()
    if not product_key or not search_keyword or not target_url:
        return jsonify({"success": False, "error": "product_key, search_keyword, target_url are required"}), 400
    add_watch_item(product_key, search_keyword, target_url)
    return jsonify({"success": True})


@app.route("/api/search/conditions", methods=["GET"])
def search_conditions():
    keyword = (request.args.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"success": False, "error": "keyword is required"}), 400
    report = search_min_prices_by_conditions(keyword)
    return jsonify({"success": True, "keyword": keyword, "conditions": report})


if __name__ == "__main__":
    init_db()
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
