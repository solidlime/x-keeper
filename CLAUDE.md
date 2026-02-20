# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 開発コマンド

```bash
# 仮想環境の作成と依存インストール
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/Mac

# ローカル起動 (要 .env)
.venv/Scripts/python -m src.main

# web_setup サーバー単独起動 (デバッグ用)
.venv/Scripts/python -m src.web_setup

# OAuth2 認証 CLI (レガシー、通常は Web UI を使う)
.venv/Scripts/python -m src.token_setup

# Docker
docker compose build
docker compose up -d
docker compose logs -f
```

テスト・lint ツールは未導入。インポートチェックは `python -c "from src.XXX import YYY"` で行う。

## アーキテクチャ

### 処理フロー

```
main.py
├── Flask (web_setup.py) をデーモンスレッドでポート 8989 に起動
├── 必須設定が揃うまで .env を 30 秒ごとに再読み込みして待機
│   (_wait_for_required_settings)
└── ポーリングループ (POLL_INTERVAL_SECONDS ごと)
     └── run_once()
          └── KeepClient.sync() → iter_notes_with_twitter_urls()
               └── process_note() (ノートごと)
                    ├── TwitterClient.get_thread(url)
                    │    └── gallery-dl --dump-json で reply_id を辿り
                    │         親ツイートを再帰収集 (最大 50 段)
                    ├── MediaDownloader.download_all(tweet_urls)
                    │    └── gallery-dl -D <日付フォルダ> でメディアを保存
                    └── KeepClient.delete_note() ← 全ファイル成功時のみ実行
```

### モジュール構成

| ファイル | 役割 |
|---|---|
| `src/main.py` | エントリーポイント・ポーリングループ・Flask デーモン起動 |
| `src/config.py` | `pydantic-settings` による設定クラス (`Settings`) |
| `src/models.py` | データクラス: `TweetThread`, `SavedFile`, `ProcessResult` |
| `src/keep_client.py` | gkeepapi ラッパー。`_OAuth2Auth` で標準 OAuth2 を gkeepapi に注入 |
| `src/twitter_client.py` | `gallery-dl --dump-json` でスレッドを遡り `TweetThread` を返す |
| `src/image_downloader.py` | `gallery-dl -D` でメディアをダウンロードし `list[SavedFile]` を返す |
| `src/web_setup.py` | Flask アプリ。OAuth2 セットアップ UI + `/gallery` メディアビューア |
| `src/token_setup.py` | `upsert_env_value()` など OAuth2 フローのユーティリティ (web_setup も使用) |

### 重要な設計上の注意点

**gkeepapi の認証**: gkeepapi は本来 Android の gpsoauth を使うが、`_OAuth2Auth` アダプタを実装して標準 OAuth2 リフレッシュトークンで動作させている (`keep_client.py:24`)。デバイス ID は MAC アドレスから導出（gkeepapi の内部挙動に合わせるため）。

**gallery-dl の使い方 (2 フェーズ)**:
- フェーズ 1 (`TwitterClient`): `--dump-json` でメタデータのみ取得し `reply_id` を解析してスレッドを遡る
- フェーズ 2 (`MediaDownloader`): URL リストを `-D <dest>` でダウンロード。新規ファイルはディレクトリ差分 (`files_after - files_before`) で特定する。ファイル名: `{author[name]}-{tweet_id}-{num:02d}.{extension}`

**cookies あり時の差異**: `--cookies` + `extractor.twitter.conversations=true` を追加することでスレッド全体を 1 コマンドで取得できる

**ノート削除ポリシー**: `ProcessResult.errors` が空かつ保存ファイルが 1 件以上の場合のみ Keep ノートを削除。エラーがあれば次回ポーリングで自動再試行される。

**Web セットアップと .env の永続化**: `.env` はホストに bind-mount (`./env:/app/.env`) されており、`upsert_env_value()` がキーの上書き追記を担う。認証情報がない状態でも Flask サーバーは起動し続け、Web UI から入力すると自動的にポーリングが開始される。

**web_setup.py のルート**:
- `/` — OAuth2 セットアップフォーム
- `/start`, `/callback` — Google OAuth2 フロー
- `/save-cookies` — Cookie ファイルパスの保存
- `/gallery` — 日付フォルダ一覧
- `/gallery/<YYYY-MM-DD>` — 画像グリッド・動画・音声プレイヤー
- `/media/<path>` — `send_from_directory` によるメディア配信

### Docker

2 段階ビルド (builder → runtime)。`WORKDIR=/app`、非 root ユーザー (`appuser:1000`) で実行。

ボリューム:
- `./.env:/app/.env` — 設定の永続化
- `./data:/data` — メディア保存先 (NAS では `/volume1/data:/data` に変更)

GitHub Actions (`docker-build.yml`) が `ghcr.io/solidlime/x-keeper:latest` に自動ビルドする。ローカルビルドイメージを使う場合は `.env` に `DOCKER_IMAGE=keep-image-saver:latest` を設定する。

### 非公式 API への依存

- **gkeepapi**: Google Keep の非公式クライアント。Google の仕様変更で壊れる可能性がある。
- **gallery-dl**: Twitter API キー不要だが X の仕様変更で壊れる可能性がある。
