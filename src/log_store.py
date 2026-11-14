"""ダウンロードログと失敗リトライキューの永続化ストア。"""

import json
import queue
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .notify import notify_download

# 日付ディレクトリ名 (YYYY-MM-DD) の判定用
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ストレージ集計・整合性チェック対象のメディア拡張子
_MEDIA_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp4", ".mov", ".avi", ".webm",
    ".mp3", ".ogg", ".wav",
})

# 終了済み (done/failed) ジョブの保持件数
_MAX_QUEUE_HISTORY = 100


def _utc_now() -> str:
    """SQLite の datetime('now') と同じ UTC 表記。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
                url           TEXT PRIMARY KEY,
                queued_at     TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                retry_count   INTEGER NOT NULL DEFAULT 0,
                last_error    TEXT,
                next_retry_at TEXT,
                source        TEXT NOT NULL DEFAULT 'api',
                started_at    TEXT,
                finished_at   TEXT,
                updated_at    TEXT
            );
        """)
        self._conn.commit()
        # 既存DB互換: 古いテーブルに足りないカラムを ALTER TABLE で追加
        for col, col_def in [
            ("status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_error", "TEXT"),
            ("next_retry_at", "TEXT"),
            ("source", "TEXT NOT NULL DEFAULT 'api'"),
            ("started_at", "TEXT"),
            ("finished_at", "TEXT"),
            ("updated_at", "TEXT"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE api_queue ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
        self._conn.commit()
        # 検索・絞り込み用インデックス (ALTER 後に作成する)
        self._conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_api_queue_status ON api_queue(status, queued_at);
            CREATE INDEX IF NOT EXISTS idx_download_log_status ON download_log(status, id);
            CREATE INDEX IF NOT EXISTS idx_download_log_ts ON download_log(ts);
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
        notify_download(status, urls, file_count, error)

    # ── ログ読み出し ──────────────────────────────────────────────────────────

    def get_recent_logs(
        self,
        limit: int = 100,
        status: str | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """直近ログを返す。status / q (URL・エラー部分一致) / since / until で絞り込める。"""
        where: list[str] = []
        params: list = []
        if status:
            where.append("status = ?")
            params.append(status)
        if q:
            where.append("(urls LIKE ? OR error LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if since:
            where.append("ts >= ?")
            params.append(since)
        if until:
            where.append("ts <= ?")
            params.append(until + "~")  # 日付のみ指定でも同日を含める
        sql = "SELECT ts, status, urls, file_count, error FROM download_log"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
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
                (url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
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

    # ── ダウンロード済みフラグ削除 ────────────────────────────────────────────

    def remove_downloaded_id(self, tweet_id: str) -> bool:
        """指定 tweet_id を downloaded_ids から削除する。削除できたら True。"""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM downloaded_ids WHERE tweet_id = ?", (tweet_id,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def remove_downloaded_url(self, url: str) -> bool:
        """指定 URL を downloaded_urls から削除する。削除できたら True。"""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM downloaded_urls WHERE url = ?", (url,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def find_orphaned_downloaded_ids(self) -> list[str]:
        """ファイルが実在しないダウンロード済 tweet_id を返す。

        downloaded_ids にある tweet_id のうち、データディレクトリ内の
        ファイル名に tweet_id が含まれないものを抽出する。
        """
        with self._lock:
            rows = self._conn.execute("SELECT tweet_id FROM downloaded_ids").fetchall()

        existing_ids = {tid for _, tid in self._iter_media_files() if tid}
        return [row[0] for row in rows if row[0] not in existing_ids]

    # ── ストレージ整合性チェック・再インデックス ───────────────────────────────

    def _iter_media_files(self):
        """日付フォルダ内のメディアファイルを (Path, tweet_id|None) で列挙する。"""
        from src.patterns import TWEET_ID_FROM_FILENAME

        if not self._data_dir.exists():
            return
        for day_dir in sorted(self._data_dir.iterdir()):
            if not day_dir.is_dir() or not _DATE_DIR_RE.match(day_dir.name):
                continue
            try:
                files = sorted(day_dir.iterdir())
            except OSError:
                continue
            for f in files:
                if not f.is_file() or f.suffix.lower() not in _MEDIA_EXTS:
                    continue
                m = TWEET_ID_FROM_FILENAME.search(f.name)
                yield f, (m.group(1) if m else None)

    def find_orphaned_files(self) -> list[str]:
        """ファイル名の tweet_id が未登録のメディアファイル (data からの相対パス)。"""
        known = self.get_downloaded_ids()
        return [
            f"{f.parent.name}/{f.name}"
            for f, tid in self._iter_media_files()
            if tid and tid not in known
        ]

    def reindex_from_files(self) -> dict:
        """実ファイル名から tweet_id を再登録する。"""
        found: set[str] = set()
        scanned = 0
        for _f, tid in self._iter_media_files():
            scanned += 1
            if tid:
                found.add(tid)
        added = self.mark_downloaded(sorted(found))
        return {"scanned": scanned, "found_ids": len(found), "added_ids": added}

    def check_consistency(self) -> dict:
        """DB と実ファイルの整合性サマリを返す。"""
        orphaned_ids = self.find_orphaned_downloaded_ids()
        orphaned_files = self.find_orphaned_files()
        return {
            "total_files": sum(1 for _ in self._iter_media_files()),
            "total_tracked_ids": len(self.get_downloaded_ids()),
            "orphaned_ids": len(orphaned_ids),
            "orphaned_files": len(orphaned_files),
            "in_sync": not orphaned_ids and not orphaned_files,
        }

    # ── API 直接ダウンロードキュー ─────────────────────────────────────────────
    # Chrome 拡張 / Android アプリから直接投入された URL を管理する。

    def queue_url_download(self, url: str, source: str = "api") -> None:
        """URL を直接ダウンロードキューに追加する。

        待機/実行中の重複 URL は追加しない。終了済み (done/failed) の URL は
        再投入できるよう pending に戻す。
        """
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO api_queue
                       (url, queued_at, status, retry_count, last_error, next_retry_at,
                        source, started_at, finished_at, updated_at)
                   VALUES (?, ?, 'pending', 0, NULL, NULL, ?, NULL, NULL, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       status = 'pending', retry_count = 0, last_error = NULL,
                       next_retry_at = NULL, queued_at = excluded.queued_at,
                       source = excluded.source, started_at = NULL,
                       finished_at = NULL, updated_at = excluded.updated_at
                   WHERE api_queue.status IN ('done', 'failed')""",
                (url, now, source, now),
            )
            self._conn.commit()

    def peek_api_queue(
        self,
        statuses: tuple[str, ...] = ("pending", "running", "processing"),
        q: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """直接ダウンロードキューの内容をクリアせずに返す。

        statuses で状態を絞り込める (UI は既定で待機/実行中のみ)。
        """
        placeholders = ",".join("?" for _ in statuses)
        sql = (
            "SELECT url, queued_at, status, retry_count, last_error, next_retry_at, "
            "source, started_at, finished_at, updated_at FROM api_queue "
            f"WHERE status IN ({placeholders})"
        )
        params: list = list(statuses)
        if q:
            sql += " AND url LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY queued_at"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "url": row[0], "queued_at": row[1], "status": row[2],
                "retry_count": row[3], "last_error": row[4], "next_retry_at": row[5],
                "source": row[6], "started_at": row[7], "finished_at": row[8],
                "updated_at": row[9],
            }
            for row in rows
        ]

    def remove_api_url(self, url: str) -> bool:
        """指定 URL を直接ダウンロードキューから削除する。削除できた場合は True を返す。"""
        with self._lock:
            cur = self._conn.execute("DELETE FROM api_queue WHERE url = ?", (url,))
            if cur.rowcount == 0:
                return False
            self._conn.commit()
        return True

    def clear_api_queue(self) -> int:
        """待機/実行中のジョブを全件削除する。終了済みの履歴は残す。"""
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM api_queue WHERE status IN ('pending', 'running', 'processing')"
            ).fetchone()[0]
            if count:
                self._conn.execute(
                    "DELETE FROM api_queue WHERE status IN ('pending', 'running', 'processing')"
                )
                self._conn.commit()
        return count

    def pop_api_queue(self, max_attempts: int = 3) -> list[str]:
        """処理可能な URL を 'running' に遷移させて返す。DELETE はしない。

        Args:
            max_attempts: 総試行回数（初回＋リトライ上限）。
        """
        now = _utc_now()
        with self._lock:
            rows = self._conn.execute(
                """SELECT url FROM api_queue
                   WHERE status = 'pending'
                   AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   AND retry_count < ?
                   ORDER BY queued_at""",
                (now, max_attempts),
            ).fetchall()
            urls = [row[0] for row in rows]
            for url in urls:
                self._conn.execute(
                    """UPDATE api_queue
                       SET status = 'running', started_at = ?, updated_at = ?
                       WHERE url = ? AND status = 'pending'""",
                    (now, now, url),
                )
            self._conn.commit()
        return urls

    def complete_api_url(self, url: str) -> bool:
        """ジョブを成功 (done) として記録する。"""
        now = _utc_now()
        with self._lock:
            cur = self._conn.execute(
                """UPDATE api_queue
                   SET status = 'done', finished_at = ?, updated_at = ?, last_error = NULL
                   WHERE url = ?""",
                (now, now, url),
            )
            self._prune_queue_history()
            self._conn.commit()
        return cur.rowcount > 0

    def fail_api_url(self, url: str, error: str) -> bool:
        """ジョブを恒久失敗 (failed) として記録する。"""
        now = _utc_now()
        with self._lock:
            cur = self._conn.execute(
                """UPDATE api_queue
                   SET status = 'failed', retry_count = retry_count + 1,
                       last_error = ?, finished_at = ?, updated_at = ?
                   WHERE url = ?""",
                (error, now, now, url),
            )
            self._prune_queue_history()
            self._conn.commit()
        return cur.rowcount > 0

    def requeue_api_url(self, url: str, error: str, max_attempts: int = 3) -> bool:
        """失敗 URL をリトライ待ちに戻す。上限到達なら failed にして False を返す。

        Args:
            max_attempts: 総試行回数（初回＋リトライ上限）。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT retry_count FROM api_queue WHERE url = ? AND status IN ('running', 'processing')",
                (url,)
            ).fetchone()
            if not row:
                return False
            current_count = row[0] + 1
            if current_count >= max_attempts:
                now = _utc_now()
                self._conn.execute(
                    """UPDATE api_queue
                       SET status = 'failed', retry_count = ?, last_error = ?,
                           finished_at = ?, updated_at = ?
                       WHERE url = ?""",
                    (current_count, error, now, now, url),
                )
                self._prune_queue_history()
                self._conn.commit()
                return False
            delays = [60, 300, 900]
            delay = delays[min(current_count - 1, len(delays) - 1)]
            now_dt = datetime.now(timezone.utc)
            next_at = (now_dt + timedelta(seconds=delay)).strftime('%Y-%m-%d %H:%M:%S')
            self._conn.execute(
                """UPDATE api_queue
                   SET status = 'pending', retry_count = ?, last_error = ?,
                       next_retry_at = ?, updated_at = ?
                   WHERE url = ?""",
                (current_count, error, next_at, _utc_now(), url)
            )
            self._conn.commit()
        return True

    def reset_processing_urls(self) -> int:
        """クラッシュ復旧: 実行中で止まった URL を pending に戻す。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE api_queue SET status = 'pending' WHERE status IN ('running', 'processing')"
            )
            self._conn.commit()
        return cur.rowcount

    def _prune_queue_history(self) -> None:
        """終了済みジョブを最新 _MAX_QUEUE_HISTORY 件だけ残す (要ロック)。"""
        self._conn.execute(
            """DELETE FROM api_queue
               WHERE status IN ('done', 'failed')
               AND url NOT IN (
                   SELECT url FROM api_queue
                   WHERE status IN ('done', 'failed')
                   ORDER BY finished_at DESC, rowid DESC LIMIT ?
               )""",
            (_MAX_QUEUE_HISTORY,),
        )

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

