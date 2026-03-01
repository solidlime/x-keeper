@echo off
chcp 65001 > nul

REM ダブルクリック実行時は cmd /k で再起動し、ウィンドウが閉じないようにする
if "%1" neq "_run" (
    start "x-keeper APK Build" cmd /k ""%~f0" _run"
    exit /b 0
)

setlocal enabledelayedexpansion

echo ========================================
echo   x-keeper Android APK ビルド
echo ========================================
echo.

cd /d "%~dp0"

REM %~dp0 は末尾に \ が付くため、引用符エスケープ防止のため除去する
set "BASE_DIR=%~dp0"
if "!BASE_DIR:~-1!" == "\" set "BASE_DIR=!BASE_DIR:~0,-1!"

REM ── Flutter 確認 / 自動セットアップ ──────────────────────────────────────────

set "LOCAL_FLUTTER=%~dp0flutter\bin\flutter.bat"
if exist "!LOCAL_FLUTTER!" (
    set "FLUTTER_CMD=!LOCAL_FLUTTER!"
    goto :flutter_ready
)

where flutter >nul 2>&1
if not errorlevel 1 (
    set "FLUTTER_CMD=flutter"
    goto :flutter_ready
)

echo [INFO] Flutter not found. Downloading...
set "FLUTTER_ZIP=%TEMP%\flutter_sdk.zip"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_flutter.ps1" -OutFile "%FLUTTER_ZIP%" -DestDir "!BASE_DIR!"
if errorlevel 1 (
    echo [ERROR] Flutter download failed. Install manually:
    echo   https://docs.flutter.dev/get-started/install/windows
    pause & exit /b 1
)

if not exist "!LOCAL_FLUTTER!" (
    echo [ERROR] flutter.bat not found after setup: !LOCAL_FLUTTER!
    pause & exit /b 1
)
set "FLUTTER_CMD=!LOCAL_FLUTTER!"

:flutter_ready
call "%FLUTTER_CMD%" --version 2>nul | findstr /i "Flutter"
echo.

REM ── Android SDK 確認 / 自動セットアップ ──────────────────────────────────────

set "LOCAL_SDK=%~dp0android-sdk"
set "LOCAL_ADB=%LOCAL_SDK%\platform-tools\adb.exe"

REM local.properties に sdk.dir がある場合はそのパスを確認する
set "PROPS=%~dp0android\local.properties"
set "SDK_FROM_PROPS="
for /f "tokens=1,* delims==" %%a in ('findstr /i "sdk.dir" "%PROPS%" 2^>nul') do set "SDK_FROM_PROPS=%%b"

if defined SDK_FROM_PROPS (
    REM フォワードスラッシュをバックスラッシュに統一して存在チェック
    set "ADB_CHECK=!SDK_FROM_PROPS:/=\!"
    set "ADB_CHECK=!ADB_CHECK:\\\=\!"
    set "ADB_CHECK=!ADB_CHECK:\\=\!"
    if exist "!ADB_CHECK!\platform-tools\adb.exe" (
        echo [INFO] Android SDK (from local.properties)
        goto :sdk_ready
    )
)

if exist "!LOCAL_ADB!" (
    echo [INFO] Android SDK (local)
    goto :sdk_ready
)

REM ANDROID_HOME / ANDROID_SDK_ROOT 環境変数を確認する
if defined ANDROID_HOME (
    if exist "%ANDROID_HOME%\platform-tools\adb.exe" (
        echo [INFO] Android SDK (ANDROID_HOME)
        goto :sdk_ready
    )
)
if defined ANDROID_SDK_ROOT (
    if exist "%ANDROID_SDK_ROOT%\platform-tools\adb.exe" (
        echo [INFO] Android SDK (ANDROID_SDK_ROOT)
        goto :sdk_ready
    )
)

REM デフォルトインストール先を確認する
if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
    echo [INFO] Android SDK (default location)
    goto :sdk_ready
)

echo [INFO] Android SDK not found. Downloading...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_android_sdk.ps1" -SDKDir "!LOCAL_SDK!"
if errorlevel 1 (
    echo [ERROR] Android SDK setup failed. Install manually:
    echo   https://developer.android.com/studio
    pause & exit /b 1
)

:sdk_ready
echo [INFO] Android SDK OK

REM JAVA_HOME をローカル JDK に設定する (Gradle Wrapper が Java を必要とするため)
if exist "%~dp0android-sdk\jdk\java-21\bin\java.exe" (
    set "JAVA_HOME=%~dp0android-sdk\jdk\java-21"
    set "PATH=%JAVA_HOME%\bin;%PATH%"
)
echo.

REM ── [1/4] パッケージ取得 ──────────────────────────────────────────────────────
echo [1/4] flutter pub get ...
call "%FLUTTER_CMD%" pub get
if errorlevel 2 ( echo [ERROR] pub get failed & pause & exit /b 1 )

REM ── [2/4] アイコン生成 ────────────────────────────────────────────────────────
echo.
echo [2/4] Generating icons...
where python >nul 2>&1
if not errorlevel 1 (
    python make_icon.py
    if errorlevel 1 echo [WARN] make_icon.py failed ^(Pillow not installed?^) -- skipped
) else (
    echo [WARN] python not found -- icon generation skipped
)
call "%FLUTTER_CMD%" dart run flutter_launcher_icons 2>nul
if errorlevel 1 echo [WARN] flutter_launcher_icons failed -- using default icon

REM ── [3/4] APK ビルド ──────────────────────────────────────────────────────────
echo.
echo [3/4] flutter build apk --release ...
echo [INFO] APK ビルド中... 数分かかります
call "%FLUTTER_CMD%" build apk --release 2>&1
if errorlevel 1 ( echo [ERROR] Build failed & pause & exit /b 1 )

REM ── [4/4] 完了 ────────────────────────────────────────────────────────────────
echo.
echo [4/4] Build complete!
echo   APK: build\app\outputs\flutter-apk\app-release.apk
echo.

REM ── ADB インストール (任意) ───────────────────────────────────────────────────
set /p INSTALL=Install to device via ADB? [y/N]:
if /i "!INSTALL!" neq "y" goto :end

where adb >nul 2>&1
if errorlevel 1 (
    if exist "!LOCAL_ADB!" (
        set "PATH=!PATH!;!LOCAL_SDK!\platform-tools"
    ) else (
        echo [ERROR] adb not found.
        goto :end
    )
)

echo Installing via ADB...
adb install -r "build\app\outputs\flutter-apk\app-release.apk"
if errorlevel 1 ( echo [ERROR] ADB install failed ) else ( echo Install complete! )

:end
echo.
pause
exit /b 0
