# SPEC.md

x-keeper の技術仕様。実装と乖離した場合は随時更新する。

## API 仕様

### Web UI ルート

`src/web_setup.py` で定義。詳細は `CLAUDE.md` の「web_setup.py のルート」セクション参照。

| ルート | Method | 説明 |
|---|---|---|
| `/` | GET | セットアップ UI ／ ギャラリーへリダイレクト |
| `/gallery` | GET | ギャラリートップ（日付アコーディオン・先読みサムネイル） |
| `/media/<path>` | GET | メディア配信（send_from_directory） |
| `/logs` | GET | ログ表示（最新 100 件） |
| `/failures` | GET | 失敗リスト |
| `/api/health` | GET | ヘルスチェック（拡張・APK 用） |
| `/api/queue` | POST | キューに URL 追加 |
| `/api/queue/status` | GET | キュー一覧（拡張・APK 用） |

### Discord Bot

`src/discord_bot.py` で定義。

**監視対象 URL パターン**:
- X status: `twitter.com|x.com/*/status/*`
- X ユーザーメディア: `twitter.com|x.com/*/media`
- Pixiv: `pixiv.net/*/artworks/*`
- Imgur: `imgur.com/*`

**リアクション仕様**:
- ✅: 処理完了・再処理不要
- ⏳: 処理中（削除される）
- ❌: 処理失敗（Web UI からリトライ可能）
- ⏭️: 重複スキップ（全アイテムが既取得）

## データ永続化

### JSON ログファイル

| ファイル | 役割 | 最大件数 |
|---|---|---|
| `_download_log.json` | 処理ログ（成功・失敗） | 500 |
| `_retry_queue.json` | リトライキュー | 無制限 |
| `_downloaded_ids.json` | tweet_id 重複防止リスト | 無制限 |
| `_api_queue.json` | API キュー（拡張・APK） | 無制限 |

### ギャラリー保存先

デフォルト: `./data` （SAVE_PATH）
構造:
```
./data/
├── 2026-03-01/
│   ├── user-1234567890-01.jpg
│   ├── user-1234567890-02.jpg
│   └── ...
├── 2026-03-02/
│   └── ...
└── _download_log.json
```

## 環境変数

詳細は `CLAUDE.md` の「環境変数 / .env」セクション参照。

必須:
- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`

オプション:
- `GALLERY_DL_COOKIES_FILE`: Twitter API キー不要な代わり cookie 必須
- `PIXIV_REFRESH_TOKEN`: Pixiv 鍵垢対応
- `SAVE_PATH`: デフォルト `./data`
- `WEB_SETUP_PORT`: デフォルト 8989

## エッジケース・既知の制限

### X (Twitter)

- スレッド遡り: 最大遡行数は gallery-dl に依存
- メディア欄: ユーザー全メディアを一括ダウンロード（カウントが多い場合はタイムアウトリスク）

### Pixiv

- R-18 コンテンツ: PIXIV_REFRESH_TOKEN による OAuth 認証が必須
- マンガ: 現在対応予定中

### Imgur

- EXIF データ削除: Imgur 側で自動削除（メタデータ取得不可）

### gallery-dl

- 非公式 API: X の仕様変更で壊れる可能性がある
- `--dump-json` フォーマット: type=2 (メタデータ)・type=3 (ファイル) に依存

## 参考

- `CLAUDE.md`: 詳細なアーキテクチャ・処理フロー
- `AGENTS.md`: コーディング注意点・設計パターン
- `.agent/memory/MEMORY.md`: 設計メモ・学習事項
