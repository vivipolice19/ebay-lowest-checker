import sys
import os

# Replit の Nix ランタイムのみ（Render 等ではパスが無いので設定しない）
_nix_gcc_lib = "/nix/store/4wpp8mpgwk12j25w9vsls3scmz9smi1j-gcc-12.3.0-lib/lib"
if os.path.isdir(_nix_gcc_lib):
    os.environ.setdefault("LD_LIBRARY_PATH", _nix_gcc_lib)

app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ebay_stock_manager")
sys.path.insert(0, app_dir)

from web_app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
