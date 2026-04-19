"""管理ページルート (/logs, /queue, /failures, /stats)。"""

from flask import Blueprint, redirect, render_template_string

from ..globals import get_log_store
from ..templates import _FAILURES_HTML, _LOGS_HTML, _QUEUE_HTML, _STATS_HTML

bp_admin = Blueprint("bp_admin", __name__)


@bp_admin.route("/logs")
def logs():
    _log_store = get_log_store()
    entries = _log_store.get_recent_logs(100) if _log_store else []
    return render_template_string(_LOGS_HTML, entries=entries)


@bp_admin.route("/queue")
def queue_page():
    _log_store = get_log_store()
    queue_items = _log_store.peek_api_queue() if _log_store else []
    failure_entries = _log_store.get_failures() if _log_store else []
    return render_template_string(
        _QUEUE_HTML,
        queue_items=queue_items,
        failure_entries=failure_entries,
    )


@bp_admin.route("/failures")
def failures():
    return redirect("/queue")


@bp_admin.route("/stats")
def stats():
    return render_template_string(_STATS_HTML)
