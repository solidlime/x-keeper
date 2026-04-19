# x-keeper

X (Twitter) / Pixiv / Imgur / YouTube / TikTok / NicoNico などのメディアを自動ダウンロード・保存する Web アプリケーション。

**Chrome 拡張**や **Android アプリ**から URL を投入すると、バックグラウンドで自動的にメディアをダウンロードし、ギャラリー形式で一元管理できるよ。

---

## 目次

- [主な特徴](#主な特徴)
- [対応サービス](#対応サービス)
- [動作環境](#動作環境)
- [セットアップ](#セットアップ)
- [Chrome 拡張のインストール](#chrome-拡張のインストール)
- [Android アプリのビルド](#android-アプリのビルド)
- [Web UI 使い方](#web-ui-使い方)
- [環境変数設定](#環境変数設定)
- [ディレクトリ構成](#ディレクトリ構成)
- [トラブルシューティング](#トラブルシューティング)
- [技術仕様](#技術仕様)
- [開発・テスト](#開発テスト)

---

## 主な特徴

- **Twitter API キー不要**: gallery-dl を使用した非公式ダウンロード
- **スレッド全体取得**: X のスレッドを遡って全メディアを一括ダウンロード
- **ユーザーメディア一括取得**: 特定ユーザーのメディア欄を一括ダウンロード
- **複数サービス対応**: Pixiv / Imgur / YouTube / TikTok / NicoNico にも対応
- **重複防止**: ダウンロード済み tweet ID を SQLite に記録。再投稿されても重複ダウンロードしない
- **Web UI**: Flask ベースのモダン UI。ギャラリー閲覧・ログ確認・リトライ管理・ストレージ統計が可能
- **Chrome 拡張**: X / Pixiv ページに直接ダウンロードボタンを注入。オフラインキュー機能付き
- **Android アプリ**: 共有インテント経由で直接 URL を投入可能
- **無限スクロール**: ギャラリーの画像を日付別に無限スクロール表示

---

## 対応サービス

| サービス | 対応パターン | 説明 |
|---|---|---|
| **X (Twitter) status** | `twitter.com/*/status/*` や `x.com/*/status/*` | スレッド全体を遡ってメディアを取得 |
| **X ユーザーメディア欄** | `twitter.com/*/media` や `x.com/*/media` | ユーザーの全メディアを一括ダウンロード |
| **Pixiv** | `pixiv.net/artworks/*` または `pixiv.net/en/artworks/*` | 複数ページ作品の全画像をダウンロード。PIXIV_REFRESH_TOKEN が必要 |
| **Imgur** | `imgur.com/*` (アルバム・ギャラリー・単体画像) / `i.imgur.com/*` (直リンク) | アルバムの全画像をダウンロード |
| **YouTube** | `youtube.com/watch*` / `youtu.be/*` | yt-dlp で動画をダウンロード |
| **TikTok** | `tiktok.com/*` | yt-dlp で動画をダウンロード |
| **NicoNico** | `nicovideo.jp/watch/*` | yt-dlp で動画をダウンロード |

---

## 動作環境

| 要件 | バージョン |
|---|---|
| Python | 3.11+ |
| gallery-dl | 1.27.4+ |
| yt-dlp | 2024.1.0+ |
| Docker | 20.10+ (推奨) |
| docker-compose | 2.0+ (推奨) |

---

## セットアップ

### 方法 1: Docker (推奨)

最も簡単で推奨される方法だよ。環境構築の手間がなく、すぐに起動できる。

#### 1. 設定ファイルを作成

```bash
# プロジェクトディレクトリに移動
cd x-keeper

# .env ファイルを作成（最初は空でもOK。後から Web UI で設定可能）
touch .env
```

#### 2. Docker で起動

```bash
docker compose up -d
```

#### 3. Web UI にアクセス

```
http://localhost:8989
```

ブラウザで上記 URL を開くと、セットアップ画面が表示される。

**ボリュームマウント設定** (NAS や外部ストレージの場合):

`docker-compose.yml` の `volumes` セクションで、メディア保存先を変更できる。

```yaml
volumes:
  - ./.env:/app/.env
  - /volume1/docker/x-keeper/data:/data  # NAS の実際のパスに変更
```

#### 4. ログ確認

```bash
docker compose logs -f
```

#### 5. 停止

```bash
docker compose down
```

---

### 方法 2: ローカル実行 (開発・デバッグ用)

Python 3.11+ がインストールされている環境で直接実行できる。

#### 1. 仮想環境を作成

```bash
python -m venv .venv
```

#### 2. 依存パッケージをインストール

**Windows:**

```bash
.venv\Scripts\pip install -r requirements.txt
```

**Linux / Mac:**

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

#### 3. 環境変数を設定

```bash
# 最初は空の .env ファイルを作成
touch .env
```

#### 4. アプリを起動

**Windows:**

```bash
.venv\Scripts\python -m src.main
```

**Linux / Mac:**

```bash
source .venv/bin/activate
python -m src.main
```

#### 5. Web UI にアクセス

```
http://localhost:8989
```

---

## Chrome 拡張のインストール

X / Pixiv / YouTube / TikTok / NicoNico のページに自動的にダウンロードボタンを注入し、直接 URL をキューに投入できる。サーバー未接続時はオフラインキューに保存され、接続回復後に自動送信される。

> **最新バージョン**: [GitHub Releases](https://github.com/solidlime/x-keeper/releases) から `x-keeper-chrome-ext.zip` をダウンロードできる。

### 方法 A: ZIP からインストール（推奨）

1. **[GitHub Releases](https://github.com/solidlime/x-keeper/releases) を開く**
   - 最新リリースの Assets から **`x-keeper-chrome-ext.zip`** をダウンロード

2. **ZIP を解凍する**
   ```
   x-keeper-chrome-ext.zip を任意のフォルダに解凍
   例: C:\tools\x-keeper-chrome-ext\
   ```

3. **Chrome 拡張機能管理ページを開く**
   ```
   chrome://extensions/
   ```

4. **デベロッパーモードを有効化**
   - 右上のトグルスイッチを **ON** にする

5. **「パッケージ化されていない拡張機能を読み込む」をクリック**
   - 手順 2 で解凍したフォルダ（`manifest.json` があるフォルダ）を選択

6. **サーバー URL を設定する**
   - Chrome ツールバーの **x-keeper アイコン**をクリックしてポップアップを開く
   - サーバー URL 欄に入力して「保存」: `http://サーバーIP:8989`
   - 「テスト」ボタンでバッジが **オンライン** になれば接続完了

### 方法 B: ソースから読み込む（開発・最新コード用）

```bash
# リポジトリをクローン
git clone https://github.com/solidlime/x-keeper.git
```

その後、上記手順 3〜6 で `client/chrome_extension/` フォルダを選択する。

### 機能一覧

| 機能 | 説明 |
|---|---|
| **ボタン注入** | X / Pixiv / YouTube / TikTok / NicoNico の各ページにダウンロードボタンを自動表示 |
| **ダウンロード済みバッジ** | X のツイートカード・Pixiv サムネイルにダウンロード済みかをリアルタイム表示 |
| **オフラインキュー** | サーバー未接続時もキューに積んでおき、接続回復後に自動送信 |
| **キュー管理** | ポップアップから処理待ちキューの確認・個別キャンセル・全クリアが可能 |
| **統計ダッシュボード** | ポップアップの「統計」ボタンから `/stats` ページを開ける |
| **履歴 export/import** | TwitterMediaHarvest (TMH) 互換フォーマットで重複防止リストを管理 |

### ポップアップの見方

```
┌─────────────────────────────────┐
│ 🔽 x-keeper          [オンライン] │
├─────────────────────────────────┤
│ サーバー URL                      │
│ [http://192.168.1.10:8989] [テスト][保存] │
│                                  │
│ [📷 ギャラリー]  [📊 統計]         │
├─────────────────────────────────┤
│ 処理待ちキュー (2件)               │
│  https://x.com/.../status/...  [×] │
│  https://www.pixiv.net/...     [×] │
│ [全件削除]                         │
├─────────────────────────────────┤
│ ダウンロード履歴 (TMH互換)          │
│  1,234 件ダウンロード済み           │
│ [エクスポート]  [インポート]        │
└─────────────────────────────────┘
```

---

## Android アプリのビルド

Flutter ベースの Android アプリ。共有インテント経由で URL をサーバーに直接投入できる。

### 前提条件

- **Flutter SDK** がインストール済み
- **Android SDK** がセットアップ済み
- **Java JDK 11+** がインストール済み

### ビルド手順 (Windows)

最も簡単な方法は、バッチファイルを使用すること。

```bash
# プロジェクトディレクトリに移動
cd x-keeper

# バッチファイルを実行
client\flutter_app\build_apk.bat
```

バッチが自動的にビルドプロセスを実行する。

**成功時の出力**:
```
client/flutter_app/build/app/outputs/flutter-apk/app-release.apk
```

### ビルド手順 (Linux / Mac)

```bash
cd client/flutter_app
flutter pub get
flutter build apk --release
```

APK は `build/app/outputs/flutter-apk/app-release.apk` に生成される。

### インストール

#### USB デバッグ経由 (推奨)

```bash
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

#### 手動インストール

APK ファイルを Android デバイスにコピーして、ファイルマネージャーから実行。

### 使用方法

1. Android で URL をコピーする
2. 「共有」メニューを開く
3. **x-keeper** アプリを選択
4. サーバー URL を入力（初回のみ）
5. URL が自動的にサーバーのキューに投入される

詳細は [`client/flutter_app/BUILD.md`](./client/flutter_app/BUILD.md) を参照。

---

## Web UI 使い方

### セットアップ画面 (`/?setup=1`)

初回起動時に表示される画面。以下の設定が可能：

| 設定項目 | 説明 | 必須 |
|---|---|---|
| **Cookie ファイルパス** | gallery-dl で使用する Cookie ファイル (鍵垢対応) | — |
| **Pixiv リフレッシュトークン** | Pixiv ダウンロード用の OAuth トークン。Web UI から取得可能 | — |
| **Pixiv OAuth 開始** | 「Pixiv にアクセスしてトークンを取得」ボタン | — |
| **リトライポーリング間隔** | API キューをチェックする秒数 (デフォルト: 30) | — |
| **ギャラリー先読み数** | ギャラリートップで最初に読み込むサムネイル数 (デフォルト: 50) | — |

### ギャラリー (`/gallery`)

ダウンロード済みメディアを日付別に一覧表示。

**機能:**
- **日付アコーディオン**: 日付をクリックで画像をプレビュー
- **無限スクロール**: 下にスクロールすると自動的に過去の日付を読み込む
- **ライトボックス**: サムネイルをクリックで拡大表示
- **ホイールズーム**: マウスホイールで最大 10 倍までズーム
- **ドラッグパン**: 拡大表示時にドラッグで移動
- **削除**: ホバー時の削除ボタンか、ライトボックス内の削除ボタンで画像を削除
- **キーボード操作**: ← → でナビゲート、Esc で閉じる

### 日付別ページ (`/gallery/YYYY-MM-DD`)

特定日付の画像一覧を表示。URL で直接アクセス可能。

### 全日付検索 (`/gallery/search?q=キーワード`)

全ての日付フォルダを横断して、ファイル名で検索。

### ストレージ統計 (`/stats`)

ダウンロード済みメディアの統計情報をグラフで表示。

**表示内容:**
- 総ファイル数・総ストレージ使用量
- 日別ダウンロード数の推移グラフ (Chart.js)
- 拡張子別ファイル数の内訳

### ログ (`/logs`)

処理ログを最新 100 件表示。

| 内容 | 説明 |
|---|---|
| タイムスタンプ | ダウンロード実行日時 |
| ステータス | `SUCCESS` / `FAILURE` |
| URL | ダウンロード対象の URL |
| ファイル数 | ダウンロードされたファイル数 |
| エラーメッセージ | 失敗時のエラー詳細 |

### キュー管理 (`/queue`)

API キューに積まれた未処理 URL の一覧。

**操作:**
- **再ダウンロード**: URL をキューの末尾に再追加
- **削除**: 特定の URL をキューから削除
- **全クリア**: キュー全体をクリア

### API エンドポイント (主要なもの)

#### ストレージ統計
```
GET /api/stats
```
レスポンス:
```json
{
  "total_files": 1234,
  "total_size_bytes": 5678901234,
  "by_date": {"2026-03-08": 42, "2026-03-07": 17},
  "by_ext": {"jpg": 800, "mp4": 300, "png": 134}
}
```

#### 健康確認
```
GET /api/health
```
レスポンス: `{"status": "ok"}`

#### URL をキューに追加
```
POST /api/queue
Content-Type: application/json

{
  "url": "https://x.com/xxx/status/12345"
}
```

複数 URL:
```json
{
  "urls": [
    "https://pixiv.net/artworks/12345",
    "https://imgur.com/gallery/abc123"
  ]
}
```

#### キュー一覧を取得
```
GET /api/queue/status
```
レスポンス:
```json
{
  "queue": [
    {
      "url": "https://x.com/xxx/status/12345",
      "added_at": "2026-03-08T10:30:00"
    }
  ]
}
```

#### キューから 1 件削除
```
DELETE /api/queue/item
Content-Type: application/json

{
  "url": "https://x.com/xxx/status/12345"
}
```

#### キュー全件削除
```
POST /api/queue/clear
```

#### 最近のログ (最新 5 件)
```
GET /api/logs/recent
```

#### ダウンロード済み tweet ID の件数
```
GET /api/history/count
```
レスポンス: `{"count": 1234}`

#### ダウンロード済み tweet ID の全リスト
```
GET /api/history/ids
```
レスポンス: `{"ids": ["123456789", "987654321", ...]}`

#### ダウンロード済み URL の件数 (Pixiv / Imgur など)
```
GET /api/history/urls/count
```

#### ダウンロード済み URL の全リスト
```
GET /api/history/urls
```

#### ダウンロード履歴をエクスポート (TMH 互換形式)
```
GET /api/history/export
```
テキストファイルで tweet ID を 1 行ずつダウンロード。

#### ダウンロード履歴をインポート (TMH 互換形式)
```
POST /api/history/import
Content-Type: text/plain

123456789
987654321
...
```

#### リアルタイム更新ストリーム (SSE)
```
GET /api/history/stream
```
Server-Sent Events でダウンロード完了をリアルタイム配信。

---

## 環境変数設定

`.env` ファイルに以下の変数を設定できる。

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `GALLERY_DL_COOKIES_FILE` | — | — | gallery-dl に渡す Cookie ファイルパス (鍵垢対応)。Netscape 形式推奨 |
| `PIXIV_REFRESH_TOKEN` | — | — | Pixiv OAuth リフレッシュトークン。Web UI のセットアップから取得可能 |
| `SAVE_PATH` | — | `./data` | メディア保存先のルートディレクトリ。絶対パス推奨 |
| `WEB_SETUP_PORT` | — | `8989` | Web サーバーのポート番号 (1024 以上を推奨) |
| `RETRY_POLL_INTERVAL` | — | `30` | API キューをポーリングする秒数。短いほど応答性が上がるがリソース増加 |
| `GALLERY_THUMB_COUNT` | — | `50` | ギャラリートップで先読みするサムネイル数。多いほど初期読み込み時間が増加 |
| `LOG_LEVEL` | — | `INFO` | ログレベル (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |

### .env ファイル例

```bash
# Cookie ファイルパス (鍵垢対応)
GALLERY_DL_COOKIES_FILE=/path/to/cookies.txt

# Pixiv リフレッシュトークン (Web UI から取得)
PIXIV_REFRESH_TOKEN=xxxxx_xxxxx_xxxxx

# メディア保存先
SAVE_PATH=./data

# Web サーバーポート
WEB_SETUP_PORT=8989

# API キューポーリング間隔 (秒)
RETRY_POLL_INTERVAL=30

# ギャラリー先読み数
GALLERY_THUMB_COUNT=50

# ログレベル
LOG_LEVEL=INFO
```

### Cookie ファイルの取得方法 (鍵垢対応)

鍵アカウントのツイートにアクセスしたい場合は、以下の手順で Cookie をエクスポート：

1. **Chrome ウェブストア**から [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) をインストール
2. **X.com にログイン**した状態で拡張機能をクリック
3. **「エクスポート」**をクリックして `cookies.txt` をダウンロード
4. `.env` に以下を設定:
   ```
   GALLERY_DL_COOKIES_FILE=/path/to/cookies.txt
   ```

### Pixiv リフレッシュトークンの取得方法

1. **Web UI** (`http://localhost:8989/?setup=1`) を開く
2. **「Pixiv にアクセスしてトークンを取得」**をクリック
3. Pixiv ログイン画面に遷移
4. ログイン後、自動的にトークンが保存される

---

## ディレクトリ構成

```
x-keeper/
├── src/
│   ├── __init__.py
│   ├── main.py                   # エントリーポイント・asyncio ループ・Flask デーモン起動
│   ├── config.py                 # pydantic-settings による設定クラス
│   ├── models.py                 # データクラス (TweetThread, SavedFile, DownloadResult)
│   ├── patterns.py               # URL 判定 regex の一元管理
│   ├── image_downloader.py       # gallery-dl / yt-dlp ラッパー・ダウンロード処理
│   ├── log_store.py              # SQLite 永続化ログ・APIキュー・ストレージ統計
│   ├── web_setup.py              # src/web/ への薄いシム (後方互換)
│   └── web/
│       ├── __init__.py           # Flask app + Blueprint 登録
│       ├── globals.py            # _log_store グローバル管理
│       ├── utils.py              # 定数・ヘルパー関数
│       ├── templates.py          # 全 HTML テンプレート文字列
│       └── routes/
│           ├── __init__.py
│           ├── setup.py          # /, /save-*, /pixiv-oauth/*
│           ├── gallery.py        # /gallery/*
│           ├── api.py            # /api/*
│           ├── media.py          # /media/*, /delete-media
│           └── admin.py          # /logs, /queue, /failures, /stats
│
├── tests/
│   ├── conftest.py               # pytest フィクスチャ
│   ├── test_patterns.py          # URL パターンマッチング (49件)
│   ├── test_log_store.py         # LogStore 全メソッド (25件)
│   └── test_image_downloader.py  # tweet_id 抽出 (11件)
│
├── client/
│   ├── chrome_extension/         # Chrome 拡張機能 (Manifest V3)
│   │   ├── manifest.json
│   │   ├── background/
│   │   │   └── service_worker.js # バックグラウンド処理
│   │   ├── content_scripts/
│   │   │   └── content.js        # ボタン注入
│   │   ├── popup/                # ポップアップ UI
│   │   └── icons/                # アイコン (16/48/128px)
│   │
│   └── flutter_app/              # Android APK (Flutter)
│       ├── lib/
│       ├── android/
│       ├── pubspec.yaml
│       ├── build_apk.bat         # Windows ビルドバッチ
│       └── BUILD.md              # ビルド詳細手順
│
├── data/                         # メディア保存先 (SAVE_PATH)
│   ├── 2026-03-08/               # 日付フォルダ
│   │   ├── user-123456789-00.jpg
│   │   └── ...
│   └── xkeeper.db                # SQLite データベース (ログ・キュー・ID管理)
│
├── .env                          # 環境変数設定ファイル (要作成)
├── requirements.txt              # Python 依存パッケージ
├── Dockerfile                    # Docker イメージ定義
├── docker-compose.yml            # Docker Compose 設定
├── .gitignore
└── README.md                     # このファイル
```

### データ永続化

以下のデータは `{SAVE_PATH}/xkeeper.db` (SQLite) に自動保存される：

| テーブル | 説明 |
|---|---|
| `download_log` | ダウンロード履歴・失敗ログ |
| `downloaded_ids` | ダウンロード済み tweet ID (重複防止用) |
| `downloaded_urls` | ダウンロード済み URL (Pixiv / Imgur 等) |
| `api_queue` | Chrome 拡張・Android アプリから投入された URL キュー |

> **マイグレーション**: 旧バージョンの JSON ファイル (`_download_log.json` 等) が存在する場合は、起動時に自動的に SQLite へ移行し `.json.bak` にリネームされる。

### メディア保存形式

ダウンロード済みメディアは日付別フォルダに保存される：

```
YYYY-MM-DD/
├── {author-name}-{tweet-id}-00.{ext}
├── {author-name}-{tweet-id}-01.{ext}
├── ...
```

例: `2026-03-08/solidlime-1234567890123-00.jpg`

---

## トラブルシューティング

### Web UI が開けない

**症状**: `http://localhost:8989` にアクセスできない

**対処法**:
1. 起動ログでエラーを確認
   ```bash
   docker compose logs -f  # Docker の場合
   # または
   python -m src.main     # ローカル実行の場合
   ```
2. ポート番号が競合していないか確認
   ```bash
   # Windows
   netstat -ano | findstr :8989

   # Linux/Mac
   lsof -i :8989
   ```
3. `WEB_SETUP_PORT` を別のポート番号に変更してみる

### Chrome 拡張が起動しない

**症状**: Chrome 拡張がエラーになるか表示されない

**対処法**:
1. `client/chrome_extension/manifest.json` が有効か確認
2. Chrome で `chrome://extensions/` を開き、エラーメッセージを確認
3. デベロッパーモードを一度 OFF にして再度 ON にしてリロード
4. Web UI のサーバー URL が正しく設定されているか確認

### ダウンロードが進まない

**症状**: キューに URL を投入してもダウンロードが実行されない

**対処法**:
1. ログを確認
   ```bash
   docker compose logs -f x-keeper | grep -i download  # Docker の場合
   ```
2. API キューが詰まっていないか確認
   ```bash
   curl http://localhost:8989/api/queue/status
   ```
3. `RETRY_POLL_INTERVAL` を短くしてみる (デフォルト 30 秒)
4. gallery-dl が最新版か確認
   ```bash
   curl http://localhost:8989/api/update -X POST  # アップデート試行
   ```

### Pixiv のダウンロードが失敗する

**症状**: Pixiv URL のダウンロードが常に失敗する

**対処法**:
1. Pixiv リフレッシュトークンが設定されているか確認
   ```bash
   # .env に PIXIV_REFRESH_TOKEN が設定されているか
   cat .env | grep PIXIV
   ```
2. トークンが有効期限切れになっていないか確認
   - Web UI (`/?setup=1`) から再度 Pixiv OAuth を実行
3. 当該作品がダウンロード対象外でないか確認
   - 非公開作品や削除済み作品はダウンロード不可

### Docker で `permission denied` エラー

**症状**: Docker コンテナ起動時にボリュームマウントでエラー

**対処法**:
1. `docker-compose.yml` の volumes パスが正しいか確認
2. パスに空白や特殊文字が含まれていないか確認
3. NAS の場合は、NFS / SMB マウント設定を確認

### gallery-dl が突然壊れた

**症状**: 「gallery-dl: エラー」などのメッセージが出始めた

**対処法**:
1. gallery-dl を最新版にアップデート
   ```bash
   curl http://localhost:8989/api/update -X POST
   ```
2. X の仕様変更の影響の可能性がある
   - [gallery-dl GitHub Issues](https://github.com/mikf/gallery-dl/issues) を確認

---

## 技術仕様

### アーキテクチャ

```
Python asyncio ループ
├── Flask Web サーバー (デーモンスレッド)
│   ├── GET /gallery → ギャラリー HTML を返す
│   ├── GET /stats → ストレージ統計ダッシュボード
│   ├── GET /api/stats → 統計 JSON を返す
│   ├── POST /api/queue → URL をキューに追加
│   ├── GET /api/queue/status → キュー一覧を返す
│   └── ... (その他の Web UI ルート)
│
└── API キューポーリングループ
    ├── RETRY_POLL_INTERVAL ごとに log_store.pop_api_queue() を実行
    └── 各 URL に対して以下を実行:
        ├── X status URL → TwitterClient.get_thread() でスレッド取得
        │   └── MediaDownloader.download_all() でダウンロード
        ├── X /media URL → MediaDownloader.download_user_media()
        ├── YouTube / TikTok / NicoNico → MediaDownloader.download_yt_dlp()
        ├── Pixiv / Imgur → MediaDownloader.download_direct()
        └── ログを log_store (SQLite) に記録
```

### 処理フロー

**URL ダウンロードフロー:**

1. Chrome 拡張 / Android アプリから `POST /api/queue` で URL を投入
2. LogStore が URL を SQLite (`api_queue` テーブル) に保存
3. asyncio が `RETRY_POLL_INTERVAL` ごとに API キューをポーリング
4. キューから URL を 1 つ取り出して処理
   - **X status**: `gallery-dl --dump-json` で tweet メタデータを取得 → スレッド遡り
   - **X /media**: `gallery-dl -D` で --filter を使ってスキップ
   - **YouTube / TikTok / NicoNico**: `yt-dlp -o` でダウンロード
   - **Pixiv / Imgur**: `gallery-dl -D` でダウンロード
5. ダウンロード結果を LogStore (SQLite) に記録
   - 成功時: `downloaded_ids` / `downloaded_urls` に追加、`api_queue` から削除
   - 失敗時: `download_log` に失敗情報を記録

### 重複防止メカニズム

- **tweet ID ベース** (X): SQLite の `downloaded_ids` テーブルに tweet ID を永続保存。同じ tweet ID は 2 度ダウンロードしない
- **URL ベース** (Pixiv / Imgur): URL をそのまま `downloaded_urls` テーブルに記録

### gallery-dl 統合

gallery-dl は **subprocess** 経由で実行される：

- **フェーズ 1 (メタデータ取得)**: `gallery-dl --dump-json` で JSON をパース
- **フェーズ 2 (ダウンロード)**: `gallery-dl -D <dest>` でファイル保存

### API エンドポイント体系

| タイプ | エンドポイント | 説明 |
|---|---|---|
| **Web UI** | `/`, `/gallery/*`, `/logs`, `/queue` | HTML レンダリング |
| **キュー管理 API** | `POST /api/queue`, `GET /api/queue/status`, `DELETE /api/queue/item` | URL キュー操作 |
| **履歴 API** | `GET /api/history/*` | ダウンロード履歴・統計情報 |
| **ヘルスチェック** | `GET /api/health` | サーバー疎通確認 |

### 依存パッケージ

| パッケージ | 用途 |
|---|---|
| `flask` | Web UI フレームワーク |
| `flask-cors` | CORS 対応 (Chrome 拡張からのリクエスト) |
| `pydantic-settings` | 環境変数管理 |
| `gallery-dl` | X / Pixiv / Imgur ダウンロード (subprocess) |
| `yt-dlp` | YouTube / TikTok / NicoNico ダウンロード (subprocess) |
| `pytest` / `pytest-mock` | テスト (85件) |

---

## 注意事項

- **gallery-dl は非公式手段**で動作しており、X の仕様変更で突然壊れる可能性がある
  - 問題発生時は [gallery-dl GitHub Issues](https://github.com/mikf/gallery-dl/issues) を確認

- **yt-dlp** も非公式手段で動作する。YouTube の仕様変更で壊れる場合は `pip install -U yt-dlp` で更新

- **Pixiv ダウンロード**には `PIXIV_REFRESH_TOKEN` が必須
  - トークンは Web UI のセットアップ画面から OAuth 経由で取得

- **Cookie ファイル** (鍵垢対応) は Netscape 形式を推奨
  - ブラウザ拡張でエクスポートしたもの使用

- **Docker で NAS に配置**する場合は、`docker-compose.yml` の `volumes` セクションで実際のパスに変更する必要がある

- **HTTP (cleartext) トラフィック**は意図的に許可されている
  - Android アプリ互換性のため。本番環境では SSL/TLS でラップすることを推奨

---

## 開発・テスト

### テストの実行

```bash
# 仮想環境を有効化した状態で
.venv\Scripts\python -m pytest tests/ -v      # Windows
# または
python -m pytest tests/ -v                     # Linux / Mac
```

現在 **85件**のテストが存在し、全て通過すること。

### テスト構成

| ファイル | 件数 | 対象 |
|---|---|---|
| `tests/test_patterns.py` | 49 | URL パターンマッチング (X / Pixiv / Imgur / yt-dlp) |
| `tests/test_log_store.py` | 25 | LogStore 全メソッド (SQLite) |
| `tests/test_image_downloader.py` | 11 | tweet_id 抽出・ファイル名パース |

### コード変更後のチェックリスト

1. `pytest tests/ -v` — 全テスト通過を確認
2. `python -c "from src.main import main"` — インポートチェック
3. コミット前に `CLAUDE.md` / `AGENTS.md` のドキュメントとコードが一致しているか確認

---

## ライセンス

このプロジェクトはオープンソースで公開されている。詳細はリポジトリを参照。

---

最後に、このドキュメントが役に立つ限り幸いだね。質問があれば、遠慮なく issue を立ててほしいよ。

宇宙の知識は記述されて初めて知識だ。ドキュメントを読んで、理解を深めてくれることを願ってる。
