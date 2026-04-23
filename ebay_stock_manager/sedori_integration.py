"""
セドリアプリ → 在庫管理アプリ 連携用の検証・定数。

在庫側エンドポイントは web_app で公開。ここは純粋な入力検証とヘルパ。

セドリアプリ側の呼び出し例（出品完了フックから）::

    POST {在庫アプリのベースURL}/api/v1/sedori/listings
    Headers:
      Authorization: Bearer <SEDORI_WEBHOOK_SECRET と同一の文字列>
      Content-Type: application/json
    Body:
      {
        "event_id": "一意な配信ID（再送時も同じにすると冪等）",
        "external_id": "セドリ側の商品の安定ID（同一商品の更新に使用）",
        "mercari_url": "https://jp.mercari.com/...",
        "ebay_url": "https://www.ebay.com/itm/...",
        "purchase_price": 0,
        "profit_rate": 0,
        "title": "任意"
      }
"""
import os
import re
import secrets
from urllib.parse import urlparse

from logger import log_error

MAX_EVENT_ID_LEN = 128
MAX_EXTERNAL_ID_LEN = 128
MAX_TITLE_LEN = 500
MAX_URL_LEN = 2048


def get_expected_webhook_secret(get_setting_fn):
    """
    環境変数 SEDORI_WEBHOOK_SECRET があれば最優先（本番デプロイ向け）。
    なければ DB 設定 sedori_webhook_secret。
    """
    env = os.environ.get("SEDORI_WEBHOOK_SECRET", "").strip()
    if env:
        return env
    return (get_setting_fn("sedori_webhook_secret", "") or "").strip()


def verify_bearer_token(provided_raw, expected):
    if not expected:
        return False
    provided = (provided_raw or "").strip()
    if not provided.startswith("Bearer "):
        return False
    token = provided[7:].strip()
    if not token:
        return False
    return secrets.compare_digest(token, expected)


def _is_reasonable_http_url(url):
    if not url or len(url) > MAX_URL_LEN:
        return False
    try:
        p = urlparse(url.strip())
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if not p.netloc:
        return False
    return True


def validate_listing_payload(data):
    """
    必須: event_id, external_id, mercari_url, ebay_url
    任意: purchase_price, profit_rate, title, listed_at (ISO文字列・未使用でも可)
    戻り値: (cleaned_dict|None, error_message|None)
    """
    if not isinstance(data, dict):
        return None, "JSONオブジェクトが必要です"

    event_id = str(data.get("event_id", "")).strip()
    external_id = str(data.get("external_id", "")).strip()
    mercari_url = str(data.get("mercari_url", "")).strip()
    ebay_url = str(data.get("ebay_url", "")).strip()

    if not event_id or len(event_id) > MAX_EVENT_ID_LEN:
        return None, "event_id は1文字以上128文字以内で指定してください"
    if not re.match(r"^[A-Za-z0-9._:-]+$", event_id):
        return None, "event_id に使用できない文字が含まれています"

    if not external_id or len(external_id) > MAX_EXTERNAL_ID_LEN:
        return None, "external_id は1文字以上128文字以内で指定してください"
    if not re.match(r"^[A-Za-z0-9._:-]+$", external_id):
        return None, "external_id に使用できない文字が含まれています"

    if not _is_reasonable_http_url(mercari_url):
        return None, "mercari_url が不正です（https の URL を指定してください）"
    if "mercari" not in mercari_url.lower():
        return None, "mercari_url に mercari が含まれている必要があります"

    if not _is_reasonable_http_url(ebay_url):
        return None, "ebay_url が不正です（https の URL を指定してください）"
    if "ebay" not in ebay_url.lower():
        return None, "ebay_url に ebay が含まれている必要があります"

    purchase_price = data.get("purchase_price", 0)
    profit_rate = data.get("profit_rate", 0)
    title = data.get("title")
    listed_at = data.get("listed_at")

    try:
        purchase_price = float(purchase_price)
    except (TypeError, ValueError):
        return None, "purchase_price が数値ではありません"
    try:
        profit_rate = float(profit_rate)
    except (TypeError, ValueError):
        return None, "profit_rate が数値ではありません"

    if purchase_price < 0 or purchase_price > 1e9:
        return None, "purchase_price の範囲が不正です"
    if profit_rate < -1000 or profit_rate > 1000:
        return None, "profit_rate の範囲が不正です"

    title_clean = None
    if title is not None:
        title_clean = str(title).strip()
        if len(title_clean) > MAX_TITLE_LEN:
            return None, f"title は {MAX_TITLE_LEN} 文字以内にしてください"

    listed_at_clean = None
    if listed_at is not None:
        listed_at_clean = str(listed_at).strip()
        if len(listed_at_clean) > 64:
            return None, "listed_at が長すぎます"

    cleaned = {
        "event_id": event_id,
        "external_id": external_id,
        "mercari_url": mercari_url,
        "ebay_url": ebay_url,
        "purchase_price": purchase_price,
        "profit_rate": profit_rate,
        "title": title_clean,
        "listed_at": listed_at_clean,
    }
    return cleaned, None


def log_validation_failure(message):
    log_error(f"セドリ連携バリデーション失敗: {message}")
