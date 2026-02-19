# keep-image-saver

Google Keep に X (Twitter) のツイート URL を投稿すると、そのツイートの画像を自動で保存し、Keep のノートを削除するツール。

- 複数画像付きツイートに対応
- スレッド（連投）を遡って全画像・動画を取得
- **Twitter API キー不要** （gallery-dl を使用）
- Synology NAS の Docker で動作

---

## 機能概要

1. Google Keep を定期ポーリングする
2. X (Twitter) の URL を含むノートを検出する
3. **gallery-dl** でツイートの画像・動画（最高解像度）を取得する
4. `reply_to` メタデータを使って親ツイートを再帰的に遡りスレッド全体の画像を収集する
5. 日付フォルダ（`YYYY-MM-DD`）に保存する
6. 全画像の保存が成功した場合のみ Keep ノートをゴミ箱に移動する

---

## 必要なもの

- Docker が動く環境（Synology NAS、Linux サーバーなど）
- Google アカウント
- Google Cloud Console で発行した OAuth2 クライアント ID（初回のみ）
- Twitter API キーは不要

---

## セットアップ

### 1. 設定ファイルの作成

```bash
cp .env.example .env
```

NAS の保存先パスだけ変更しておく（Google 認証は次のステップで入力される）:

```dotenv
# NAS の場合は実際のパスに変える
SAVE_PATH=/volume1/images

# ポーリング間隔 (秒)。3600 で1時間ごと
POLL_INTERVAL_SECONDS=300
```

鍵垢のツイートにもアクセスしたい場合は Cookie ファイルを追加する:

```dotenv
GALLERY_DL_COOKIES_FILE=/data/cookies.txt
```

Cookie ファイルの取得: ブラウザ拡張 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) などで Netscape 形式でエクスポートし、`docker-compose.yml` でボリュームにマウントする。

---

### 2. Google OAuth2 クライアント ID の発行（初回のみ）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成する
2. 「**APIとサービス > 認証情報**」を開き、「**OAuth 2.0 クライアント ID を作成**」を選択する
   - アプリケーションの種類: **デスクトップアプリ**
   - ライブラリで API を有効化する手順は不要
     （memento/reminders スコープは Cloud Console ライブラリには存在しない内部スコープのため）
3. 発行された認証情報を `.env` に設定する（2通りの方法）:

   **方法 A**: `client_secrets.json` をダウンロードしてプロジェクトルートに配置する

   **方法 B**: `.env` に直接記述する

   ```dotenv
   GOOGLE_OAUTH_CLIENT_ID=123456789-xxx.apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxx
   ```

---

### 3. Google OAuth2 認証セットアップ

初回のみ、対話セットアップコマンドを実行する。
ブラウザが開くので、Google アカウントでログインしてアクセスを許可すると、
リフレッシュトークンが自動取得されて `.env` に書き込まれる。

```bash
docker compose run --rm -it keep-image-saver python -m src.token_setup
```

```
============================================================
 Google Keep OAuth2 認証
============================================================
ブラウザが開きます。Google アカウントでログインして
アクセスを許可してください。

認証に成功しました。リフレッシュトークンを .env に保存しました。
============================================================
```

> **ヘッドレス環境（ブラウザが開けない NAS など）**: ローカル PC でセットアップを実行して `.env` の `GOOGLE_OAUTH_REFRESH_TOKEN` を NAS の `.env` にコピーする

---

### 4. Docker で起動

```bash
docker compose up -d
```

ログを確認:

```bash
docker compose logs -f
```

---

## Synology NAS での設定

### ボリュームのマウント先を変更する

`docker-compose.yml` の `volumes` セクションを NAS の実際のパスに変更する:

```yaml
volumes:
  - /volume1/images:/data/images
```

### Container Manager を使う場合

1. Container Manager を開く
2. **プロジェクト** → **作成** → フォルダを指定して `docker-compose.yml` をアップロード
3. `.env` ファイルを同じフォルダに配置
4. プロジェクトを起動

---

## ディレクトリ構成

```
keep-image-saver/
├── src/
│   ├── config.py           # 設定（環境変数）
│   ├── models.py           # データクラス定義
│   ├── keep_client.py      # Google Keep クライアント
│   ├── twitter_client.py   # X (Twitter) API クライアント
│   ├── image_downloader.py # 画像ダウンロード・保存
│   ├── token_setup.py      # OAuth2 認証セットアップユーティリティ
│   └── main.py             # ポーリングループ（エントリーポイント）
├── data/
│   └── images/             # 保存先（Docker ボリュームでマウント）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 設定一覧

| 環境変数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `GOOGLE_EMAIL` | | — | Google アカウントのメールアドレス |
| `GOOGLE_OAUTH_CLIENT_ID` | ✅ | — | Google OAuth2 クライアント ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | ✅ | — | Google OAuth2 クライアントシークレット |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | ✅ | — | Google OAuth2 リフレッシュトークン（`token_setup` 実行後に自動入力） |
| `GALLERY_DL_COOKIES_FILE` | | `None` | gallery-dl の Cookie ファイルパス（鍵垢対応時のみ） |
| `SAVE_PATH` | | `/data/images` | 画像保存先ルートディレクトリ |
| `POLL_INTERVAL_SECONDS` | | `60` | Keep の確認間隔（秒） |
| `LOG_LEVEL` | | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## 注意事項

- **gkeepapi は非公式ライブラリ**であり、Google の仕様変更により動作しなくなる可能性がある
- **gallery-dl も非公式手段**で動作しており、X の仕様変更により動作しなくなる可能性がある
- Keep ノートは完全削除ではなく**ゴミ箱移動**（誤操作からの復元が可能）
- スレッド遡りは `reply_to` を使って親方向にのみ追従する（起点から遡る形）
- ダウンロード失敗が1件でもある場合は Keep ノートを削除しない（次回のポーリングで再試行される）
