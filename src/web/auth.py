"""API トークン認証。

`API_TOKEN` が未設定なら認証無効 (ローカル利便性優先)。
設定済みなら `/api/*` は `X-API-Token` / `Authorization: Bearer` / ブラウザセッションで保護する。
`/api/health` と OPTIONS プリフライトは常に素通し。
"""

import os
import secrets
from pathlib import Path

from flask import jsonify, request, session

_ENV_FILE = Path(".env")

# 認証不要のパス
_PUBLIC_PATHS = frozenset({"/api/health"})


def get_api_token() -> str:
    """現在有効な API トークンを返す (環境変数 → .env の順)。"""
    token = os.getenv("API_TOKEN", "").strip()
    if token:
        return token
    try:
        from dotenv import dotenv_values

        if _ENV_FILE.exists():
            return (dotenv_values(_ENV_FILE).get("API_TOKEN") or "").strip()
    except Exception:
        pass
    return ""


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


def _request_token() -> str:
    token = request.headers.get("X-API-Token", "").strip()
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def is_authenticated() -> bool:
    expected = get_api_token()
    if not expected:
        return True
    provided = _request_token()
    if provided and secrets.compare_digest(provided, expected):
        return True
    session_token = session.get("api_token") or ""
    return bool(session_token) and secrets.compare_digest(str(session_token), expected)


def require_api_token():
    """Blueprint before_request フック。未認証なら 401 JSON を返す。"""
    if request.method == "OPTIONS" or request.path in _PUBLIC_PATHS:
        return None
    if is_authenticated():
        return None
    return jsonify({"error": "unauthorized"}), 401
