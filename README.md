# x-keeper

Discord チャンネルに投稿された X (Twitter) / Pixiv / Imgur の URL を自動でダウンロード保存する Bot。

- **Twitter API キー不要** (gallery-dl を使用)
- X のスレッド全体を遡って取得
- ユーザーのメディア欄を一括ダウンロード
- Pixiv / Imgur にも対応
- Flask Web UI でギャラリー閲覧・ログ確認・リトライ管理
- Chrome 拡張・Android アプリから直接 URL を投入可能

---

## 機能概要

| 機能 | 説明 |
|---|---|
| X status URL | スレッドを遡って全メディアをダウンロード |
| X ユーザーメディア欄 | ユーザーの全メディアを一括ダウンロード |
| Pixiv artworks | 作品の全画像をダウンロード (要 PIXIV_REFRESH_TOKEN) |
| Imgur | アルバム・ギャラリー・単体画像に対応 |
| 重複防止 | ダウンロード済み tweet ID を記録。再投稿されても重複ダウンロードしない |
| リトライ | 失敗したメッセージを Web UI から再処理可能 |
| オフラインキュー | Chrome 拡張でサーバー未接続時にキューに積んで後で送信 |

### Discord リアクション

| リアクション | 意味 |
|---|---|
| ✅ | 処理済み |
| ⏳ | 処理中 (完了後に削除) |
| ❌ | 失敗 (Web UI の「失敗」タブからリトライ可能) |
| ⏭️ | 全ツイートが重複スキップ済み |

---

## セットアップ

### Docker (推奨)

```bash
# 1. 設定ファイルを作成
cp .env.example .env
# .env を編集して DISCORD_BOT_TOKEN と DISCORD_CHANNEL_ID を設定

# 2. 起動
docker compose up -d

# ログ確認
docker compose logs -f
```

### ローカル実行 (開発・デバッグ用)

```bash
python -m venv .venv

# Windows
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m src.main

# Linux/Mac
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

---

## Discord Bot のセットアップ

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成
2. **Bot** タブ → **Token** をコピーして `DISCORD_BOT_TOKEN` に設定
3. **Privileged Gateway Intents** の **Message Content Intent** を **ON** にする (必須)
4. **OAuth2 > URL Generator** で `bot` スコープを選択
5. Bot Permissions: `Read Messages/View Channels`, `Send Messages`, `Add Reactions`, `Read Message History`
6. 生成された URL でサーバーに招待
7. 監視したいチャンネルの ID をコピーして `DISCORD_CHANNEL_ID` に設定

---

## 環境変数一覧

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

### Cookie ファイル (鍵垢対応)

鍵垢のツイートにアクセスしたい場合は、ブラウザ拡張 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) などで Netscape 形式の Cookie をエクスポートし、パスを `GALLERY_DL_COOKIES_FILE` に設定する。

### Pixiv の設定

Pixiv をダウンロードするには OAuth リフレッシュトークンが必要。Web UI (`http://localhost:8989`) のセットアップ画面から取得できる。

---

## Chrome 拡張のインストール

1. Chrome で `chrome://extensions/` を開く
2. 「デベロッパーモード」を ON にする
3. 「パッケージ化されていない拡張機能を読み込む」→ `client/chrome_extension/` フォルダを選択
4. 拡張機能のポップアップを開き、サーバー URL (`http://localhost:8989`) を設定

**機能**:
- X / Pixiv ページにダウンロードボタンを自動注入
- ダウンロード済みバッジをリアルタイム表示
- サーバー未接続時はオフラインキューに保存し、接続回復後に一括送信

---

## Android APK ビルド

Flutter がインストール済みの環境で:

```bash
# Windows: バッチファイルをダブルクリック
client/flutter_app/build_apk.bat
```

ビルド成功後、`client/flutter_app/build/app/outputs/flutter-apk/app-release.apk` が生成される。

インストール後、Android の「共有」メニューから URL を選んでアプリに送ると、サーバーに直接投入できる。

---

## Web UI

`http://localhost:8989` でアクセス可能。

| ページ | URL | 説明 |
|---|---|---|
| セットアップ | `/?setup=1` | Bot Token / Channel ID 等の設定 |
| ギャラリー | `/gallery` | ダウンロード済みメディアの一覧 |
| ログ | `/logs` | 処理ログ (最新 100 件) |
| 失敗一覧 | `/failures` | 失敗したメッセージ。リトライボタンあり |

---

## ディレクトリ構成

```
x-keeper/
├── src/
│   ├── main.py             # エントリーポイント・asyncio ループ・Flask デーモン起動
│   ├── config.py           # pydantic-settings による設定クラス
│   ├── models.py           # データクラス: TweetThread, SavedFile, DownloadResult
│   ├── discord_bot.py      # Discord Bot: チャンネル監視・リアクション管理
│   ├── twitter_client.py   # gallery-dl でスレッドを遡り TweetThread を返す
│   ├── image_downloader.py # gallery-dl でメディアをダウンロード
│   ├── log_store.py        # JSON 永続化ログ・リトライキュー管理
│   └── web_setup.py        # Flask アプリ: セットアップ UI・ギャラリー・API
├── client/
│   ├── chrome_extension/   # Chrome 拡張機能 (Manifest V3)
│   └── flutter_app/        # Android APK (Flutter)
├── data/                   # メディア保存先 (Docker ボリュームでマウント)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env                    # 設定ファイル (要作成)
```

---

## 注意事項

- **gallery-dl は非公式手段**で動作しており、X の仕様変更で突然壊れる可能性がある
- **Pixiv** のダウンロードには `PIXIV_REFRESH_TOKEN` が必要。Web UI のセットアップ画面から取得できる
- **Discord の Message Content Intent** は Developer Portal で明示的に ON にする必要がある
- Docker で NAS に配置する場合は `docker-compose.yml` の volumes の左辺を実際のパスに変更する

```yaml
volumes:
  - ./.env:/app/.env
  - /volume1/docker/x-keeper/data:/data  # NAS の実際のパスに変更
```
