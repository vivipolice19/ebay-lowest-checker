# eBay Condition Lowest Checker

独立デプロイ用の最安値チェッカーです。  
既存の在庫管理アプリとは分離して動作します。

## 1. 機能

- 同一商品のコンディション別最安値検索
- 監視対象 URL の定期チェック
- 自分の価格より安い出品を検知したら通知
- 任意で自動価格改定フロー（現状はフック実装）
- 実行ログを SQLite に保存

## 2. 管理画面

- `/` にアクセスすると、以下の操作が可能です
  - 商品キーワード入力 -> コンディション別最安値表示
  - 監視URL登録
  - 手動チェック / 定期監視開始・停止
  - 監視一覧表示（シートの状態）

## 3. 監視元スプレッドシート（sheet1）

必要ヘッダー（不足分は自動追加されます）:

`product_key,search_keyword,target_url,own_price,floor_price,alert_enabled,auto_reprice,active,monitor_status,last_checked,min_new,min_open_box,min_used,min_seller_refurbished,min_certified_refurbished,min_for_parts,min_url,note`

`own_price` はシート側の値を優先して監視に使います。

## 4. 環境変数

- `SPREADSHEET_ID`: Google Sheets の ID
- `GOOGLE_SERVICE_ACCOUNT_JSON`: サービスアカウント JSON を文字列で
- `EBAY_BROWSE_TOKEN`: eBay Browse API の OAuth トークン
- `CHECK_INTERVAL_MINUTES`: 既定 360 (6時間)
- `DISCORD_WEBHOOK_URL`: 任意
- `AUTO_REPRICE_ENABLED`: `true/false`（既定 false）
- `AUTO_REPRICE_DRY_RUN`: `true/false`（既定 true）

## 5. 起動

```bash
pip install -r requirements.txt
python app.py
```

## 6. API

- `POST /api/check/run`: 手動1回チェック
- `POST /api/check/start`: 定期監視開始
- `POST /api/check/stop`: 定期監視停止
- `GET /api/check/status`: 状態取得
- `GET /api/search/conditions?keyword=`: コンディション別最安値検索
- `POST /api/watch/add`: 監視行をシートに追加
- `GET /api/watch/list`: 監視行一覧
- `GET /api/logs`: 直近ログ取得

## 7. 自動価格改定について

`ebay_client.py` の `revise_own_listing_price()` は、  
あなたの eBay 本番認証情報に合わせて実装する前提のフックです。
