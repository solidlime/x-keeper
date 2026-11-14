"""ダウンロード完了/失敗の Webhook 通知 (最小実装)。

`NOTIFY_WEBHOOK_URL` 未設定なら何もしない。送信失敗は本処理に影響させない。
"""

import json
import logging
import os
import threading
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_FILE = Path(".env")
_TIMEOUT = 5


def get_webhook_url() -> str:
    """Webhook URL を環境変数 → .env の順で解決する。"""
    url = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    if url:
        return url
    try:
        from dotenv import dotenv_values

        if _ENV_FILE.exists():
            return (dotenv_values(_ENV_FILE).get("NOTIFY_WEBHOOK_URL") or "").strip()
    except Exception:
        pass
    return ""


def notify_download(
    status: str,
    urls: list[str],
    file_count: int = 0,
    error: str | None = None,
) -> None:
    """通知をバックグラウンドスレッドで POST する。未設定なら何もしない。"""
    url = get_webhook_url()
    if not url:
        return
    payload = {
        "event": f"download.{status}",
        "status": status,
        "urls": urls,
        "file_count": file_count,
        "error": error,
    }
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()


def _post(url: str, payload: dict) -> None:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            pass
    except Exception as exc:  # 通知失敗は本処理に影響させない
        logger.warning("Webhook 通知失敗: %s", exc)
