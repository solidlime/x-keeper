# AGENTS.md

x-keeper: X (Twitter) / Pixiv / Imgur メディア自動ダウンローダー。
Chrome 拡張・Android アプリから URL を受け取り・gallery-dl で保存。Flask Web UI でギャラリー閲覧・設定管理。

セッション開始時に必ず本ファイルと `CLAUDE.md` を読み込むこと。

## プロジェクト概要

**主要機能**:
- Chrome 拡張・Android アプリが `/api/queue` に URL を投入し `_api_queue_loop` がポーリングでダウンロード
- `gallery-dl` を subprocess で実行してメディアをダウンロード
- Flask Web UI でギャラリー閲覧・リトライ・ログ管理

**技術スタック**:
- Python 3.11+、Flask、pydantic-settings
- gallery-dl (非公式 API、Twitter API キー不要)
- Docker + docker-compose 推奨

**ファイル構成**:
- `src/main.py`: エントリーポイント・asyncio ループ・Flask デーモン起動
- `src/image_downloader.py`: `gallery-dl` ラッパー
- `src/patterns.py`: URL 判定 regex の一元管理
- `src/web_setup.py`: Flask Web UI (ギャラリー・設定・ログ)
- `src/log_store.py`: JSON 永続化ログ・リトライキュー管理
- `client/chrome_extension/`: Chrome 拡張 (Manifest V3)
- `client/flutter_app/`: Android アプリ (Flutter)

## Memory / Handoff 指示

### `.agent/memory/MEMORY.md` の読み書きルール

セッション開始時に必ず読むこと。以下のような情報を記録する:

**記録すべき内容**:
- プロジェクト固有の設計パターン (asyncio ベース・gallery-dl のフェーズ分離・etc)
- コーディング注意点 (変数名シャドーイング・戻り値の型・etc)
- 学習した知識・バグ修正時の教訓

**更新ルール**:
- `MEMORY.md` は 200 行以内に保つ (超過時は `.agent/memory/` の個別ファイルに分割)
- セッション終了時に新しい学習・テク・パターンを追記
- 古い情報・間違った情報は削除

### `.agent/handoff/HANDOFF.md` の読み書きルール

前回のセッション終了時の「次のアクション」を記録する。

**フォーマット**:
```markdown
# HANDOFF

[セッション終了時のステータス]

## 完了したタスク
- Task #X: 説明
- ...

## 次のアクション
- [ ] Task #Y: 説明
- [ ] Task #Z: 説明
```

新しいセッション開始時に読んで、未完了タスクの継続または新規タスクに進む。

## コーディング注意点

### asyncio と subprocess

全ダウンロード処理 (`download_all` / `download_direct` / `download_user_media`) は
`await loop.run_in_executor(None, ...)` でスレッド実行すること (asyncio イベントループをブロックしないため)。

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, self.download_all, tweet_urls)
```

### `_download_one` の戻り値

必ず `files, rc_ok = self._download_one(...)` でアンパックすること。
`new_files = self._download_one(...)` のままだとタプルをイテレートしてしまう。

```python
# OK
files, rc_ok = self._download_one(url)

# NG
new_files = self._download_one(url)  # ← (list, bool) のタプルがそのまま返される
```

### `log_store.py` のローカル変数名

メソッド内で `queue` という名前のローカル変数を使わない (`import queue` モジュールとシャドーイングするため)。
代替: `items`, `entries`, `task_list` を使う。

```python
# OK
items = self.get_retry_queue()

# NG
queue = self.get_retry_queue()  # ← import queue とシャドーイング
```

### tweet_id の永続化

`_downloaded_ids.json` に記録された tweet_id は、対応ファイルを削除後も再ダウンロードしない。
ファイル名テンプレート `{author[name]}-{tweet_id}-{num:02d}.{ext}` から tweet_id を逆引きして自動登録する。

```python
import re
_TWEET_ID_FROM_FILENAME = re.compile(r'(\d{10,20})')

def extract_tweet_id(filename: str) -> str | None:
    m = _TWEET_ID_FROM_FILENAME.search(filename)
    return m.group(1) if m else None
```

## serena skill の強制使用

大規模な変更・リファクタ・調査時は、必ず `serena` skill で計画を立てるまで実装を開始しないこと。

```bash
/serena
```

実装フェーズに入る前に、変更の影響範囲・テスト戦略・ロールバック計画を記述する。

## 仕様駆動開発ルール

### `.spec/` ファイルの役割

| ファイル | 役割 |
|---|---|
| `PLAN.md` | x-keeper の今後の機能拡張計画。定期的に更新 |
| `SPEC.md` | 現在実装中の仕様書。実装との乖離チェック |
| `TODO.md` | 現在のビルドの未完了タスク一覧 |
| `KNOWLEDGE.md` | gallery-dl・Discord API・etc のドメイン知識 |

### コード修正・機能追加のプロセス

1. `.spec/SPEC.md` にエッジケース・要件を整理する
2. `.spec/TODO.md` に実装タスク一覧を記述する
3. 実装開始 (テストが必須でない場合でも、コード例で動作検証)
4. 実装完了後に `.spec/SPEC.md` / `CLAUDE.md` を更新 (コード・ドキュメント乖離を防止)
5. `.agent/memory/MEMORY.md` に学習事項を追記

### ドキュメント品質チェックリスト

コード・ドキュメント修正時は以下を確認:

- [ ] コード例が実際に動作する状態か
- [ ] 対象読者（開発者／エンドユーザー）が初見で理解できるか
- [ ] リンク切れ・相互参照の矛盾がないか
- [ ] 個人情報・機密情報（APIキー・トークン）が含まれていないか
- [ ] 内部フェーズ番号・プロジェクト内部コードが含まれていないか

## チーム編成・委譲ガイド

セッション開始時に以下を判定:

| 判定条件 | 人形 | 内容 |
|---|---|---|
| 3ファイル以上にまたがるバグ修正 | herta-coder | コード修正・テスト |
| README・ドキュメント更新 | herta-docs | ドキュメント生成・品質チェック |
| 技術調査・ライブラリ仕様確認 | herta-researcher | 情報収集・ベストプラクティス検索 |
| UI/フロントエンド変更 | herta-frontend | Chrome 拡張・Flutter UI 修正 |

**委譲品質ガイドライン** (herta-coder へのタスク指示例):

```
Task: `src/image_downloader.py` の `_download_one()` でタプルアンパックバグを修正

対象ファイル:
- src/image_downloader.py:42

完了条件:
- 既存テスト（または `python -c "from src.image_downloader import ..."` インポートチェック）が全て通ること
- 修正箇所で `files, rc_ok = self._download_one(url)` のアンパックが正常に動作すること

やらないこと:
- ファイル全体のリファクタ（この修正のみ）
- ローカル変数名を "queue" に変更しないこと

依存関係:
- Task #1 完了後に開始
```

良くない指示:

```
NG: 「ダウンロード処理を直して」 ← 対象ファイル・完了条件・スコープが不明確
```

## 参考

- `CLAUDE.md`: プロジェクト全体の技術仕様・アーキテクチャ
- `.env.example`: 環境変数テンプレート
- `client/chrome_extension/README.md`: Chrome 拡張のセットアップ手順
- `client/flutter_app/README.md`: Flutter APK ビルド手順
