"""API 契約テスト (認証無効時)。"""

import pytest

QUEUE_URL = "https://x.com/u/status/1"
PIXIV_URL = "https://www.pixiv.net/artworks/123"


class TestQueueApi:
    def test_post_single_url(self, client):
        res = client.post("/api/queue", json={"url": QUEUE_URL})
        assert res.status_code == 202
        assert res.get_json() == {
            "queued": True, "accepted": [QUEUE_URL], "rejected": [],
        }

    def test_post_multiple_urls_with_rejected(self, client):
        res = client.post(
            "/api/queue",
            json={"urls": [QUEUE_URL, PIXIV_URL, "https://example.com/x"]},
        )
        assert res.status_code == 202
        body = res.get_json()
        assert body["accepted"] == [QUEUE_URL, PIXIV_URL]
        assert body["rejected"] == ["https://example.com/x"]

    def test_post_without_url_is_400(self, client):
        assert client.post("/api/queue", json={}).status_code == 400

    def test_post_unsupported_only_is_400(self, client):
        res = client.post("/api/queue", json={"url": "https://example.com/x"})
        assert res.status_code == 400
        assert res.get_json()["error"] == "no supported URLs"

    def test_status_returns_array_of_active_items(self, client):
        client.post("/api/queue", json={"url": QUEUE_URL, "source": "android"})
        res = client.get("/api/queue/status")
        assert res.status_code == 200
        items = res.get_json()
        assert isinstance(items, list)
        assert items[0]["url"] == QUEUE_URL
        assert items[0]["status"] == "pending"
        assert items[0]["source"] == "android"

    def test_status_include_finished(self, client, web_app):
        from src.web.globals import get_log_store

        client.post("/api/queue", json={"url": QUEUE_URL})
        store = get_log_store()
        store.pop_api_queue()
        store.complete_api_url(QUEUE_URL)
        assert client.get("/api/queue/status").get_json() == []
        items = client.get("/api/queue/status?include_finished=1").get_json()
        assert items[0]["status"] == "done"

    def test_status_filter_and_limit(self, client):
        client.post("/api/queue", json={"urls": [QUEUE_URL, PIXIV_URL]})
        items = client.get("/api/queue/status?q=pixiv").get_json()
        assert [i["url"] for i in items] == [PIXIV_URL]
        assert len(client.get("/api/queue/status?limit=1").get_json()) == 1

    def test_delete_item(self, client):
        client.post("/api/queue", json={"url": QUEUE_URL})
        res = client.delete("/api/queue/item", json={"url": QUEUE_URL})
        assert res.get_json() == {"deleted": True}
        assert client.delete("/api/queue/item", json={"url": QUEUE_URL}).status_code == 404
        assert client.delete("/api/queue/item", json={}).status_code == 400

    def test_clear(self, client):
        client.post("/api/queue", json={"urls": [QUEUE_URL, PIXIV_URL]})
        assert client.post("/api/queue/clear").get_json() == {"deleted": 2}


class TestLogsApi:
    def test_recent_default_limit_5(self, client, web_app):
        from src.web.globals import get_log_store

        store = get_log_store()
        for i in range(7):
            store.append_success([f"https://x.com/u/status/{i}"], 1)
        assert len(client.get("/api/logs/recent").get_json()) == 5

    def test_recent_filter_by_status(self, client, web_app):
        from src.web.globals import get_log_store

        store = get_log_store()
        store.append_success([QUEUE_URL], 1)
        store.append_failure(["https://x.com/u/status/2"], "timeout")
        logs = client.get("/api/logs/recent?status=failure").get_json()
        assert len(logs) == 1
        assert logs[0]["error"] == "timeout"


class TestStorageApi:
    def test_consistency_shape(self, client):
        body = client.get("/api/storage/consistency").get_json()
        for key in ("total_files", "total_tracked_ids", "orphaned_ids",
                    "orphaned_files", "in_sync"):
            assert key in body
        assert body["in_sync"] is True

    def test_orphans_lists(self, client, web_app, tmp_path):
        from src.web.globals import get_log_store

        store = get_log_store()
        store.mark_downloaded(["1234567890123456789"])
        day = tmp_path / "2025-01-01"
        day.mkdir()
        (day / "alice-1234567890123456789-01.jpg").write_bytes(b"x")
        (day / "alice-9999999999999999999-01.jpg").write_bytes(b"x")
        body = client.get("/api/storage/orphans").get_json()
        assert body["counts"]["orphaned_files"] == 1
        assert body["orphaned_files"] == ["2025-01-01/alice-9999999999999999999-01.jpg"]
        assert body["counts"]["orphaned_ids"] == 0

    def test_reindex_registers_ids_from_filenames(self, client, web_app, tmp_path):
        from src.web.globals import get_log_store

        day = tmp_path / "2025-01-01"
        day.mkdir()
        (day / "alice-1234567890123456789-01.jpg").write_bytes(b"x")
        body = client.post("/api/storage/reindex").get_json()
        assert body == {"scanned": 1, "found_ids": 1, "added_ids": 1}
        assert "1234567890123456789" in get_log_store().get_downloaded_ids()


class TestHistoryApi:
    def test_urls_filter(self, client, web_app):
        from src.web.globals import get_log_store

        store = get_log_store()
        store.mark_downloaded_url(PIXIV_URL)
        store.mark_downloaded_url("https://imgur.com/abc")
        assert client.get("/api/history/urls?q=pixiv").get_json() == [PIXIV_URL]

    def test_ids_unchanged_shape(self, client, web_app):
        from src.web.globals import get_log_store

        get_log_store().mark_downloaded(["1234567890123456789"])
        assert client.get("/api/history/ids").get_json() == ["1234567890123456789"]


class TestGallerySearchApi:
    def test_search_by_name_type_and_date(self, client, monkeypatch, tmp_path):
        import src.web.routes.gallery as gallery_mod

        day = tmp_path / "2025-01-02"
        day.mkdir()
        (day / "alice-1234567890123456789-01.jpg").write_bytes(b"x")
        (day / "bob-1234567890123456789-01.mp4").write_bytes(b"x")
        monkeypatch.setattr(gallery_mod, "_SAVE_PATH", str(tmp_path))

        body = client.get("/api/gallery/search?q=alice").get_json()
        assert body["count"] == 1
        assert body["files"][0]["type"] == "image"

        body = client.get("/api/gallery/search?media_type=video").get_json()
        assert [f["name"] for f in body["files"]] == [
            "bob-1234567890123456789-01.mp4"
        ]

        body = client.get("/api/gallery/search?date=2025-01-02&limit=1").get_json()
        assert body["count"] == 1
        assert body["truncated"] is True

        assert client.get(
            "/api/gallery/search?date=2999-01-01"
        ).get_json()["count"] == 0


@pytest.mark.parametrize("path", ["/api/storage/consistency", "/api/storage/orphans"])
def test_storage_without_store_returns_500(client, monkeypatch, path):
    from src.web import globals as g

    monkeypatch.setattr(g, "_log_store", None)
    assert client.get(path).status_code == 500
