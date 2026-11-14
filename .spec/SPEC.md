# SPEC.md

x-keeper の技術仕様。実装と乖離した場合は随時更新する。

## API 仕様

### ルート定義

`src/web/` パッケージの Blueprint で定義（`src/web_setup.py` は後方互換シム）。全ルートの一覧は `CLAUDE.md` の「ルート (Blueprint 別)」セクション参照。

| ルート | Method | 説明 |
|---|---|---|
| `/` | GET | セットアップ UI ／ ギャラリーへリダイレクト |
| `/gallery` | GET | ギャラリートップ（日付アコーディオン・先読みサムネイル） |
| `/media/<path>` | GET | メディア配信（send_from_directory） |
| `/logs` | GET | ログ表示（最新 100 件） |
| `/queue` | GET | API キュー管理ページ |
| `/failures` | GET | 失敗リスト |
| `/api/health` | GET | ヘルスチェック（拡張・APK 用、認証不要） |
| `/api/queue` | POST | キューに URL 追加 → 202 `{queued, accepted, rejected}` |
| `/api/queue/status` | GET | キュー一覧（素の配列、既定は待機/実行中のみ） |
| `/api/history/ids` | GET | ダウンロード済み tweet ID（素の配列） |
| `/api/stats` | GET | ストレージ統計 |

### 認証

`src/web/auth.py` の `require_api_token` / `is_authenticated`。

- `API_TOKEN` 未設定: 認証なし（後方互換）
- `API_TOKEN` 設定時: `/api/*`（`/api/health` と OPTIONS を除く）と設定変更系ルート
  (`/save-cookies` `/save-bot-config` `/save-pixiv-token` `/save-api-token` `/pixiv-oauth/*` `/delete-media`) が保護対象
- 受理ヘッダ: `X-API-Token: <token>` / `Authorization: Bearer <token>`
- 401: `{"error": "unauthorized"}`
- Web UI はセッション認証（`app.secret_key` をトークンの SHA-256 から導出するので再起動後も維持）
- クライアント側設定: Chrome 拡張のオプション画面・Android アプリの設定画面にサーバー URL とトークンを保存させる。
  トークンはセットアップ画面（`/?setup=1`）の「API トークン」欄で生成・コピーできる

### キュー処理

`src/main.py` の asyncio ループが `RETRY_POLL_INTERVAL` 秒ごとに `pop_api_queue()` で 1 件取得して処理する。

- 取り出し時に `pending` → `running`（アトミック）
- 成功: `complete_api_url()`、失敗: `fail_api_url()`（60/300/900 秒後に再試行、最大 3 回で `failed`）
- 起動時に `reset_processing_urls()` で `running` を `pending` に戻す（クラッシュ復旧）
- 同一 URL の再投入は終了済み（`done`/`failed`）のみ `pending` に戻り、待機/実行中は重複しない
- 完了/失敗時に `NOTIFY_WEBHOOK_URL` があれば `notify_download()` で JSON を POST

**対応 URL パターン** (`src/patterns.py`):
- X status: `twitter.com|x.com/*/status/*`
- X ユーザーメディア: `twitter.com|x.com/*/media`
- Pixiv: `pixiv.net/*/artworks/*`
- Imgur: `imgur.com/*`
- YouTube / TikTok / NicoNico: yt-dlp で処理

Discord Bot (`src/discord_bot.py` / リアクション仕様) は廃止済み。

## データ永続化

### SQLite

`{SAVE_PATH}/xkeeper.db`（標準ライブラリ `sqlite3` のみ、`threading.Lock` + `check_same_thread=False`）

| テーブル | 役割 |
|---|---|
| `download_log` | 処理ログ（成功・失敗） |
| `downloaded_ids` | tweet_id 重複防止リスト |
| `downloaded_urls` | URL 重複防止リスト（Pixiv / Imgur 等） |
| `api_queue` | API キュー（拡張・APK）、`status` / `retry_count` / `last_error` / `next_retry_at` |

旧 JSON ファイル (`_download_log.json` 等) が残っている場合は起動時に自動マイグレーションし `.json.bak` にリネームする。

### ギャラリー保存先

デフォルト: `./data` （SAVE_PATH）
構造:
```
./data/
├── 2026-03-01/
│   ├── user-1234567890-01.jpg
│   ├── user-1234567890-02.jpg
│   └── ...
├── 2026-03-02/
│   └── ...
└── xkeeper.db
```

## 環境変数

詳細は `CLAUDE.md` の「環境変数 / .env」セクション参照。必須項目は無い。

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `API_TOKEN` | — | API トークン（未設定なら認証なし） |
| `NOTIFY_WEBHOOK_URL` | — | 完了/失敗時の通知先 |
| `GALLERY_DL_COOKIES_FILE` | — | 鍵垢対応 Cookie |
| `PIXIV_REFRESH_TOKEN` | — | Pixiv OAuth |
| `SAVE_PATH` | `./data` | 保存先ルート |
| `WEB_SETUP_PORT` | `8989` | Web サーバーポート |
| `RETRY_POLL_INTERVAL` | `30` | キューポーリング間隔（秒） |
| `GALLERY_THUMB_COUNT` | `50` | ギャラリー先読み数 |
| `LOG_LEVEL` | `INFO` | ログレベル |

## エッジケース・既知の制限

### X (Twitter)

- スレッド遡り: 最大遡行数は gallery-dl に依存
- メディア欄: ユーザー全メディアを一括ダウンロード（カウントが多い場合はタイムアウトリスク）

### Pixiv

- R-18 コンテンツ: PIXIV_REFRESH_TOKEN による OAuth 認証が必須
- マンガ: 現在対応予定中

### Imgur

- EXIF データ削除: Imgur 側で自動削除（メタデータ取得不可）

### gallery-dl

- 非公式 API: X の仕様変更で壊れる可能性がある
- `--dump-json` フォーマット: type=2 (メタデータ)・type=3 (ファイル) に依存

## 参考

- `CLAUDE.md`: 詳細なアーキテクチャ・処理フロー
- `AGENTS.md`: コーディング注意点・設計パターン
- `.spec/KNOWLEDGE.md` / `.spec/PLAN.md` / `.spec/TODO.md`
