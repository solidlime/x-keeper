"""src/log_store.py のテスト。"""

import sqlite3


class TestAppendAndGetLogs:
    def test_success_log(self, log_store):
        log_store.append_success(["https://x.com/u/status/123"], 3)
        logs = log_store.get_recent_logs()
        assert len(logs) == 1
        assert logs[0]["status"] == "success"
        assert logs[0]["file_count"] == 3

    def test_failure_log(self, log_store):
        log_store.append_failure(["https://x.com/u/status/456"], "timeout")
        logs = log_store.get_recent_logs()
        assert len(logs) == 1
        assert logs[0]["status"] == "failure"
        assert logs[0]["error"] == "timeout"

    def test_get_recent_logs_limit(self, log_store):
        for i in range(10):
            log_store.append_success([f"https://x.com/u/status/{i}"], 1)
        assert len(log_store.get_recent_logs(limit=5)) == 5

    def test_max_log_entries_truncates(self, log_store):
        """500件超過時に古いエントリが切り詰められること。"""
        for i in range(510):
            log_store.append_success([f"https://x.com/u/status/{i}"], 1)
        logs = log_store.get_recent_logs(limit=1000)
        assert len(logs) <= 500


class TestGetFailures:
    def test_returns_only_failures(self, log_store):
        log_store.append_success(["https://x.com/u/status/1"], 2)
        log_store.append_failure(["https://x.com/u/status/2"], "err")
        failures = log_store.get_failures()
        assert len(failures) == 1
        assert failures[0]["status"] == "failure"

    def test_empty_when_no_failures(self, log_store):
        log_store.append_success(["https://x.com/u/status/1"], 1)
        assert log_store.get_failures() == []


class TestMarkDownloaded:
    def test_mark_new_ids(self, log_store):
        added = log_store.mark_downloaded(["111", "222"])
        assert added == 2
        assert log_store.get_downloaded_ids() == frozenset({"111", "222"})

    def test_skip_existing_ids(self, log_store):
        log_store.mark_downloaded(["111"])
        added = log_store.mark_downloaded(["111", "222"])
        assert added == 1  # 111 は重複
        assert "111" in log_store.get_downloaded_ids()
        assert "222" in log_store.get_downloaded_ids()

    def test_empty_input(self, log_store):
        assert log_store.mark_downloaded([]) == 0

    def test_persists_to_disk(self, log_store, tmp_path):
        log_store.mark_downloaded(["999"])
        ids_file = tmp_path / "_downloaded_ids.json"
        assert ids_file.exists()
        data = json.loads(ids_file.read_text())
        assert "999" in data


class TestApiQueue:
    def test_queue_and_pop(self, log_store):
        log_store.queue_url_download("https://x.com/u/status/1")
        log_store.queue_url_download("https://pixiv.net/artworks/123")
        urls = log_store.pop_api_queue()
        assert len(urls) == 2
        # pop 後はキューが空になること
        assert log_store.pop_api_queue() == []

    def test_no_duplicate_in_queue(self, log_store):
        log_store.queue_url_download("https://x.com/u/status/1")
        log_store.queue_url_download("https://x.com/u/status/1")
        urls = log_store.pop_api_queue()
        assert len(urls) == 1

    def test_peek_does_not_clear(self, log_store):
        log_store.queue_url_download("https://x.com/u/status/1")
        log_store.peek_api_queue()
        assert len(log_store.pop_api_queue()) == 1

    def test_remove_single_url(self, log_store):
        log_store.queue_url_download("https://x.com/u/status/1")
        log_store.queue_url_download("https://x.com/u/status/2")
        assert log_store.remove_api_url("https://x.com/u/status/1")
        remaining = log_store.pop_api_queue()
        assert remaining == ["https://x.com/u/status/2"]

    def test_remove_nonexistent_returns_false(self, log_store):
        assert not log_store.remove_api_url("https://x.com/u/status/999")

    def test_clear_api_queue(self, log_store):
        log_store.queue_url_download("https://x.com/u/status/1")
        log_store.queue_url_download("https://x.com/u/status/2")
        count = log_store.clear_api_queue()
        assert count == 2
        assert log_store.pop_api_queue() == []


class TestDownloadedUrls:
    def test_mark_and_get(self, log_store):
        assert log_store.mark_downloaded_url("https://pixiv.net/artworks/123")
        assert "https://pixiv.net/artworks/123" in log_store.get_downloaded_urls()

    def test_mark_duplicate_returns_false(self, log_store):
        log_store.mark_downloaded_url("https://pixiv.net/artworks/123")
        assert not log_store.mark_downloaded_url("https://pixiv.net/artworks/123")

    def test_count(self, log_store):
        log_store.mark_downloaded_url("https://pixiv.net/artworks/1")
        log_store.mark_downloaded_url("https://pixiv.net/artworks/2")
        assert log_store.count_downloaded_urls() == 2


class TestGetStorageStats:
    def test_returns_expected_keys(self, log_store):
        stats = log_store.get_storage_stats()
        for key in ("total_success", "total_failure", "total_downloaded_ids",
                    "total_downloaded_urls", "total_files", "total_size_bytes",
                    "files_per_day", "by_ext"):
            assert key in stats, f"missing key: {key}"

    def test_counts_success_and_failure(self, log_store):
        log_store.append_success(["https://x.com/u/status/1"], 2)
        log_store.append_success(["https://x.com/u/status/2"], 1)
        log_store.append_failure(["https://x.com/u/status/3"], "err")
        stats = log_store.get_storage_stats()
        assert stats["total_success"] == 2
        assert stats["total_failure"] == 1

    def test_counts_downloaded_ids(self, log_store):
        log_store.mark_downloaded(["111", "222", "333"])
        stats = log_store.get_storage_stats()
        assert stats["total_downloaded_ids"] == 3

    def test_counts_media_files(self, log_store, tmp_path):
        """日付フォルダ内のメディアファイルが集計されること。"""
        day_dir = tmp_path / "2025-01-01"
        day_dir.mkdir()
        (day_dir / "file1.jpg").write_bytes(b"x" * 1024)
        (day_dir / "file2.mp4").write_bytes(b"x" * 2048)
        (day_dir / "skip.txt").write_bytes(b"x" * 100)  # 対象外
        stats = log_store.get_storage_stats()
        assert stats["total_files"] == 2
        assert stats["total_size_bytes"] == 1024 + 2048

    def test_files_per_day_structure(self, log_store, tmp_path):
        day_dir = tmp_path / "2025-06-15"
        day_dir.mkdir()
        (day_dir / "a.png").write_bytes(b"x" * 512)
        stats = log_store.get_storage_stats()
        dates = [x["date"] for x in stats["files_per_day"]]
        assert "2025-06-15" in dates
        entry = next(x for x in stats["files_per_day"] if x["date"] == "2025-06-15")
        assert entry["count"] == 1
        assert entry["size_bytes"] == 512
