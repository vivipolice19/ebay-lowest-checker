import re
from typing import Dict, List, Optional

import requests

from config import (
    EBAY_APP_ID,
    EBAY_BROWSE_TOKEN,
    EBAY_MARKETPLACE_ID,
    MAX_RESULTS_PER_QUERY,
    REQUEST_TIMEOUT_SECONDS,
)

CONDITION_MAP = {
    "new": "NEW",
    "used": "USED",
    "open box": "OPEN_BOX",
    "for parts": "FOR_PARTS_OR_NOT_WORKING",
    "certified refurbished": "CERTIFIED_REFURBISHED",
    "seller refurbished": "SELLER_REFURBISHED",
}
CONDITIONS_FOR_REPORT = [
    "New",
    "Open Box",
    "Used",
    "Seller Refurbished",
    "Certified Refurbished",
    "For Parts",
]


def _headers() -> Dict[str, str]:
    headers = {
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
    }
    if EBAY_BROWSE_TOKEN:
        headers["Authorization"] = f"Bearer {EBAY_BROWSE_TOKEN}"
    if EBAY_APP_ID:
        headers["X-EBAY-C-ENDUSERCTX"] = f"contextualLocation=country=US,appId={EBAY_APP_ID}"
    return headers


def _normalize_condition(condition_name: str) -> Optional[str]:
    key = (condition_name or "").strip().lower()
    return CONDITION_MAP.get(key)


def search_min_price(search_keyword: str, condition_name: str) -> Optional[Dict[str, str]]:
    if not search_keyword.strip():
        return None

    params = {
        "q": search_keyword,
        "limit": MAX_RESULTS_PER_QUERY,
        "sort": "price",
    }
    condition = _normalize_condition(condition_name)
    if condition:
        params["filter"] = f"conditions:{{{condition}}},itemLocationCountry:US,priceCurrency:USD"
    else:
        params["filter"] = "itemLocationCountry:US,priceCurrency:USD"

    resp = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        params=params,
        headers=_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()

    data = resp.json()
    items: List[Dict] = data.get("itemSummaries", [])
    cheapest = None
    for item in items:
        price_obj = item.get("price", {})
        value = price_obj.get("value")
        if value is None:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        url = item.get("itemWebUrl", "")
        if not url:
            continue
        if cheapest is None or price < cheapest["price"]:
            cheapest = {"price": price, "url": url, "title": item.get("title", "")}

    return cheapest


def search_min_prices_by_conditions(search_keyword: str) -> Dict[str, Optional[Dict[str, str]]]:
    report: Dict[str, Optional[Dict[str, str]]] = {}
    for condition in CONDITIONS_FOR_REPORT:
        report[condition] = search_min_price(search_keyword, condition)
    return report


def get_item_price_from_url(item_url: str) -> Optional[float]:
    if not item_url:
        return None
    match = re.search(r"/itm/(\d+)", item_url)
    if not match:
        return None
    legacy_item_id = match.group(1)
    resp = requests.get(
        "https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id",
        params={"legacy_item_id": legacy_item_id},
        headers=_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code >= 400:
        return None
    data = resp.json()
    value = ((data.get("price") or {}).get("value"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def revise_own_listing_price(target_url: str, new_price: float) -> Dict[str, str]:
    # Placeholder: connect your existing eBay revise API implementation here.
    return {
        "success": False,
        "message": f"Price update not implemented yet for {target_url}, requested={new_price:.2f}",
    }
