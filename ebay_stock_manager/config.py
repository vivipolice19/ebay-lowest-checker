import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATABASE_PATH = os.path.join(DATABASE_DIR, "products.db")
LOG_PATH = os.path.join(LOGS_DIR, "app.log")

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
