from flask import Flask, jsonify

from checker_service import LowestPriceChecker
from config import APP_HOST, APP_PORT, CHECK_INTERVAL_MINUTES
from storage import get_recent_logs, init_db

app = Flask(__name__)
checker = LowestPriceChecker()


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


if __name__ == "__main__":
    init_db()
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
