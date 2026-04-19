"""後方互換性シム。src/web/ パッケージに移行済み。"""
from .web import app, set_log_store

__all__ = ["app", "set_log_store"]
