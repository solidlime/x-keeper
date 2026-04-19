# MEMORY

## プロジェクト概要

x-keeper: X (Twitter) / Pixiv / Imgur / YouTube / TikTok / NicoNico メディア自動ダウンローダー。
Chrome 拡張・Android アプリから URL を受け取り・gallery-dl / yt-dlp で保存。Flask Web UI でギャラリー閲覧・設定管理・ストレージ統計。

**主要フロー**:
1. Chrome 拡張 / Android アプリが `/api/queue` に URL を投入
2. `_api_queue_loop` が `RETRY_POLL_INTERVAL` 秒ごとにキューをポーリング
3. URL 種別を `patterns.py` で判定し `MediaDownloader` の適切なメソッドを呼び出し
4. gallery-dl または yt-dlp を subprocess で実行してメディアを保存
5. ログ・重複チェック用データを SQLite (`xkeeper.db`) に永続化
6. Flask Web UI でギャラリー・ログ・失敗管理・統計確認

## 重要な設計メモ

### asyncio ブロック防止

全ダウンロード処理 (`download_all` / `download_direct` / `download_user_media` / `download_yt_dlp`) は
`await loop.run_in_executor(None, ...)` でスレッド実行すること。

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, self.download_all, tweet_urls)
```

### tweet_id 永続化 (SQLite)

- SQLite の `downloaded_ids` テーブルに tweet_id を記録。対応ファイル削除後も再ダウンロードしない
- ファイル名テンプレート: `{author[name]}-{tweet_id}-{num:02d}.{extension}`
- `TWEET_ID_FROM_FILENAME` regex は `\d{10,20}` でカバー (古いツイートも対応)

### `_download_one` の戻り値

必ず `files, rc_ok = self._download_one(...)` でアンパックすること。
`new_files = self._download_one(...)` のままだとタプルをイテレートしてしまう。

### log_store.py のローカル変数名

メソッド内でローカル変数名に `queue` を使わない (`import queue` とシャドーイング)。
代替: `items`, `entries`, `task_list` を使う。

### gallery-dl / yt-dlp の使い方

`MediaDownloader` は gallery-dl / yt-dlp を subprocess で呼び出す。
- `gallery-dl -D <dest>`: ダウンロード先指定、ディレクトリ差分で新規ファイルを特定
- `yt-dlp -o <template>`: 日付フォルダに保存。`_DOWNLOAD_TIMEOUT` 秒のタイムアウト付き

### src/web/ パッケージ構造

```
src/web/
  __init__.py     # Flask app + Blueprint 登録
  globals.py      # _log_store 管理
  utils.py        # 定数・ヘルパー関数
  templates.py    # 全 HTML テンプレート文字列
  routes/
    setup.py      # bp_setup  (/, save-*, pixiv-oauth/*)
    gallery.py    # bp_gallery (/gallery/*)
    api.py        # bp_api    (/api/*)
    media.py      # bp_media  (/media/*, /delete-media)
    admin.py      # bp_admin  (/logs, /queue, /failures, /stats)
```

`src/web_setup.py` は後方互換のための薄いシムのみ。

## 学習した知識・教訓

- `re` import を patterns.py に移した後も `web/utils.py` の `upsert_env_value` が `re.compile` を直接使っているためNameError → `import re` を再追加
- `API_URL_PATTERN` に youtube.com を追加したため既存テストの「マッチしないはず」ケースが失敗 → テスト側を修正
- F5(SQLite) マイグレーション: 旧JSONファイルがある場合 `.json.bak` にリネームして自動移行
