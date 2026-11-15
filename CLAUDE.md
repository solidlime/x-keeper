# CLAUDE.md

> セッション開始時に必ず AGENTS.md を読み込むこと。

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 開発コマンド

```bash
# Docker (推奨)
docker compose up -d
docker compose logs -f
docker compose down

# ローカル実行 (開発・デバッグ用)
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/Mac
.venv/Scripts/python -m src.main   # または start.bat / start.sh
```

テストは `pytest`（`.venv/bin/python -m pytest -q`）。インポートチェックは `python -c "from src.XXX import YYY"`。

## アーキテクチャ

### 処理フロー

```
python -m src.main
├── Flask (src/web/) をデーモンスレッドでポート 8989 に起動
│   └── Ctrl+C で終了するまで起動しっぱなし (ギャラリー閲覧・API用)
├── LogStore を開いて `reset_processing_urls()` でクラッシュ復旧 (処理中→pending)
└── API キュー処理ループ (asyncio)
     ├── RETRY_POLL_INTERVAL 秒ごとに `pop_api_queue()` で 1 件取得
     ├── URL 種別を判定してダウンロード
     │    ├── X /media URL → MediaDownloader.download_user_media(url)
     │    ├── X status URL → MediaDownloader.download_all([url])
     │    └── Pixiv / Imgur / YouTube 等 → MediaDownloader.download_direct([url])
     ├── 成功: complete_api_url() / 失敗: fail_api_url() (60/300/900 秒後、最大 3 回)
     └── 完了/失敗時 notify_download() で NOTIFY_WEBHOOK_URL へ POST
```

URL の投入元は Chrome 拡張・Android アプリ（`POST /api/queue`）と Web UI（`/queue`）。Discord Bot は廃止済み。

### モジュール構成

| ファイル | 役割 |
|---|---|
| `src/main.py` | エントリーポイント・asyncio ループ・Flask デーモン起動 |
| `src/config.py` | `pydantic-settings` による設定クラス (`Settings`) |
| `src/models.py` | データクラス: `TweetThread`, `SavedFile`, `DownloadResult` |
| `src/patterns.py` | URL 正規表現を一元管理 (X / Pixiv / Imgur / YT_DLP) |
| `src/image_downloader.py` | `gallery-dl` / `yt-dlp` でメディアをダウンロードし `list[SavedFile]` を返す |
| `src/log_store.py` | SQLite 永続化 (`download_log` / `downloaded_ids` / `downloaded_urls` / `api_queue`)・API キュー・ストレージ統計 |
| `src/notify.py` | `NOTIFY_WEBHOOK_URL` へのダウンロード結果通知 (`notify_download`) |
| `src/web_setup.py` | `src/web/` パッケージへの薄いシム (後方互換) |
| `src/web/__init__.py` | Flask app + CORS + Blueprint 登録 + secret_key |
| `src/web/auth.py` | API トークン認証 (`require_api_token` / `is_authenticated` / `session_secret`) |
| `src/web/globals.py` | `_log_store` グローバル管理 |
| `src/web/utils.py` | 定数 + ユーティリティ関数 |
| `src/web/templates.py` | 全 HTML テンプレート文字列 |
| `src/web/routes/setup.py` | セットアップ UI (`/`, `/save-*`, `/pixiv-oauth/*`) |

### 環境変数 / .env

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `API_TOKEN` | — | — | API トークン。設定すると `/api/*` と設定変更系ルートが保護される |
| `NOTIFY_WEBHOOK_URL` | — | — | ダウンロード完了/失敗時に JSON を POST する Webhook URL |
| `GALLERY_DL_COOKIES_FILE` | — | — | gallery-dl に渡す Cookie ファイルパス (鍵垢対応) |
| `PIXIV_REFRESH_TOKEN` | — | — | Pixiv OAuth リフレッシュトークン |
| `SAVE_PATH` | — | `./data` | メディア保存先ルートディレクトリ |
| `WEB_SETUP_PORT` | — | `8989` | Web サーバーポート番号 |
| `RETRY_POLL_INTERVAL` | — | `30` | API キューのポーリング間隔 (秒) |
| `GALLERY_THUMB_COUNT` | — | `50` | ギャラリートップで先読みするサムネイル数 |
| `LOG_LEVEL` | — | `INFO` | ログレベル (DEBUG/INFO/WARNING/ERROR) |

### 認証 (`src/web/auth.py`)

- `API_TOKEN` 未設定 → 全リクエスト素通し (後方互換)。設定時のみ認証を要求
- 保護対象: `/api/*` (`/api/health` と OPTIONS を除く)。`/api/gallery/*` は `bp_gallery` の `before_request` で保護
- 設定変更系 POST/GET も保護: `/save-cookies` `/save-bot-config` `/save-pixiv-token` `/save-api-token` `/pixiv-oauth/*` `/delete-media`
- 受理ヘッダ: `X-API-Token: <token>` または `Authorization: Bearer <token>`
- 401 は `{"error": "unauthorized"}` (拡張/Android はこれでトークン不一致を判定)
- トークンは環境変数 → `.env` の順に解決。UI から保存すると `.env` に書き込まれる (プロセス再起動で有効)
- `app.secret_key` は `session_secret()` = トークンの SHA-256 由来。トークン未設定時のみランダム。UI で保存するとセッション認証されるため、再起動後もブラウザから操作可能
- 既にトークン設定済みの状態で別トークンに差し替えるには認証が必要 (同じトークンを保存し直すとログイン扱い)

### 重要な設計上の注意点

**API キュー** (`src/log_store.py` の `api_queue` テーブル):
- `queue_url_download()` は UPSERT。`done`/`failed` の URL を再投入すると `pending` に戻るが、待機/実行中なら重複追加しない
- `pop_api_queue()` が `pending` → `running` に遷移させて 1 件返す (アトミック)
- 失敗時は `requeue_api_url()` で 60/300/900 秒後に再試行 (`max_attempts=3`)。超過で `failed`
- 起動時の `reset_processing_urls()` で `running`/`processing` を `pending` に戻す (クラッシュ復旧)
- 完了/失敗レコードは `_prune_queue_history()` で古いものから削除される

**対応サービス**:
- **X (Twitter) status**: URL パターン `twitter.com|x.com/*/status/*`。スレッド遡り対応
- **X ユーザーメディア欄**: URL パターン `twitter.com|x.com/*/media`。ユーザーの全メディアを一括ダウンロード
- **Pixiv**: URL パターン `pixiv.net/*/artworks/*`。`PIXIV_REFRESH_TOKEN` が必要
- **Imgur**: URL パターン `imgur.com/*`（アルバム・ギャラリー・単体画像・i.imgur.com 直リンク）
- **YouTube / TikTok / NicoNico**: `yt-dlp` で動画をダウンロード (F1)。`YT_DLP_URL_PATTERN` が一致した URL を自動検出

**gallery-dl の使い方 (2 フェーズ)**:
- フェーズ 1 (`TwitterClient`): `--dump-json` でメタデータのみ取得し `reply_id` を解析してスレッドを遡る
  - 出力フォーマット: stdout 全体が1つの JSON 配列 `[[type, metadata], [type, url, metadata], ...]`
  - type=2: ツイートメタデータ、type=3: ダウンロード対象ファイル
- フェーズ 2 (`MediaDownloader`): URL リストを `-D <dest>` でダウンロード。新規ファイルはディレクトリ差分で特定する

**cookies あり時の差異**: `--cookies` + `extractor.twitter.conversations=true` を追加することでスレッド全体を 1 コマンドで取得できる

**保存先**: デフォルト `./data`（実行ディレクトリ基準）。日付サブフォルダ (`YYYY-MM-DD`) が自動作成される。

**ルート (Blueprint 別)**:

| ルート | 説明 |
|---|---|
| `GET /` | セットアップフォーム (クエリパラメータなしなら `/gallery` にリダイレクト) |
| `GET /?setup=1` | セットアップフォームを強制表示 |
| `POST /save-cookies` | Cookie ファイルパスの保存 🔒 |
| `POST /save-api-token` | API トークンの保存/自動生成/無効化 (アクション: `save` / `generate` / `disable`) 🔒 |
| `POST /save-pixiv-token` | Pixiv リフレッシュトークンの手動保存 🔒 |
| `GET /pixiv-oauth/start` | Pixiv OAuth PKCE 開始 (JSON レスポンス) 🔒 |
| `POST /pixiv-oauth/exchange` | code → refresh_token 交換・保存 🔒 |
| `GET /pixiv-oauth/cancel` | OAuth セッションクリア 🔒 |
| `POST /save-bot-config` | RETRY_POLL_INTERVAL / GALLERY_THUMB_COUNT の保存 🔒 |
| `GET /gallery` | ギャラリートップ。日付アコーディオン + 先読みサムネイル + 無限スクロール |
| `GET /gallery/thumbs/<date>` | AJAX: 日付フォルダのサムネイル HTML フラグメントを返す |
| `GET /gallery/search?q=` | 全日付横断ファイル名検索 |
| `GET /gallery/<YYYY-MM-DD>` | 日付別ページ (個別アクセス用) |
| `POST /delete-media` | メディアファイル削除 (パストラバーサル対策済み) 🔒 |
| `GET /media/<path>` | `send_from_directory` によるメディア配信 |
| `GET /logs` | 処理ログ (最新 100 件) |
| `GET /failures` | 失敗リスト |
| `GET /stats` | ストレージ統計ダッシュボード (Chart.js) |
| `GET /queue` | API キューの管理ページ (処理待ちキュー一覧・全件削除) |
| `GET /api/health` | サーバー疎通確認 (`{"status": "ok", "version": "1.0"}`、認証不要) |
| `POST /api/update` | gallery-dl / yt-dlp を更新 |
| `GET /api/stats` | ストレージ統計 (`total_*` / `files_per_day` / `by_ext`) |
| `POST /api/queue` | URL をキューに追加。`{"url": "..."}` または `{"urls": [...]}` → 202 `{"queued", "accepted", "rejected"}` |
| `GET /api/queue/status` | キュー一覧 (素の配列、既定は待機/実行中のみ、`include_finished=1` で全件) |
| `DELETE /api/queue/item` | 指定 URL の 1 件を削除。`{"url": "..."}` |
| `POST /api/queue/clear` | 待機/実行中のキューを全件削除 `{"deleted": N}` |
| `GET /api/logs/recent` | 最近の処理ログ (既定 5 件) |
| `GET /api/history/count` | ダウンロード済み tweet ID の総件数 `{"count": N}` |
| `GET /api/history/ids` | ダウンロード済み tweet ID の全リスト (素の配列) |
| `GET /api/history/urls/count` | ダウンロード済み URL の総件数 `{"count": N}` |
| `GET /api/history/urls` | ダウンロード済み URL の全リスト (素の配列) |
| `GET /api/history/export` | TMH 互換 JSON (`{version, exportedAt, records}`) |
| `POST /api/history/import` | TMH 互換 JSON のインポート → `{"imported": N}` |
| `GET /api/history/stream` | SSE で完了イベントを配信 (ヘッダ認証必須なのでクライアントは fetch ポーリング推奨) |
| `DELETE /api/downloaded/id/<tweet_id>` | ダウンロード済みフラグの削除 |
| `DELETE /api/downloaded/url` | URL フラグの削除 `{"url": "..."}` |
| `GET|DELETE /api/downloaded/orphans` | 孤立フラグの一覧/全削除 |
| `GET /api/storage/consistency` | DB と実ファイルの整合性サマリ |
| `GET /api/storage/orphans` | 孤立フラグ + 孤立ファイル |
| `POST /api/storage/reindex` | 実ファイル名から tweet ID を再登録 |
| `GET /api/gallery/search` | ギャラリー検索 API (q / media_type / date / limit) |
| `GET /api/gallery/calendar` | 日別件数カレンダー API (year / month) |

🔒 = `API_TOKEN` 設定時に認証必須

**ギャラリー** (`/gallery`):
- `GALLERY_THUMB_COUNT` (デフォルト50) 件に達するまでの日付を先読み表示 (サーバーサイドレンダリング)
- 残りの日付は `<details>` アコーディオン (閉じた状態) でリスト表示
- アコーディオンを開くか無限スクロールで到達すると `/gallery/thumbs/<date>` を AJAX で取得
- ライトボックス: サムネイルクリックでページ内表示、← → ナビ、Esc で閉じる
- ホイールズーム (最大10倍)、ドラッグパン、ピンチズーム、ダブルクリックでリセット
- 削除ボタン (サムネイルホバー時 + ライトボックス内 + Del キー)
- イベント委譲により動的読み込みコンテンツにも削除・ライトボックスが動作

**LogStore** (`src/log_store.py`):
- `{SAVE_PATH}/xkeeper.db` (SQLite) に永続化。外部依存ゼロ (標準ライブラリ `sqlite3` のみ)
- テーブル: `download_log` / `downloaded_ids` / `downloaded_urls` / `api_queue`
- 初回起動時に `CREATE TABLE IF NOT EXISTS` で自動作成
- 旧 JSON ファイル (`_download_log.json` 等) がある場合、起動時に自動マイグレーションして `.json.bak` にリネーム
- スレッドセーフ (`threading.Lock` + `check_same_thread=False`)
- `get_storage_stats()` で日別・拡張子別のファイル統計を取得可能

**重複ダウンロード防止**:
- `download_all()` は各ツイート URL の tweet_id を SQLite `downloaded_ids` テーブルと照合し、既取得のものをスキップする
- `download_user_media()` は gallery-dl の `--filter` オプションで既取得 tweet_id を除外する
  - 除外リストはテンポラリファイル経由で渡す (コマンドライン長制限を回避)
- ファイル名テンプレート `{author[name]}-{tweet_id}-{num:02d}.{ext}` から tweet_id を逆引きして自動登録する

### クライアント (`client/`)

サーバーに Discord を経由せず直接 URL を投入するクライアント群。

| パス | 説明 |
|---|---|
| `client/chrome_extension/` | Chrome 拡張機能 (Manifest V3) |
| `client/chrome_extension/manifest.json` | 拡張マニフェスト。host_permissions: `http://*/*` `https://*/*` (任意のサーバー URL に対応するため) |
| `client/chrome_extension/background/service_worker.js` | オフラインキュー管理・HTTP 通信・SPA ナビゲーション検知 |
| `client/chrome_extension/content_scripts/content.js` | X/Pixiv へのボタン注入 |
| `client/chrome_extension/popup/` | ポップアップ UI (サーバーURL設定・キュー表示・履歴 export/import) |
| `client/chrome_extension/icons/` | アイコン PNG (16/48/128px)。原本は `assets/icon.svg` と `assets/icon-small.svg` |
| `client/flutter_app/` | Android APK (Flutter)。共有インテントで URL を受け取りサーバーに投入 |
| `client/flutter_app/build_apk.bat` | APK ビルド用 Windows バッチ |
| `client/xkeeper.user.js` | Tampermonkey スクリプト (非推奨。Chrome 拡張に移行) |

**Chrome 拡張の動作**:
- `chrome.storage.local` でサーバー URL とオフラインキューを管理 (`chrome.storage.sync` は Chrome 未サインイン環境で不安定なため使用しない)
- サーバー未接続時は `chrome.storage.local` にキューを保存し、次回接続時に一括送信
- SPA ナビゲーション検知: `chrome.webNavigation.onHistoryStateUpdated` → `chrome.tabs.sendMessage` → コンテンツスクリプト
- ダウンロード履歴は TMH (TwitterMediaHarvest) 互換フォーマットで export/import 可能
- ポップアップのキュー済みアイテムは個別キャンセル（× ボタン）・全件クリアに対応
- `IDS_UPDATED` / `URLS_UPDATED` 受信時にダウンロード完了済みアイテムを自動でリストから削除する

### Docker

`Dockerfile` はシングルステージビルド。非 root ユーザー (`appuser:1000`) で実行。

ボリューム:
- `./.env:/app/.env` — 設定の永続化
- `./data:/data` — メディア保存先 (NAS では左辺を実際のパスに変更、例: `/volume1/docker/x-keeper/data:/data`)

`SAVE_PATH=/data` は `docker-compose.yml` の `environment` で設定済み。`.env` の同名キーより `environment` が優先されるため、`.env` 側の値は無視される。

GitHub Actions (`docker-build.yml`) が `ghcr.io/solidlime/x-keeper:latest` に自動ビルドする。
ローカルビルドを使う場合は `.env` に `DOCKER_IMAGE=x-keeper:latest` を設定して `docker compose build` する。

### 非公式 API への依存

- **gallery-dl**: Twitter API キー不要だが X の仕様変更で壊れる可能性がある。
  - `--dump-json` 出力フォーマットが変わった場合は `_parse_tweet_info` を確認すること

### コーディング注意点

**`_download_one` の戻り値**:
- 必ず `files, rc_ok = self._download_one(...)` でアンパックすること
- `new_files = self._download_one(...)` のままだとタプルをイテレートしてしまう

**`log_store.py` のローカル変数名**:
- メソッド内で `queue` という名前のローカル変数を使わない (`import queue` モジュールとシャドーイングするため)
- 代替: `items`, `entries` を使う

**asyncio と subprocess**:
- 全ダウンロード処理 (`get_thread` / `download_all` / `download_direct` / `download_user_media`) は
  `await loop.run_in_executor(None, ...)` でスレッド実行すること (asyncio イベントループをブロックしないため)

