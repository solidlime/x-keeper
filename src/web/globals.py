"""LogStore グローバル管理。main.py から set_log_store() で注入される。"""

_log_store = None


def set_log_store(store) -> None:
    global _log_store
    _log_store = store


def get_log_store():
    return _log_store
