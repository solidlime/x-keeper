# TODO.md

現在のビルドの未完了タスク一覧。

## 実装完了
- ✅ Discord Bot: X/Pixiv/Imgur URL 自動検出
- ✅ Flask Web UI: ギャラリー・ログ・リトライ管理
- ✅ Chrome 拡張 (Manifest V3): オフラインキュー・オンライン投入
- ✅ Flutter Android APK: 共有インテント対応
- ✅ Docker: 自動ビルド・GitHub Actions デプロイ

## 実装予定
- [ ] Discord 統合完全削除（API キュー単一化）
- [ ] 自動アップデート機能（Docker イメージ・GitHub Releases）
- [ ] バグ修正
  - [ ] メモリリーク調査（長時間実行時）
  - [ ] Edge case 処理（特殊文字ファイル名・超大型スレッド）

## 参考

詳細な実装計画は `PLAN.md` を参照。
