import sqlite3
import threading
import time
from datetime import datetime
from config import DATABASE_PATH
from logger import log_info, log_error

_db_lock = threading.Lock()

def _get_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _execute_with_retry(operation, max_retries=3):
    for attempt in range(max_retries):
        try:
            with _db_lock:
                conn = _get_connection()
                try:
                    result = operation(conn)
                    conn.commit()
                    return result
                finally:
                    conn.close()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
    return None

def _query_with_retry(operation, max_retries=3):
    for attempt in range(max_retries):
        try:
            with _db_lock:
                conn = _get_connection()
                try:
                    result = operation(conn)
                    return result
                finally:
                    conn.close()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
    return None

def init_database():
    try:
        def op(conn):
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mercari_url TEXT NOT NULL,
                    ebay_url TEXT NOT NULL,
                    purchase_price REAL DEFAULT 0,
                    profit_rate REAL DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    last_check DATETIME DEFAULT NULL,
                    ebay_price_usd REAL DEFAULT 0,
                    last_profit_check DATETIME DEFAULT NULL,
                    profit_rate_actual REAL DEFAULT 0,
                    alert_status TEXT DEFAULT 'normal'
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exchange_rates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    currency_pair TEXT NOT NULL,
                    rate REAL NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            return True
        _execute_with_retry(op)
        _migrate_database()
        log_info("データベース初期化完了")
    except Exception as e:
        log_error(f"データベース初期化エラー: {e}")

def _migrate_database():
    try:
        def op(conn):
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(products)")
            columns = [col[1] for col in cursor.fetchall()]
            migrations = {
                "ebay_price_usd": "ALTER TABLE products ADD COLUMN ebay_price_usd REAL DEFAULT 0",
                "last_profit_check": "ALTER TABLE products ADD COLUMN last_profit_check DATETIME DEFAULT NULL",
                "profit_rate_actual": "ALTER TABLE products ADD COLUMN profit_rate_actual REAL DEFAULT 0",
                "alert_status": "ALTER TABLE products ADD COLUMN alert_status TEXT DEFAULT 'normal'",
                "ebay_updated": "ALTER TABLE products ADD COLUMN ebay_updated INTEGER DEFAULT 1",
                "external_id": "ALTER TABLE products ADD COLUMN external_id TEXT",
                "import_title": "ALTER TABLE products ADD COLUMN import_title TEXT",
            }
            for col_name, sql in migrations.items():
                if col_name not in columns:
                    cursor.execute(sql)
                    log_info(f"カラム追加: {col_name}")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS integration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL DEFAULT 'sedori',
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    product_id INTEGER,
                    external_id TEXT,
                    error_message TEXT
                )
            """)
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_external_id "
                "ON products(external_id) WHERE external_id IS NOT NULL AND length(trim(external_id)) > 0"
            )
            return True
        _execute_with_retry(op)
    except Exception as e:
        log_error(f"マイグレーションエラー: {e}")

def add_product(mercari_url, ebay_url, purchase_price, profit_rate):
    try:
        from config import MAX_PRODUCTS
        def op(conn):
            cursor = conn.cursor()
            count = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            if count >= MAX_PRODUCTS:
                log_error(f"商品数上限({MAX_PRODUCTS})に達しています")
                return False
            cursor.execute(
                "INSERT INTO products (mercari_url, ebay_url, purchase_price, profit_rate) VALUES (?, ?, ?, ?)",
                (mercari_url, ebay_url, purchase_price, profit_rate)
            )
            return True
        result = _execute_with_retry(op)
        if result:
            log_info(f"商品追加: {mercari_url}")
        return result if result else False
    except Exception as e:
        log_error(f"商品追加エラー: {e}")
        return False

def delete_product(product_id):
    try:
        def op(conn):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
            return True
        _execute_with_retry(op)
        log_info(f"商品削除: ID={product_id}")
        return True
    except Exception as e:
        log_error(f"商品削除エラー: {e}")
        return False

def get_all_products():
    try:
        def op(conn):
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM products ORDER BY id").fetchall()
            return [dict(row) for row in rows]
        return _query_with_retry(op) or []
    except Exception as e:
        log_error(f"商品取得エラー: {e}")
        return []

def get_active_products():
    try:
        def op(conn):
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM products WHERE status = 'active' ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]
        return _query_with_retry(op) or []
    except Exception as e:
        log_error(f"アクティブ商品取得エラー: {e}")
        return []

def update_product_status(product_id, status):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        def op(conn):
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE products SET status = ?, last_check = ? WHERE id = ?",
                (status, now, product_id)
            )
            return True
        _execute_with_retry(op)
        log_info(f"商品ステータス更新: ID={product_id}, status={status}")
        return True
    except Exception as e:
        log_error(f"ステータス更新エラー: {e}")
        return False

def update_last_check(product_id):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        def op(conn):
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE products SET last_check = ? WHERE id = ?",
                (now, product_id)
            )
            return True
        _execute_with_retry(op)
        return True
    except Exception as e:
        log_error(f"最終チェック更新エラー: {e}")
        return False

def get_product_count():
    try:
        def op(conn):
            cursor = conn.cursor()
            count = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            return count
        return _query_with_retry(op) or 0
    except Exception as e:
        log_error(f"商品数取得エラー: {e}")
        return 0

def update_product_profit(product_id, ebay_price_usd, profit_rate_actual, alert_status):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        def op(conn):
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE products SET ebay_price_usd = ?, profit_rate_actual = ?,
                   alert_status = ?, last_profit_check = ? WHERE id = ?""",
                (ebay_price_usd, profit_rate_actual, alert_status, now, product_id)
            )
            return True
        _execute_with_retry(op)
        return True
    except Exception as e:
        log_error(f"利益情報更新エラー: {e}")
        return False

def update_ebay_price(product_id, ebay_price_usd):
    try:
        def op(conn):
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE products SET ebay_price_usd = ? WHERE id = ?",
                (ebay_price_usd, product_id)
            )
            return True
        _execute_with_retry(op)
        return True
    except Exception as e:
        log_error(f"eBay価格更新エラー: {e}")
        return False

def update_product_prices(product_id, purchase_price=None, ebay_price_usd=None):
    try:
        def op(conn):
            cursor = conn.cursor()
            updates = []
            params = []
            if purchase_price is not None:
                updates.append("purchase_price = ?")
                params.append(purchase_price)
            if ebay_price_usd is not None:
                updates.append("ebay_price_usd = ?")
                params.append(ebay_price_usd)
            if not updates:
                return True
            params.append(product_id)
            cursor.execute(
                f"UPDATE products SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            return True
        _execute_with_retry(op)
        return True
    except Exception as e:
        log_error(f"価格更新エラー: {e}")
        return False


def get_products_missing_prices():
    try:
        def op(conn):
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM products WHERE (purchase_price = 0 OR purchase_price IS NULL OR ebay_price_usd = 0 OR ebay_price_usd IS NULL) ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]
        return _query_with_retry(op) or []
    except Exception as e:
        log_error(f"価格未取得商品取得エラー: {e}")
        return []


def get_alert_products():
    try:
        def op(conn):
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM products WHERE alert_status != 'normal' AND status = 'active' ORDER BY profit_rate_actual ASC"
            ).fetchall()
            return [dict(row) for row in rows]
        return _query_with_retry(op) or []
    except Exception as e:
        log_error(f"アラート商品取得エラー: {e}")
        return []

def save_exchange_rate(currency_pair, rate):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        def op(conn):
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO exchange_rates (id, currency_pair, rate, updated_at) VALUES ((SELECT id FROM exchange_rates WHERE currency_pair = ?), ?, ?, ?)",
                (currency_pair, currency_pair, rate, now)
            )
            return True
        _execute_with_retry(op)
        return True
    except Exception as e:
        log_error(f"為替レート保存エラー: {e}")
        return False

def get_exchange_rate(currency_pair="USD_JPY"):
    try:
        def op(conn):
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT rate, updated_at FROM exchange_rates WHERE currency_pair = ? ORDER BY updated_at DESC LIMIT 1",
                (currency_pair,)
            ).fetchone()
            if row:
                return {"rate": row[0], "updated_at": row[1]}
            return None
        return _query_with_retry(op)
    except Exception as e:
        log_error(f"為替レート取得エラー: {e}")
        return None

def save_setting(key, value):
    try:
        def op(conn):
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
            return True
        _execute_with_retry(op)
        return True
    except Exception as e:
        log_error(f"設定保存エラー: {e}")
        return False

def get_setting(key, default=None):
    try:
        def op(conn):
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if row:
                return row[0]
            return default
        return _query_with_retry(op)
    except Exception as e:
        log_error(f"設定取得エラー: {e}")
        return default


def apply_sedori_listing(payload):
    """
    セドリアプリからの出品確定を冪等に取り込む。
    payload は sedori_integration.validate_listing_payload 済みの dict。

    Returns:
      {"success": True, "result": "created"|"updated"|"duplicate_event", "product_id": int|None}
      {"success": False, "error": str, "code": "LIMIT"|"INTEGRITY"|"INTERNAL"}
    """
    from config import MAX_PRODUCTS

    event_id = payload["event_id"]
    external_id = payload["external_id"]
    mercari_url = payload["mercari_url"]
    ebay_url = payload["ebay_url"]
    purchase_price = payload["purchase_price"]
    profit_rate = payload["profit_rate"]
    title = payload.get("title")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def op(conn):
        cursor = conn.cursor()
        cursor.execute(
            "SELECT product_id FROM integration_events WHERE event_id = ?",
            (event_id,),
        )
        dup = cursor.fetchone()
        if dup:
            return {"success": True, "result": "duplicate_event", "product_id": dup[0]}

        cursor.execute(
            "SELECT id FROM products WHERE external_id = ?",
            (external_id,),
        )
        prow = cursor.fetchone()
        if prow:
            pid = prow[0]
            if title is not None:
                cursor.execute(
                    """UPDATE products SET mercari_url = ?, ebay_url = ?, purchase_price = ?,
                       profit_rate = ?, import_title = ? WHERE id = ?""",
                    (mercari_url, ebay_url, purchase_price, profit_rate, title, pid),
                )
            else:
                cursor.execute(
                    """UPDATE products SET mercari_url = ?, ebay_url = ?, purchase_price = ?,
                       profit_rate = ? WHERE id = ?""",
                    (mercari_url, ebay_url, purchase_price, profit_rate, pid),
                )
            cursor.execute(
                """INSERT INTO integration_events
                   (event_id, source, created_at, status, product_id, external_id, error_message)
                   VALUES (?, 'sedori', ?, 'applied', ?, ?, NULL)""",
                (event_id, now, pid, external_id),
            )
            log_info(f"セドリ連携: 商品更新 external_id={external_id} product_id={pid}")
            return {"success": True, "result": "updated", "product_id": pid}

        count = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count >= MAX_PRODUCTS:
            log_error(f"セドリ連携: 商品数上限のため拒否 external_id={external_id}")
            return {
                "success": False,
                "error": f"商品数上限({MAX_PRODUCTS})に達しています",
                "code": "LIMIT",
            }

        cursor.execute(
            """INSERT INTO products
               (mercari_url, ebay_url, purchase_price, profit_rate, status, external_id, import_title)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (
                mercari_url,
                ebay_url,
                purchase_price,
                profit_rate,
                external_id,
                title,
            ),
        )
        pid = cursor.lastrowid
        cursor.execute(
            """INSERT INTO integration_events
               (event_id, source, created_at, status, product_id, external_id, error_message)
               VALUES (?, 'sedori', ?, 'applied', ?, ?, NULL)""",
            (event_id, now, pid, external_id),
        )
        log_info(f"セドリ連携: 商品新規 external_id={external_id} product_id={pid}")
        return {"success": True, "result": "created", "product_id": pid}

    try:
        return _execute_with_retry(op)
    except sqlite3.IntegrityError as e:
        log_error(f"セドリ連携: 一意制約違反 {e}")
        return {
            "success": False,
            "error": "external_id または event_id が競合しました。同一リクエストの再送か、IDの重複を確認してください。",
            "code": "INTEGRITY",
        }
    except Exception as e:
        log_error(f"セドリ連携: 内部エラー {e}")
        return {"success": False, "error": "内部エラーが発生しました", "code": "INTERNAL"}
