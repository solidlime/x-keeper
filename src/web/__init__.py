"""Flask アプリケーション。src/web/ パッケージのエントリーポイント。"""

import secrets

from flask import Flask

from .globals import set_log_store
from .routes import register_blueprints

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)


@app.after_request
def _add_cors_headers(response):
    """全レスポンスに CORS ヘッダーを付与する。"""
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
    return response


register_blueprints(app)

__all__ = ["app", "set_log_store"]
