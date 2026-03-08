# PLAN.md

x-keeper の今後の機能拡張計画。優先度・依存関係を記載。

## Phase 1: 基盤完成（現在）

**ステータス**: 実装中

### 完了済み
- Discord Bot: X/Pixiv/Imgur URL 自動検出・ダウンロード
- Flask Web UI: ギャラリー・ログ・失敗管理
- Chrome 拡張: オフラインキュー・オンライン投入
- Flutter Android アプリ: 共有インテント対応
- Docker: 自動ビルド・デプロイ

### 実装中
- [ ] Discord 統合完全削除 (API キュー単一化)
- [ ] 自動アップデート機能（Docker + GitHub Releases）
- [ ] バグ修正（メモリリーク・edge case）

### 予定
- [ ] Pixiv マンガ・R-18 対応

## Phase 2: UI 改善

- [ ] Web UI トレンド表示（閲覧頻度・ランダム推薦）
- [ ] 複数サーバー対応（リモート同期）
- [ ] ダークモード対応

## Phase 3: 拡張性向上

- [ ] プラグイン API（カスタムダウンローダー）
- [ ] WebSocket リアルタイム処理通知
- [ ] Amazon S3 / NAS バックアップ

## 参考

詳細仕様は `SPEC.md` を参照。
