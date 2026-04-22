import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
import os
from database import (
    init_database, add_product, delete_product,
    get_all_products, get_product_count
)
from monitor import MonitorManager
from sheets_sync import SheetsSyncManager
from logger import log_info, log_error
from config import MAX_PRODUCTS

class StockManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mercari → eBay 在庫同期ツール")
        self.root.geometry("1100x750")
        self.root.minsize(900, 650)

        init_database()

        self.monitor = MonitorManager(status_callback=self._on_status_update)
        self.sheets_sync = SheetsSyncManager(status_callback=self._on_sheets_status_update)

        self._build_ui()
        self._refresh_table()

        log_info("アプリケーション起動")

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        main_tab = ttk.Frame(notebook, padding=10)
        notebook.add(main_tab, text="商品管理")

        sheets_tab = ttk.Frame(notebook, padding=10)
        notebook.add(sheets_tab, text="スプレッドシート連携")

        self._build_main_tab(main_tab)
        self._build_sheets_tab(sheets_tab)

    def _build_main_tab(self, parent):
        title_label = ttk.Label(
            parent,
            text="Mercari → eBay 在庫同期ツール",
            font=("Arial", 16, "bold")
        )
        title_label.pack(pady=(0, 10))

        input_frame = ttk.LabelFrame(parent, text="商品登録", padding=10)
        input_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(input_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Mercari URL:", width=14).pack(side=tk.LEFT)
        self.mercari_url_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.mercari_url_var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        row2 = ttk.Frame(input_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="eBay URL:", width=14).pack(side=tk.LEFT)
        self.ebay_url_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.ebay_url_var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        row3 = ttk.Frame(input_frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="仕入れ価格:", width=14).pack(side=tk.LEFT)
        self.purchase_price_var = tk.StringVar(value="0")
        ttk.Entry(row3, textvariable=self.purchase_price_var, width=15).pack(side=tk.LEFT, padx=(5, 20))
        ttk.Label(row3, text="利益率(%):", width=10).pack(side=tk.LEFT)
        self.profit_rate_var = tk.StringVar(value="0")
        ttk.Entry(row3, textvariable=self.profit_rate_var, width=15).pack(side=tk.LEFT, padx=(5, 0))

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(btn_frame, text="商品追加", command=self._add_product).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="商品削除", command=self._delete_product).pack(side=tk.LEFT, padx=5)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.start_btn = ttk.Button(btn_frame, text="監視開始", command=self._start_monitor)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(btn_frame, text="監視停止", command=self._stop_monitor, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(btn_frame, text="CSV出力", command=self._export_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="更新", command=self._refresh_table).pack(side=tk.LEFT, padx=5)

        table_frame = ttk.LabelFrame(parent, text="商品一覧", padding=5)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        columns = ("id", "mercari_url", "ebay_url", "purchase_price", "profit_rate", "status", "last_check")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        self.tree.heading("id", text="ID")
        self.tree.heading("mercari_url", text="Mercari URL")
        self.tree.heading("ebay_url", text="eBay URL")
        self.tree.heading("purchase_price", text="仕入れ価格")
        self.tree.heading("profit_rate", text="利益率(%)")
        self.tree.heading("status", text="状態")
        self.tree.heading("last_check", text="最終チェック")

        self.tree.column("id", width=50, anchor=tk.CENTER)
        self.tree.column("mercari_url", width=250)
        self.tree.column("ebay_url", width=250)
        self.tree.column("purchase_price", width=100, anchor=tk.CENTER)
        self.tree.column("profit_rate", width=80, anchor=tk.CENTER)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.column("last_check", width=150, anchor=tk.CENTER)

        v_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        h_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X)

        self.status_var = tk.StringVar(value="準備完了")
        ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.count_var = tk.StringVar(value="商品数: 0")
        ttk.Label(status_frame, textvariable=self.count_var, relief=tk.SUNKEN, anchor=tk.E, width=20).pack(side=tk.RIGHT)

    def _build_sheets_tab(self, parent):
        title_label = ttk.Label(
            parent,
            text="Googleスプレッドシート連携",
            font=("Arial", 16, "bold")
        )
        title_label.pack(pady=(0, 15))

        config_frame = ttk.LabelFrame(parent, text="接続設定", padding=10)
        config_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(config_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="スプレッドシートID/URL:", width=22).pack(side=tk.LEFT)
        self.sheet_id_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.sheet_id_var, width=55).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        row2 = ttk.Frame(config_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="認証JSONファイル:", width=22).pack(side=tk.LEFT)
        self.creds_path_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.creds_path_var, width=45).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        ttk.Button(row2, text="参照...", command=self._browse_credentials).pack(side=tk.LEFT)

        row3 = ttk.Frame(config_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="同期間隔（分）:", width=22).pack(side=tk.LEFT)
        self.sync_interval_var = tk.StringVar(value="5")
        ttk.Entry(row3, textvariable=self.sync_interval_var, width=10).pack(side=tk.LEFT, padx=(5, 0))

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(btn_frame, text="手動同期", command=self._manual_sync).pack(side=tk.LEFT, padx=5)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.sync_start_btn = ttk.Button(btn_frame, text="自動同期開始", command=self._start_auto_sync)
        self.sync_start_btn.pack(side=tk.LEFT, padx=5)
        self.sync_stop_btn = ttk.Button(btn_frame, text="自動同期停止", command=self._stop_auto_sync, state=tk.DISABLED)
        self.sync_stop_btn.pack(side=tk.LEFT, padx=5)

        status_frame = ttk.LabelFrame(parent, text="同期状態", padding=10)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.sheets_status_var = tk.StringVar(value="未接続")
        ttk.Label(status_frame, textvariable=self.sheets_status_var, font=("Arial", 11), anchor=tk.W).pack(fill=tk.X)

        help_frame = ttk.LabelFrame(parent, text="使い方", padding=10)
        help_frame.pack(fill=tk.BOTH, expand=True)

        help_text = (
            "【セットアップ手順】\n"
            "1. Google Cloud Consoleでプロジェクトを作成\n"
            "2. Google Sheets APIとGoogle Drive APIを有効化\n"
            "3. サービスアカウントを作成し、JSONキーをダウンロード\n"
            "4. スプレッドシートをサービスアカウントのメールアドレスに共有\n\n"
            "【スプレッドシートの書き方】\n"
            "  A列: Mercari URL\n"
            "  B列: eBay URL\n"
            "  C列: 仕入れ価格（任意）\n"
            "  D列: 利益率（任意）\n"
            "  E列: 状態（自動書き込み）\n"
            "  F列: 最終チェック日時（自動書き込み）\n\n"
            "【動作】\n"
            "  - スプレッドシートの新しいURLを自動でDBに登録\n"
            "  - チェック結果をE列・F列に自動反映"
        )
        help_label = ttk.Label(help_frame, text=help_text, justify=tk.LEFT, wraplength=700)
        help_label.pack(fill=tk.BOTH, expand=True)

    def _browse_credentials(self):
        file_path = filedialog.askopenfilename(
            title="認証JSONファイルを選択",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            self.creds_path_var.set(file_path)

    def _validate_sheets_config(self):
        sheet_id = self.sheet_id_var.get().strip()
        creds_path = self.creds_path_var.get().strip()

        if not sheet_id:
            messagebox.showwarning("入力エラー", "スプレッドシートIDまたはURLを入力してください。")
            return False
        if not creds_path:
            messagebox.showwarning("入力エラー", "認証JSONファイルを選択してください。")
            return False
        if not os.path.exists(creds_path):
            messagebox.showwarning("ファイルエラー", f"認証ファイルが見つかりません:\n{creds_path}")
            return False

        try:
            interval = int(self.sync_interval_var.get())
            if interval < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("入力エラー", "同期間隔は1以上の整数で入力してください。")
            return False

        return True

    def _apply_sheets_config(self):
        self.sheets_sync.set_config(
            spreadsheet_id=self.sheet_id_var.get().strip(),
            credentials_path=self.creds_path_var.get().strip(),
            sync_interval_minutes=int(self.sync_interval_var.get())
        )

    def _manual_sync(self):
        if not self._validate_sheets_config():
            return

        self._apply_sheets_config()
        self.sheets_status_var.set("手動同期実行中...")
        self.root.update_idletasks()

        import threading
        def do_sync():
            success = self.sheets_sync.sync_once()
            self.root.after(0, self._refresh_table)
            if not success:
                self.root.after(0, lambda: messagebox.showerror("エラー", "同期に失敗しました。ログを確認してください。"))

        t = threading.Thread(target=do_sync, daemon=True)
        t.start()

    def _start_auto_sync(self):
        if self.sheets_sync.is_running:
            return
        if not self._validate_sheets_config():
            return

        self._apply_sheets_config()
        self.sheets_sync.start_auto_sync()
        self.sync_start_btn.config(state=tk.DISABLED)
        self.sync_stop_btn.config(state=tk.NORMAL)

    def _stop_auto_sync(self):
        if not self.sheets_sync.is_running:
            return
        self.sheets_sync.stop_auto_sync()
        self.sync_start_btn.config(state=tk.NORMAL)
        self.sync_stop_btn.config(state=tk.DISABLED)

    def _on_sheets_status_update(self, message):
        try:
            self.root.after(0, lambda: self.sheets_status_var.set(message))
            self.root.after(0, self._refresh_table)
        except Exception:
            pass

    def _add_product(self):
        mercari_url = self.mercari_url_var.get().strip()
        ebay_url = self.ebay_url_var.get().strip()

        if not mercari_url or not ebay_url:
            messagebox.showwarning("入力エラー", "Mercari URLとeBay URLは必須です。")
            return

        try:
            purchase_price = float(self.purchase_price_var.get() or "0")
        except ValueError:
            messagebox.showwarning("入力エラー", "仕入れ価格は数値で入力してください。")
            return

        try:
            profit_rate = float(self.profit_rate_var.get() or "0")
        except ValueError:
            messagebox.showwarning("入力エラー", "利益率は数値で入力してください。")
            return

        current_count = get_product_count()
        if current_count >= MAX_PRODUCTS:
            messagebox.showwarning("上限エラー", f"商品数の上限({MAX_PRODUCTS})に達しています。")
            return

        success = add_product(mercari_url, ebay_url, purchase_price, profit_rate)
        if success:
            self.mercari_url_var.set("")
            self.ebay_url_var.set("")
            self.purchase_price_var.set("0")
            self.profit_rate_var.set("0")
            self._refresh_table()
            self.status_var.set("商品を追加しました")
        else:
            messagebox.showerror("エラー", "商品の追加に失敗しました。")

    def _delete_product(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("選択エラー", "削除する商品を選択してください。")
            return

        item = self.tree.item(selected[0])
        product_id = item["values"][0]

        confirm = messagebox.askyesno("確認", f"商品ID {product_id} を削除しますか？")
        if confirm:
            success = delete_product(product_id)
            if success:
                self._refresh_table()
                self.status_var.set(f"商品ID {product_id} を削除しました")
            else:
                messagebox.showerror("エラー", "商品の削除に失敗しました。")

    def _refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        products = get_all_products()
        for p in products:
            status_display = p["status"]
            if status_display == "active":
                status_display = "監視中"
            elif status_display == "out_of_stock":
                status_display = "売り切れ"

            self.tree.insert("", tk.END, values=(
                p["id"],
                p["mercari_url"],
                p["ebay_url"],
                p["purchase_price"],
                p["profit_rate"],
                status_display,
                p["last_check"] or "未チェック"
            ))

        count = get_product_count()
        self.count_var.set(f"商品数: {count}/{MAX_PRODUCTS}")

    def _start_monitor(self):
        if self.monitor.is_running:
            return
        self.monitor.start()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("監視実行中...")

    def _stop_monitor(self):
        if not self.monitor.is_running:
            return
        self.monitor.stop()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("監視停止")

    def _export_csv(self):
        products = get_all_products()
        if not products:
            messagebox.showinfo("情報", "エクスポートする商品がありません。")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="products.csv"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["MercariURL", "EbayURL", "Status", "LastCheck"])
                for p in products:
                    writer.writerow([
                        p["mercari_url"],
                        p["ebay_url"],
                        p["status"],
                        p["last_check"] or ""
                    ])
            log_info(f"CSV出力完了: {file_path}")
            self.status_var.set(f"CSV出力完了: {os.path.basename(file_path)}")
            messagebox.showinfo("完了", f"CSVファイルを出力しました。\n{file_path}")
        except Exception as e:
            log_error(f"CSV出力エラー: {e}")
            messagebox.showerror("エラー", f"CSV出力に失敗しました。\n{e}")

    def _on_status_update(self, message):
        try:
            self.root.after(0, lambda: self.status_var.set(message))
            self.root.after(0, self._refresh_table)
        except Exception:
            pass
