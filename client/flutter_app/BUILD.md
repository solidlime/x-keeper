# x-keeper Android アプリ ビルド手順

## 前提条件

- [Flutter SDK](https://docs.flutter.dev/get-started/install/windows) 3.19 以上
- Android Studio / Android SDK (API 21+)
- Python 3 + Pillow (`pip install Pillow`) — アイコン生成用

## ビルド手順

```bash
# 1. Flutter プロジェクトとして初期化 (このディレクトリで実行)
flutter create . --org com.xkeeper --project-name xkeeper_client

# 2. 依存パッケージを取得
flutter pub get

# 3. アイコンを生成
python make_icon.py
dart run flutter_launcher_icons

# 4. APK をビルド (リリース版)
flutter build apk --release

# 出力先: build/app/outputs/flutter-apk/app-release.apk
```

## デバッグビルド (実機接続時)

```bash
flutter run --debug
```

## インストール

```bash
# ADB でインストール
adb install build/app/outputs/flutter-apk/app-release.apk
```

または `app-release.apk` をAndroid端末に転送して直接インストール。

## 設定

1. アプリを起動する
2. 右上の歯車アイコン → サーバー URL を設定
   - 例: `http://192.168.1.10:8989`
3. 「接続テスト」で疎通確認

## 使い方

X (Twitter) / Pixiv のブラウザで共有ボタン → **x-keeper** を選択すると、
URL がサーバーのダウンロードキューに追加される。

サーバーに接続できない場合は端末内にキューイングされ、
次回接続時に自動送信される。

## サーバー側の注意

Docker 使用時は `usesCleartextTraffic="true"` を設定済み。
外部からアクセスする場合はルーターのポート転送 (8989) を設定するか、
同一 Wi-Fi 内での利用を推奨する。
