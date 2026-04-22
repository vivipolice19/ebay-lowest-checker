import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import log_info, log_error

def main():
    mode = os.environ.get("APP_MODE", "web").lower()

    if mode == "tkinter" or mode == "desktop":
        run_desktop()
    else:
        run_web()

def run_web():
    try:
        log_info("=== Webアプリケーション起動 ===")
        from web_app import start_web_app
        start_web_app()
    except Exception as e:
        log_error(f"Webアプリ起動エラー: {e}")
        import traceback
        traceback.print_exc()

def run_desktop():
    try:
        import tkinter as tk
        log_info("=== デスクトップアプリケーション起動 ===")
        from ui import StockManagerApp
        root = tk.Tk()
        app = StockManagerApp(root)

        def on_closing():
            try:
                if app.monitor.is_running:
                    app.monitor.stop()
                log_info("=== アプリケーション終了 ===")
            except Exception:
                pass
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()
    except Exception as e:
        log_error(f"デスクトップアプリ起動エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
