@echo off
chcp 65001 > nul

if not exist .venv (
    echo 仮想環境を作成しています...
    python -m venv .venv
    echo 依存パッケージをインストールしています...
    .venv\Scripts\pip install -r requirements.txt
)

echo x-keeper を起動しています...
echo ギャラリー: http://localhost:8989/gallery
echo 終了するには Ctrl+C を押してください。
echo.
.venv\Scripts\python -m src.main

pause