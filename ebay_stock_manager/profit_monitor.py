import threading
import time
import json
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from database import (
    get_all_products, update_product_profit, update_product_status,
    save_exchange_rate, get_exchange_rate
)
from logger import log_info, log_error, log_warning
from config import (
    EXCHANGE_API_URL, EXCHANGE_UPDATE_INTERVAL_HOURS,
    PROFIT_ALERT_THRESHOLD, PROFIT_WARNING_THRESHOLD,
    AUTO_STOP_THRESHOLD, AUTO_STOP_ON_LOSS,
    EBAY_FEE_PERCENT, DEFAULT_SHIPPING_USD, OTHER_EXPENSES
)

class ProfitMonitor:
    def __init__(self, status_callback=None, alert_callback=None):
        self._running = False
        self._thread = None
        self._status_callback = status_callback
        self._alert_callback = alert_callback
        self._exchange_rate = None
        self._last_rate_update = None
        self._check_interval_minutes = 60
        self._ebay_fee_percent = EBAY_FEE_PERCENT
        self._shipping_usd = DEFAULT_SHIPPING_USD
        self._other_expenses = OTHER_EXPENSES
        self._alert_threshold = PROFIT_ALERT_THRESHOLD
        self._warning_threshold = PROFIT_WARNING_THRESHOLD
        self._auto_stop_threshold = AUTO_STOP_THRESHOLD
        self._auto_stop_enabled = AUTO_STOP_ON_LOSS

    @property
    def is_running(self):
        return self._running

    @property
    def exchange_rate(self):
        return self._exchange_rate

    def set_config(self, ebay_fee_percent=None, shipping_usd=None, other_expenses=None,
                   alert_threshold=None, warning_threshold=None, auto_stop_threshold=None,
                   auto_stop_enabled=None, check_interval=None):
        if ebay_fee_percent is not None:
            self._ebay_fee_percent = ebay_fee_percent
        if shipping_usd is not None:
            self._shipping_usd = shipping_usd
        if other_expenses is not None:
            self._other_expenses = other_expenses
        if alert_threshold is not None:
            self._alert_threshold = alert_threshold
        if warning_threshold is not None:
            self._warning_threshold = warning_threshold
        if auto_stop_threshold is not None:
            self._auto_stop_threshold = auto_stop_threshold
        if auto_stop_enabled is not None:
            self._auto_stop_enabled = auto_stop_enabled
        if check_interval is not None:
            self._check_interval_minutes = max(1, check_interval)

    def fetch_exchange_rate(self):
        try:
            req = Request(EXCHANGE_API_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())

            if "rates" in data and "JPY" in data["rates"]:
                rate = data["rates"]["JPY"]
                self._exchange_rate = rate
                self._last_rate_update = datetime.now()
                save_exchange_rate("USD_JPY", rate)
                log_info(f"為替レート取得: 1 USD = {rate} JPY")
                self._update_status(f"為替レート: 1 USD = {rate:.2f} JPY")
                return rate
            else:
                log_error("為替レートデータの形式が不正です")
                return None
        except URLError as e:
            log_error(f"為替レート取得エラー (ネットワーク): {e}")
            return self._load_cached_rate()
        except Exception as e:
            log_error(f"為替レート取得エラー: {e}")
            return self._load_cached_rate()

    def _load_cached_rate(self):
        cached = get_exchange_rate("USD_JPY")
        if cached:
            self._exchange_rate = cached["rate"]
            log_info(f"キャッシュ済み為替レート使用: 1 USD = {cached['rate']} JPY (更新: {cached['updated_at']})")
            return cached["rate"]
        self._exchange_rate = 150.0
        log_warning("為替レート取得不可 - デフォルト値使用: 150 JPY/USD")
        return 150.0

    def _should_update_rate(self):
        if self._exchange_rate is None or self._last_rate_update is None:
            return True
        elapsed = datetime.now() - self._last_rate_update
        return elapsed > timedelta(hours=EXCHANGE_UPDATE_INTERVAL_HOURS)

    def calculate_profit(self, purchase_price_jpy, ebay_price_usd, exchange_rate=None):
        if exchange_rate is None:
            exchange_rate = self._exchange_rate or 150.0

        if purchase_price_jpy <= 0 or ebay_price_usd <= 0:
            return {"profit_jpy": 0, "profit_rate": 0, "revenue_jpy": 0, "expenses_jpy": 0}

        revenue_jpy = ebay_price_usd * exchange_rate
        ebay_fee_jpy = revenue_jpy * (self._ebay_fee_percent / 100)
        shipping_jpy = self._shipping_usd * exchange_rate
        total_expenses = purchase_price_jpy + ebay_fee_jpy + shipping_jpy + self._other_expenses
        profit_jpy = revenue_jpy - total_expenses
        profit_rate = (profit_jpy / purchase_price_jpy) * 100 if purchase_price_jpy > 0 else 0

        return {
            "profit_jpy": round(profit_jpy, 0),
            "profit_rate": round(profit_rate, 1),
            "revenue_jpy": round(revenue_jpy, 0),
            "expenses_jpy": round(total_expenses, 0),
            "ebay_fee_jpy": round(ebay_fee_jpy, 0),
            "shipping_jpy": round(shipping_jpy, 0)
        }

    def determine_alert_status(self, profit_rate):
        if profit_rate < 0:
            return "danger"
        elif profit_rate < self._alert_threshold:
            return "danger"
        elif profit_rate < self._warning_threshold:
            return "warning"
        return "normal"

    def check_all_products(self):
        try:
            if self._should_update_rate():
                self.fetch_exchange_rate()

            if self._exchange_rate is None:
                self.fetch_exchange_rate()

            products = get_all_products()
            alerts = []
            auto_stopped = []

            for product in products:
                try:
                    if product["status"] != "active":
                        continue

                    purchase_price = product.get("purchase_price", 0) or 0
                    ebay_price = product.get("ebay_price_usd", 0) or 0

                    if purchase_price <= 0 or ebay_price <= 0:
                        continue

                    result = self.calculate_profit(purchase_price, ebay_price)
                    alert_status = self.determine_alert_status(result["profit_rate"])

                    update_product_profit(
                        product["id"],
                        ebay_price,
                        result["profit_rate"],
                        alert_status
                    )

                    if alert_status != "normal":
                        alerts.append({
                            "id": product["id"],
                            "mercari_url": product["mercari_url"],
                            "profit_rate": result["profit_rate"],
                            "profit_jpy": result["profit_jpy"],
                            "alert_status": alert_status
                        })

                    if (self._auto_stop_enabled and
                        result["profit_rate"] < self._auto_stop_threshold):
                        update_product_status(product["id"], "out_of_stock")
                        auto_stopped.append(product["id"])
                        log_warning(
                            f"利益率低下による自動停止: ID={product['id']} "
                            f"利益率={result['profit_rate']}%"
                        )
                        self._trigger_ebay_stop(product)

                except Exception as e:
                    log_error(f"利益チェックエラー: ID={product.get('id', '?')} - {e}")
                    continue

            if alerts and self._alert_callback:
                try:
                    self._alert_callback(alerts)
                except Exception:
                    pass

            msg = f"利益チェック完了: {len(products)}商品, アラート{len(alerts)}件"
            if auto_stopped:
                msg += f", 自動停止{len(auto_stopped)}件"
            log_info(msg)
            self._update_status(msg)

            return {"alerts": alerts, "auto_stopped": auto_stopped}

        except Exception as e:
            log_error(f"利益チェックエラー: {e}")
            self._update_status(f"利益チェックエラー: {e}")
            return {"alerts": [], "auto_stopped": []}

    def start(self):
        if self._running:
            log_warning("利益監視は既に実行中です")
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log_info("利益監視開始")

    def stop(self):
        self._running = False
        log_info("利益監視停止")

    def _monitor_loop(self):
        while self._running:
            try:
                self.check_all_products()
            except Exception as e:
                log_error(f"利益監視ループエラー: {e}")

            wait_seconds = self._check_interval_minutes * 60
            elapsed = 0
            while elapsed < wait_seconds and self._running:
                time.sleep(1)
                elapsed += 1

        self._running = False

    def _trigger_ebay_stop(self, product):
        import threading
        import asyncio
        def _run():
            try:
                from ebay_controller import update_ebay_quantity_to_zero
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success = loop.run_until_complete(
                    update_ebay_quantity_to_zero(product["ebay_url"])
                )
                loop.close()
                if success:
                    log_info(f"利益低下によるeBay在庫0更新成功: ID={product['id']}")
                else:
                    log_error(f"利益低下によるeBay在庫0更新失敗: ID={product['id']}")
            except Exception as e:
                log_error(f"eBay自動停止エラー: ID={product['id']} - {e}")
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def load_settings(self):
        from database import get_setting
        try:
            self._ebay_fee_percent = float(get_setting("ebay_fee", str(EBAY_FEE_PERCENT)))
            self._shipping_usd = float(get_setting("shipping_usd", str(DEFAULT_SHIPPING_USD)))
            self._other_expenses = float(get_setting("other_expenses", str(OTHER_EXPENSES)))
            self._alert_threshold = float(get_setting("alert_threshold", str(PROFIT_ALERT_THRESHOLD)))
            self._warning_threshold = float(get_setting("warning_threshold", str(PROFIT_WARNING_THRESHOLD)))
            self._auto_stop_threshold = float(get_setting("auto_stop_threshold", str(AUTO_STOP_THRESHOLD)))
            self._auto_stop_enabled = get_setting("auto_stop_enabled", "true") == "true"
            log_info("利益管理設定をDBから読み込みました")
        except Exception as e:
            log_error(f"設定読み込みエラー: {e}")

    def _update_status(self, message):
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass
