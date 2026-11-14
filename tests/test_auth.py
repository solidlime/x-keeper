"""API トークン認証 (src/web/auth.py) のテスト。"""

import pytest

from src.web.auth import session_secret


@pytest.fixture
def client_no_token(client, monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("src.web.auth._ENV_FILE", _Nowhere())
    return client


@pytest.fixture
def client_token(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-token")
    return client


class _Nowhere:
    """存在しない .env パス (実環境の .env を読ませない)。"""

    def exists(self) -> bool:
        return False


class TestAuthDisabled:
    def test_api_open_when_token_unset(self, client_no_token):
        res = client_no_token.get("/api/history/count")
        assert res.status_code == 200
        assert res.get_json() == {"count": 0}


class TestAuthEnabled:
    def test_missing_token_returns_401_json(self, client_token):
        res = client_token.get("/api/history/count")
        assert res.status_code == 401
        assert res.get_json() == {"error": "unauthorized"}

    def test_x_api_token_header(self, client_token):
        res = client_token.get(
            "/api/history/count", headers={"X-API-Token": "secret-token"}
        )
        assert res.status_code == 200

    def test_bearer_header(self, client_token):
        res = client_token.get(
            "/api/history/count",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert res.status_code == 200

    def test_wrong_token_returns_401(self, client_token):
        res = client_token.get(
            "/api/history/count", headers={"X-API-Token": "wrong"}
        )
        assert res.status_code == 401

    def test_health_is_public(self, client_token):
        res = client_token.get("/api/health")
        assert res.status_code == 200
        assert res.get_json()["status"] == "ok"

    def test_options_preflight_is_public(self, client_token):
        res = client_token.options("/api/queue")
        assert res.status_code == 204
        assert "X-API-Token" in res.headers["Access-Control-Allow-Headers"]
        assert "Authorization" in res.headers["Access-Control-Allow-Headers"]

    def test_stream_requires_auth(self, client_token):
        res = client_token.get("/api/history/stream")
        assert res.status_code == 401

    def test_session_authenticates_browser(self, client_token):
        with client_token.session_transaction() as sess:
            sess["api_token"] = "secret-token"
        res = client_token.get("/api/history/count")
        assert res.status_code == 200

    def test_session_with_stale_token_denied(self, client_token):
        with client_token.session_transaction() as sess:
            sess["api_token"] = "old-token"
        res = client_token.get("/api/history/count")
        assert res.status_code == 401


class TestSaveApiTokenRoute:
    def test_generate_persists_and_sets_session(self, client, monkeypatch):
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )
        monkeypatch.setattr("src.web.routes.setup.generate_api_token", lambda: "new-token")

        res = client.post("/save-api-token", data={"action": "generate"})

        assert res.status_code == 302
        assert saved == [("API_TOKEN", "new-token")]
        with client.session_transaction() as sess:
            assert sess["api_token"] == "new-token"

    def test_explicit_token_saved(self, client, monkeypatch):
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )

        client.post("/save-api-token", data={"token": "hand-made"})

        assert saved == [("API_TOKEN", "hand-made")]

    def test_saved_token_sets_stable_secret_key(self, client, web_app, monkeypatch):
        """再起動してもブラウザ認証が切れないよう、セッション鍵はトークン由来にする。"""
        monkeypatch.setattr("src.web.routes.setup.upsert_env_value", lambda k, v: None)
        monkeypatch.setattr("src.web.routes.setup.generate_api_token", lambda: "stable")

        client.post("/save-api-token", data={"action": "generate"})

        assert web_app.secret_key == session_secret("stable")

    def test_empty_save_does_not_generate_token(self, client, monkeypatch):
        """「保存する」で空なら無効化ではなくエラー (誤操作でトークンが変わるのを防ぐ)。"""
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )

        res = client.post("/save-api-token", data={"token": "", "action": "save"})

        assert saved == []
        assert "error=" in res.headers["Location"]

    def test_disable_clears_token_and_session(self, client, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret-token")
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )
        with client.session_transaction() as sess:
            sess["api_token"] = "secret-token"

        client.post("/save-api-token", data={"action": "disable"})

        assert saved == [("API_TOKEN", "")]
        with client.session_transaction() as sess:
            assert "api_token" not in sess

    def test_existing_token_cannot_be_replaced_unauthenticated(self, client, monkeypatch):
        """トークン設定済みなら、未認証の POST でトークンを書き換えられない。"""
        monkeypatch.setenv("API_TOKEN", "secret-token")
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )

        res = client.post("/save-api-token", data={"token": "takeover"})

        assert saved == []
        assert "error=" in res.headers["Location"]

    def test_same_token_acts_as_login(self, client, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret-token")
        monkeypatch.setattr("src.web.routes.setup.upsert_env_value", lambda k, v: None)

        client.post("/save-api-token", data={"token": "secret-token"})

        with client.session_transaction() as sess:
            assert sess["api_token"] == "secret-token"


class TestSessionSecret:
    def test_secret_is_derived_from_token(self):
        assert session_secret("abc") == session_secret("abc")
        assert session_secret("abc") != session_secret("xyz")
        assert len(session_secret("")) == 64


class TestManagementRoutes:
    def test_delete_media_requires_token(self, client_token):
        res = client_token.post("/delete-media", data={"path": "2025-01-01/a.jpg"})
        assert res.status_code == 401

    def test_delete_media_with_token_reaches_handler(self, client_token):
        res = client_token.post(
            "/delete-media",
            data={"path": "nope/a.jpg"},
            headers={"X-API-Token": "secret-token"},
        )
        assert res.status_code != 401

    def test_save_cookies_requires_token(self, client_token, monkeypatch):
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )

        res = client_token.post("/save-cookies", data={"cookies_file": "/tmp/x"})

        assert saved == []
        assert "error=" in res.headers["Location"]

    def test_save_cookies_with_token_saves(self, client_token, monkeypatch):
        saved = []
        monkeypatch.setattr(
            "src.web.routes.setup.upsert_env_value",
            lambda key, value: saved.append((key, value)),
        )

        client_token.post(
            "/save-cookies",
            data={"cookies_file": "/tmp/x"},
            headers={"X-API-Token": "secret-token"},
        )

        assert saved == [("GALLERY_DL_COOKIES_FILE", "/tmp/x")]

    def test_gallery_api_requires_token(self, client_token):
        assert client_token.get("/api/gallery/search").status_code == 401
        assert client_token.get("/api/gallery/calendar").status_code == 401

    def test_gallery_api_with_token(self, client_token):
        res = client_token.get(
            "/api/gallery/calendar", headers={"X-API-Token": "secret-token"}
        )
        assert res.status_code == 200
