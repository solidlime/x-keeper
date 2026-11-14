"""共通フィクスチャ。"""

import pytest

from src.log_store import LogStore


@pytest.fixture
def log_store(tmp_path):
    """一時ディレクトリを使った LogStore インスタンス。"""
    return LogStore(tmp_path)


@pytest.fixture
def web_app(tmp_path):
    """LogStore を注入した Flask アプリ (認証テスト用)。"""
    from src.web import app, set_log_store

    store = LogStore(tmp_path)
    set_log_store(store)
    app.config["TESTING"] = True
    yield app
    set_log_store(None)


@pytest.fixture
def client(web_app):
    return web_app.test_client()
