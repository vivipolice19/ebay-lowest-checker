# Mercari → eBay 在庫同期ツール

## Overview
日本→eBay在庫同期ツール。スプレッドシートが主要インターフェース。仕入先URLとeBayのURLをスプレッドシートに貼り付けると、仕入れ値・売値を自動取得し、売り切れ時にeBay在庫を0に変更。利益率は任意入力。50人以上への配布対応。

**対応仕入先サイト**: メルカリ / ヤフオク / 楽天市場 / Amazon.co.jp / Yahoo!ショッピング / ラクマ(fril.jp)

## Architecture
- **Language**: Python 3.11
- **Web Framework**: Flask (port 5000) - ダッシュボード/設定用
- **Primary Interface**: Google Spreadsheet (スプレッドシートで全管理)
- **Multi-Source Scraping**: curl + Googlebot UA. detect_source(url) → scrape_source_full(url) で自動判定+スクレイプ
  - Mercari: __NEXT_DATA__ / __next_f.push JSON解析
  - ヤフオク: LD+JSON / 埋め込みRedux state JSON
  - 楽天: LD+JSON / カートテキストパターン
  - Amazon: LD+JSON / 在庫テキストパターン (クラウドIPブロックあり)
  - Yahoo!ショッピング: LD+JSON / soldOutパターン
  - ラクマ: fril.jp公開API (api.fril.jp/v2/items/{id}) / LD+JSON / og:タグ
- **eBay Price Fetch**: eBay Browse API (OAuth Client Credentials). Requires ebay_client_id + ebay_client_secret in settings.
- **Sold Detection**: Integrated into sync loop. Status field + fallback text patterns per source.
- **eBay Inventory Update**: eBay Trading API (ReviseItem). Requires ebay_oauth_token (User Auth Token) in settings.
- **Database**: SQLite (WAL mode, thread-safe)
- **Sheets Auth**: Replit OAuth (開発) / サービスアカウントJSON (配布版)

## Project Structure
```
ebay_stock_manager/
  main.py              - エントリーポイント (web/desktop切替)
  web_app.py           - Flask Webダッシュボード
  database.py          - SQLiteデータベース操作
  price_scraper.py     - Mercari 価格+ステータス統合スクレイピング (curl+BS4)
  ebay_controller.py   - eBay API統合 (Browse API価格取得 + Trading API在庫更新)
  sheets_connector.py  - Google Sheets認証 (Replit OAuth/サービスアカウント)
  sheets_sync.py       - スプレッドシート同期エンジン (価格取得+売切れ検出+eBay更新統合)
  profit_monitor.py    - 利益計算・為替レート・アラート
  monitor.py           - 旧売切れ監視 (Playwright依存、未使用)
  scraper.py           - 旧スクレイパー (Playwright依存、未使用)
  notifier.py          - LINE/メール通知
  logger.py            - ログシステム
  config.py            - 設定値
  templates/           - HTMLテンプレート
  static/              - CSS/JS
  database/            - SQLiteデータベース
wsgi.py                - デプロイ用エントリーポイント
```

## Sync Loop (sheets_sync.py - Core Engine)
Every sync cycle (default 2 minutes):
1. Read spreadsheet URLs
2. For each product: scrape Mercari price + sold status (single HTTP request via curl)
3. Fetch eBay price via Browse API (OAuth Application Token, auto-refresh)
4. If Mercari sold_out/trading/stop → mark out_of_stock → try Trading API to set quantity=0
5. Update spreadsheet columns C-H
6. Apply conditional formatting

## Spreadsheet Column Layout (Primary Interface)
- A: Mercari URL (ユーザー入力)
- B: eBay URL (ユーザー入力)
- C: 仕入値(円) (自動取得 - 毎回再取得)
- D: 売値(USD) (自動取得 - eBay Browse API)
- E: 利益率(%) (任意ユーザー入力、未入力ならそのまま)
- F: 状態 (自動: 監視中/売り切れ/取引中)
- G: アラート (自動: 正常/警告/危険/要eBay停止)
- H: 最終チェック (自動タイムスタンプ)

## eBay API Integration (ebay_controller.py)
### Browse API (価格取得)
- OAuth Client Credentials flow → Application Access Token (2時間有効、自動更新)
- GET /buy/browse/v1/item/get_item_by_legacy_id → item price
- Settings: ebay_client_id, ebay_client_secret
- Web scraping does NOT work (eBay returns ChallengeGet/CAPTCHA page from server IPs)

### Trading API (在庫更新)
- ReviseItem XML to set quantity=0 when Mercari sold out
- Settings: ebay_oauth_token (User Auth Token)

## Key Technical Notes
- **CRITICAL**: Playwright does NOT work in this Replit env (missing shared libs). All scraping uses curl subprocess.
- **Mercari SSR**: Must use Googlebot UA to get __NEXT_DATA__ with item data. Normal browser UA returns SPA shell with no product data.
- **eBay web scraping BROKEN**: eBay returns bot detection ChallengeGet page for ALL curl/requests from server IPs. Must use Browse API.
- **scrape_mercari_full()**: Single function returns {price, sold, name, status_raw} from one HTTP request.
- **Token caching**: eBay Application Token cached in memory with expiry check.

## Auth Modes
- **Replit環境**: REPLIT_CONNECTORS_HOSTNAMEで自動検出→OAuth
- **配布版**: credentials.jsonパス指定→サービスアカウント

## Deployment
- wsgi.py at workspace root, fixed LD_LIBRARY_PATH
- VM deployment with gunicorn, 1 sync worker

## Current Spreadsheet
- ID: 1j-SK1yrXw2Sl_3-LakDHe6FMh23v64wDPYZvlg84Gug
- URL: https://docs.google.com/spreadsheets/d/1j-SK1yrXw2Sl_3-LakDHe6FMh23v64wDPYZvlg84Gug
