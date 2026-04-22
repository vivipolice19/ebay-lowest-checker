import re
import subprocess
import json
import time
import base64
import urllib.parse
from logger import log_info, log_error, log_warning, log_debug
from database import get_setting

_app_token_cache = {
    "access_token": None,
    "expires_at": 0
}

_user_token_cache = {
    "access_token": None,
    "expires_at": 0
}

EBAY_SCOPES = (
    "https://api.ebay.com/oauth/api_scope "
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.account"
)


def extract_item_id(ebay_url):
    try:
        match = re.search(r'/itm/(\d+)', ebay_url)
        if match:
            return match.group(1)
        match = re.search(r'item=(\d+)', ebay_url)
        if match:
            return match.group(1)
        parts = ebay_url.rstrip('/').split('/')
        for part in reversed(parts):
            if part.isdigit() and len(part) > 8:
                return part
        return None
    except Exception:
        return None


def _get_application_token():
    """クライアント認証トークン（Browse API用）"""
    global _app_token_cache

    if _app_token_cache["access_token"] and time.time() < _app_token_cache["expires_at"] - 60:
        return _app_token_cache["access_token"]

    client_id = get_setting("ebay_client_id", "")
    client_secret = get_setting("ebay_client_secret", "")

    if not client_id or not client_secret:
        return None

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "15",
                "-X", "POST",
                "-H", f"Authorization: Basic {credentials}",
                "-H", "Content-Type: application/x-www-form-urlencoded",
                "-d", "grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
                "https://api.ebay.com/identity/v1/oauth2/token"
            ],
            capture_output=True, text=True, timeout=20
        )

        if result.returncode != 0:
            log_error("eBay OAuth トークン取得失敗 (curl)")
            return None

        data = json.loads(result.stdout)

        if "access_token" in data:
            _app_token_cache["access_token"] = data["access_token"]
            _app_token_cache["expires_at"] = time.time() + data.get("expires_in", 7200)
            log_info("eBay Application Token取得成功")
            return data["access_token"]
        else:
            error_desc = data.get("error_description", data.get("error", "不明"))
            log_error(f"eBay OAuth エラー: {error_desc}")
            return None

    except json.JSONDecodeError as e:
        log_error(f"eBay OAuth レスポンス解析エラー: {e}")
        return None
    except Exception as e:
        log_error(f"eBay OAuth 例外: {e}")
        return None


def _refresh_oauth_token(refresh_token):
    """リフレッシュトークンで新しいアクセストークンを取得"""
    from database import save_setting

    client_id = get_setting("ebay_client_id", "")
    client_secret = get_setting("ebay_client_secret", "")

    if not client_id or not client_secret or not refresh_token:
        return None

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "20",
                "-X", "POST",
                "-H", f"Authorization: Basic {credentials}",
                "-H", "Content-Type: application/x-www-form-urlencoded",
                "-d", f"grant_type=refresh_token&refresh_token={urllib.parse.quote(refresh_token)}&scope={urllib.parse.quote(EBAY_SCOPES)}",
                "https://api.ebay.com/identity/v1/oauth2/token"
            ],
            capture_output=True, text=True, timeout=25
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        if "access_token" in data:
            new_token = data["access_token"]
            expires_in = data.get("expires_in", 7200)
            expires_at = time.time() + expires_in

            save_setting("ebay_oauth_token", new_token)
            save_setting("ebay_token_expires_at", str(expires_at))
            if "refresh_token" in data:
                save_setting("ebay_refresh_token", data["refresh_token"])

            _user_token_cache["access_token"] = new_token
            _user_token_cache["expires_at"] = expires_at

            log_info("eBay OAuthトークン自動リフレッシュ成功")
            return new_token
        else:
            err = data.get("error_description", "不明")
            log_warning(f"eBay OAuthトークンリフレッシュ失敗: {err}")
            return None

    except Exception as e:
        log_error(f"eBay OAuthトークンリフレッシュ例外: {e}")
        return None


def _get_user_access_token():
    """
    ユーザーOAuthアクセストークンを取得。
    期限切れの場合はリフレッシュトークンで自動更新。
    """
    global _user_token_cache

    if _user_token_cache["access_token"] and time.time() < _user_token_cache["expires_at"] - 300:
        return _user_token_cache["access_token"]

    oauth_token = get_setting("ebay_oauth_token", "")
    if not oauth_token:
        return None

    token_expires_at = float(get_setting("ebay_token_expires_at", "0") or "0")
    refresh_token = get_setting("ebay_refresh_token", "")

    if token_expires_at > 0 and time.time() < token_expires_at - 300:
        _user_token_cache["access_token"] = oauth_token
        _user_token_cache["expires_at"] = token_expires_at
        return oauth_token

    if refresh_token:
        log_info("eBay OAuthトークンの期限が近いため自動リフレッシュを試みます")
        new_token = _refresh_oauth_token(refresh_token)
        if new_token:
            return new_token
        log_warning("リフレッシュ失敗 - 既存トークンを使用して試みます")

    return oauth_token


def get_ebay_item_price(ebay_url):
    item_id = extract_item_id(ebay_url)
    if not item_id:
        log_error(f"eBay商品IDを抽出できません: {ebay_url}")
        return None

    price = _get_price_via_browse_api(item_id, ebay_url)
    if price is not None:
        return price

    price = _get_price_via_scraping(ebay_url)
    return price


def _get_price_via_browse_api(item_id, ebay_url):
    token = _get_application_token()
    if not token:
        user_token = get_setting("ebay_oauth_token", "")
        if user_token:
            token = user_token
            log_debug("Browse API: User Auth Tokenを使用")
        else:
            return None

    try:
        api_url = f"https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id={item_id}"

        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "15",
                "-H", f"Authorization: Bearer {token}",
                "-H", "Accept: application/json",
                "-H", "X-EBAY-C-MARKETPLACE-ID: EBAY_US",
                api_url
            ],
            capture_output=True, text=True, timeout=20
        )

        if result.returncode != 0:
            log_error(f"eBay Browse API呼び出し失敗 (curl): item={item_id}")
            return None

        data = json.loads(result.stdout)

        if "errors" in data:
            error_msg = data["errors"][0].get("message", "不明なエラー")
            error_id = data["errors"][0].get("errorId", "")

            if "1001" in str(error_id) or "Invalid" in error_msg:
                _app_token_cache["access_token"] = None
                _app_token_cache["expires_at"] = 0
                log_warning(f"eBay APIトークン無効、次回再取得: {error_msg}")
            else:
                log_error(f"eBay Browse API エラー: item={item_id} - {error_msg}")
            return None

        price_info = data.get("price", {})
        price_value = price_info.get("value")
        price_currency = price_info.get("currency", "USD")

        if price_value and price_currency == "USD":
            price = float(price_value)
            if 0.01 <= price <= 100000:
                log_info(f"eBay価格(API): ${price:.2f} - {ebay_url}")
                return price
        return None

    except Exception as e:
        log_debug(f"eBay Browse API 例外: item={item_id} - {e}")
        return None


def _get_price_via_scraping(ebay_url):
    import random
    import time as _time

    EBAY_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]

    try:
        _time.sleep(random.uniform(1, 3))

        ua = random.choice(EBAY_USER_AGENTS)
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "20",
                "-A", ua,
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", "Accept: text/html,application/xhtml+xml",
                ebay_url
            ],
            capture_output=True, text=True, timeout=25
        )

        if result.returncode != 0 or not result.stdout:
            return None

        html = result.stdout

        if "ChallengeGet" in html or len(html) < 20000:
            log_debug(f"eBayボット検出 (スクレイピング失敗): {ebay_url}")
            return None

        price = None

        matches = re.findall(r'"priceCurrency"\s*:\s*"(\w+)"\s*,\s*"price"\s*:\s*"?([\d.]+)', html[:200000])
        for currency, p in matches:
            if currency == "USD":
                try:
                    price = float(p)
                    if 0.01 <= price <= 100000:
                        break
                    price = None
                except ValueError:
                    continue

        if price is None:
            matches = re.findall(r'US \$([\d,.]+)', html[:200000])
            for m in matches:
                try:
                    val = float(m.replace(",", ""))
                    if 0.01 <= val <= 100000:
                        price = val
                        break
                except ValueError:
                    continue

        if price:
            log_info(f"eBay価格: ${price:.2f} - {ebay_url}")

        return price

    except Exception as e:
        log_debug(f"eBayスクレイピング例外: {ebay_url} - {e}")
        return None


def update_ebay_inventory_api(ebay_url, quantity=0):
    """eBay在庫数量を更新（売り切れ→0、再販売→1）"""
    oauth_token = _get_user_access_token()
    if not oauth_token:
        log_warning(f"eBay OAuthトークン未設定のため在庫更新スキップ: {ebay_url}")
        return False

    item_id = extract_item_id(ebay_url)
    if not item_id:
        log_error(f"eBay商品IDを抽出できません: {ebay_url}")
        return False

    return _update_via_trading_api(item_id, quantity, oauth_token)


def _update_via_trading_api(item_id, quantity, oauth_token):
    success = _try_trading_iaf(item_id, quantity, oauth_token)
    if success:
        return True

    return _try_trading_auth_n_auth(item_id, quantity, oauth_token)


def _try_trading_iaf(item_id, quantity, oauth_token):
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <Item>
    <ItemID>{item_id}</ItemID>
    <Quantity>{quantity}</Quantity>
  </Item>
</ReviseItemRequest>"""

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "30",
                "-X", "POST",
                "-H", "Content-Type: text/xml",
                "-H", "X-EBAY-API-COMPATIBILITY-LEVEL: 967",
                "-H", "X-EBAY-API-CALL-NAME: ReviseItem",
                "-H", "X-EBAY-API-SITEID: 0",
                "-H", f"X-EBAY-API-IAF-TOKEN: {oauth_token}",
                "-d", xml_body,
                "https://api.ebay.com/ws/api.dll"
            ],
            capture_output=True, text=True, timeout=35
        )

        if result.returncode != 0:
            return False

        response = result.stdout

        if "<Ack>Success</Ack>" in response or "<Ack>Warning</Ack>" in response:
            log_info(f"eBay在庫更新成功 (IAF): item={item_id}, quantity={quantity}")
            return True

        return False

    except Exception:
        return False


def _try_trading_auth_n_auth(item_id, quantity, oauth_token):
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{oauth_token}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <Quantity>{quantity}</Quantity>
  </Item>
</ReviseItemRequest>"""

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", "30",
                "-X", "POST",
                "-H", "Content-Type: text/xml",
                "-H", "X-EBAY-API-COMPATIBILITY-LEVEL: 967",
                "-H", "X-EBAY-API-CALL-NAME: ReviseItem",
                "-H", "X-EBAY-API-SITEID: 0",
                "-d", xml_body,
                "https://api.ebay.com/ws/api.dll"
            ],
            capture_output=True, text=True, timeout=35
        )

        if result.returncode != 0:
            log_error(f"eBay API呼び出しエラー (curl): item={item_id}")
            return False

        response = result.stdout

        if "<Ack>Success</Ack>" in response or "<Ack>Warning</Ack>" in response:
            log_info(f"eBay在庫更新成功 (AuthToken): item={item_id}, quantity={quantity}")
            return True

        error_match = re.search(r'<ShortMessage>(.*?)</ShortMessage>', response)
        error_msg = error_match.group(1) if error_match else "不明なエラー"
        long_error = re.search(r'<LongMessage>(.*?)</LongMessage>', response)
        if long_error:
            error_msg += f" - {long_error.group(1)}"

        log_error(f"eBay API更新失敗: item={item_id} - {error_msg}")
        return False

    except Exception as e:
        log_error(f"eBay API呼び出し例外: item={item_id} - {e}")
        return False


def check_ebay_api_status():
    client_id = get_setting("ebay_client_id", "")
    client_secret = get_setting("ebay_client_secret", "")
    oauth_token = get_setting("ebay_oauth_token", "")
    refresh_token = get_setting("ebay_refresh_token", "")
    token_expires_at = float(get_setting("ebay_token_expires_at", "0") or "0")

    token_valid = False
    token_status = "未設定"
    if oauth_token:
        if token_expires_at > 0:
            remaining = token_expires_at - time.time()
            if remaining > 0:
                token_valid = True
                hours = int(remaining // 3600)
                token_status = f"有効 (残り{hours}時間)"
            else:
                token_status = "期限切れ" + ("（リフレッシュ可能）" if refresh_token else "（要再連携）")
        else:
            token_status = "期限不明"

    return {
        "browse_api": bool(client_id and client_secret) or bool(oauth_token),
        "trading_api": bool(oauth_token),
        "token_valid": token_valid,
        "token_status": token_status,
        "refresh_available": bool(refresh_token),
        "price_fetch": "API" if (client_id and client_secret) or oauth_token else "無効",
        "inventory_update": "有効" if oauth_token else "無効"
    }
