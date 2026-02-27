"""ダウンロードログと失敗リトライキューの永続化ストア。"""

import json
import queue
import threading
from datetime import datetime
from pathlib import Path


class LogStore:
    """ダウンロード結果を JSON ファイルに記録し、リトライキューを管理する。"""

    _MAX_LOG_ENTRIES = 500

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._data_dir / "_download_log.json"
        self._retry_file = self._data_dir / "_retry_queue.json"
        self._ids_file = self._data_dir / "_downloaded_ids.json"
        # Chrome 拡張 / Android アプリから直接投入されたダウンロード URL キュー
        self._api_queue_file = self._data_dir / "_api_queue.json"
        self._lock = threading.Lock()
        # SSE 購読者: mark_downloaded 時に新規 ID を通知するキューのセット
        self._subscribers: set[queue.Queue[list[str]]] = set()

    # ── 内部ユーティリティ ────────────────────────────────────────────────────

    def _read(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write(self, path: Path, data: list) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _append_log(self, entry: dict) -> None:
        with self._lock:
            logs = self._read(self._log_file)
            logs.append(entry)
            if len(logs) > self._MAX_LOG_ENTRIES:
                logs = logs[-self._MAX_LOG_ENTRIES :]
            self._write(self._log_file, logs)

    # ── ログ書き込み ──────────────────────────────────────────────────────────

    def append_success(
        self,
        message_id: int,
        channel_id: int,
        urls: list[str],
        file_count: int,
    ) -> None:
        self._append_log({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "message_id": message_id,
            "channel_id": channel_id,
            "urls": urls,
            "file_count": file_count,
        })

    def append_failure(
        self,
        message_id: int,
        channel_id: int,
        urls: list[str],
        error: str,
    ) -> None:
        self._append_log({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "status": "failure",
            "message_id": message_id,
            "channel_id": channel_id,
            "urls": urls,
            "error": error,
        })

    # ── ログ読み出し ──────────────────────────────────────────────────────────

    def get_recent_logs(self, limit: int = 100) -> list[dict]:
        with self._lock:
            logs = self._read(self._log_file)
        return list(reversed(logs[-limit:]))

    def get_failures(self) -> list[dict]:
        """message_id ごとに最新エントリが failure のものだけ返す。"""
        with self._lock:
            logs = self._read(self._log_file)
        seen: set[int] = set()
        result = []
        for entry in reversed(logs):
            mid = entry.get("message_id")
            if mid in seen:
                continue
            seen.add(mid)
            if entry.get("status") == "failure":
                result.append(entry)
        return result

    # ── リトライキュー ────────────────────────────────────────────────────────

    def queue_retry(self, message_id: int, channel_id: int) -> None:
        with self._lock:
            queue = self._read(self._retry_file)
            if not any(
                e["message_id"] == message_id and e["channel_id"] == channel_id
                for e in queue
            ):
                queue.append({"message_id": message_id, "channel_id": channel_id})
                self._write(self._retry_file, queue)

    def pop_retry_queue(self) -> list[dict]:
        """キュー全件を取り出してクリアする。"""
        with self._lock:
            queue = self._read(self._retry_file)
            if queue:
                self._write(self._retry_file, [])
        return queue

    # ── ダウンロード済み tweet ID 管理 ─────────────────────────────────────

    def get_downloaded_ids(self) -> frozenset[str]:
        """ダウンロード済みの tweet ID セットを返す。"""
        with self._lock:
            return frozenset(self._read_id_list())

    def mark_downloaded(self, tweet_ids: list[str]) -> int:
        """tweet ID リストをダウンロード済みとして記録し、純新規追加件数を返す。

        既に登録済みの ID は無視される。新規追加された ID は SSE 購読者に通知される。
        """
        if not tweet_ids:
            return 0
        new_ids: list[str] = []
        with self._lock:
            existing = set(self._read_id_list())
            new_ids = [tid for tid in tweet_ids if tid not in existing]
            if new_ids:
                existing.update(new_ids)
                self._ids_file.write_text(
                    json.dumps(sorted(existing), ensure_ascii=False),
                    encoding="utf-8",
                )
        # ロック解放後に購読者へ通知（デッドロック防止）
        if new_ids:
            self._notify_subscribers(new_ids)
        return len(new_ids)

    # ── SSE pub/sub ───────────────────────────────────────────────────────────

    def subscribe(self) -> "queue.Queue[list[str]]":
        """新規ダウンロード ID の通知を受け取るキューを登録して返す。

        SSE エンドポイントが接続ごとに呼び出す。不要になったら必ず unsubscribe すること。
        """
        q: queue.Queue[list[str]] = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "queue.Queue[list[str]]") -> None:
        """subscribe で登録したキューを解除する。"""
        with self._lock:
            self._subscribers.discard(q)

    def _notify_subscribers(self, new_ids: list[str]) -> None:
        """全購読者に新規 ID を非ブロッキングで通知する。

        キューが満杯の購読者（応答が遅い接続）は切断済みとみなして削除する。
        """
        dead: set[queue.Queue[list[str]]] = set()
        with self._lock:
            subscribers = set(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(new_ids)
            except queue.Full:
                dead.add(q)
        if dead:
            with self._lock:
                self._subscribers -= dead

    def _read_id_list(self) -> list[str]:
        """_downloaded_ids.json の内容をリストで返す (ロックなし)。"""
        if not self._ids_file.exists():
            return []
        try:
            data = json.loads(self._ids_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ── API 直接ダウンロードキュー ─────────────────────────────────────────────
    # Chrome 拡張 / Android アプリから Discord を経由せずに
    # 直接投入された URL を管理する。

    def queue_url_download(self, url: str) -> None:
        """URL を直接ダウンロードキューに追加する。重複 URL は追加しない。"""
        with self._lock:
            queue = self._read(self._api_queue_file)
            if not any(e["url"] == url for e in queue):
                queue.append({
                    "url": url,
                    "queued_at": datetime.now().isoformat(timespec="seconds"),
                })
                self._write(self._api_queue_file, queue)

    def pop_api_queue(self) -> list[str]:
        """直接ダウンロードキューの全 URL を取り出してクリアする。"""
        with self._lock:
            queue = self._read(self._api_queue_file)
            if queue:
                self._write(self._api_queue_file, [])
        return [e["url"] for e in queue]
