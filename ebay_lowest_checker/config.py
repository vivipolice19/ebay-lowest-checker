import os


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


APP_HOST = os.getenv("LOWEST_CHECKER_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("LOWEST_CHECKER_PORT", "5100"))

CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "360"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "20"))

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")
EBAY_BROWSE_TOKEN = os.getenv("EBAY_BROWSE_TOKEN", "")
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
LINE_NOTIFY_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")

AUTO_REPRICE_ENABLED = _to_bool(os.getenv("AUTO_REPRICE_ENABLED", "false"))
AUTO_REPRICE_DRY_RUN = _to_bool(os.getenv("AUTO_REPRICE_DRY_RUN", "true"))
AUTO_REPRICE_UNDERCUT = float(os.getenv("AUTO_REPRICE_UNDERCUT", "0.01"))

SQLITE_PATH = os.getenv("LOWEST_CHECKER_SQLITE_PATH", "ebay_lowest_checker.db")
