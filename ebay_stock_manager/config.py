import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_env_database_path = os.environ.get("DATABASE_PATH", "").strip()
if _env_database_path:
    DATABASE_PATH = os.path.abspath(_env_database_path)
    DATABASE_DIR = os.path.dirname(DATABASE_PATH) or BASE_DIR
else:
    DATABASE_DIR = os.path.join(BASE_DIR, "database")
    DATABASE_PATH = os.path.join(DATABASE_DIR, "products.db")

_env_log_path = os.environ.get("LOG_PATH", "").strip()
if _env_log_path:
    LOG_PATH = os.path.abspath(_env_log_path)
    LOGS_DIR = os.path.dirname(LOG_PATH) or BASE_DIR
elif _env_database_path:
    LOG_PATH = os.path.join(DATABASE_DIR, "app.log")
    LOGS_DIR = DATABASE_DIR
else:
    LOGS_DIR = os.path.join(BASE_DIR, "logs")
    LOG_PATH = os.path.join(LOGS_DIR, "app.log")

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

MERCARI_CONCURRENCY = 20
EBAY_CONCURRENCY = 5
MONITOR_INTERVAL_MINUTES = 30
MAX_PRODUCTS = 3000

RANDOM_WAIT_MIN = 0.5
RANDOM_WAIT_MAX = 1.5

SOLD_KEYWORDS = ["売り切れ", "SOLD"]

SHEETS_SYNC_INTERVAL_MINUTES = 5

PROFIT_ALERT_THRESHOLD = 10
PROFIT_WARNING_THRESHOLD = 15
AUTO_STOP_THRESHOLD = 5
AUTO_STOP_ON_LOSS = True
EBAY_FEE_PERCENT = 10
DEFAULT_SHIPPING_USD = 15
OTHER_EXPENSES = 0

EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/USD"
EXCHANGE_UPDATE_INTERVAL_HOURS = 24

LINE_NOTIFY_TOKEN = ""
LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"
EMAIL_ALERTS = False
ALERT_EMAIL = ""
SMTP_SERVER = ""
SMTP_PORT = 587
SMTP_USER = ""
SMTP_PASSWORD = ""

WEB_HOST = "0.0.0.0"
WEB_PORT = 5000

os.makedirs(DATABASE_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
