"""Flask アプリケーション。src/web/ パッケージのエントリーポイント。"""

import hashlib
import os
import secrets

from flask import Flask

from .globals import set_log_store
from .routes import register_blueprints

_ALLOWED_HEADERS = "Content-Type, X-API-Token, Authorization"

app = Flask(__name__)
# API_TOKEN 設定時はセッション鍵を安定化 (再起動でブラウザ認証が切れないように)
app.secret_key = (
    hashlib.sha256(f"x-keeper:{os.getenv('API_TOKEN', '')}".encode()).hexdigest()
    if os.getenv("API_TOKEN", "")
    else secrets.token_hex(32)
)


@app.after_request
def _add_cors_headers(response):
    """全レスポンスに CORS ヘッダーを付与する。"""
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", _ALLOWED_HEADERS)
    return response


register_blueprints(app)

__all__ = ["app", "set_log_store"]
