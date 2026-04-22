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
    "target_url",
    "own_price",
    "floor_price",
    "alert_enabled",
    "auto_reprice",
    "active",
    "monitor_status",
    "last_checked",
    "min_new",
    "min_open_box",
    "min_used",
    "min_seller_refurbished",
    "min_certified_refurbished",
    "min_for_parts",
    "min_url",
    "note",
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


def _ensure_header(worksheet):
    values = worksheet.row_values(1)
    if not values:
        worksheet.append_row(REQUIRED_COLUMNS)
        return
    normalized = [v.strip() for v in values]
    if normalized == REQUIRED_COLUMNS:
        return
    existing_set = set(normalized)
    for col in REQUIRED_COLUMNS:
        if col not in existing_set:
            normalized.append(col)
    worksheet.update("A1", [normalized])


def load_watch_items() -> List[Dict[str, Any]]:
    worksheet = _sheet()
    _ensure_header(worksheet)
    rows = worksheet.get_all_records()
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        item = {k: row.get(k, "") for k in REQUIRED_COLUMNS}
        if not str(item["product_key"]).strip():
            continue
        parsed.append(
            {
                "product_key": str(item["product_key"]).strip(),
                "search_keyword": str(item["search_keyword"]).strip(),
                "target_url": str(item["target_url"]).strip(),
                "own_price": _normalize_float(item["own_price"]),
                "floor_price": _normalize_float(item["floor_price"]),
                "alert_enabled": _normalize_bool(item["alert_enabled"], True),
                "auto_reprice": _normalize_bool(item["auto_reprice"], False),
                "active": _normalize_bool(item["active"], True),
            }
        )
    return parsed


def add_watch_item(product_key: str, search_keyword: str, target_url: str):
    worksheet = _sheet()
    _ensure_header(worksheet)
    row = {
        "product_key": product_key.strip(),
        "search_keyword": search_keyword.strip(),
        "target_url": target_url.strip(),
        "own_price": "",
        "floor_price": "",
        "alert_enabled": "true",
        "auto_reprice": "false",
        "active": "true",
        "monitor_status": "",
        "last_checked": "",
        "min_new": "",
        "min_open_box": "",
        "min_used": "",
        "min_seller_refurbished": "",
        "min_certified_refurbished": "",
        "min_for_parts": "",
        "min_url": "",
        "note": "",
    }
    worksheet.append_row([row.get(col, "") for col in REQUIRED_COLUMNS])


def list_watch_items() -> List[Dict[str, Any]]:
    worksheet = _sheet()
    _ensure_header(worksheet)
    return worksheet.get_all_records()


def update_watch_result(
    product_key: str,
    own_price: float,
    status: str,
    min_values: Dict[str, float],
    min_url: str,
    note: str,
    checked_at: str,
):
    worksheet = _sheet()
    _ensure_header(worksheet)
    values = worksheet.get_all_values()
    if len(values) < 2:
        return

    headers = values[0]
    try:
        key_idx = headers.index("product_key")
    except ValueError:
        return
    col_map = {name: idx for idx, name in enumerate(headers)}
    target_row = None
    for i in range(1, len(values)):
        row = values[i]
        key = row[key_idx].strip() if len(row) > key_idx else ""
        if key == product_key:
            target_row = i + 1
            break
    if not target_row:
        return

    updates = {
        "own_price": f"{own_price:.2f}" if own_price else "",
        "monitor_status": status,
        "last_checked": checked_at,
        "min_new": f"{min_values.get('New', 0):.2f}" if min_values.get("New") else "",
        "min_open_box": f"{min_values.get('Open Box', 0):.2f}" if min_values.get("Open Box") else "",
        "min_used": f"{min_values.get('Used', 0):.2f}" if min_values.get("Used") else "",
        "min_seller_refurbished": f"{min_values.get('Seller Refurbished', 0):.2f}" if min_values.get("Seller Refurbished") else "",
        "min_certified_refurbished": f"{min_values.get('Certified Refurbished', 0):.2f}" if min_values.get("Certified Refurbished") else "",
        "min_for_parts": f"{min_values.get('For Parts', 0):.2f}" if min_values.get("For Parts") else "",
        "min_url": min_url or "",
        "note": note or "",
    }
    batch = []
    for name, value in updates.items():
        if name not in col_map:
            continue
        col = col_map[name] + 1
        batch.append(
            {
                "range": gspread.utils.rowcol_to_a1(target_row, col),
                "values": [[value]],
            }
        )
    if batch:
        worksheet.batch_update(batch, value_input_option="RAW")
