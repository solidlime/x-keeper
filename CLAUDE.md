# CLAUDE.md

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

テスト・lint ツールは未導入。インポートチェックは `python -c "from src.XXX import YYY"` で行う。

## アーキテクチャ

### 処理フロー

```
python -m src.main
├── Flask (web_setup.py) をデーモンスレッドでポート 8989 に起動
│   └── Ctrl+C で終了するまで起動しっぱなし (ギャラリー閲覧用)
├── 必須設定が揃うまで .env を 30 秒ごとに再読み込みして待機
│   (DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID)
└── Discord Bot 起動 (asyncio ベース、イベント駆動)
     ├── on_ready: 監視チャンネルの最新 100 件をスキャンして未処理メッセージを処理
     ├── on_message: X/Pixiv/Imgur の URL を検出したメッセージを自動処理
     │    ├── Twitter URL → TwitterClient.get_thread(url) でスレッド収集
     │    │    └── gallery-dl --dump-json でスレッドを遡る (reply_id を解析)
     │    ├── Pixiv / Imgur URL → MediaDownloader.download_direct([url])
     │    └── MediaDownloader.download_all(tweet_urls)
     │         └── gallery-dl -D <日付フォルダ> でメディアを保存
     └── _retry_queue_task (バックグラウンド)
          ├── RETRY_POLL_INTERVAL 秒ごとに Web UI リトライキューを処理
          └── SCAN_INTERVAL 秒ごとに未処理メッセージを定期スキャン (0=起動時のみ)
```

### モジュール構成

| ファイル | 役割 |
|---|---|
| `src/main.py` | エントリーポイント・asyncio ループ・Flask デーモン起動 |
| `src/config.py` | `pydantic-settings` による設定クラス (`Settings`) |
| `src/models.py` | データクラス: `TweetThread`, `SavedFile` |
| `src/discord_bot.py` | Discord Bot。チャンネル監視・メッセージ処理・リアクション管理・リトライ |
| `src/twitter_client.py` | `gallery-dl --dump-json` でスレッドを遡り `TweetThread` を返す |
| `src/image_downloader.py` | `gallery-dl -D` でメディアをダウンロードし `list[SavedFile]` を返す |
| `src/log_store.py` | JSON 永続化ログ。成功/失敗記録・リトライキュー管理 |
| `src/web_setup.py` | Flask アプリ。セットアップ UI・ギャラリー・ログ・失敗管理 |

### 環境変数 / .env

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | ✅ | — | Discord Bot トークン |
| `DISCORD_CHANNEL_ID` | ✅ | — | 監視チャンネル ID (カンマ区切りで複数指定可) |
| `GALLERY_DL_COOKIES_FILE` | — | — | gallery-dl に渡す Cookie ファイルパス (鍵垢対応) |
| `PIXIV_REFRESH_TOKEN` | — | — | Pixiv OAuth リフレッシュトークン |
| `SAVE_PATH` | — | `./data` | メディア保存先ルートディレクトリ |
| `WEB_SETUP_PORT` | — | `8989` | Web サーバーポート番号 |
| `RETRY_POLL_INTERVAL` | — | `30` | リトライキューのポーリング間隔 (秒) |
| `SCAN_INTERVAL` | — | `0` | 未処理メッセージの定期スキャン間隔 (秒、0=起動時のみ) |
| `GALLERY_THUMB_COUNT` | — | `50` | ギャラリートップで先読みするサムネイル数 |
| `LOG_LEVEL` | — | `INFO` | ログレベル (DEBUG/INFO/WARNING/ERROR) |

### 重要な設計上の注意点

**Discord Bot の動作**:
- `discord.Intents.message_content = True` (Privileged Intent) が必要。Developer Portal で ON にすること
- 監視チャンネルはカンマ区切りで複数指定可能 (`DISCORD_CHANNEL_ID=111,222,333`)
- 起動時に監視チャンネルの最新 100 件をスキャンして未処理メッセージを処理する
- ✅ リアクション済みのメッセージは再処理しない
- ⏳ リアクションは処理中を示す (完了後に削除)
- ❌ リアクションは失敗を示す。Web UI の「失敗」タブからリトライ可能

**対応サービス**:
- **X (Twitter)**: URL パターン `twitter.com|x.com/*/status/*`。スレッド遡り対応
- **Pixiv**: URL パターン `pixiv.net/*/artworks/*`。`PIXIV_REFRESH_TOKEN` が必要
- **Imgur**: URL パターン `imgur.com/*`（アルバム・ギャラリー・単体画像・i.imgur.com 直リンク）

**gallery-dl の使い方 (2 フェーズ)**:
- フェーズ 1 (`TwitterClient`): `--dump-json` でメタデータのみ取得し `reply_id` を解析してスレッドを遡る
  - 出力フォーマット: stdout 全体が1つの JSON 配列 `[[type, metadata], [type, url, metadata], ...]`
  - type=2: ツイートメタデータ、type=3: ダウンロード対象ファイル
- フェーズ 2 (`MediaDownloader`): URL リストを `-D <dest>` でダウンロード。新規ファイルはディレクトリ差分で特定する

**cookies あり時の差異**: `--cookies` + `extractor.twitter.conversations=true` を追加することでスレッド全体を 1 コマンドで取得できる

**保存先**: デフォルト `./data`（実行ディレクトリ基準）。日付サブフォルダ (`YYYY-MM-DD`) が自動作成される。

**web_setup.py のルート**:

| ルート | 説明 |
|---|---|
| `GET /` | Discord 設定済みなら `/gallery` にリダイレクト。未設定またはクエリパラメータあり時はセットアップフォームを表示 |
| `GET /?setup=1` | セットアップフォームを強制表示 |
| `POST /save-discord` | Bot Token / Channel ID の保存 |
| `POST /save-cookies` | Cookie ファイルパスの保存 |
| `POST /save-pixiv-token` | Pixiv リフレッシュトークンの手動保存 |
| `GET /pixiv-oauth/start` | Pixiv OAuth PKCE 開始 (JSON レスポンス) |
| `POST /pixiv-oauth/exchange` | code → refresh_token 交換・保存 |
| `GET /pixiv-oauth/cancel` | OAuth セッションクリア |
| `POST /save-bot-config` | RETRY_POLL_INTERVAL / SCAN_INTERVAL / GALLERY_THUMB_COUNT の保存 |
| `GET /gallery` | ギャラリートップ。日付アコーディオン + 先読みサムネイル + 無限スクロール |
| `GET /gallery/thumbs/<date>` | AJAX: 日付フォルダのサムネイル HTML フラグメントを返す |
| `GET /gallery/search?q=` | 全日付横断ファイル名検索 |
| `GET /gallery/<YYYY-MM-DD>` | 日付別ページ (個別アクセス用) |
| `DELETE /delete-media` | メディアファイル削除 (パストラバーサル対策済み) |
| `GET /media/<path>` | `send_from_directory` によるメディア配信 |
| `GET /logs` | 処理ログ (最新 100 件) |
| `GET /failures` | 失敗リスト |
| `POST /retry/<message_id>/<channel_id>` | リトライキューへ追加 |

**ギャラリー** (`/gallery`):
- `GALLERY_THUMB_COUNT` (デフォルト50) 件に達するまでの日付を先読み表示 (サーバーサイドレンダリング)
- 残りの日付は `<details>` アコーディオン (閉じた状態) でリスト表示
- アコーディオンを開くか無限スクロールで到達すると `/gallery/thumbs/<date>` を AJAX で取得
- ライトボックス: サムネイルクリックでページ内表示、← → ナビ、Esc で閉じる
- ホイールズーム (最大10倍)、ドラッグパン、ピンチズーム、ダブルクリックでリセット
- 削除ボタン (サムネイルホバー時 + ライトボックス内 + Del キー)
- イベント委譲により動的読み込みコンテンツにも削除・ライトボックスが動作

**LogStore** (`src/log_store.py`):
- `{SAVE_PATH}/logs.json` に JSON 形式で保存 (最大 500 件)
- `{SAVE_PATH}/retry_queue.json` にリトライキューを保存
- スレッドセーフ (`threading.Lock` 使用)

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
