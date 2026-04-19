"""ダウンロードログと失敗リトライキューの永続化ストア。"""

import json
import queue
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class LogStore:
    """ダウンロード結果を SQLite に記録し、リトライキューを管理する。"""

    _MAX_LOG_ENTRIES = 500

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "xkeeper.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._migrate_from_json()
        # SSE 購読者: mark_downloaded 時に新規 ID を通知するキューのセット
        self._subscribers: set[queue.Queue[list[str]]] = set()

    # ── 初期化・マイグレーション ──────────────────────────────────────────────

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS download_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                urls        TEXT    NOT NULL,
                file_count  INTEGER NOT NULL DEFAULT 0,
                error       TEXT
            );
            CREATE TABLE IF NOT EXISTS downloaded_ids (
                tweet_id    TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS downloaded_urls (
                url         TEXT PRIMARY KEY,
                added_at    TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS api_queue (
                url         TEXT PRIMARY KEY,
                queued_at   TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def _migrate_from_json(self) -> None:
        """既存 JSON ファイルを SQLite にマイグレーションし、.json.bak にリネームする。"""
        def _load(path: Path):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None

        log_file = self._data_dir / "_download_log.json"
        if log_file.exists():
            data = _load(log_file)
            if isinstance(data, list):
                for entry in data:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO download_log (ts, status, urls, file_count, error) VALUES (?,?,?,?,?)",
                        (
                            entry.get("ts", ""),
                            entry.get("status", ""),
                            json.dumps(entry.get("urls", []), ensure_ascii=False),
                            entry.get("file_count", 0),
                            entry.get("error"),
                        ),
                    )
                self._conn.commit()
            log_file.rename(log_file.with_suffix(".json.bak"))

        ids_file = self._data_dir / "_downloaded_ids.json"
        if ids_file.exists():
            data = _load(ids_file)
            if isinstance(data, list):
                self._conn.executemany(
                    "INSERT OR IGNORE INTO downloaded_ids (tweet_id) VALUES (?)",
                    [(tid,) for tid in data if isinstance(tid, str)],
                )
                self._conn.commit()
            ids_file.rename(ids_file.with_suffix(".json.bak"))

        urls_file = self._data_dir / "_downloaded_urls.json"
        if urls_file.exists():
            data = _load(urls_file)
            if isinstance(data, list):
                now = datetime.now().isoformat(timespec="seconds")
                self._conn.executemany(
                    "INSERT OR IGNORE INTO downloaded_urls (url, added_at) VALUES (?,?)",
                    [(u, now) for u in data if isinstance(u, str)],
                )
                self._conn.commit()
            urls_file.rename(urls_file.with_suffix(".json.bak"))

        api_file = self._data_dir / "_api_queue.json"
        if api_file.exists():
            data = _load(api_file)
            if isinstance(data, list):
                self._conn.executemany(
                    "INSERT OR IGNORE INTO api_queue (url, queued_at) VALUES (?,?)",
                    [
                        (e["url"], e.get("queued_at", ""))
                        for e in data
                        if isinstance(e, dict) and "url" in e
                    ],
                )
                self._conn.commit()
            api_file.rename(api_file.with_suffix(".json.bak"))

    # ── ログ書き込み ──────────────────────────────────────────────────────────

    def append_success(self, urls: list[str], file_count: int) -> None:
        """ダウンロード成功を記録する。"""
        self._append_log(
            ts=datetime.now().isoformat(timespec="seconds"),
            status="success",
            urls=urls,
            file_count=file_count,
            error=None,
        )

    def append_failure(self, urls: list[str], error: str) -> None:
        """ダウンロード失敗を記録する。"""
        self._append_log(
            ts=datetime.now().isoformat(timespec="seconds"),
            status="failure",
            urls=urls,
            file_count=0,
            error=error,
        )

    def _append_log(self, ts: str, status: str, urls: list[str], file_count: int, error: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO download_log (ts, status, urls, file_count, error) VALUES (?,?,?,?,?)",
                (ts, status, json.dumps(urls, ensure_ascii=False), file_count, error),
            )
            # 上限超過分を古い順に削除
            self._conn.execute(
                """DELETE FROM download_log WHERE id IN (
                    SELECT id FROM download_log ORDER BY id ASC
                    LIMIT MAX(0, (SELECT COUNT(*) FROM download_log) - ?)
                )""",
                (self._MAX_LOG_ENTRIES,),
            )
            self._conn.commit()

    # ── ログ読み出し ──────────────────────────────────────────────────────────

    def get_recent_logs(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, status, urls, file_count, error FROM download_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            entry: dict = {
                "ts": row["ts"],
                "status": row["status"],
                "urls": json.loads(row["urls"]),
                "file_count": row["file_count"],
            }
            if row["error"] is not None:
                entry["error"] = row["error"]
            result.append(entry)
        return result

    def get_failures(self) -> list[dict]:
        """URL ごとに最新エントリが failure のものだけ返す。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, status, urls, file_count, error FROM download_log ORDER BY id DESC"
            ).fetchall()
        seen: set[str] = set()
        result = []
        for row in rows:
            urls_list: list[str] = json.loads(row["urls"])
            # タイムスタンプ + 最初の URL でユニーク化する
            key = f"{row['ts']}|{urls_list[0] if urls_list else ''}"
            if key in seen:
                continue
            seen.add(key)
            if row["status"] == "failure":
                result.append({
                    "ts": row["ts"],
                    "status": row["status"],
                    "urls": urls_list,
                    "file_count": row["file_count"],
                    "error": row["error"],
                })
        return result

    # ── ダウンロード済み tweet ID 管理 ─────────────────────────────────────

    def get_downloaded_ids(self) -> frozenset[str]:
        """ダウンロード済みの tweet ID セットを返す。"""
        with self._lock:
            rows = self._conn.execute("SELECT tweet_id FROM downloaded_ids").fetchall()
        return frozenset(row[0] for row in rows)

    def mark_downloaded(self, tweet_ids: list[str]) -> int:
        """tweet ID リストをダウンロード済みとして記録し、純新規追加件数を返す。

        既に登録済みの ID は無視される。新規追加された ID は SSE 購読者に通知される。
        """
        if not tweet_ids:
            return 0
        new_ids: list[str] = []
        with self._lock:
            for tid in tweet_ids:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO downloaded_ids (tweet_id) VALUES (?)", (tid,)
                )
                if cur.rowcount > 0:
                    new_ids.append(tid)
            if new_ids:
                self._conn.commit()
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

    # ── Pixiv / Imgur ダウンロード済み URL 管理 ──────────────────────────────────
    # tweet_id を持たない URL (Pixiv 作品・Imgur 等) のダウンロード済み追跡。

    def mark_downloaded_url(self, url: str) -> bool:
        """URL をダウンロード済みとして記録する。既登録の場合は False を返す。"""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO downloaded_urls (url, added_at) VALUES (?,?)",
                (url, datetime.now().isoformat(timespec="seconds")),
            )
            if cur.rowcount == 0:
                return False
            self._conn.commit()
        return True

    def get_downloaded_urls(self) -> frozenset[str]:
        """ダウンロード済みの URL セットを返す。"""
        with self._lock:
            rows = self._conn.execute("SELECT url FROM downloaded_urls").fetchall()
        return frozenset(row[0] for row in rows)

    def count_downloaded_urls(self) -> int:
        """ダウンロード済み URL の件数を返す。"""
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM downloaded_urls").fetchone()[0]

    # ── API 直接ダウンロードキュー ─────────────────────────────────────────────
    # Chrome 拡張 / Android アプリから直接投入された URL を管理する。

    def queue_url_download(self, url: str) -> None:
        """URL を直接ダウンロードキューに追加する。重複 URL は追加しない。"""
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO api_queue (url, queued_at) VALUES (?,?)",
                (url, datetime.now().isoformat(timespec="seconds")),
            )
            self._conn.commit()

    def peek_api_queue(self) -> list[dict]:
        """直接ダウンロードキューの内容をクリアせずに返す。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT url, queued_at FROM api_queue ORDER BY queued_at"
            ).fetchall()
        return [{"url": row[0], "queued_at": row[1]} for row in rows]

    def remove_api_url(self, url: str) -> bool:
        """指定 URL を直接ダウンロードキューから削除する。削除できた場合は True を返す。"""
        with self._lock:
            cur = self._conn.execute("DELETE FROM api_queue WHERE url = ?", (url,))
            if cur.rowcount == 0:
                return False
            self._conn.commit()
        return True

    def clear_api_queue(self) -> int:
        """直接ダウンロードキューを全件削除する。削除件数を返す。"""
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM api_queue").fetchone()[0]
            if count:
                self._conn.execute("DELETE FROM api_queue")
                self._conn.commit()
        return count

    def pop_api_queue(self) -> list[str]:
        """直接ダウンロードキューの全 URL を取り出してクリアする。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT url FROM api_queue ORDER BY queued_at"
            ).fetchall()
            urls = [row[0] for row in rows]
            if urls:
                self._conn.execute("DELETE FROM api_queue")
                self._conn.commit()
        return urls

    # ── ストレージ統計 ─────────────────────────────────────────────────────────

    def get_storage_stats(self) -> dict:
        """ストレージ統計情報を収集して返す。

        Returns:
            以下のキーを持つ辞書:
            - total_success (int): 成功ダウンロード件数
            - total_failure (int): 失敗ダウンロード件数
            - total_downloaded_ids (int): 重複防止リストの tweet ID 総数
            - total_downloaded_urls (int): 重複防止リストの URL 総数
            - total_files (int): data ディレクトリ内のメディアファイル総数
            - total_size_bytes (int): メディアファイルの合計サイズ (バイト)
            - files_per_day (list[dict]): 日付別ファイル数・サイズ [{date, count, size_bytes}]
            - by_ext (dict[str, int]): 拡張子別ファイル数
        """
        import os

        # ログ集計
        with self._lock:
            row = self._conn.execute(
                "SELECT "
                "  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS s, "
                "  SUM(CASE WHEN status='failure' THEN 1 ELSE 0 END) AS f "
                "FROM download_log"
            ).fetchone()
        total_success = row[0] or 0
        total_failure = row[1] or 0

        # tweet ID / URL カウント
        total_ids = len(self.get_downloaded_ids())
        total_urls = self.count_downloaded_urls()

        # data ディレクトリ内のメディアファイルを日付フォルダ別に集計
        _MEDIA_EXTS = frozenset({
            ".jpg", ".jpeg", ".png", ".gif", ".webp",
            ".mp4", ".mov", ".avi", ".webm",
            ".mp3", ".ogg", ".wav",
        })
        files_per_day: list[dict] = []
        by_ext: dict[str, int] = {}
        total_files = 0
        total_size = 0

        try:
            entries = sorted(os.scandir(self._data_dir), key=lambda e: e.name)
        except OSError:
            entries = []

        for entry in entries:
            # 日付フォルダ (YYYY-MM-DD) のみ対象
            if not entry.is_dir():
                continue
            name = entry.name
            if len(name) != 10 or name[4] != "-" or name[7] != "-":
                continue
            day_count = 0
            day_size = 0
            try:
                for f in os.scandir(entry.path):
                    if not f.is_file():
                        continue
                    ext = os.path.splitext(f.name)[1].lower()
                    if ext not in _MEDIA_EXTS:
                        continue
                    fsize = f.stat().st_size
                    day_count += 1
                    day_size += fsize
                    by_ext[ext] = by_ext.get(ext, 0) + 1
            except OSError:
                pass
            if day_count:
                files_per_day.append({
                    "date": name,
                    "count": day_count,
                    "size_bytes": day_size,
                })
            total_files += day_count
            total_size += day_size

        return {
            "total_success": total_success,
            "total_failure": total_failure,
            "total_downloaded_ids": total_ids,
            "total_downloaded_urls": total_urls,
            "total_files": total_files,
            "total_size_bytes": total_size,
            "files_per_day": files_per_day,
            "by_ext": by_ext,
        }

