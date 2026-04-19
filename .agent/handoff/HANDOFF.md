# HANDOFF

リファクタ R1〜R4 + 機能追加 F1/F3/F5 が完了。全ドキュメントを最新化済み。

## 完了したタスク

- R4: AGENTS.md / MEMORY.md のドキュメント整合性修正
- R2: `src/patterns.py` 作成・URL regex 一元管理
- R3: pytest テスト基盤構築 (85件)
- R1: `src/web_setup.py` → `src/web/` パッケージ分割
- F1: yt-dlp 統合 (YouTube / TikTok / NicoNico)
- F3: ストレージ統計ダッシュボード (`/stats`, `/api/stats`, Chart.js)
- F5: JSON 永続化 → SQLite (`xkeeper.db`) 移行・自動マイグレーション

## 次のアクション

- [ ] F7: 複数 Cookie プロファイル管理 (X用・Pixiv用を切り替え)
- [ ] F8: スケジュールダウンロード (apscheduler で定期チェック)
- [ ] F9: タグ付け・お気に入り機能 (SQLite 移行済みなので実装可能)
