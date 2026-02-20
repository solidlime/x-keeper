#!/bin/bash
set -e

if [ ! -d ".venv" ]; then
    echo "仮想環境を作成しています..."
    python3 -m venv .venv
    echo "依存パッケージをインストールしています..."
    .venv/bin/pip install -r requirements.txt
fi

echo "x-keeper を起動しています..."
echo "ギャラリー: http://localhost:8989/gallery"
echo "終了するには Ctrl+C を押してください。"
echo
.venv/bin/python -m src.main
