@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo   x-keeper Android APK ビルド
echo ========================================
echo.

cd /d "%~dp0"

REM ── Flutter 確認 / 自動セットアップ ──────────────────────────────────────────

REM バッチファイルと同じフォルダにローカルの flutter を置いた場合は優先して使う
set "LOCAL_FLUTTER=%~dp0flutter\bin\flutter.bat"
if exist "!LOCAL_FLUTTER!" (
    echo [INFO] ローカル Flutter を使用: !LOCAL_FLUTTER!
    set "FLUTTER_CMD=!LOCAL_FLUTTER!"
    goto :flutter_ready
)

REM PATH に flutter があるか確認する
where flutter >nul 2>&1
if not errorlevel 1 (
    set "FLUTTER_CMD=flutter"
    goto :flutter_ready
)

REM ── Flutter が見つからない場合: 自動ダウンロード ──────────────────────────────
echo [INFO] Flutter が見つかりません。自動セットアップを開始します...
echo.

REM ダウンロード先ディレクトリを作成する
set "FLUTTER_DIR=%~dp0flutter"
if not exist "!FLUTTER_DIR!" mkdir "!FLUTTER_DIR!"

REM winget で Flutter SDK をインストール (Windows 10 1709 以降で利用可能)
where winget >nul 2>&1
if not errorlevel 1 (
    echo [1/2] winget で Flutter SDK をインストール中...
    winget install --id Google.Flutter --accept-source-agreements --accept-package-agreements
    if not errorlevel 1 (
        echo [INFO] winget インストール完了。PATH を更新してください。
        echo        (ターミナルを再起動してから再度このバッチを実行してください)
        pause & exit /b 0
    )
    echo [WARN] winget インストール失敗。ZIP ダウンロードにフォールバックします...
)

REM winget がないまたは失敗した場合: GitHub リリースから ZIP を直接ダウンロードする
echo [1/2] Flutter SDK を GitHub からダウンロード中 (数分かかります)...
set "FLUTTER_ZIP=%TEMP%\flutter_sdk.zip"
set "FLUTTER_URL=https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_stable.zip"

REM PowerShell の Invoke-WebRequest でダウンロードする
powershell -NoProfile -Command "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%FLUTTER_URL%' -OutFile '%FLUTTER_ZIP%' -UseBasicParsing }"
if errorlevel 1 (
    echo [ERROR] ダウンロード失敗。手動でインストールしてください:
    echo   https://docs.flutter.dev/get-started/install/windows
    pause & exit /b 1
)

echo [2/2] Flutter SDK を展開中 (数分かかります)...
powershell -NoProfile -Command "& { $ProgressPreference='SilentlyContinue'; Expand-Archive -Path '%FLUTTER_ZIP%' -DestinationPath '%~dp0' -Force }"
if errorlevel 1 (
    echo [ERROR] 展開失敗。%FLUTTER_ZIP% を手動で展開してください。
    pause & exit /b 1
)
del /f /q "%FLUTTER_ZIP%" 2>nul

if not exist "!LOCAL_FLUTTER!" (
    echo [ERROR] 展開後も flutter が見つかりません。フォルダ構造を確認してください。
    echo   期待パス: !LOCAL_FLUTTER!
    pause & exit /b 1
)

echo [INFO] Flutter SDK のセットアップ完了!
set "FLUTTER_CMD=!LOCAL_FLUTTER!"

:flutter_ready

REM Flutter バージョン表示
for /f "tokens=*" %%v in ('"%FLUTTER_CMD%" --version 2^>nul ^| findstr /i "Flutter"') do (
    echo %%v
)
echo.

REM ── [1/4] パッケージ取得 ──────────────────────────────────────────────────────
echo [1/4] flutter pub get ...
"%FLUTTER_CMD%" pub get
if errorlevel 1 ( echo [ERROR] pub get 失敗 & pause & exit /b 1 )

REM ── [2/4] アイコン生成 ────────────────────────────────────────────────────────
echo.
echo [2/4] アイコン生成 ...
where python >nul 2>&1
if not errorlevel 1 (
    python make_icon.py
    if errorlevel 1 echo [WARN] make_icon.py 失敗 ^(Pillow 未インストール?^) — スキップ
) else (
    echo [WARN] python が見つかりません — アイコン生成をスキップ
)

"%FLUTTER_CMD%" dart run flutter_launcher_icons 2>nul
if errorlevel 1 echo [WARN] flutter_launcher_icons 失敗 — デフォルトアイコンを使用

REM ── [3/4] APK ビルド ──────────────────────────────────────────────────────────
echo.
echo [3/4] flutter build apk --release ...
"%FLUTTER_CMD%" build apk --release
if errorlevel 1 ( echo [ERROR] ビルド失敗 & pause & exit /b 1 )

REM ── [4/4] 完了 ────────────────────────────────────────────────────────────────
echo.
echo [4/4] ビルド完了!
echo   APK: build\app\outputs\flutter-apk\app-release.apk
echo.

REM ── ADB インストール (任意) ───────────────────────────────────────────────────
set /p INSTALL=ADB で実機にインストールしますか？ [y/N]:
if /i "!INSTALL!" neq "y" goto :end

where adb >nul 2>&1
if errorlevel 1 (
    echo [ERROR] adb が見つかりません。Android Platform Tools をインストールしてください。
    goto :end
)

echo ADB インストール中...
adb install -r "build\app\outputs\flutter-apk\app-release.apk"
if errorlevel 1 ( echo [ERROR] ADB インストール失敗 ) else ( echo インストール完了! )

:end
echo.
pause
exit /b 0
