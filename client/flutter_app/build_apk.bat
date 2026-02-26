@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo   x-keeper Android APK ビルド
echo ========================================
echo.

cd /d "%~dp0"

REM ── Flutter 確認 ──────────────────────────────────────────────────────────────
where flutter >nul 2>&1
if errorlevel 1 (
    echo [ERROR] flutter が見つかりません。
    echo   https://docs.flutter.dev/get-started/install/windows
    echo   インストール後に PATH を通してください。
    pause & exit /b 1
)

for /f "tokens=*" %%v in ('flutter --version 2^>nul ^| findstr /i "Flutter"') do (
    echo %%v
)
echo.

REM ── [1/4] パッケージ取得 ──────────────────────────────────────────────────────
echo [1/4] flutter pub get ...
flutter pub get
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

dart run flutter_launcher_icons 2>nul
if errorlevel 1 echo [WARN] flutter_launcher_icons 失敗 — デフォルトアイコンを使用

REM ── [3/4] APK ビルド ──────────────────────────────────────────────────────────
echo.
echo [3/4] flutter build apk --release ...
flutter build apk --release
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
