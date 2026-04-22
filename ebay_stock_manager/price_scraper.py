import re
import json
import subprocess
import shutil
import random
import time
from config import RANDOM_WAIT_MIN, RANDOM_WAIT_MAX
from logger import log_info, log_error, log_debug

_curl_available = shutil.which("curl") is not None
_bs4_available = False
try:
    from bs4 import BeautifulSoup
    _bs4_available = True
except ImportError:
    log_error("beautifulsoup4がインストールされていません: pip install beautifulsoup4")

if not _curl_available:
    log_error("curlがインストールされていません")

MERCARI_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

EBAY_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _fetch_page(url, user_agent=None, timeout=30):
    if not _curl_available:
        log_error("curlが使用できないため、ページ取得をスキップします")
        return None
    ua = user_agent or random.choice(EBAY_USER_AGENTS)
    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L", "--compressed",
                "--max-time", str(timeout),
                "-A", ua,
                "-H", "Accept-Language: ja,en-US;q=0.9,en;q=0.8",
                "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "-H", "Accept-Encoding: gzip, deflate, br",
                "-H", "Connection: keep-alive",
                url
            ],
            capture_output=True, timeout=timeout + 5
        )
        if result.returncode == 0 and result.stdout:
            try:
                return result.stdout.decode("utf-8", errors="replace")
            except Exception:
                return result.stdout.decode("shift_jis", errors="replace")
        return None
    except Exception as e:
        log_error(f"ページ取得エラー: {url} - {e}")
        return None


def _extract_og_price(html):
    """og:description や meta description から価格を抽出する汎用フォールバック"""
    for pat in [
        r'og:description[^>]+content="[^"]*[¥￥]([\d,]+)',
        r'name="description"[^>]+content="[^"]*[¥￥]([\d,]+)',
        r'og:title[^>]+content="[^"]*[¥￥]([\d,]+)',
        r'[¥￥]([\d,]+)\s*(?:円|JPY)',
    ]:
        m = re.search(pat, html[:10000], re.IGNORECASE)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
                if 100 <= val <= 10000000:
                    return val
            except Exception:
                pass
    return None


def _extract_mercari_data(html):
    """
    メルカリの商品ページからデータを抽出する。
    旧フォーマット(__NEXT_DATA__)と新フォーマット(__next_f.push)の両方に対応。
    """
    # --- 旧フォーマット: __NEXT_DATA__ (Pages Router) ---
    next_data = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if next_data:
        try:
            data = json.loads(next_data.group(1))
            props = data.get("props", {})
            page_props = props.get("pageProps", {})
            swr_data = page_props.get("swrData", {})

            for key, value in swr_data.items():
                if "/items/get" in key and isinstance(value, dict):
                    item_data = value.get("data", {})
                    if item_data and "price" in item_data:
                        return item_data

            item = page_props.get("item", {})
            if item and "price" in item:
                return item

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log_debug(f"Mercariデータ解析エラー(__NEXT_DATA__): {e}")

    # --- 新フォーマット: self.__next_f.push (App Router、2025年以降) ---
    # HTMLの中に "status":"on_sale" などが直接埋め込まれている
    search_area = html[:500000]

    # ステータスを取得（エスケープされた場合・されていない場合両方に対応）
    status_match = re.search(
        r'\\?"status\\?":\s*\\?"(on_sale|sold_out|trading|stop)\\?"',
        search_area
    )
    if status_match:
        status = status_match.group(1)
        result = {"status": status, "name": "", "price": None}

        # 価格を取得（エスケープされた場合・されていない場合両方）
        price_match = re.search(
            r'\\?"price\\?":\s*(\d+)',
            search_area
        )
        if price_match:
            val = int(price_match.group(1))
            if 1 <= val <= 10000000:
                result["price"] = val

        # 商品名を取得
        name_patterns = [
            r'"name"\s*:\s*"([^"]{5,80})"',
            r'\\"name\\":\s*\\"([^\\"]{5,80})\\"',
        ]
        for npat in name_patterns:
            name_match = re.search(npat, search_area)
            if name_match:
                result["name"] = name_match.group(1)[:40]
                break

        log_debug(f"Mercariデータ抽出(新フォーマット): status={status}, price={result.get('price')}")
        return result

    return None


def scrape_mercari_full(mercari_url):
    try:
        wait_time = random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX)
        time.sleep(wait_time)

        html = _fetch_page(mercari_url, user_agent=MERCARI_UA)
        if not html:
            log_debug(f"Mercariページ取得失敗: {mercari_url}")
            return {"price": None, "sold": None, "name": "", "status_raw": ""}

        price = None
        sold = None
        name = ""
        status_raw = ""

        item_data = _extract_mercari_data(html)
        if item_data:
            raw_price = item_data.get("price")
            if raw_price and isinstance(raw_price, (int, float)):
                raw_price = int(raw_price)
                if 1 <= raw_price <= 10000000:
                    price = raw_price

            name = item_data.get("name", "")[:40]
            status = item_data.get("status", "")
            status_raw = status

            if status == "sold_out":
                sold = True
                log_info(f"Mercari売り切れ: {mercari_url} (sold_out)")
            elif status == "trading":
                sold = True
                log_info(f"Mercari取引中: {mercari_url} (trading)")
            elif status == "stop":
                sold = True
                log_info(f"Mercari出品停止: {mercari_url} (stop)")
            elif status == "on_sale":
                sold = False
                log_info(f"Mercari販売中: ¥{price:,} ({name}) [{status}] - {mercari_url}" if price else f"Mercari販売中: ({name}) [{status}] - {mercari_url}")

            if price and status != "on_sale":
                log_info(f"Mercari: ¥{price:,} ({name}) [{status}] - {mercari_url}")

        # --- フォールバック: application/ld+json ---
        if price is None and _bs4_available:
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    ld_data = json.loads(script.string)
                    if isinstance(ld_data, dict):
                        offers = ld_data.get("offers", {})
                        if isinstance(offers, dict):
                            p = offers.get("price")
                            if p:
                                val = int(float(p))
                                if 1 <= val <= 10000000:
                                    price = val
                                    log_info(f"Mercari価格(LD): ¥{price:,} - {mercari_url}")

                            avail = offers.get("availability", "")
                            if sold is None:
                                if "OutOfStock" in avail or "SoldOut" in avail:
                                    sold = True
                                elif "InStock" in avail:
                                    sold = False
                except Exception:
                    continue

        # --- フォールバック: 価格のJSONパターン ---
        if price is None:
            price_json = re.findall(r'"price"\s*:\s*(\d+)', html[:200000])
            for p in price_json:
                try:
                    val = int(p)
                    if 100 <= val <= 10000000:
                        price = val
                        log_info(f"Mercari価格(JSON): ¥{val:,} - {mercari_url}")
                        break
                except ValueError:
                    continue

        # --- フォールバック: ステータスパターンマッチング ---
        # ※item_dataが取得できなかった場合のみ実行
        if sold is None and not item_data:
            # まずon_saleを確認（誤検出防止のため先にチェック）
            if re.search(r'"status"\s*:\s*"on_sale"', html[:300000]):
                sold = False
                log_info(f"Mercari販売中(パターン): {mercari_url}")
            else:
                # 売り切れパターン（誤検出しにくい厳格なパターンのみ）
                strict_sold_patterns = [
                    r'"status"\s*:\s*"sold_out"',
                    r'"status"\s*:\s*"trading"',
                    r'"availability"[^"]*"OutOfStock"',
                    r'"availability"[^"]*"SoldOut"',
                    r'この商品は売り切れです',  # 「売り切れ」単独は除外（UI上に多数出現するため）
                ]
                for pattern in strict_sold_patterns:
                    if re.search(pattern, html[:300000], re.IGNORECASE):
                        sold = True
                        log_info(f"Mercari売り切れ(パターン): {mercari_url}")
                        break

                if sold is None:
                    log_debug(f"Mercariステータス不明: {mercari_url}")

        return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}

    except Exception as e:
        log_error(f"Mercariスクレイピングエラー: {mercari_url} - {e}")
        return {"price": None, "sold": None, "name": "", "status_raw": ""}


def scrape_mercari_price(mercari_url):
    result = scrape_mercari_full(mercari_url)
    return result["price"]


def scrape_mercari_sold_status(mercari_url):
    result = scrape_mercari_full(mercari_url)
    return result["sold"]


def scrape_ebay_price(ebay_url):
    from ebay_controller import get_ebay_item_price
    return get_ebay_item_price(ebay_url)


# ============================================================
# 仕入先サイト判定
# ============================================================

def detect_source(url):
    if not url:
        return "unknown"
    u = url.lower()
    if "jp.mercari.com" in u or ("mercari.com" in u and "/item/" in u):
        return "mercari"
    if "auctions.yahoo.co.jp" in u or "page.auctions.yahoo.co.jp" in u:
        return "yahooauction"
    if "item.rakuten.co.jp" in u:
        return "rakuten"
    if "amazon.co.jp" in u or ("amazon.com" in u and "/dp/" in u):
        return "amazon"
    if "store.shopping.yahoo.co.jp" in u or ("shopping.yahoo.co.jp" in u and "/product/" in u):
        return "yahooshopping"
    if "fril.jp" in u or "rakuma.rakuten.co.jp" in u:
        return "rakuma"
    return "unknown"


# ============================================================
# ヤフオク スクレイパー
# ============================================================

def scrape_yahooauction_full(url):
    try:
        time.sleep(random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX))
        html = _fetch_page(url, user_agent=MERCARI_UA)
        if not html:
            return {"price": None, "sold": None, "name": "", "status_raw": ""}

        price = None
        sold = None
        name = ""
        status_raw = ""

        # JSON-LD からデータ取得
        if _bs4_available:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    d = json.loads(script.string or "")
                    if isinstance(d, dict) and d.get("@type") in ("Product", "Offer"):
                        offers = d.get("offers", d)
                        avail = str(offers.get("availability", "")).lower()
                        if "outofstock" in avail or "soldout" in avail:
                            sold = True
                            status_raw = "ended"
                        elif "instock" in avail or "preorder" in avail:
                            sold = False
                            status_raw = "active"
                        p = offers.get("price") or d.get("price")
                        if p:
                            val = int(float(str(p).replace(",", "")))
                            if 1 <= val <= 100000000:
                                price = val
                        name = str(d.get("name", ""))[:40]
                except Exception:
                    pass

        # 埋め込みJSON パターン（Yahoo Auctions独自フォーマット）
        if sold is None:
            # オークション終了判定
            ended_patterns = [
                r'"isEnded"\s*:\s*true',
                r'"status"\s*:\s*"closed"',
                r'"endStatus"\s*:\s*"(?:closed|ended|sold)"',
                r'class="[^"]*ended[^"]*"',
                r'このオークションは終了しています',
                r'オークションは終了しました',
            ]
            for pat in ended_patterns:
                if re.search(pat, html, re.IGNORECASE):
                    sold = True
                    status_raw = "ended"
                    break

        if sold is None:
            # 出品中 / 入札受付中
            active_patterns = [
                r'"isEnded"\s*:\s*false',
                r'"status"\s*:\s*"(?:open|active|bidding)"',
                r'入札する',
                r'即決価格',
                r'残り\d+',
            ]
            for pat in active_patterns:
                if re.search(pat, html, re.IGNORECASE):
                    sold = False
                    status_raw = "active"
                    break

        # 価格パターン
        if price is None:
            price_patterns = [
                r'"currentPrice"\s*:\s*(\d+)',
                r'"price"\s*:\s*(\d+)',
                r'"bidPrice"\s*:\s*(\d+)',
                r'現在\s*</[^>]+>\s*<[^>]+>\s*(\d[\d,]+)\s*円',
                r'即決\s*</[^>]+>\s*<[^>]+>\s*(\d[\d,]+)\s*円',
            ]
            for pat in price_patterns:
                m = re.search(pat, html[:300000])
                if m:
                    try:
                        val = int(m.group(1).replace(",", ""))
                        if 1 <= val <= 100000000:
                            price = val
                            break
                    except Exception:
                        pass

        # 商品名
        if not name:
            m = re.search(r'"title"\s*:\s*"([^"]{5,80})"', html[:200000])
            if m:
                name = m.group(1)[:40]
            if not name and _bs4_available:
                from bs4 import BeautifulSoup
                soup2 = BeautifulSoup(html, "html.parser")
                h1 = soup2.find("h1")
                if h1:
                    name = h1.get_text(strip=True)[:40]

        if sold is True:
            log_info(f"ヤフオク終了: {url} ({status_raw})")
        elif sold is False:
            log_info(f"ヤフオク出品中: ¥{price:,} ({name}) - {url}" if price else f"ヤフオク出品中: {url}")

        return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}
    except Exception as e:
        log_error(f"ヤフオクスクレイピングエラー: {url} - {e}")
        return {"price": None, "sold": None, "name": "", "status_raw": ""}


# ============================================================
# 楽天市場 スクレイパー
# ============================================================

def scrape_rakuten_full(url):
    try:
        time.sleep(random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX))
        html = _fetch_page(url, user_agent=MERCARI_UA)
        if not html:
            return {"price": None, "sold": None, "name": "", "status_raw": ""}

        price = None
        sold = None
        name = ""
        status_raw = ""

        # JSON-LD からデータ取得
        if _bs4_available:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    d = json.loads(script.string or "")
                    if isinstance(d, dict):
                        offers = d.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        avail = str(offers.get("availability", "")).lower()
                        if "outofstock" in avail:
                            sold = True
                            status_raw = "out_of_stock"
                        elif "instock" in avail:
                            sold = False
                            status_raw = "on_sale"
                        p = offers.get("price") or offers.get("lowPrice")
                        if p:
                            val = int(float(str(p).replace(",", "")))
                            if 1 <= val <= 100000000:
                                price = val
                        name = str(d.get("name", ""))[:40]
                except Exception:
                    pass

        # 在庫なしパターン
        if sold is None:
            oos_patterns = [
                r'品切れ|在庫なし|在庫切れ|売り切れ|完売|SOLD\s*OUT|soldout',
                r'"availability"\s*:\s*"(?:OutOfStock|SoldOut)"',
                r'class="[^"]*soldout[^"]*"',
                r'ただいま品切れ',
                r'この商品は現在販売しておりません',
            ]
            for pat in oos_patterns:
                if re.search(pat, html[:400000], re.IGNORECASE):
                    sold = True
                    status_raw = "out_of_stock"
                    break

        if sold is None:
            if re.search(r'カートに入れる|買い物かごに入れる|add-to-cart|addToCart', html[:400000], re.IGNORECASE):
                sold = False
                status_raw = "on_sale"

        # 価格パターン
        if price is None:
            price_pats = [
                r'"price"\s*:\s*(\d+)',
                r'class="[^"]*price[^"]*"[^>]*>\s*[¥￥]?\s*([\d,]+)',
                r'[¥￥]\s*([\d,]+)',
            ]
            for pat in price_pats:
                m = re.search(pat, html[:300000])
                if m:
                    try:
                        val = int(m.group(1).replace(",", ""))
                        if 100 <= val <= 100000000:
                            price = val
                            break
                    except Exception:
                        pass

        if sold is True:
            log_info(f"楽天品切れ: {url}")
        elif sold is False:
            log_info(f"楽天販売中: ¥{price:,} ({name}) - {url}" if price else f"楽天販売中: {url}")

        return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}
    except Exception as e:
        log_error(f"楽天スクレイピングエラー: {url} - {e}")
        return {"price": None, "sold": None, "name": "", "status_raw": ""}


# ============================================================
# Amazon Japan スクレイパー
# ============================================================

def scrape_amazon_full(url):
    try:
        time.sleep(random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX))
        # Amazon は複数UAを試す
        uas = [
            MERCARI_UA,
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]
        html = None
        for ua in uas:
            html = _fetch_page(url, user_agent=ua)
            if html and len(html) > 5000:
                break

        if not html:
            return {"price": None, "sold": None, "name": "", "status_raw": ""}

        price = None
        sold = None
        name = ""
        status_raw = ""

        # JSON-LD
        if _bs4_available:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    d = json.loads(script.string or "")
                    if isinstance(d, dict):
                        offers = d.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        avail = str(offers.get("availability", "")).lower()
                        if "outofstock" in avail:
                            sold = True
                            status_raw = "out_of_stock"
                        elif "instock" in avail:
                            sold = False
                            status_raw = "on_sale"
                        p = offers.get("price") or offers.get("lowPrice")
                        if p:
                            val = int(float(str(p).replace(",", "")))
                            if 1 <= val <= 100000000:
                                price = val
                        name = str(d.get("name", ""))[:40]
                except Exception:
                    pass

        # Amazonの在庫テキスト判定
        if sold is None:
            oos_patterns = [
                r'現在在庫切れ',
                r'一時的に在庫切れ',
                r'この商品は現在お取り扱いできません',
                r'Currently unavailable',
                r'out of stock',
                r'"availability"\s*:\s*"OutOfStock"',
            ]
            for pat in oos_patterns:
                if re.search(pat, html, re.IGNORECASE):
                    sold = True
                    status_raw = "out_of_stock"
                    break

        if sold is None:
            in_stock_patterns = [
                r'在庫あり',
                r'通常\d+～\d+日以内',
                r'カートに入れる',
                r'今すぐ購入',
                r'"availability"\s*:\s*"InStock"',
            ]
            for pat in in_stock_patterns:
                if re.search(pat, html, re.IGNORECASE):
                    sold = False
                    status_raw = "on_sale"
                    break

        # 価格
        if price is None:
            price_patterns = [
                r'"priceAmount"\s*:\s*"?([\d.]+)"?',
                r'class="a-price-whole"[^>]*>([\d,]+)',
                r'"price"\s*:\s*(\d+)',
                r'[¥￥]\s*([\d,]+)',
            ]
            for pat in price_patterns:
                m = re.search(pat, html[:300000])
                if m:
                    try:
                        val = int(float(m.group(1).replace(",", "")))
                        if 100 <= val <= 100000000:
                            price = val
                            break
                    except Exception:
                        pass

        # 商品名
        if not name and _bs4_available:
            from bs4 import BeautifulSoup
            soup2 = BeautifulSoup(html, "html.parser")
            h1 = soup2.find("span", id="productTitle") or soup2.find("h1", id="title")
            if h1:
                name = h1.get_text(strip=True)[:40]

        if sold is True:
            log_info(f"Amazon在庫切れ: {url}")
        elif sold is False:
            log_info(f"Amazon在庫あり: ¥{price:,} ({name}) - {url}" if price else f"Amazon在庫あり: {url}")

        return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}
    except Exception as e:
        log_error(f"Amazonスクレイピングエラー: {url} - {e}")
        return {"price": None, "sold": None, "name": "", "status_raw": ""}


# ============================================================
# Yahoo!ショッピング スクレイパー
# ============================================================

def scrape_yahooshopping_full(url):
    try:
        time.sleep(random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX))
        html = _fetch_page(url, user_agent=MERCARI_UA)
        if not html:
            return {"price": None, "sold": None, "name": "", "status_raw": ""}

        price = None
        sold = None
        name = ""
        status_raw = ""

        # JSON-LD
        if _bs4_available:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    d = json.loads(script.string or "")
                    if isinstance(d, dict):
                        offers = d.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        avail = str(offers.get("availability", "")).lower()
                        if "outofstock" in avail:
                            sold = True
                            status_raw = "out_of_stock"
                        elif "instock" in avail:
                            sold = False
                            status_raw = "on_sale"
                        p = offers.get("price") or offers.get("lowPrice")
                        if p:
                            val = int(float(str(p).replace(",", "")))
                            if 1 <= val <= 100000000:
                                price = val
                        name = str(d.get("name", ""))[:40]
                except Exception:
                    pass

        # 在庫判定
        if sold is None:
            oos_pats = [
                r'在庫切れ|品切れ|売り切れ|完売|SOLD\s*OUT',
                r'"soldOut"\s*:\s*true',
                r'class="[^"]*soldOut[^"]*"',
            ]
            for pat in oos_pats:
                if re.search(pat, html[:400000], re.IGNORECASE):
                    sold = True
                    status_raw = "out_of_stock"
                    break

        if sold is None:
            if re.search(r'カートに入れる|今すぐ購入|買い物かごに入れる', html[:400000], re.IGNORECASE):
                sold = False
                status_raw = "on_sale"

        # 価格
        if price is None:
            price_pats = [
                r'"price"\s*:\s*(\d+)',
                r'"salePrice"\s*:\s*(\d+)',
                r'[¥￥]([\d,]+)',
            ]
            for pat in price_pats:
                m = re.search(pat, html[:300000])
                if m:
                    try:
                        val = int(m.group(1).replace(",", ""))
                        if 100 <= val <= 100000000:
                            price = val
                            break
                    except Exception:
                        pass

        if sold is True:
            log_info(f"Yahooショッピング在庫切れ: {url}")
        elif sold is False:
            log_info(f"Yahooショッピング販売中: ¥{price:,} ({name}) - {url}" if price else f"Yahooショッピング販売中: {url}")

        return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}
    except Exception as e:
        log_error(f"Yahooショッピングスクレイピングエラー: {url} - {e}")
        return {"price": None, "sold": None, "name": "", "status_raw": ""}


# ============================================================
# ラクマ (Rakuma / Fril) スクレイパー
# ============================================================

def _extract_fril_item_id(url):
    """fril.jp / rakuma.rakuten.co.jp の商品IDを抽出"""
    m = re.search(r'/item/([a-f0-9]{32}|[a-zA-Z0-9_-]{10,})', url)
    return m.group(1) if m else None


def scrape_rakuma_full(url):
    try:
        time.sleep(random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX))

        price = None
        sold = None
        name = ""
        status_raw = ""

        # --- ラクマ公開API を最初に試す ---
        item_id = _extract_fril_item_id(url)
        if item_id:
            api_url = f"https://api.fril.jp/v2/items/{item_id}"
            api_result = subprocess.run(
                ["curl", "-s", "-L", "--compressed", "--max-time", "10",
                 "-H", "Accept: application/json",
                 "-A", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                 api_url],
                capture_output=True, timeout=15
            )
            if api_result.returncode == 0 and api_result.stdout:
                try:
                    raw = api_result.stdout.decode("utf-8", errors="replace")
                    api_data = json.loads(raw)
                    # 404 = 商品なし（削除済み/売り切れ）
                    if api_data.get("status") == 404 or api_data.get("error") == "Not Found":
                        sold = True
                        status_raw = "not_found"
                        log_info(f"ラクマAPI: 商品なし(削除済/売り切れ) id={item_id}")
                    else:
                        item = api_data.get("item", api_data)
                        if isinstance(item, dict):
                            p = item.get("price") or item.get("selling_price")
                            if p:
                                val = int(float(str(p).replace(",", "")))
                                if 1 <= val <= 10000000:
                                    price = val
                            st = str(item.get("status", "")).lower()
                            name = str(item.get("name", "") or item.get("title", ""))[:40]
                            status_raw = st
                            if st in ("sold_out", "stop", "closed", "trading", "2", "3"):
                                sold = True
                            elif st in ("on_sale", "selling", "1") or price:
                                sold = False
                            log_info(f"ラクマAPI: status={st}, price={price}, id={item_id}")
                except Exception as e:
                    log_debug(f"ラクマAPIレスポンス解析エラー: {e}")

        # --- HTMLページ取得 (APIで取得できなかった場合) ---
        if sold is None:
            # item.fril.jp に正規化
            norm_url = url
            if item_id and "fril.jp" not in url and "rakuma" in url:
                norm_url = f"https://item.fril.jp/{item_id}"
            html = _fetch_page(norm_url, user_agent=MERCARI_UA)
            if not html:
                return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}

            # JSON-LD
            if _bs4_available:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        d = json.loads(script.string or "")
                        if isinstance(d, dict):
                            offers = d.get("offers", {})
                            if isinstance(offers, list):
                                offers = offers[0] if offers else {}
                            avail = str(offers.get("availability", "")).lower()
                            if "outofstock" in avail or "soldout" in avail:
                                sold = True
                                status_raw = "sold_out"
                            elif "instock" in avail:
                                sold = False
                                status_raw = "on_sale"
                            p = offers.get("price")
                            if p:
                                val = int(float(str(p).replace(",", "")))
                                if 1 <= val <= 10000000:
                                    price = val
                            name = str(d.get("name", "") or soup.find("meta", property="og:title", content=True) or "")[:40]
                    except Exception:
                        pass

                # og: タグからデータ抽出（fril.jpはSSR og: tags）
                if sold is None:
                    og_title = soup.find("meta", property="og:title")
                    og_desc = soup.find("meta", property="og:description")
                    og_title_str = (og_title.get("content", "") if og_title else "")
                    og_desc_str = (og_desc.get("content", "") if og_desc else "")

                    if og_title_str and not name:
                        name = og_title_str[:40]

                    # SOLD OUT / 売り切れ キーワード in og
                    if re.search(r'SOLD\s*OUT|売り切れ|購入済み', og_title_str + og_desc_str, re.IGNORECASE):
                        sold = True
                        status_raw = "sold_out"
                    elif og_title_str and price is None:
                        # og:title or description に価格が入っていることがある
                        p_og = _extract_og_price(html)
                        if p_og:
                            price = p_og
                            if sold is None:
                                sold = False
                                status_raw = "on_sale"

            # 埋め込みJSON ステータス
            if sold is None:
                status_match = re.search(
                    r'"status"\s*:\s*"((?:on_sale|sold_out|trading|stop|closed))"',
                    html[:500000]
                )
                if status_match:
                    st = status_match.group(1)
                    status_raw = st
                    sold = st in ("sold_out", "trading", "stop", "closed")

            # テキストパターンフォールバック
            if sold is None:
                for pat in [r'SOLD\s*OUT', r'売り切れ', r'購入済み', r'"sold"\s*:\s*true']:
                    if re.search(pat, html[:400000], re.IGNORECASE):
                        sold = True
                        status_raw = "sold_out"
                        break

            if sold is None and re.search(r'購入する|カートに追加|いますぐ購入', html[:400000], re.IGNORECASE):
                sold = False
                status_raw = "on_sale"

            # 価格フォールバック
            if price is None:
                for pat in [r'"price"\s*:\s*(\d+)', r'[¥￥]\s*([\d,]+)']:
                    m = re.search(pat, html[:300000])
                    if m:
                        try:
                            val = int(m.group(1).replace(",", ""))
                            if 100 <= val <= 10000000:
                                price = val
                                break
                        except Exception:
                            pass

        if sold is True:
            log_info(f"ラクマ売り切れ: {url}")
        elif sold is False:
            log_info(f"ラクマ販売中: ¥{price:,} ({name}) - {url}" if price else f"ラクマ販売中: {url}")
        else:
            log_debug(f"ラクマ状態不明: {url}")

        return {"price": price, "sold": sold, "name": name, "status_raw": status_raw}
    except Exception as e:
        log_error(f"ラクマスクレイピングエラー: {url} - {e}")
        return {"price": None, "sold": None, "name": "", "status_raw": ""}


# ============================================================
# 統合スクレイパー（URLから自動判定）
# ============================================================

def scrape_source_full(source_url):
    source = detect_source(source_url)
    if source == "mercari":
        return scrape_mercari_full(source_url)
    elif source == "yahooauction":
        return scrape_yahooauction_full(source_url)
    elif source == "rakuten":
        return scrape_rakuten_full(source_url)
    elif source == "amazon":
        return scrape_amazon_full(source_url)
    elif source == "yahooshopping":
        return scrape_yahooshopping_full(source_url)
    elif source == "rakuma":
        return scrape_rakuma_full(source_url)
    else:
        log_error(f"対応していないURL: {source_url}")
        return {"price": None, "sold": None, "name": "", "status_raw": "unsupported"}
