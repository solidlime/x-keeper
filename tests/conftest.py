"""共通フィクスチャ。"""

import pytest

from src.log_store import LogStore


@pytest.fixture
def log_store(tmp_path):
    """一時ディレクトリを使った LogStore インスタンス。"""
    return LogStore(tmp_path)
