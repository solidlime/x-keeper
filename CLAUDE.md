# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 開発コマンド

```bash
# 仮想環境の作成と依存インストール
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/Mac

# 起動 (要 .env)
.venv/Scripts/python -m src.main

# Web サーバー単独起動 (デバッグ用)
.venv/Scripts/python -m src.web_setup
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
3. 成功: ✅ リアクション / 失敗: ❌ リアクション

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

### 非公式 API への依存

- **gallery-dl**: Twitter API キー不要だが X の仕様変更で壊れる可能性がある。
