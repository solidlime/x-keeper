# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

**x-keeper** は Google Keep を監視し、Keep ノートに含まれる X/Twitter の URL を検出して、gallery-dl で画像・動画をダウンロードするポーリングサービス。Twitter API キー不要。ダウンロード成功後にノートを自動削除する。

## Commands

```bash
# Docker (通常の起動方法)
docker compose build
docker compose up -d
docker compose logs -f

# Web UI で OAuth2 セットアップ
docker compose --profile setup up setup  # http://localhost:8080

# ローカル開発
pip install -r requirements.txt
python -m src.main           # メインアプリ
python -m src.web_setup      # Web セットアップサーバー (port 8080)
python -m src.token_setup    # CLI セットアップ
```

テスト・lint ツールは未導入。

## Architecture

```
Google Keep (gkeepapi)
  → keep_client.py       X/Twitter URL をノートから検出
  → twitter_client.py    gallery-dl でスレッドを遡って tweet URL を収集
  → image_downloader.py  gallery-dl サブプロセスで画像ダウンロード
  → /data/images/YYYY-MM-DD/{author}-{tweet_id}-{num}.{ext}
  → keep_client.delete_note()  エラーがなければノートを削除
```

### Key Modules

- **`main.py`**: エントリーポイント。ポーリングループ・`process_note()` でノート1件を処理。
- **`config.py`**: pydantic-settings で `.env` から設定を読む。
- **`models.py`**: `TweetThread`, `SavedImage`, `ProcessResult` の3データクラス。
- **`keep_client.py`**: gkeepapi ラッパー。`_OAuth2Auth` で google-auth と gkeepapi を橋渡し。
- **`twitter_client.py`**: gallery-dl `--dump-json` で `reply_to` チェーンを再帰的に遡る（最大 50 段）。
- **`image_downloader.py`**: gallery-dl サブプロセスを起動。ディレクトリ差分で保存ファイルを特定。ファイル名テンプレート: `{author[name]}-{tweet_id}-{num:02d}.{extension}`。
- **`web_setup.py`**: Flask 製 OAuth2 セットアップ UI。`/start` → Google OAuth → `/callback` → `.env` 更新。
- **`token_setup.py`**: CLI 版 OAuth2 セットアップユーティリティ。`upsert_env_value()` で `.env` を直接書き換える。

### Important Behaviors

- **fail-safe な削除**: `ProcessResult.errors` が空のときだけノートを削除する。
- **非公式 API 依存**: gkeepapi (Google Keep) と gallery-dl (Twitter) はどちらも非公式で、サービス変更で壊れる可能性がある。
- **OAuth2**: google-auth の Credentials を gkeepapi に注入するカスタムアダプター `_OAuth2Auth` を使用。デバイス ID は MAC アドレスから導出（gkeepapi の内部挙動に合わせている）。
- **画像整理**: `/data/images/YYYY-MM-DD/` の日付フォルダに保存。ダウンロード前後のディレクトリスナップショット差分で新規ファイルを検出する。
