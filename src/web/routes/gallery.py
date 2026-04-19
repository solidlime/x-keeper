"""ギャラリールート。"""

import re
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template_string, request

from ..templates import (
    _ACCORDION_FRAGMENT_HTML,
    _GALLERY_DATE_HTML,
    _GALLERY_INDEX_HTML,
    _THUMBS_FRAGMENT_HTML,
)
from ..utils import _ENV_FILE, _SAVE_PATH, _media_type

bp_gallery = Blueprint("bp_gallery", __name__)


@bp_gallery.route("/gallery")
def gallery():
    from dotenv import dotenv_values
    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    try:
        thumb_count = int(env.get("GALLERY_THUMB_COUNT", "50"))
    except ValueError:
        thumb_count = 50

    sort = request.args.get("sort", "new")
    sort_reverse = sort != "old"

    now = datetime.now()
    try:
        year = int(request.args.get("year", now.year))
        month = int(request.args.get("month", now.month))
        if not (1 <= month <= 12):
            year, month = now.year, now.month
    except (ValueError, TypeError):
        year, month = now.year, now.month

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    month_prefix = f"{year:04d}-{month:02d}"

    save_path = Path(_SAVE_PATH)
    if not save_path.exists():
        date_data = []
    else:
        date_dirs = sorted(
            [d for d in save_path.iterdir()
             if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", d.name)
             and d.name.startswith(month_prefix)],
            reverse=sort_reverse,
        )
        date_data = []
        total_preloaded = 0
        for d in date_dirs:
            files_sorted = sorted(
                (f for f in d.iterdir() if f.is_file()),
                key=lambda f: f.stat().st_mtime,
                reverse=sort_reverse,
            )
            count = len(files_sorted)
            if total_preloaded < thumb_count:
                file_data = [
                    {"name": f.name, "type": _media_type(f.name), "path": f"{d.name}/{f.name}"}
                    for f in files_sorted
                ]
                total_preloaded += count
                date_data.append({"name": d.name, "count": count, "files": file_data, "preloaded": True})
            else:
                date_data.append({"name": d.name, "count": count, "files": [], "preloaded": False})
    return render_template_string(
        _GALLERY_INDEX_HTML, dates=date_data, sort=sort,
        year=year, month=month,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        now_year=now.year, now_month=now.month,
    )


@bp_gallery.route("/gallery/<date_str>")
def gallery_date(date_str: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return redirect("/gallery")
    target = Path(_SAVE_PATH) / date_str
    if not target.exists() or not target.is_dir():
        return redirect("/gallery")
    files = [
        {"name": f.name, "type": _media_type(f.name), "path": f"{date_str}/{f.name}"}
        for f in sorted(target.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        if f.is_file()
    ]
    return render_template_string(_GALLERY_DATE_HTML, date=date_str, files=files)


@bp_gallery.route("/gallery/thumbs/<date_str>")
def gallery_thumbs(date_str: str):
    """AJAX: 日付フォルダのサムネイルグリッド HTML フラグメントを返す。"""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return "", 400
    target = Path(_SAVE_PATH) / date_str
    if not target.exists() or not target.is_dir():
        return "", 404
    sort_reverse = request.args.get("sort", "new") != "old"
    files = [
        {"name": f.name, "type": _media_type(f.name), "path": f"{date_str}/{f.name}"}
        for f in sorted(target.iterdir(), key=lambda f: f.stat().st_mtime, reverse=sort_reverse)
        if f.is_file()
    ]
    return render_template_string(_THUMBS_FRAGMENT_HTML, files=files)


@bp_gallery.route("/gallery/search")
def gallery_search():
    q = request.args.get("q", "").strip().lower()
    fragment = request.args.get("fragment", "0") == "1"
    if not q:
        if fragment:
            return "", 200
        return redirect("/gallery")
    save_path = Path(_SAVE_PATH)
    files = []
    if save_path.exists():
        for date_dir in sorted(save_path.iterdir(), reverse=True):
            if not date_dir.is_dir() or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_dir.name):
                continue
            for f in sorted(date_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True):
                if f.is_file() and q in f.name.lower():
                    files.append({
                        "name": f.name,
                        "type": _media_type(f.name),
                        "path": f"{date_dir.name}/{f.name}",
                    })
    if fragment:
        return render_template_string(_THUMBS_FRAGMENT_HTML, files=files)
    return render_template_string(_GALLERY_DATE_HTML, date=f"🔍 {q}", files=files)


@bp_gallery.route("/gallery/fragment")
def gallery_fragment():
    """AJAX: 月別アコーディオン HTML + メタデータを JSON で返す。"""
    from dotenv import dotenv_values
    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    try:
        thumb_count = int(env.get("GALLERY_THUMB_COUNT", "50"))
    except ValueError:
        thumb_count = 50

    now = datetime.now()
    try:
        year = int(request.args.get("year", now.year))
        month = int(request.args.get("month", now.month))
        if not (1 <= month <= 12):
            return jsonify({"error": "invalid month"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "invalid year/month"}), 400

    sort = request.args.get("sort", "new")
    sort_reverse = sort != "old"
    month_prefix = f"{year:04d}-{month:02d}"

    save_path = Path(_SAVE_PATH)
    date_data = []
    if save_path.exists():
        date_dirs = sorted(
            [d for d in save_path.iterdir()
             if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", d.name)
             and d.name.startswith(month_prefix)],
            reverse=sort_reverse,
        )
        total_preloaded = 0
        for d in date_dirs:
            files_sorted = sorted(
                (f for f in d.iterdir() if f.is_file()),
                key=lambda f: f.stat().st_mtime,
                reverse=sort_reverse,
            )
            count = len(files_sorted)
            if total_preloaded < thumb_count:
                file_data = [
                    {"name": f.name, "type": _media_type(f.name), "path": f"{d.name}/{f.name}"}
                    for f in files_sorted
                ]
                total_preloaded += count
                date_data.append({"name": d.name, "count": count, "files": file_data, "preloaded": True})
            else:
                date_data.append({"name": d.name, "count": count, "files": [], "preloaded": False})

    accordion_html = render_template_string(_ACCORDION_FRAGMENT_HTML, dates=date_data, sort=sort)
    return jsonify({
        "accordion_html": accordion_html,
        "count": len(date_data),
        "year": year,
        "month": month,
        "sort": sort,
    })


@bp_gallery.route("/api/gallery/calendar")
def api_gallery_calendar():
    """指定年月のファイル数を日付ごとに返す。 {"YYYY-MM-DD": count, ...}"""
    now = datetime.now()
    try:
        year = int(request.args.get("year", now.year))
        month = int(request.args.get("month", now.month))
        if not (1 <= month <= 12):
            return jsonify({"error": "invalid month"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "invalid year/month"}), 400
    month_prefix = f"{year:04d}-{month:02d}"
    save_path = Path(_SAVE_PATH)
    counts = {}
    if save_path.exists():
        for date_dir in save_path.iterdir():
            if date_dir.is_dir() and date_dir.name.startswith(month_prefix):
                count = sum(1 for f in date_dir.iterdir() if f.is_file())
                if count > 0:
                    counts[date_dir.name] = count
    return jsonify(counts)
