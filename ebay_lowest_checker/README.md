# eBay Condition Lowest Checker

独立デプロイ用の最安値チェッカーです。  
既存の在庫管理アプリとは分離して動作します。

## 1. 機能

- 同一商品のコンディション別最安値検索
- 監視対象 URL の定期チェック
- 自分の価格より安い出品を検知したら通知
- 任意で自動価格改定フロー（現状はフック実装）
- 実行ログを SQLite に保存

## 2. 監視元スプレッドシート（sheet1）

ヘッダー行は以下を使用してください。

`product_key,search_keyword,condition,target_url,target_price,floor_price,alert_enabled,auto_reprice,active`

例:

- `SWITCH-001,Nintendo Switch HAC-001,Used,https://www.ebay.com/itm/xxxx,239.99,219.99,true,false,true`

## 3. 環境変数

- `SPREADSHEET_ID`: Google Sheets の ID
- `GOOGLE_SERVICE_ACCOUNT_JSON`: サービスアカウント JSON を文字列で
- `EBAY_BROWSE_TOKEN`: eBay Browse API の OAuth トークン
- `CHECK_INTERVAL_MINUTES`: 既定 360 (6時間)
- `DISCORD_WEBHOOK_URL`: 任意
- `AUTO_REPRICE_ENABLED`: `true/false`（既定 false）
- `AUTO_REPRICE_DRY_RUN`: `true/false`（既定 true）

## 4. 起動

```bash
pip install -r requirements.txt
python app.py
```

## 5. API

- `POST /api/check/run`: 手動1回チェック
- `POST /api/check/start`: 定期監視開始
- `POST /api/check/stop`: 定期監視停止
- `GET /api/check/status`: 状態取得
- `GET /api/logs`: 直近ログ取得

## 6. 自動価格改定について

`ebay_client.py` の `revise_own_listing_price()` は、  
あなたの eBay 本番認証情報に合わせて実装する前提のフックです。
