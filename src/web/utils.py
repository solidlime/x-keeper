"""共通ユーティリティ・定数。"""

import os
import re
from pathlib import Path

from flask import Response

from ..patterns import TWEET_ID_RE as _TWEET_ID_RE

# ── 定数 ──────────────────────────────────────────────────────────────────────

_PORT = int(os.getenv("WEB_SETUP_PORT", "8989"))
_SAVE_PATH = os.getenv("SAVE_PATH", "./data")
_ENV_FILE = Path(".env")

# サムネイルキャッシュ
_THUMBS_DIR = "_thumbs"
_THUMB_MAX_SIZE = (320, 320)
_THUMB_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.webp', '.gif'})


# ── CORS プリフライト ──────────────────────────────────────────────────────────

def _cors_preflight() -> Response:
    """OPTIONS プリフライトリクエストに対して 204 を返す。"""
    response = Response("", 204)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ── .env ユーティリティ ────────────────────────────────────────────────────────

def upsert_env_value(key: str, value: str) -> None:
    """.env ファイルに key=value を上書き追加する。"""
    lines = (
        _ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        if _ENV_FILE.exists()
        else []
    )
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    new_line = f"{key}={value}\n"

    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            _ENV_FILE.write_text("".join(lines), encoding="utf-8")
            return

    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    lines.append(new_line)
    _ENV_FILE.write_text("".join(lines), encoding="utf-8")


# ── メディアヘルパー ───────────────────────────────────────────────────────────

def _media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "gif", "webp", "avif"}:
        return "image"
    if ext in {"mp4", "mov", "mkv", "avi", "webm", "m4v"}:
        return "video"
    if ext in {"mp3", "ogg", "aac", "flac", "wav", "m4a", "opus"}:
        return "audio"
    return "other"


# ── 設定ヘルパー ───────────────────────────────────────────────────────────────

def _current_status() -> dict[str, bool]:
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    keys = ["GALLERY_DL_COOKIES_FILE", "PIXIV_REFRESH_TOKEN"]
    return {k: bool(env.get(k)) for k in keys}


def _prefill_values() -> dict[str, str]:
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    return {
        "cookies_file": env.get("GALLERY_DL_COOKIES_FILE", ""),
        "pixiv_token": env.get("PIXIV_REFRESH_TOKEN", ""),
        "retry_poll_interval": env.get("RETRY_POLL_INTERVAL", "30"),
        "gallery_thumb_count": env.get("GALLERY_THUMB_COUNT", "50"),
    }


# ── history インポートヘルパー ─────────────────────────────────────────────────

def _extract_tweet_ids_from_import(data: dict | list) -> list[str]:
    """TwitterMediaHarvest 互換フォーマットまたは ID リストから tweet_id を抽出する。

    対応フォーマット:
      - TMH 形式: {"records": [{"tweetId": "123..."}, ...]}
      - シンプルリスト: ["123...", "456...", ...]
      - フラット辞書: {"data": [{"tweet_id": "123..."}, ...]}
    """
    ids: set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str) and _TWEET_ID_RE.match(item):
                ids.add(item)
    elif isinstance(data, dict):
        records = data.get("records") or data.get("items") or data.get("data") or []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            tid = rec.get("tweetId") or rec.get("tweet_id") or rec.get("id")
            if tid and _TWEET_ID_RE.match(str(tid)):
                ids.add(str(tid))
    return sorted(ids)
