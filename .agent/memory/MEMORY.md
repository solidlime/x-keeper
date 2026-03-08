# MEMORY

## プロジェクト概要

x-keeper: X (Twitter) / Pixiv / Imgur メディア自動ダウンローダー。
Discord Bot が監視チャンネルをスキャンし gallery-dl で保存。Flask Web UI でギャラリー閲覧・設定管理。

**主要フロー**:
1. Discord Bot が `on_message` で URL 検出 (X/Pixiv/Imgur)
2. `MediaDownloader.download_all()` / `download_user_media()` / `download_direct()` を呼び出し
3. gallery-dl を subprocess で実行 (2フェーズ: メタデータ取得 → ダウンロード)
4. ログ・リトライキューを JSON に永続化
5. Flask Web UI でギャラリー・ログ・失敗管理

## 重要な設計メモ

### asyncio ブロック防止

全ダウンロード処理 (`get_thread` / `download_all` / `download_direct` / `download_user_media`) は
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

### gallery-dl の 2フェーズ動作

**フェーズ 1** (`TwitterClient.get_thread()`): `--dump-json` でメタデータのみ取得
- 出力: JSON 配列 `[[type, metadata], [type, url, metadata], ...]`
- type=2: ツイートメタデータ、type=3: ダウンロード対象ファイル
- reply_id を解析してスレッドを遡る

**フェーズ 2** (`MediaDownloader.download_all()`): URL リストを `-D <dest>` でダウンロード
- ディレクトリ差分で新規ファイルを特定
- `--filter` オプションで既取得 tweet_id を除外 (cookies ありの場合)

## 学習した知識・教訓

（セッション進行に応じて更新）
