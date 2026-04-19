"""REST API ルート (Chrome 拡張 / Android アプリ向け)。"""

import json
import queue as _queue_module
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask import current_app

from ...patterns import API_URL_PATTERN as _API_URL_PATTERN
from ..globals import get_log_store
from ..utils import _cors_preflight, _extract_tweet_ids_from_import

bp_api = Blueprint("bp_api", __name__)


@bp_api.route("/api/update", methods=["POST", "OPTIONS"])
def api_update():
    """gallery-dl と yt-dlp を最新バージョンに更新する。"""
    if request.method == "OPTIONS":
        return _cors_preflight()
    import subprocess
    import re as _re
    try:
        result = subprocess.run(
            ["pip", "install", "--upgrade", "gallery-dl", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        gdl_match = _re.search(r"Successfully installed .*?gallery-dl-([\d.]+)", output)
        ytdlp_match = _re.search(r"Successfully installed .*?yt-dlp-([\d.]+)", output)
        already = "already up-to-date" in output.lower() or "already satisfied" in output.lower()
        versions = {}
        if gdl_match:
            versions["gallery_dl"] = gdl_match.group(1)
        if ytdlp_match:
            versions["yt_dlp"] = ytdlp_match.group(1)
        return jsonify({
            "ok": result.returncode == 0,
            "versions": versions,
            # 後方互換: 単一バージョンフィールドは gallery-dl を優先
            "version": gdl_match.group(1) if gdl_match else None,
            "already_up_to_date": already and not versions,
            "output": output[-2000:],
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "タイムアウト (120秒)"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp_api.route("/api/health")
def api_health():
    """サーバー疎通確認エンドポイント。"""
    return jsonify({"status": "ok", "version": "1.0"})


@bp_api.route("/api/stats")
def api_stats():
    """ストレージ統計情報を返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log_store not initialized"}), 503
    try:
        stats = _log_store.get_storage_stats()
        return jsonify(stats)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp_api.route("/api/queue", methods=["POST", "OPTIONS"])
def api_queue():
    """URL を直接ダウンロードキューに追加する。

    Request body (JSON):
        {"url": "https://x.com/user/status/123..."}

    Response (202):
        {"queued": true, "url": "https://..."}

    複数 URL を一括投入する場合は {"urls": ["https://...", ...]} でも受け付ける。
    """
    if request.method == "OPTIONS":
        return _cors_preflight()

    _log_store = get_log_store()
    data = request.get_json(silent=True) or {}

    raw_urls: list[str] = []
    if "urls" in data:
        raw_urls = [u.strip() for u in data["urls"] if isinstance(u, str)]
    elif "url" in data:
        raw_urls = [data["url"].strip()]

    if not raw_urls:
        return jsonify({"error": "url or urls is required"}), 400

    accepted: list[str] = []
    rejected: list[str] = []
    for url in raw_urls:
        if _API_URL_PATTERN.match(url):
            if _log_store:
                _log_store.queue_url_download(url)
            accepted.append(url)
        else:
            rejected.append(url)

    if not accepted:
        return jsonify({"error": "no supported URLs", "rejected": rejected}), 400

    return jsonify({"queued": True, "accepted": accepted, "rejected": rejected}), 202


@bp_api.route("/api/logs/recent")
def api_logs_recent():
    """直近のダウンロード処理結果を最新 5 件返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    logs = _log_store.get_recent_logs(limit=5)
    result = [
        {
            "ts": entry.get("ts"),
            "status": entry.get("status"),
            "urls": entry.get("urls", []),
            "file_count": entry.get("file_count"),
            "error": entry.get("error"),
        }
        for entry in logs
    ]
    return jsonify(result)


@bp_api.route("/api/history/count")
def api_history_count():
    """ダウンロード済み tweet ID の件数を返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    return jsonify({"count": len(_log_store.get_downloaded_ids())})


@bp_api.route("/api/history/ids")
def api_history_ids():
    """ダウンロード済み tweet ID の全件リストを返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify([]), 503
    return jsonify(sorted(_log_store.get_downloaded_ids()))


@bp_api.route("/api/history/urls/count")
def api_history_urls_count():
    """ダウンロード済み URL (Pixiv / Imgur 等) の件数を返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"count": 0})
    return jsonify({"count": _log_store.count_downloaded_urls()})


@bp_api.route("/api/history/urls")
def api_history_urls():
    """ダウンロード済み URL (Pixiv / Imgur 等) の全件リストを返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify([])
    return jsonify(sorted(_log_store.get_downloaded_urls()))


@bp_api.route("/api/queue/status")
def api_queue_status():
    """直接ダウンロードキュー (処理待ち URL 一覧) を返す。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify([])
    return jsonify(_log_store.peek_api_queue())


@bp_api.route("/api/queue/item", methods=["DELETE", "OPTIONS"])
def api_queue_item():
    """直接ダウンロードキューから指定 URL を削除する。"""
    if request.method == "OPTIONS":
        return _cors_preflight()
    _log_store = get_log_store()
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    if _log_store.remove_api_url(url):
        return jsonify({"deleted": True})
    return jsonify({"error": "not found"}), 404


@bp_api.route("/api/queue/clear", methods=["POST", "OPTIONS"])
def api_queue_clear():
    """直接ダウンロードキューを全件削除する。"""
    if request.method == "OPTIONS":
        return _cors_preflight()
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    count = _log_store.clear_api_queue()
    return jsonify({"deleted": count})


@bp_api.route("/api/history/export")
def api_history_export():
    """ダウンロード済み tweet ID を TwitterMediaHarvest 互換フォーマットでエクスポートする。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503

    ids = sorted(_log_store.get_downloaded_ids())
    records = [{"tweetId": tid, "downloadedAt": None} for tid in ids]
    payload = {
        "version": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    return jsonify(payload)


@bp_api.route("/api/history/import", methods=["POST", "OPTIONS"])
def api_history_import():
    """TwitterMediaHarvest 互換フォーマットで tweet ID をインポートする。"""
    if request.method == "OPTIONS":
        return _cors_preflight()

    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503

    data = request.get_json(silent=True)
    if data is None:
        current_app.logger.warning(
            "history/import: JSON 解析失敗 (Content-Type=%s)", request.content_type
        )
        return jsonify({"error": "invalid JSON body"}), 400

    tweet_ids = _extract_tweet_ids_from_import(data)
    if not tweet_ids:
        if isinstance(data, dict):
            current_app.logger.warning(
                "history/import: tweet ID が見つかりません。トップレベルキー: %s",
                list(data.keys()),
            )
        else:
            current_app.logger.warning(
                "history/import: tweet ID が見つかりません。データ型: %s, 先頭要素: %s",
                type(data).__name__,
                data[:3] if isinstance(data, list) else data,
            )
        return jsonify({"error": "no valid tweet IDs found in request body"}), 400

    added = _log_store.mark_downloaded(tweet_ids)
    return jsonify({"imported": added})


@bp_api.route("/api/history/stream")
def api_history_stream():
    """SSE: ダウンロード済み tweet ID をリアルタイムでクライアントにプッシュする。"""
    _log_store = get_log_store()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503

    def event_stream():
        ids = sorted(_log_store.get_downloaded_ids())
        yield f"event: snapshot\ndata: {json.dumps(ids)}\n\n"

        q = _log_store.subscribe()
        try:
            while True:
                try:
                    new_ids = q.get(timeout=25)
                    yield f"event: update\ndata: {json.dumps(new_ids)}\n\n"
                except _queue_module.Empty:
                    yield ": keepalive\n\n"
        finally:
            _log_store.unsubscribe(q)

    response = Response(
        stream_with_context(event_stream()),
        content_type="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
