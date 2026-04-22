import threading
import time
import gspread
from datetime import datetime
from sheets_connector import get_sheets_client, open_spreadsheet
from database import (
    add_product, get_all_products, get_product_count,
    update_product_prices, update_product_status, update_last_check, get_exchange_rate,
    save_setting, get_setting
)
from logger import log_info, log_error, log_warning
from config import MAX_PRODUCTS

HEADER_ROW = ["仕入先URL", "eBay URL", "仕入値(円)", "売値(USD)", "利益率(%)", "状態", "アラート", "最終チェック"]


class SheetsSyncManager:
    def __init__(self, status_callback=None):
        self._running = False
        self._syncing = False
        self._sync_lock = threading.Lock()
        self._thread = None
        self._spreadsheet_id = ""
        self._creds_path = ""
        self._sync_interval_minutes = 2
        self._status_callback = status_callback
        self._last_sync = None
        self._last_error = None

    @property
    def is_running(self):
        return self._running

    @property
    def last_sync(self):
        return self._last_sync

    @property
    def last_error(self):
        return self._last_error

    def set_config(self, spreadsheet_id, creds_path="", sync_interval_minutes=2):
        self._spreadsheet_id = spreadsheet_id.strip()
        self._creds_path = creds_path.strip() if creds_path else ""
        self._sync_interval_minutes = max(1, sync_interval_minutes)

    def sync_once(self):
        if not self._spreadsheet_id:
            self._last_error = "スプレッドシートIDが未設定です"
            self._update_status(self._last_error)
            return False

        if not self._sync_lock.acquire(blocking=False):
            log_warning("同期は既に実行中です、スキップします")
            return False

        self._syncing = True
        try:
            return self._do_sync()
        finally:
            self._syncing = False
            self._sync_lock.release()

    def _do_sync(self):
        client = get_sheets_client(self._creds_path if self._creds_path else None)
        if not client:
            self._last_error = "Google Sheets認証に失敗しました"
            self._update_status(self._last_error)
            return False

        try:
            spreadsheet = open_spreadsheet(client, self._spreadsheet_id)
            if not spreadsheet:
                self._last_error = "スプレッドシートを開けません"
                self._update_status(self._last_error)
                return False

            worksheet = spreadsheet.sheet1
            log_info(f"スプレッドシート接続: {spreadsheet.title}")

            all_values = worksheet.get_all_values()

            if not all_values:
                worksheet.update(values=[HEADER_ROW], range_name='A1:H1')
                self._format_header(worksheet)
                log_info("ヘッダー行を作成しました")
                self._last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._last_error = None
                self._update_status("ヘッダー作成完了")
                return True

            has_header = False
            is_old_layout = False
            if all_values and len(all_values) > 0:
                first_cell = all_values[0][0].strip().lower() if all_values[0] else ""
                if first_cell in ["mercari url", "mercari_url", "url", "mercari", "仕入先url", "仕入先 url", "仕入先", "source url"]:
                    has_header = True
                    if len(all_values[0]) >= 3:
                        third_col = all_values[0][2].strip() if all_values[0][2] else ""
                        if "目標" in third_col or "利益率" in third_col:
                            is_old_layout = True

            if is_old_layout:
                log_info("旧レイアウト検出: 新しいヘッダーに更新します")
                worksheet.update(values=[HEADER_ROW], range_name='A1:H1')
                self._format_header(worksheet)
                data_rows = all_values[1:]
                if data_rows:
                    for i, row in enumerate(data_rows):
                        if len(row) >= 2 and row[0].strip().startswith("http"):
                            clear_range = f"C{i+2}:H{i+2}"
                            worksheet.update(values=[["", "", "", "", "", ""]], range_name=clear_range)
                all_values = worksheet.get_all_values()
                log_info("旧レイアウトをリセットしました（URLは保持）")

            if not has_header:
                worksheet.insert_row(HEADER_ROW, 1)
                self._format_header(worksheet)
                all_values = worksheet.get_all_values()
                has_header = True
                log_info("ヘッダー行を追加しました")

            start_row = 1 if has_header else 0

            existing_products = get_all_products()
            existing_mercari_urls = {p["mercari_url"].strip(): p for p in existing_products}

            added_count = 0

            for row_idx in range(start_row, len(all_values)):
                row = all_values[row_idx]
                if len(row) < 2:
                    continue

                mercari_url = row[0].strip()
                ebay_url = row[1].strip()

                if not mercari_url or not ebay_url:
                    continue

                if not (mercari_url.startswith("http") and ebay_url.startswith("http")):
                    continue

                if mercari_url not in existing_mercari_urls:
                    current_count = get_product_count()
                    if current_count >= MAX_PRODUCTS:
                        log_warning(f"商品数上限({MAX_PRODUCTS})のためスキップ: {mercari_url}")
                        continue
                    success = add_product(mercari_url, ebay_url, 0, 0)
                    if success:
                        added_count += 1
                        log_info(f"スプレッドシートから追加: {mercari_url}")

            if added_count > 0:
                existing_products = get_all_products()
                existing_mercari_urls = {p["mercari_url"].strip(): p for p in existing_products}

            self._scrape_and_check_all(existing_products)

            existing_products = get_all_products()
            existing_mercari_urls = {p["mercari_url"].strip(): p for p in existing_products}

            batch_updates = []
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for row_idx in range(start_row, len(all_values)):
                row = all_values[row_idx]
                if len(row) < 1:
                    continue

                mercari_url = row[0].strip()
                if not mercari_url:
                    continue

                product = existing_mercari_urls.get(mercari_url)
                if not product:
                    continue

                sheet_row = row_idx + 1

                purchase_price = product.get("purchase_price", 0) or 0
                ebay_price_usd = product.get("ebay_price_usd", 0) or 0

                status_display = product["status"]
                if status_display == "active":
                    status_display = "監視中"
                elif status_display == "out_of_stock":
                    status_display = "売り切れ"
                elif status_display == "trading":
                    status_display = "取引中"

                from database import get_setting
                rate_data = get_exchange_rate()
                exchange_rate = rate_data["rate"] if rate_data and isinstance(rate_data, dict) else 150.0

                # E列: ユーザー入力の利益率を読み取る
                user_profit_rate_str = ""
                if len(row) > 4:
                    user_profit_rate_str = row[4].strip()

                # 利益率を計算（仕入値と売値の両方が揃っている場合）
                calculated_profit_rate = None
                if purchase_price and purchase_price > 0 and ebay_price_usd and ebay_price_usd > 0:
                    ebay_price_jpy = ebay_price_usd * exchange_rate
                    profit_jpy = ebay_price_jpy - purchase_price
                    calculated_profit_rate = (profit_jpy / purchase_price) * 100

                # E列に書き込む利益率: ユーザー入力があればそれを使い、なければ自動計算値
                if user_profit_rate_str:
                    new_e = user_profit_rate_str
                    try:
                        profit_rate_value = float(user_profit_rate_str.replace('%', ''))
                    except (ValueError, TypeError):
                        profit_rate_value = calculated_profit_rate
                elif calculated_profit_rate is not None:
                    new_e = f"{calculated_profit_rate:.1f}%"
                    profit_rate_value = calculated_profit_rate
                else:
                    new_e = ""
                    profit_rate_value = None

                alert_display = "正常"

                if status_display in ("売り切れ", "取引中"):
                    alert_display = "要eBay停止"
                elif profit_rate_value is not None:
                    try:
                        danger_threshold = float(get_setting("alert_threshold", "10") or "10")
                        warning_threshold = float(get_setting("warning_threshold", "15") or "15")
                        if profit_rate_value <= danger_threshold:
                            alert_display = "危険"
                        elif profit_rate_value <= warning_threshold:
                            alert_display = "警告"
                    except (ValueError, TypeError):
                        pass

                last_check = product.get("last_check", "") or now_str

                new_c = f"{purchase_price:,.0f}" if purchase_price > 0 else ""
                new_d = f"{ebay_price_usd:.2f}" if ebay_price_usd > 0 else ""
                new_f = status_display
                new_g = alert_display
                new_h = last_check

                current_c = row[2].strip() if len(row) > 2 else ""
                current_d = row[3].strip() if len(row) > 3 else ""
                current_e = row[4].strip() if len(row) > 4 else ""
                current_f = row[5].strip() if len(row) > 5 else ""
                current_g = row[6].strip() if len(row) > 6 else ""
                current_h = row[7].strip() if len(row) > 7 else ""

                needs_update = (
                    current_c != new_c or current_d != new_d or
                    current_f != new_f or current_g != new_g or
                    current_h != new_h
                )
                # E列: ユーザーが手動入力した場合は上書きしない。自動計算値が変わった場合のみ更新
                e_needs_update = (not user_profit_rate_str) and (current_e != new_e)

                if needs_update or e_needs_update:
                    batch_updates.append({
                        "range": f"C{sheet_row}:E{sheet_row}",
                        "values": [[new_c, new_d, new_e if e_needs_update or not current_e else current_e]]
                    })
                    batch_updates.append({
                        "range": f"F{sheet_row}:H{sheet_row}",
                        "values": [[new_f, new_g, new_h]]
                    })

            if batch_updates:
                for i in range(0, len(batch_updates), 100):
                    chunk = batch_updates[i:i+100]
                    worksheet.batch_update(chunk, value_input_option="RAW")
                log_info(f"スプレッドシート更新: {len(batch_updates)//2}行")

            self._apply_conditional_formatting(worksheet, start_row, len(all_values))

            updated_rows = len(batch_updates) // 2
            msg = f"同期完了: 追加{added_count}件, 更新{updated_rows}行"
            log_info(msg)
            self._last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_error = None
            self._update_status(msg)
            return True

        except gspread.exceptions.APIError as e:
            error_code = getattr(e, 'response', None)
            status_code = error_code.status_code if error_code else 0
            if status_code in (401, 403):
                from sheets_connector import invalidate_token_cache
                invalidate_token_cache()
                log_warning(f"認証エラー (トークン更新予定): {e}")
            self._last_error = str(e)
            log_error(f"スプレッドシート同期エラー: {e}")
            self._update_status(f"同期エラー: {e}")
            return False
        except Exception as e:
            self._last_error = str(e)
            log_error(f"スプレッドシート同期エラー: {e}")
            self._update_status(f"同期エラー: {e}")
            return False

    def _scrape_and_check_all(self, products):
        try:
            from price_scraper import scrape_source_full
            from ebay_controller import get_ebay_item_price

            for product in products:
                try:
                    mercari_url = product.get("mercari_url", "")
                    ebay_url = product.get("ebay_url", "")
                    product_id = product["id"]
                    current_status = product.get("status", "active")
                    ebay_updated = product.get("ebay_updated", 1)

                    mercari_price = None
                    is_sold = None
                    mercari_status_raw = ""

                    if mercari_url:
                        mercari_result = scrape_source_full(mercari_url)
                        mercari_price = mercari_result["price"]
                        is_sold = mercari_result["sold"]
                        mercari_status_raw = mercari_result.get("status_raw", "")

                    ebay_price = None
                    if ebay_url:
                        ebay_price = get_ebay_item_price(ebay_url)

                    if mercari_price or ebay_price:
                        update_product_prices(
                            product_id,
                            purchase_price=mercari_price,
                            ebay_price_usd=ebay_price
                        )

                    if is_sold is True:
                        new_status = "trading" if mercari_status_raw == "trading" else "out_of_stock"
                        if current_status not in ("out_of_stock", "trading"):
                            update_product_status(product_id, new_status)
                            self._mark_ebay_pending(product_id)
                            log_info(f"★売り切れ検出★ ID={product_id} status={new_status} {mercari_url}")
                            self._try_update_ebay_inventory(product, product_id)
                        elif current_status != new_status:
                            update_product_status(product_id, new_status)
                        elif ebay_updated == 0:
                            self._try_update_ebay_inventory(product, product_id)
                    elif is_sold is False:
                        if current_status != "active":
                            update_product_status(product_id, "active")
                            log_info(f"再販売検出: ID={product_id} {mercari_url} → eBay在庫を1に復元試行")
                            self._mark_ebay_pending(product_id)
                            ebay_restore_ok = self._try_update_ebay_inventory(product, product_id, quantity=1)
                            if ebay_restore_ok:
                                log_info(f"★eBay在庫1復元成功★ ID={product_id} {ebay_url}")
                        elif ebay_updated == 0:
                            ebay_restore_ok = self._try_update_ebay_inventory(product, product_id, quantity=1)
                            if ebay_restore_ok:
                                log_info(f"★eBay在庫1確認更新成功★ ID={product_id} {ebay_url}")

                    update_last_check(product_id)

                except Exception as e:
                    log_error(f"商品チェックエラー ID={product['id']}: {e}")

            log_info(f"全商品チェック完了: {len(products)}件")
        except Exception as e:
            log_error(f"商品一括チェックエラー: {e}")

    def _try_update_ebay_inventory(self, product, product_id, quantity=0):
        try:
            from ebay_controller import update_ebay_inventory_api
            ebay_url = product.get("ebay_url", "")
            if not ebay_url:
                return False

            success = update_ebay_inventory_api(ebay_url, quantity=quantity)
            if success:
                self._mark_ebay_updated(product_id)
                action = "在庫0(停止)" if quantity == 0 else f"在庫{quantity}(復元)"
                log_info(f"★eBay{action}更新成功★ ID={product_id} {ebay_url}")
                return True
            else:
                log_warning(f"eBay在庫更新失敗（次回再試行）: ID={product_id} {ebay_url}")
                return False
        except Exception as e:
            log_warning(f"eBay在庫更新エラー（次回再試行）: ID={product_id} - {e}")
            return False

    def _mark_ebay_pending(self, product_id):
        try:
            from database import _execute_with_retry
            def op(conn):
                conn.execute("UPDATE products SET ebay_updated = 0 WHERE id = ?", (product_id,))
                return True
            _execute_with_retry(op)
        except Exception:
            pass

    def _mark_ebay_updated(self, product_id):
        try:
            from database import _execute_with_retry
            def op(conn):
                conn.execute("UPDATE products SET ebay_updated = 1 WHERE id = ?", (product_id,))
                return True
            _execute_with_retry(op)
        except Exception:
            pass

    def _format_header(self, worksheet):
        try:
            worksheet.format('A1:H1', {
                "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.4},
                "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True}
            })
        except Exception:
            pass

    def _apply_conditional_formatting(self, worksheet, start_row, total_rows):
        try:
            if total_rows <= start_row:
                return

            requests = [
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": worksheet.id,
                                "startRowIndex": start_row,
                                "endRowIndex": total_rows,
                                "startColumnIndex": 6,
                                "endColumnIndex": 7
                            }],
                            "booleanRule": {
                                "condition": {
                                    "type": "TEXT_EQ",
                                    "values": [{"userEnteredValue": "要eBay停止"}]
                                },
                                "format": {
                                    "backgroundColor": {"red": 0.96, "green": 0.8, "blue": 0.8},
                                    "textFormat": {"foregroundColor": {"red": 0.8, "green": 0, "blue": 0}, "bold": True}
                                }
                            }
                        },
                        "index": 0
                    }
                },
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": worksheet.id,
                                "startRowIndex": start_row,
                                "endRowIndex": total_rows,
                                "startColumnIndex": 6,
                                "endColumnIndex": 7
                            }],
                            "booleanRule": {
                                "condition": {
                                    "type": "TEXT_EQ",
                                    "values": [{"userEnteredValue": "危険"}]
                                },
                                "format": {
                                    "backgroundColor": {"red": 0.96, "green": 0.8, "blue": 0.8},
                                    "textFormat": {"foregroundColor": {"red": 0.8, "green": 0, "blue": 0}, "bold": True}
                                }
                            }
                        },
                        "index": 1
                    }
                },
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": worksheet.id,
                                "startRowIndex": start_row,
                                "endRowIndex": total_rows,
                                "startColumnIndex": 6,
                                "endColumnIndex": 7
                            }],
                            "booleanRule": {
                                "condition": {
                                    "type": "TEXT_EQ",
                                    "values": [{"userEnteredValue": "警告"}]
                                },
                                "format": {
                                    "backgroundColor": {"red": 1, "green": 0.95, "blue": 0.8},
                                    "textFormat": {"foregroundColor": {"red": 0.8, "green": 0.5, "blue": 0}, "bold": True}
                                }
                            }
                        },
                        "index": 2
                    }
                },
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": worksheet.id,
                                "startRowIndex": start_row,
                                "endRowIndex": total_rows,
                                "startColumnIndex": 5,
                                "endColumnIndex": 6
                            }],
                            "booleanRule": {
                                "condition": {
                                    "type": "TEXT_EQ",
                                    "values": [{"userEnteredValue": "売り切れ"}]
                                },
                                "format": {
                                    "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                                    "textFormat": {"foregroundColor": {"red": 0.5, "green": 0.5, "blue": 0.5}}
                                }
                            }
                        },
                        "index": 3
                    }
                }
            ]

            worksheet.spreadsheet.batch_update({"requests": requests})

        except Exception as e:
            log_warning(f"条件付き書式設定エラー (無視): {e}")

    def start_auto_sync(self):
        if self._running:
            log_warning("自動同期は既に実行中です")
            return
        if self._thread and self._thread.is_alive():
            log_warning("前回の同期スレッドがまだ実行中です")
            return
        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        log_info(f"自動同期開始 (間隔: {self._sync_interval_minutes}分)")
        self._update_status(f"自動同期実行中 (間隔: {self._sync_interval_minutes}分)")

    def stop_auto_sync(self):
        self._running = False
        log_info("自動同期停止")
        self._update_status("自動同期停止")

    def _sync_loop(self):
        while self._running:
            try:
                self.sync_once()
            except Exception as e:
                log_error(f"自動同期ループエラー: {e}")
                self._update_status(f"同期エラー - 再試行待機中")

            wait_seconds = self._sync_interval_minutes * 60
            elapsed = 0
            while elapsed < wait_seconds and self._running:
                time.sleep(1)
                elapsed += 1

        self._running = False

    def _update_status(self, message):
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass
