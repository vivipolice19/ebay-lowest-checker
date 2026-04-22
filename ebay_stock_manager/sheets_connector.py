import os
import json
import gspread
from logger import log_info, log_error, log_warning

_cached_token = None
_cached_token_expires = 0


def invalidate_token_cache():
    global _cached_token, _cached_token_expires
    _cached_token = None
    _cached_token_expires = 0


def _get_replit_access_token():
    global _cached_token, _cached_token_expires
    import time
    import urllib.request

    now = time.time() * 1000
    if _cached_token and (_cached_token_expires - 60000) > now:
        return _cached_token

    hostname = os.environ.get("REPLIT_CONNECTORS_HOSTNAME")
    repl_identity = os.environ.get("REPL_IDENTITY")
    web_repl_renewal = os.environ.get("WEB_REPL_RENEWAL")

    if not hostname:
        return None

    if repl_identity:
        x_replit_token = "repl " + repl_identity
    elif web_repl_renewal:
        x_replit_token = "depl " + web_repl_renewal
    else:
        return None

    url = f"https://{hostname}/api/v2/connection?include_secrets=true&connector_names=google-sheet"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Replit-Token": x_replit_token
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("items", [])
            if not items:
                log_error("Google Sheets連携: 接続情報なし")
                return None

            settings = items[0].get("settings", {})
            access_token = settings.get("access_token")
            if not access_token:
                oauth = settings.get("oauth", {})
                creds = oauth.get("credentials", {})
                access_token = creds.get("access_token")

            if not access_token:
                log_error("Google Sheets連携: アクセストークンなし")
                return None

            expires_at = settings.get("expires_at")
            if expires_at:
                try:
                    from datetime import datetime
                    exp_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    _cached_token_expires = exp_time.timestamp() * 1000
                except Exception:
                    _cached_token_expires = now + 3000000

            _cached_token = access_token
            return access_token

    except Exception as e:
        log_error(f"Replit OAuth トークン取得エラー: {e}")
        return None


def _is_replit_env():
    return bool(os.environ.get("REPLIT_CONNECTORS_HOSTNAME"))


def get_sheets_client(creds_path=None):
    if _is_replit_env():
        token = _get_replit_access_token()
        if token:
            try:
                from google.oauth2.credentials import Credentials
                creds = Credentials(token=token)
                client = gspread.Client(auth=creds)
                log_info("Google Sheets接続 (Replit OAuth)")
                return client
            except Exception as e:
                log_error(f"Replit OAuth クライアント作成エラー: {e}")

    if creds_path and os.path.exists(creds_path):
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            SCOPES = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            credentials = ServiceAccountCredentials.from_json_keyfile_name(creds_path, SCOPES)
            client = gspread.authorize(credentials)
            log_info("Google Sheets接続 (サービスアカウント)")
            return client
        except Exception as e:
            log_error(f"サービスアカウント認証エラー: {e}")
            return None

    if _is_replit_env():
        log_warning("Google Sheets連携が未設定です。設定画面で連携してください。")
    else:
        log_warning("Google Sheets: credentials.jsonのパスを設定してください。")

    return None


def open_spreadsheet(client, spreadsheet_id_or_url):
    import re
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_id_or_url)
    if match:
        sheet_id = match.group(1)
    elif re.match(r"^[a-zA-Z0-9-_]+$", spreadsheet_id_or_url):
        sheet_id = spreadsheet_id_or_url
    else:
        sheet_id = spreadsheet_id_or_url

    try:
        spreadsheet = client.open_by_key(sheet_id)
        return spreadsheet
    except gspread.exceptions.SpreadsheetNotFound:
        log_error(f"スプレッドシートが見つかりません: {sheet_id}")
        return None
    except gspread.exceptions.APIError as e:
        log_error(f"スプレッドシートAPI エラー: {e}")
        return None
    except Exception as e:
        log_error(f"スプレッドシート接続エラー: {e}")
        return None
