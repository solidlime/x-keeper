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
     └── on_message / 起動時スキャン
          └── X URL を検出したメッセージを処理
               ├── TwitterClient.get_thread(url)
               │    └── gallery-dl --dump-json でスレッドを遡る
               ├── MediaDownloader.download_all(tweet_urls)
               │    └── gallery-dl -D <日付フォルダ> でメディアを保存
               └── ✅ リアクション (成功) / ❌ リアクション (失敗)
```

### モジュール構成

| ファイル | 役割 |
|---|---|
| `src/main.py` | エントリーポイント・asyncio ループ・Flask デーモン起動 |
| `src/config.py` | `pydantic-settings` による設定クラス (`Settings`) |
| `src/models.py` | データクラス: `TweetThread`, `SavedFile` |
| `src/discord_bot.py` | Discord Bot。チャンネル監視・メッセージ処理・リアクション管理 |
| `src/twitter_client.py` | `gallery-dl --dump-json` でスレッドを遡り `TweetThread` を返す |
| `src/image_downloader.py` | `gallery-dl -D` でメディアをダウンロードし `list[SavedFile]` を返す |
| `src/web_setup.py` | Flask アプリ。Discord セットアップ UI + `/gallery` メディアビューア |

### 重要な設計上の注意点

**Discord Bot の動作**:
- `discord.Intents.message_content = True` (Privileged Intent) が必要。Developer Portal で ON にすること
- 起動時に監視チャンネルの最新 100 件をスキャンして未処理メッセージを処理する
- ✅/❌ リアクション済みのメッセージは再処理しない
- ⏳ リアクションは処理中を示す (完了後に削除)

**使い方**:
1. Android で X のツイートを共有 → Discord → 監視チャンネルに送信
2. Bot が URL を検知して自動ダウンロード
3. 成功: ✅ リアクション / 失敗: リアクションなし (次回 Bot 起動時に再処理)

**gallery-dl の使い方 (2 フェーズ)**:
- フェーズ 1 (`TwitterClient`): `--dump-json` でメタデータのみ取得し `reply_id` を解析してスレッドを遡る
- フェーズ 2 (`MediaDownloader`): URL リストを `-D <dest>` でダウンロード。新規ファイルはディレクトリ差分で特定する

**cookies あり時の差異**: `--cookies` + `extractor.twitter.conversations=true` を追加することでスレッド全体を 1 コマンドで取得できる

**保存先**: デフォルト `./data`（実行ディレクトリ基準）。`.env` の `SAVE_PATH` で変更可能。

**web_setup.py のルート**:
- `/` — Discord セットアップフォーム
- `/save-discord` — Bot Token / Channel ID の保存
- `/save-cookies` — Cookie ファイルパスの保存
- `/gallery` — 日付フォルダ一覧
- `/gallery/<YYYY-MM-DD>` — 画像グリッド・動画・音声プレイヤー
- `/media/<path>` — `send_from_directory` によるメディア配信

### Docker

`Dockerfile` はシングルステージビルド。非 root ユーザー (`appuser:1000`) で実行。

ボリューム:
- `./.env:/app/.env` — 設定の永続化
- `./data:/app/data` — メディア保存先 (NAS では左辺を適宜変更、例: `/volume1/data:/app/data`)

`save_path` のデフォルトは `./data`。WORKDIR が `/app` のため `/app/data` にマウントすれば `SAVE_PATH` 指定不要。

GitHub Actions (`docker-build.yml`) が `ghcr.io/solidlime/x-keeper:latest` に自動ビルドする。
ローカルビルドを使う場合は `.env` に `DOCKER_IMAGE=x-keeper:latest` を設定して `docker compose build` する。

### 非公式 API への依存

- **gallery-dl**: Twitter API キー不要だが X の仕様変更で壊れる可能性がある。
