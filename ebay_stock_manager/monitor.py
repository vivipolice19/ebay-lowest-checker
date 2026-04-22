import asyncio
import threading
from datetime import datetime
from database import get_active_products, update_product_status, update_last_check
from config import MERCARI_CONCURRENCY, EBAY_CONCURRENCY, MONITOR_INTERVAL_MINUTES
from logger import log_info, log_error, log_warning

class MonitorManager:
    def __init__(self, status_callback=None):
        self._running = False
        self._thread = None
        self._loop = None
        self._status_callback = status_callback
        self._current_tasks = []
        self._stop_event = None

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            log_warning("監視は既に実行中です")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log_info("監視開始")

    def stop(self):
        self._running = False
        if self._stop_event and self._loop:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        for task in self._current_tasks:
            if not task.done():
                self._loop.call_soon_threadsafe(task.cancel)
        log_info("監視停止")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._monitor_cycle())
        except asyncio.CancelledError:
            log_info("監視タスクがキャンセルされました")
        except Exception as e:
            log_error(f"監視ループエラー: {e}")
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            try:
                self._loop.close()
            except Exception:
                pass
            self._running = False

    async def _monitor_cycle(self):
        while self._running:
            try:
                log_info("監視サイクル開始")
                self._update_status("監視サイクル実行中...")

                products = get_active_products()
                if not products:
                    log_info("アクティブ商品なし")
                    self._update_status("アクティブ商品なし - 待機中")
                    await self._wait_interval()
                    continue

                log_info(f"チェック対象: {len(products)}商品")
                self._update_status(f"{len(products)}商品をチェック中...")

                sold_products = []
                sold_lock = asyncio.Lock()
                semaphore = asyncio.Semaphore(MERCARI_CONCURRENCY)

                async def check_with_semaphore(product):
                    if not self._running:
                        return False
                    async with semaphore:
                        try:
                            from scraper import check_mercari_sold
                            is_sold = await check_mercari_sold(product["mercari_url"])
                            update_last_check(product["id"])
                            if is_sold:
                                async with sold_lock:
                                    sold_products.append(product)
                                update_product_status(product["id"], "out_of_stock")
                                log_info(f"売り切れ確認: ID={product['id']} {product['mercari_url']}")
                            return is_sold
                        except Exception as e:
                            log_error(f"商品チェックエラー: ID={product['id']} - {e}")
                            return False

                self._current_tasks = [asyncio.create_task(check_with_semaphore(p)) for p in products]
                await asyncio.gather(*self._current_tasks, return_exceptions=True)
                self._current_tasks = []

                if not self._running:
                    break

                if sold_products:
                    log_info(f"売り切れ商品数: {len(sold_products)} - eBay更新開始")
                    self._update_status(f"{len(sold_products)}商品のeBay在庫を更新中...")

                    ebay_semaphore = asyncio.Semaphore(EBAY_CONCURRENCY)

                    async def update_with_semaphore(product):
                        if not self._running:
                            return False
                        async with ebay_semaphore:
                            try:
                                from ebay_controller import update_ebay_quantity_to_zero
                                success = await update_ebay_quantity_to_zero(product["ebay_url"])
                                if success:
                                    log_info(f"eBay在庫更新成功: ID={product['id']}")
                                else:
                                    log_error(f"eBay在庫更新失敗: ID={product['id']}")
                                return success
                            except Exception as e:
                                log_error(f"eBay更新エラー: ID={product['id']} - {e}")
                                return False

                    self._current_tasks = [asyncio.create_task(update_with_semaphore(p)) for p in sold_products]
                    await asyncio.gather(*self._current_tasks, return_exceptions=True)
                    self._current_tasks = []

                now = datetime.now().strftime("%H:%M:%S")
                next_check = f"{MONITOR_INTERVAL_MINUTES}分後"
                self._update_status(f"最終チェック: {now} / 次回: {next_check}")

                log_info(f"監視サイクル完了 - 次回: {MONITOR_INTERVAL_MINUTES}分後")
                await self._wait_interval()

            except asyncio.CancelledError:
                log_info("監視サイクルがキャンセルされました")
                break
            except Exception as e:
                log_error(f"監視サイクルエラー: {e}")
                self._update_status(f"エラー発生 - 再試行待機中")
                await self._wait_interval()

    async def _wait_interval(self):
        try:
            self._stop_event.clear()
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=MONITOR_INTERVAL_MINUTES * 60
            )
        except asyncio.TimeoutError:
            pass

    def _update_status(self, message):
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass
