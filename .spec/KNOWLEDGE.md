# KNOWLEDGE.md

gallery-dl・Discord API・Twitter API 等のドメイン知識を記録。

## gallery-dl の使い方

### 基本的な invocation

```bash
# メディアをダウンロード
gallery-dl -D <destination_dir> <url>

# メタデータのみ取得（JSON 出力）
gallery-dl --dump-json <url>

# 除外フィルター（既取得 ID をスキップ）
gallery-dl -D <destination_dir> --filter '<id> not in {1234567890, 1111111111}' <url>
```

### JSON 出力フォーマット

`--dump-json` は stdout 全体が1つの JSON 配列：

```json
[
  [2, {"author": {"name": "user"}, "date": "2026-03-08", "tweet_id": "1234567890"}],
  [3, "https://example.com/image.jpg", {"filename": "image.jpg"}],
  [3, "https://example.com/image2.jpg", {"filename": "image2.jpg"}],
  ...
]
```

- `type=2`: ツイートメタデータ (author・date・tweet_id・reply_id 等)
- `type=3`: ダウンロード対象ファイル (URL・filename)

### ファイル名テンプレート

デフォルト: `{author[name]}-{tweet_id}-{num:02d}.{extension}`

例: `user-1234567890-01.jpg`

tweet_id は正規表現 `\d{10,20}` で逆引き可能 (古いツイートも対応)。

### Cookies ありの場合の最適化

```bash
gallery-dl --cookies <cookies.txt> \
  --extractor twitter.conversations=true \
  --dump-json <twitter_url>
```

`extractor.twitter.conversations=true` でスレッド全体を1コマンドで取得可能。
`reply_id` を手動で遡る必要がなくなる。

## Discord API

### Privileged Intents

`discord.Intents.message_content = True` が必須。
Developer Portal > Applications > [App] > Bot > Privileged Gateway Intents で有効化。

### メッセージリアクション

`message.add_reaction()` でリアクション追加。

```python
await message.add_reaction('✅')  # 処理完了
await message.add_reaction('⏳')  # 処理中（後で削除）
await message.add_reaction('❌')  # 失敗
await message.add_reaction('⏭️')   # 重複スキップ
```

### チャンネル履歴スキャン

```python
async for message in channel.history(limit=100, oldest_first=False):
    if message.author == bot.user:
        continue
    # メッセージ処理
```

最新 100 件を取得（`oldest_first=False` で新しい順）。

## Twitter / X API

### URL パターン

- **Status**: `https://x.com/{user}/status/{tweet_id}`
- **Media 欄**: `https://x.com/{user}/media`
- **Legacy**: `https://twitter.com/{user}/status/{tweet_id}`

### gallery-dl の Twitter 拡張

非公式 API を使用。Twitter API キー不要だが仕様変更で壊れるリスクあり。

`_parse_tweet_info` で JSON レスポンスを解析する際、`--dump-json` フォーマット変更に注意。

## Pixiv API

### OAuth PKCE フロー

```
1. /pixiv-oauth/start で PKCE コード・state を生成
2. ユーザーが Pixiv ログイン・認可
3. /pixiv-oauth/exchange で code → refresh_token を交換
4. refresh_token を環境変数 PIXIV_REFRESH_TOKEN に保存
```

Refresh token の有効期限は約 60 日。期限切れ時は再認可が必要。

### R-18 コンテンツ

gallery-dl が Pixiv OAuth を使用している場合のみ取得可能。
Cookie での直接アクセスは制限される可能性あり。

## Imgur API

### 対応形式

- アルバム: `imgur.com/a/{album_id}`
- ギャラリー: `imgur.com/gallery/{gallery_id}`
- 単体画像: `imgur.com/{image_id}`
- 直リンク: `i.imgur.com/{image_id}.{ext}`

### gallery-dl での取得

非公式 API。API キー不要。
メタデータ（EXIF）は削除される場合がある。

## asyncio と subprocess

### run_in_executor を使う理由

`subprocess.run()` はブロッキング。asyncio イベントループを止めてしまう。
`loop.run_in_executor()` でスレッドプールで実行することで、イベントループの応答性を保つ。

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, long_running_function)
```

### ThreadPoolExecutor のデフォルト

`None` を渡すと Python のデフォルト ThreadPoolExecutor を使用。
スレッド数は `min(32, os.cpu_count() + 4)` (Python 3.13+)。

## セキュリティ上の注意

### パストラバーサル対策

Flask で `/media/<path>` ルートを提供する場合：

```python
from flask import safe_join, abort
import os

@app.get('/media/<path>')
def serve_media(path):
    try:
        full_path = safe_join(SAVE_PATH, path)
    except ValueError:
        abort(400)
    if not os.path.exists(full_path):
        abort(404)
    return send_file(full_path)
```

`safe_join()` でパストラバーサル(`../../../etc/passwd`) を防止。
