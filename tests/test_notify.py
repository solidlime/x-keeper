"""src/notify.py と Webhook 通知フックのテスト。"""

import src.main as main_mod
import src.notify as notify_mod


class _InlineThread:
    """start() で即座に対象を実行するスレッド代用。"""

    def __init__(self, target=None, args=(), **kwargs):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class TestGetWebhookUrl:
    def test_env_value_used(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hook.example/x")
        assert notify_mod.get_webhook_url() == "https://hook.example/x"

    def test_unset_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
        monkeypatch.setattr(notify_mod, "_ENV_FILE", tmp_path / "missing.env")
        assert notify_mod.get_webhook_url() == ""


class TestNotifyDownload:
    def test_noop_when_unset(self, monkeypatch, tmp_path):
        monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
        monkeypatch.setattr(notify_mod, "_ENV_FILE", tmp_path / "missing.env")
        started = []
        monkeypatch.setattr(notify_mod.threading, "Thread", lambda **kw: started.append(kw))
        notify_mod.notify_download("done", ["u"])
        assert started == []

    def test_posts_payload(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hook.example/x")
        monkeypatch.setattr(notify_mod.threading, "Thread", _InlineThread)
        posted = []
        monkeypatch.setattr(notify_mod, "_post", lambda url, payload: posted.append((url, payload)))

        notify_mod.notify_download("failed", ["https://x.com/u/status/1"], error="boom")

        assert posted == [
            (
                "https://hook.example/x",
                {
                    "event": "download.failed",
                    "status": "failed",
                    "urls": ["https://x.com/u/status/1"],
                    "file_count": 0,
                    "error": "boom",
                },
            )
        ]

    def test_post_failure_is_swallowed(self, monkeypatch):
        def _boom(*a, **kw):
            raise OSError("refused")

        monkeypatch.setattr(notify_mod.urllib.request, "urlopen", _boom)
        notify_mod._post("https://hook.example/x", {})  # 例外を投げない


class TestNotifyFinished:
    def test_notifies_done(self, log_store, monkeypatch):
        url = "https://x.com/u/status/1"
        log_store.queue_url_download(url)
        log_store.pop_api_queue()
        log_store.complete_api_url(url)
        calls = []
        monkeypatch.setattr(main_mod, "notify_download", lambda *a, **kw: calls.append((a, kw)))

        main_mod._notify_finished(log_store, url)

        assert calls == [(("done", [url]), {"error": None})]

    def test_skips_unknown_url(self, log_store, monkeypatch):
        calls = []
        monkeypatch.setattr(main_mod, "notify_download", lambda *a, **kw: calls.append((a, kw)))
        main_mod._notify_finished(log_store, "https://x.com/u/status/999")
        assert calls == []
