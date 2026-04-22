import json
from typing import Any, Dict, List

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, SPREADSHEET_ID

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

REQUIRED_COLUMNS = [
    "product_key",
    "search_keyword",
    "condition",
    "target_url",
    "target_price",
    "floor_price",
    "alert_enabled",
    "auto_reprice",
    "active",
]


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if cleaned == "":
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def _client():
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
    return gspread.authorize(credentials)


def _sheet():
    if not SPREADSHEET_ID:
        raise ValueError("SPREADSHEET_ID is empty")
    return _client().open_by_key(SPREADSHEET_ID).sheet1


def load_watch_items() -> List[Dict[str, Any]]:
    rows = _sheet().get_all_records()
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        item = {k: row.get(k, "") for k in REQUIRED_COLUMNS}
        if not str(item["product_key"]).strip():
            continue
        parsed.append(
            {
                "product_key": str(item["product_key"]).strip(),
                "search_keyword": str(item["search_keyword"]).strip(),
                "condition": str(item["condition"]).strip() or "Used",
                "target_url": str(item["target_url"]).strip(),
                "target_price": _normalize_float(item["target_price"]),
                "floor_price": _normalize_float(item["floor_price"]),
                "alert_enabled": _normalize_bool(item["alert_enabled"], True),
                "auto_reprice": _normalize_bool(item["auto_reprice"], False),
                "active": _normalize_bool(item["active"], True),
            }
        )
    return parsed
