"""API トークン認証 (src/web/auth.py) のテスト。"""

import pytest


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
