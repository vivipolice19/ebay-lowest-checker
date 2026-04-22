import threading
import time
from datetime import datetime
from typing import Dict, List

from config import (
    AUTO_REPRICE_DRY_RUN,
    AUTO_REPRICE_ENABLED,
    AUTO_REPRICE_UNDERCUT,
    CHECK_INTERVAL_MINUTES,
)
from ebay_client import revise_own_listing_price, search_min_price
from notifier import send_alert
from sheets_gateway import load_watch_items
from storage import add_check_log, add_price_action


class LowestPriceChecker:
    def __init__(self):
        self._running = False
        self._thread = None
        self._last_run = None
        self._last_error = None
        self._last_results: List[Dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_run(self):
        return self._last_run

    @property
    def last_error(self):
        return self._last_error

    @property
    def last_results(self) -> List[Dict]:
        return self._last_results

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def run_once(self) -> Dict:
        self._last_error = None
        results: List[Dict] = []
        items = [item for item in load_watch_items() if item["active"]]

        for item in items:
            result = self._check_item(item)
            results.append(result)

        self._last_run = datetime.utcnow().isoformat()
        self._last_results = results
        return {"checked": len(results), "results": results}

    def _loop(self):
        while self._running:
            try:
                self.run_once()
            except Exception as exc:
                self._last_error = str(exc)
            sleep_seconds = CHECK_INTERVAL_MINUTES * 60
            waited = 0
            while self._running and waited < sleep_seconds:
                time.sleep(1)
                waited += 1

    def _check_item(self, item: Dict) -> Dict:
        product_key = item["product_key"]
        condition_name = item["condition"]
        target_url = item["target_url"]
        target_price = float(item["target_price"] or 0.0)
        floor_price = float(item["floor_price"] or 0.0)
        cheapest = search_min_price(item["search_keyword"], condition_name)

        if not cheapest:
            add_check_log(
                product_key=product_key,
                condition_name=condition_name,
                target_url=target_url,
                target_price=target_price,
                min_price=None,
                min_url="",
                status="no_result",
                note="No listing found",
            )
            return {"product_key": product_key, "status": "no_result"}

        min_price = float(cheapest["price"])
        min_url = cheapest["url"]
        status = "ok"
        note = ""

        if target_price > 0 and min_price < target_price:
            status = "undercut"
            note = f"Competitor {min_price:.2f} < own {target_price:.2f}"
            if item["alert_enabled"]:
                send_alert(
                    f"[UNDERCUT] {product_key} ({condition_name})\n"
                    f"own={target_price:.2f} / min={min_price:.2f}\n{min_url}"
                )

            if AUTO_REPRICE_ENABLED and item["auto_reprice"]:
                proposed = max(min_price - AUTO_REPRICE_UNDERCUT, floor_price)
                action = revise_own_listing_price(target_url, proposed)
                add_price_action(
                    product_key=product_key,
                    old_price=target_price,
                    new_price=proposed,
                    floor_price=floor_price,
                    dry_run=AUTO_REPRICE_DRY_RUN,
                    success=bool(action.get("success")),
                    detail=action.get("message", ""),
                )

        add_check_log(
            product_key=product_key,
            condition_name=condition_name,
            target_url=target_url,
            target_price=target_price,
            min_price=min_price,
            min_url=min_url,
            status=status,
            note=note,
        )
        return {
            "product_key": product_key,
            "condition": condition_name,
            "target_price": target_price,
            "min_price": min_price,
            "min_url": min_url,
            "status": status,
        }
