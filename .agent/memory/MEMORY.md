# MEMORY

## プロジェクト概要

x-keeper: X (Twitter) / Pixiv / Imgur メディア自動ダウンローダー。
Chrome 拡張・Android アプリから URL を受け取り・gallery-dl で保存。Flask Web UI でギャラリー閲覧・設定管理。

**主要フロー**:
1. Chrome 拡張 / Android アプリが `/api/queue` に URL を投入
2. `_api_queue_loop` が `RETRY_POLL_INTERVAL` 秒ごとにキューをポーリング
3. URL 種別を `patterns.py` で判定し `MediaDownloader` の適切なメソッドを呼び出し
4. gallery-dl を subprocess で実行してメディアを保存
5. ログ・重複チェック用 tweet_id を JSON に永続化
6. Flask Web UI でギャラリー・ログ・失敗管理

## 重要な設計メモ

### asyncio ブロック防止

全ダウンロード処理 (`download_all` / `download_direct` / `download_user_media`) は
`await loop.run_in_executor(None, ...)` でスレッド実行すること。

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, self.download_all, tweet_urls)
```

### tweet_id 永続化

- `_downloaded_ids.json` に記録された tweet_id は、対応ファイル削除後も再ダウンロードしない
- ファイル名テンプレート: `{author[name]}-{tweet_id}-{num:02d}.{extension}`
- `_TWEET_ID_FROM_FILENAME` regex は `\d{10,20}` でカバー (古いツイートも対応)

### `_download_one` の戻り値

必ず `files, rc_ok = self._download_one(...)` でアンパックすること。
`new_files = self._download_one(...)` のままだとタプルをイテレートしてしまう。

### log_store.py のローカル変数名

メソッド内でローカル変数名に `queue` を使わない (`import queue` とシャドーイング)。
代替: `items`, `entries`, `task_list` を使う。

### gallery-dl の使い方

`MediaDownloader` は gallery-dl を subprocess で呼び出す。`-D <dest>` でダウンロード先を指定し、
ディレクトリ差分で新規ファイルを特定する。`--filter` オプションで既取得 tweet_id を除外 (cookies あり時)。

## 学習した知識・教訓

（セッション進行に応じて更新）
