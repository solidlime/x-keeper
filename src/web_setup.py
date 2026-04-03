"""
Web サーバー。設定 UI + /gallery メディアビューア + ログ管理。

起動方法:
    python -m src.web_setup

または main.py からデーモンスレッドで自動起動される。
ブラウザで http://localhost:8989 を開いてセットアップを進めてください。
"""

import base64
import hashlib
import json
import os
import queue as _queue_module
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_from_directory, session, stream_with_context

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

_PORT = int(os.getenv("WEB_SETUP_PORT", "8989"))
_SAVE_PATH = os.getenv("SAVE_PATH", "./data")
_ENV_FILE = Path(".env")

# Pixiv OAuth (gallery-dl と同じ公式アプリ資格情報)
_PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
_PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
_PIXIV_REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"

# LogStore — main.py から set_log_store() で注入される
_log_store = None


def set_log_store(store) -> None:
    global _log_store
    _log_store = store


# ── CORS (Chrome 拡張 / Android アプリからの cross-origin リクエスト対応) ─────────

@app.after_request
def _add_cors_headers(response):
    """全レスポンスに CORS ヘッダーを付与する。"""
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
    return response


def _cors_preflight():
    """OPTIONS プリフライトリクエストに対して 204 を返す。"""
    response = app.make_response(("", 204))
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# X/Pixiv/Imgur URL を受け付けるパターン
_API_URL_PATTERN = re.compile(
    r"https?://(?:"
    r"(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/(?:status/\d+|media)"
    r"|(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+"
    r"|(?:i\.)?imgur\.com/[A-Za-z0-9/_\-.]+"
    r")"
)

# tweet_id として有効な桁数 (10〜20 桁)
_TWEET_ID_RE = re.compile(r"^\d{10,20}$")

# サムネイルキャッシュの設定
_THUMBS_DIR = "_thumbs"           # {SAVE_PATH}/_thumbs/ 以下にキャッシュを保存する
_THUMB_MAX_SIZE = (320, 320)      # サムネイルの最大辺長 (px)
_THUMB_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.webp', '.gif'})


def _extract_tweet_ids_from_import(data: dict | list) -> list[str]:
    """TwitterMediaHarvest 互換フォーマットまたは ID リストから tweet_id を抽出する。

    対応フォーマット:
      - TMH 形式: {"records": [{"tweetId": "123..."}, ...]}
      - シンプルリスト: ["123...", "456...", ...]
      - フラット辞書: {"data": [{"tweet_id": "123..."}, ...]}
    """
    ids: set[str] = set()
    if isinstance(data, list):
        # シンプルな ID 文字列リスト
        for item in data:
            if isinstance(item, str) and _TWEET_ID_RE.match(item):
                ids.add(item)
    elif isinstance(data, dict):
        # TMH 形式 / フラット辞書: v2 は "items"、v1 は "records"、独自形式は "data" キーを使う
        records = data.get("records") or data.get("items") or data.get("data") or []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            tid = rec.get("tweetId") or rec.get("tweet_id") or rec.get("id")
            if tid and _TWEET_ID_RE.match(str(tid)):
                ids.add(str(tid))
    return sorted(ids)


# ── .env ユーティリティ ────────────────────────────────────────────────────────


def upsert_env_value(key: str, value: str) -> None:
    """.env ファイルに key=value を上書き追加する。"""
    lines = (
        _ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        if _ENV_FILE.exists()
        else []
    )
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    new_line = f"{key}={value}\n"

    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            _ENV_FILE.write_text("".join(lines), encoding="utf-8")
            return

    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    lines.append(new_line)
    _ENV_FILE.write_text("".join(lines), encoding="utf-8")


# ── HTML テンプレート ──────────────────────────────────────────────────────────

_BASE_STYLE = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>x-keeper</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        rel="stylesheet"
        integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
        crossorigin="anonymous">
  <style>
    body { background: #f8f9fa; }
    .card { max-width: 680px; margin: 24px auto; border-radius: 12px; }
    .badge-set   { background-color: #198754; }
    .badge-unset { background-color: #dc3545; }
    details { border: 1px solid #dee2e6; border-radius: 6px; margin-bottom: 1rem; }
    summary { padding: .75rem 1rem; cursor: pointer; font-weight: 500; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    summary::before { content: "▶ "; font-size: .75em; }
    details[open] summary::before { content: "▼ "; }
    details .details-body { padding: .75rem 1rem; border-top: 1px solid #dee2e6; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-sm navbar-dark bg-dark mb-3">
  <div class="container-fluid px-4">
    <span class="navbar-brand fw-bold">x-keeper</span>
    <div class="navbar-nav flex-row gap-3">
      <a class="nav-link" href="/?setup=1">セットアップ</a>
      <a class="nav-link" href="/gallery">ギャラリー</a>
      <a class="nav-link" href="/logs">ログ</a>
      <a class="nav-link" href="/queue">キュー</a>
    </div>
  </div>
</nav>
"""

_INDEX_HTML = (
    _BASE_STYLE
    + """
<div class="card shadow-sm">
  <div class="card-body p-4">
    <h4 class="card-title mb-1">x-keeper セットアップ</h4>
    <p class="text-muted mb-4">各種設定を行います。</p>

    <!-- 現在の設定状態 -->
    <h6 class="fw-bold">現在の設定状態</h6>
    <ul class="list-group mb-4">
      {% for key, val in status.items() %}
      <li class="list-group-item d-flex justify-content-between align-items-center">
        <code>{{ key }}</code>
        {% if val %}
        <span class="badge badge-set rounded-pill">設定済み</span>
        {% else %}
        <span class="badge badge-unset rounded-pill">未設定</span>
        {% endif %}
      </li>
      {% endfor %}
    </ul>

    {% if error %}
    <div class="alert alert-danger py-2 small">{{ error }}</div>
    {% endif %}

    <!-- Cookie ファイル設定 -->
    <h6 class="fw-bold">
      Cookie ファイル設定
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      鍵アカウントなど認証が必要なツイートの画像も取得したい場合に設定します。<br>
      ブラウザ拡張機能 <strong>Get cookies.txt LOCALLY</strong> などで
      x.com のクッキーを書き出し、<code>data/</code> フォルダに配置してください。
    </p>

    {% if cookies_saved %}
    <div class="alert alert-success py-2 small">Cookie ファイルのパスを保存しました。</div>
    {% endif %}

    <form method="post" action="/save-cookies">
      <div class="mb-3">
        <label class="form-label fw-semibold">Cookie ファイルのパス</label>
        <input type="text" class="form-control font-monospace"
               name="cookies_file"
               placeholder="./data/x.com_cookies.txt"
               value="{{ prefill.cookies_file }}">
        <div class="form-text">空のまま保存すると設定を削除します。</div>
      </div>
      <button type="submit" class="btn btn-outline-primary">保存する</button>
    </form>

    <hr class="my-4">

    <!-- Pixiv リフレッシュトークン設定 -->
    <h6 class="fw-bold">
      Pixiv リフレッシュトークン
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      Pixiv の画像をダウンロードするために必要です。
    </p>

    {% if pixiv_saved %}
    <div class="alert alert-success py-2 small">Pixiv リフレッシュトークンを保存しました。</div>
    {% endif %}
    {% if pixiv_error %}
    <div class="alert alert-danger py-2 small">{{ pixiv_error }}</div>
    {% endif %}

    {% if pixiv_auth_url %}
    <div class="alert alert-info small mb-3">
      <strong>手順:</strong>
      <ol class="mb-2 ps-3 mt-1">
        <li>F12 → <strong>[Network]</strong> タブを開く（まだなら）</li>
        <li>別タブで Pixiv のログインページが開いています。ログインする</li>
        <li>Network タブに <code>callback?state=...</code> という行が表示されたらクリック</li>
        <li>Request URL 内の <code>code=</code> の値をコピーして下に貼り付ける</li>
      </ol>
      <span class="text-muted">コード値だけでも、URL ごとでも OK。コードはログインから <strong>30 秒</strong>で失効します。</span>
    </div>
    <div class="mb-3">
      <a href="{{ pixiv_auth_url }}" target="_blank" class="btn btn-sm btn-outline-secondary">
        ログインページをもう一度開く
      </a>
    </div>
    <form method="post" action="/pixiv-oauth/exchange">
      <div class="input-group">
        <input type="text" class="form-control font-monospace"
               name="code" required autofocus
               placeholder="code の値、または callback?state=...&code=... の URL">
        <button type="submit" class="btn btn-primary">取得して保存</button>
      </div>
    </form>
    <div class="mt-2">
      <a href="/pixiv-oauth/cancel" class="small text-muted">← キャンセル</a>
    </div>
    {% else %}
    <button type="button" class="btn btn-outline-danger mb-3"
            onclick="startPixivOAuth(this)">
      Pixiv でログインしてトークンを取得
    </button>
    <script>
    async function startPixivOAuth(btn) {
      btn.disabled = true;
      btn.textContent = '認証 URL を生成中...';
      try {
        const res = await fetch('/pixiv-oauth/start');
        const data = await res.json();
        window.open(data.auth_url, '_blank');
        window.location.href = '/';
      } catch (e) {
        btn.textContent = 'エラーが発生しました。再試行してください。';
        btn.disabled = false;
      }
    }
    </script>

    <details class="mt-2">
      <summary class="small text-muted">手動でトークンを直接入力する</summary>
      <div class="details-body">
        <form method="post" action="/save-pixiv-token">
          <div class="input-group mt-2">
            <input type="password" class="form-control font-monospace"
                   name="pixiv_token"
                   placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                   value="{{ prefill.pixiv_token }}">
            <button type="submit" class="btn btn-outline-secondary">保存する</button>
          </div>
          <div class="form-text">空のまま保存すると設定を削除します。</div>
        </form>
      </div>
    </details>
    {% endif %}

    <hr class="my-4">

    <!-- キュー設定 -->
    <h6 class="fw-bold">
      キュー設定
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      ポーリング間隔とギャラリー表示を調整します。変更はサーバーの再起動後に反映されます。
    </p>

    {% if bot_config_saved %}
    <div class="alert alert-success py-2 small">設定を保存しました。</div>
    {% endif %}

    <form method="post" action="/save-bot-config">
      <div class="mb-3">
        <label class="form-label fw-semibold">API キューポーリング間隔 (秒)</label>
        <input type="number" class="form-control" name="retry_poll_interval"
               min="5" max="300" value="{{ prefill.retry_poll_interval }}">
        <div class="form-text">
          Chrome 拡張・Android アプリから投入された URL をサーバーが処理する間隔。<br>
          推奨: <code>30</code>（デフォルト）
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold">ギャラリー初期表示サムネイル数</label>
        <input type="number" class="form-control" name="gallery_thumb_count"
               min="1" max="500" value="{{ prefill.gallery_thumb_count }}">
        <div class="form-text">
          ギャラリートップページで先読みするサムネイルの件数。<br>
          推奨: <code>50</code>（デフォルト）
        </div>
      </div>
      <button type="submit" class="btn btn-outline-primary">保存する</button>
    </form>

    <hr class="my-4">
    <h6 class="fw-bold">パッケージ更新</h6>
    <p class="small text-muted mb-3">gallery-dl を最新バージョンに更新します。</p>
    <button type="button" class="btn btn-outline-secondary" onclick="updatePackages(this)">
      gallery-dl を更新する
    </button>
    <div id="update-result" class="mt-2 small"></div>
    <script>
    async function updatePackages(btn) {
      btn.disabled = true;
      btn.textContent = '更新中...';
      document.getElementById('update-result').textContent = '';
      try {
        const res = await fetch('/api/update', {method: 'POST'});
        const data = await res.json();
        if (data.already_up_to_date) {
          document.getElementById('update-result').innerHTML = '<span class="text-success">最新バージョンです</span>';
        } else if (data.version) {
          document.getElementById('update-result').innerHTML = `<span class="text-success">gallery-dl ${data.version} に更新しました</span>`;
        } else if (!data.ok) {
          document.getElementById('update-result').innerHTML = `<span class="text-danger">エラー: ${data.error || data.output}</span>`;
        } else {
          document.getElementById('update-result').innerHTML = '<span class="text-success">更新完了</span>';
        }
      } catch (e) {
        document.getElementById('update-result').innerHTML = `<span class="text-danger">通信エラー: ${e}</span>`;
      } finally {
        btn.textContent = 'gallery-dl を更新する';
        btn.disabled = false;
      }
    }
    </script>
  </div>
</div>
</body></html>
"""
)

_GALLERY_INDEX_HTML = (
    _BASE_STYLE
    + """
{% macro thumb_item(f) %}
<div class="col media-item" data-name="{{ f.name }}">
  <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
  {% if f.type == "image" %}
  <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
       style="width:100%;aspect-ratio:1/1;object-fit:cover"
       data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
       data-path="{{ f.path }}" alt="{{ f.name }}">
  {% elif f.type == "video" %}
  <div class="position-relative media-thumb"
       data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
       data-path="{{ f.path }}"
       style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
    <video muted preload="metadata"
           style="width:100%;height:100%;object-fit:cover;pointer-events:none">
      <source src="/media/{{ f.path }}">
    </video>
    <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
      <span style="font-size:2.5rem;opacity:.8">▶</span>
    </div>
  </div>
  {% elif f.type == "audio" %}
  <div class="p-2 bg-white rounded border">
    <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
    <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
  </div>
  {% else %}
  <div class="p-2 bg-white rounded border">
    <a href="/media/{{ f.path }}" target="_blank"
       class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
  </div>
  {% endif %}
</div>
{% endmacro %}
<style>
  .media-thumb { cursor:pointer; transition: opacity .15s; }
  .media-thumb:hover { opacity:.8; }
  .col.media-item { position:relative; }
  .del-btn {
    position:absolute; top:.3rem; right:.3rem; z-index:20;
    background:rgba(220,53,69,.85); color:#fff; border:none;
    border-radius:50%; width:1.7rem; height:1.7rem;
    font-size:.85rem; cursor:pointer; opacity:0;
    transition: opacity .15s; display:flex; align-items:center; justify-content:center;
    line-height:1;
  }
  .col.media-item:hover .del-btn { opacity:1; }
  .col.media-item.deleting { opacity:0; transform:scale(.88); transition: opacity .25s, transform .25s; }
  /* アコーディオン上書き */
  #accordion-list .date-accordion { margin-bottom:0; border-radius:8px; overflow:hidden; }
  .date-accordion > summary {
    background:#f1f3f5; display:flex;
    justify-content:space-between; align-items:center;
  }
  .date-accordion .date-body { padding:.75rem; }
  /* 複数選択 */
  .media-item.selected .media-thumb { outline:3px solid #1d9bf0; outline-offset:-3px; border-radius:.375rem; }
  .media-item.sel-hover  { background:rgba(29,155,240,.06); border-radius:.375rem; }
  #select-toolbar {
    display:none; position:sticky; top:0; z-index:200;
    background:#1e3a5f; border:1px solid #1d9bf0; border-radius:8px;
    padding:8px 16px; margin-bottom:12px; gap:12px; align-items:center;
  }
  #select-toolbar.active { display:flex; }
  #select-rect {
    position:fixed; pointer-events:none; z-index:499;
    border:2px solid #1d9bf0; background:rgba(29,155,240,.12); display:none;
  }
  /* ライトボックス取得元リンク */
  #lb-source { margin-top:4px; min-height:18px; }
  /* ライトボックス */
  #lb-backdrop {
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.88);
    z-index:1050; align-items:center; justify-content:center; flex-direction:column;
  }
  #lb-backdrop.active { display:flex; }
  #lb-content { display:flex; align-items:center; justify-content:center; }
  #lb-caption { color:#ccc; font-size:.8rem; margin-top:.5rem; max-width:92vw;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #lb-close  { position:fixed; top:1rem; right:1.25rem; font-size:2rem;
               color:#fff; cursor:pointer; line-height:1; z-index:1060; }
  #lb-delete { position:fixed; top:1rem; right:3.25rem; font-size:1.5rem;
               color:#f88; cursor:pointer; line-height:1; z-index:1060; }
  #lb-prev, #lb-next {
    position:fixed; top:50%; transform:translateY(-50%);
    font-size:2.5rem; color:#fff; cursor:pointer; z-index:1060;
    padding:.25rem .75rem; user-select:none;
  }
  #lb-prev { left:.5rem; }
  #lb-next { right:.5rem; }
  #lb-hint { position:fixed; bottom:1rem; left:50%; transform:translateX(-50%);
             color:#aaa; font-size:.75rem; pointer-events:none; z-index:1060; }
  /* カレンダー */
  #cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:3px; margin-bottom:1rem; }
  .cal-head { text-align:center; font-size:.7rem; font-weight:600;
              color:#666; padding:2px 0; }
  .cal-day {
    text-align:center; font-size:.78rem; padding:4px 2px;
    border-radius:6px; cursor:default; min-height:42px;
    display:flex; flex-direction:column; align-items:center; justify-content:center; gap:1px;
  }
  .cal-day.has-media { cursor:pointer; background:#e8f4fd; }
  .cal-day.has-media:hover { background:#bde3fa; }
  .cal-day.today { font-weight:700; color:#1d9bf0; }
  .cal-badge { font-size:.65rem; background:#1d9bf0; color:#fff;
               border-radius:10px; padding:0 5px; line-height:1.5; }
  #search-results-wrap { display:none; }
  #search-results-wrap.active { display:block; }
</style>

<!-- 複数選択ツールバー (Ctrl+クリックまたはドラッグ選択時に表示) -->
<div id="select-toolbar">
  <span id="select-count" style="color:#90cdf4;font-weight:600"></span>
  <button id="btn-delete-selected" class="btn btn-sm btn-danger">まとめて削除</button>
  <button id="btn-clear-selection" class="btn btn-sm btn-outline-secondary ms-auto">選択解除</button>
</div>
<!-- ドラッグ選択矩形 -->
<div id="select-rect"></div>

<div class="container" style="max-width:1200px">
  <!-- 月ナビ + 並び替え -->
  <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
    <button id="btn-prev" class="btn btn-sm btn-outline-secondary"
            data-year="{{ prev_year }}" data-month="{{ prev_month }}">‹</button>
    <h5 class="mb-0" id="month-label">{{ year }}年{{ month }}月</h5>
    <button id="btn-next" class="btn btn-sm btn-outline-secondary"
            data-year="{{ next_year }}" data-month="{{ next_month }}">›</button>
    <button id="btn-today" class="btn btn-sm btn-outline-primary ms-1"
            data-year="{{ now_year }}" data-month="{{ now_month }}">今月</button>
    <span class="text-muted small" id="date-count">{{ dates|length }} 日分</span>
    <div class="ms-auto btn-group btn-group-sm" role="group" aria-label="並び順">
      <button id="btn-sort-new" class="btn {{ 'btn-primary' if sort == 'new' else 'btn-outline-secondary' }}"
              data-sort="new">新 → 古</button>
      <button id="btn-sort-old" class="btn {{ 'btn-primary' if sort == 'old' else 'btn-outline-secondary' }}"
              data-sort="old">古 → 新</button>
    </div>
  </div>

  <!-- カレンダーグリッド -->
  <div id="cal-grid" class="mb-3">
    <div class="cal-head">日</div><div class="cal-head">月</div>
    <div class="cal-head">火</div><div class="cal-head">水</div>
    <div class="cal-head">木</div><div class="cal-head">金</div>
    <div class="cal-head">土</div>
  </div>

  <!-- AJAX検索 -->
  <form id="search-form" class="d-flex gap-2 mb-3">
    <input id="search-q" type="text" name="q" class="form-control form-control-sm"
           placeholder="ファイル名で全日付を横断検索">
    <button type="submit" class="btn btn-sm btn-primary text-nowrap">検索</button>
    <button type="button" id="btn-search-clear" class="btn btn-sm btn-outline-secondary text-nowrap" style="display:none">✕ クリア</button>
  </form>

  <!-- 検索結果 (インプレース) -->
  <div id="search-results-wrap">
    <p class="text-muted small mb-2" id="search-label"></p>
    <div id="search-results"></div>
  </div>

  <!-- 月別アコーディオン -->
  <div id="accordion-wrap">
    {% if not dates %}
    <p class="text-muted">この月のメディアはありません。</p>
    {% else %}
    <div id="accordion-list" class="d-flex flex-column gap-2">
      {% for d in dates %}
      <details {% if d.preloaded %}open{% endif %}
               class="date-accordion" data-date="{{ d.name }}"
               data-loaded="{{ 'true' if d.preloaded else 'false' }}">
        <summary>
          <span class="fw-semibold font-monospace">{{ d.name }}</span>
          <span class="badge bg-secondary rounded-pill">{{ d.count }} ファイル</span>
        </summary>
        <div class="date-body">
          {% if d.preloaded and d.files %}
          <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
            {% for f in d.files %}{{ thumb_item(f) }}{% endfor %}
          </div>
          {% elif d.preloaded %}
          <p class="text-muted small m-0">ファイルがありません。</p>
          {% else %}
          <div class="lazy-body text-center py-3" data-date="{{ d.name }}" data-sort="{{ sort }}">
            <div class="spinner-border spinner-border-sm text-secondary" role="status">
              <span class="visually-hidden">読み込み中...</span>
            </div>
          </div>
          {% endif %}
        </div>
      </details>
      {% endfor %}
    </div>
    <div id="scroll-sentinel" style="height:1px;margin-top:40px"></div>
    {% endif %}
  </div>
</div>

<!-- ライトボックス -->
<div id="lb-backdrop">
  <span id="lb-close"  title="閉じる (Esc)">✕</span>
  <span id="lb-delete" title="削除 (Del)">🗑</span>
  <span id="lb-prev"   title="前へ (←)">‹</span>
  <span id="lb-next"   title="次へ (→)">›</span>
  <div id="lb-content"></div>
  <div id="lb-caption"></div>
  <div id="lb-source"></div>
  <div id="lb-hint">ホイール / ピンチ: ズーム　ダブルクリック: リセット　Del: 削除</div>
</div>

<script>
(function () {
  const backdrop = document.getElementById('lb-backdrop');
  const content  = document.getElementById('lb-content');
  const caption  = document.getElementById('lb-caption');
  const lbSource = document.getElementById('lb-source');
  let cur = 0;

  // ── ズーム状態 ────────────────────────────────────────────────────────────
  let scale = 1, tx = 0, ty = 0;
  let dragging = false, didDrag = false;
  let drag0 = { x: 0, y: 0, tx: 0, ty: 0 };
  let pinch0 = { dist: 0, scale: 0 };
  let closeCancelled = false;

  function mediaEl() { return content.querySelector('img, video'); }

  function applyTransform() {
    const el = mediaEl();
    if (!el) return;
    el.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    if (el.tagName === 'IMG')
      el.style.cursor = scale > 1 ? (dragging ? 'grabbing' : 'grab') : '';
  }

  function resetZoom() {
    scale = 1; tx = 0; ty = 0;
    const el = mediaEl();
    if (el) { el.style.transform = ''; el.style.cursor = ''; }
  }

  // ── サムネイル一覧 (動的取得) ──────────────────────────────────────────────
  function visibleThumbs() {
    return Array.from(document.querySelectorAll('.media-thumb'))
      .filter(el => el.closest('.media-item').style.display !== 'none');
  }

  // ── ライトボックス開閉 ────────────────────────────────────────────────────

  /** ファイル名から元投稿 URL を推定する。対応しない場合は null を返す。 */
  function sourceUrl(filename) {
    // X/Twitter ファイル名テンプレート: username-tweetid-01.ext
    const mx = (filename || '').match(/-(\\d{10,20})-\\d{2,}\\.\\w+$/);
    if (mx) return `https://x.com/i/web/status/${mx[1]}`;
    // Pixiv ファイル名 (gallery-dl デフォルト): ARTWORKID_p0.ext
    const mp = (filename || '').match(/^(\\d{5,12})(?:_p\\d+)?\\./);
    if (mp) return `https://www.pixiv.net/artworks/${mp[1]}`;
    return null;
  }

  function open(idx) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    cur = ((idx % vt.length) + vt.length) % vt.length;
    const el = vt[cur];
    caption.textContent = el.dataset.caption || '';
    const url = sourceUrl(el.dataset.caption);
    lbSource.innerHTML = url
      ? `<a href="${url}" target="_blank" rel="noopener"
             style="color:#60a5fa;font-size:.75rem;text-decoration:none">🔗 元ポストを開く</a>`
      : '';
    content.innerHTML = '';
    scale = 1; tx = 0; ty = 0;
    if (el.dataset.type === 'image') {
      const img = document.createElement('img');
      img.src = el.dataset.src;
      img.style.cssText = 'max-width:92vw;max-height:84vh;object-fit:contain;border-radius:4px;display:block;transform-origin:center';
      content.appendChild(img);
    } else {
      const v = document.createElement('video');
      v.controls = true; v.autoplay = true;
      v.style.cssText = 'max-width:92vw;max-height:84vh;border-radius:4px;display:block';
      const s = document.createElement('source');
      s.src = el.dataset.src; v.appendChild(s);
      content.appendChild(v);
    }
    backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    content.innerHTML = '';
    backdrop.classList.remove('active');
    document.body.style.overflow = '';
    scale = 1; tx = 0; ty = 0;
  }

  function move(delta) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    open(cur + delta);
  }

  // ── 削除 ──────────────────────────────────────────────────────────────────
  async function deleteOne(path) {
    const res = await fetch('/delete-media', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'path=' + encodeURIComponent(path),
    });
    return res.ok;
  }

  async function deleteFile(path, onSuccess) {
    const name = path.split('/').pop();
    if (!confirm(`「${name}」を削除しますか？\nこの操作は取り消せません。`)) return;
    try {
      if (!await deleteOne(path)) { alert('削除に失敗しました'); return; }
      onSuccess();
    } catch (e) {
      alert('削除に失敗しました: ' + e);
    }
  }

  // ── 複数選択 ──────────────────────────────────────────────────────────────
  const selectedPaths = new Set();

  function updateToolbar() {
    const toolbar   = document.getElementById('select-toolbar');
    const countEl   = document.getElementById('select-count');
    if (!toolbar || !countEl) return;
    if (selectedPaths.size > 0) {
      toolbar.classList.add('active');
      countEl.textContent = `${selectedPaths.size} 件選択中`;
    } else {
      toolbar.classList.remove('active');
    }
  }

  function toggleSelect(item) {
    const thumb = item.querySelector('.media-thumb');
    if (!thumb) return;
    if (item.classList.contains('selected')) {
      item.classList.remove('selected');
      selectedPaths.delete(thumb.dataset.path);
    } else {
      item.classList.add('selected');
      selectedPaths.add(thumb.dataset.path);
    }
    updateToolbar();
  }

  function clearSelection() {
    document.querySelectorAll('.media-item.selected').forEach(el => el.classList.remove('selected'));
    selectedPaths.clear();
    updateToolbar();
  }

  document.getElementById('btn-delete-selected')?.addEventListener('click', async () => {
    const paths = [...selectedPaths];
    if (!paths.length) return;
    if (!confirm(`${paths.length} 件をまとめて削除しますか？\nこの操作は取り消せません。`)) return;
    for (const path of paths) {
      try {
        if (!await deleteOne(path)) continue;
        const item = document.querySelector(`.media-thumb[data-path="${CSS.escape(path)}"]`)
                     ?.closest('.media-item');
        if (item) { item.classList.add('deleting'); setTimeout(() => item.remove(), 280); }
      } catch { /* ネットワークエラーはスキップ */ }
    }
    clearSelection();
  });

  document.getElementById('btn-clear-selection')?.addEventListener('click', clearSelection);

  // ── ドラッグ選択 ──────────────────────────────────────────────────────────
  const selectRectEl = document.getElementById('select-rect');
  let dragSel = { triggered: false, x0: 0, y0: 0 };

  document.addEventListener('mousedown', e => {
    if (backdrop.classList.contains('active')) return;
    if (e.ctrlKey || e.metaKey) return;
    if (e.target.closest('.del-btn, #select-toolbar, #lb-backdrop')) return;
    if (!e.target.closest('#accordion-list')) return;
    // ブラウザの画像ネイティブドラッグを抑制してカスタム矩形選択のみ動作させる
    e.preventDefault();
    dragSel = { triggered: false, x0: e.clientX, y0: e.clientY };
  });

  document.addEventListener('mousemove', e => {
    if (!dragSel.x0 && !dragSel.y0) return;
    const dx = e.clientX - dragSel.x0, dy = e.clientY - dragSel.y0;
    if (!dragSel.triggered && Math.hypot(dx, dy) > 5) {
      dragSel.triggered = true;
      selectRectEl.style.display = 'block';
    }
    if (!dragSel.triggered) return;
    const x = Math.min(e.clientX, dragSel.x0), y = Math.min(e.clientY, dragSel.y0);
    const w = Math.abs(dx), h = Math.abs(dy);
    Object.assign(selectRectEl.style, {
      left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px',
    });
    const rect = { left: x, top: y, right: x + w, bottom: y + h };
    document.querySelectorAll('.media-item').forEach(item => {
      const r = item.getBoundingClientRect();
      const inside = r.left < rect.right && r.right > rect.left
                  && r.top  < rect.bottom && r.bottom > rect.top;
      item.classList.toggle('sel-hover', inside);
    });
  });

  document.addEventListener('mouseup', e => {
    if (!dragSel.triggered) { dragSel = { triggered: false, x0: 0, y0: 0 }; return; }
    selectRectEl.style.display = 'none';
    document.querySelectorAll('.media-item.sel-hover').forEach(item => {
      item.classList.remove('sel-hover');
      toggleSelect(item);
    });
    dragSel = { triggered: false, x0: 0, y0: 0 };
  });

  // ── イベント委譲 (動的コンテンツ対応) ────────────────────────────────────
  document.addEventListener('click', e => {
    // 削除ボタンを先にチェック
    const btn = e.target.closest('.del-btn');
    if (btn) {
      e.stopPropagation();
      const item = btn.closest('.media-item');
      deleteFile(btn.dataset.path, () => {
        item.classList.add('deleting');
        setTimeout(() => item.remove(), 280);
      });
      return;
    }
    // Ctrl+クリック: 選択トグル (ライトボックスは開かない)
    if (e.ctrlKey || e.metaKey) {
      const item = e.target.closest('.media-item');
      if (item) { e.preventDefault(); toggleSelect(item); }
      return;
    }
    // ドラッグ後はクリックを無視する
    if (dragSel.triggered) return;
    // サムネイルクリック → ライトボックス
    const thumb = e.target.closest('.media-thumb');
    if (thumb) {
      const vt = visibleThumbs();
      open(vt.indexOf(thumb));
    }
  });

  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', () => move(-1));
  document.getElementById('lb-next').addEventListener('click', () => move(1));

  // ライトボックス削除
  document.getElementById('lb-delete').addEventListener('click', () => {
    const vt = visibleThumbs();
    if (!vt.length) return;
    const el = vt[cur];
    const item = el.closest('.media-item');
    deleteFile(el.dataset.path, () => {
      close();
      item.classList.add('deleting');
      setTimeout(() => item.remove(), 280);
    });
  });

  backdrop.addEventListener('click', e => {
    if (closeCancelled) { closeCancelled = false; return; }
    if (e.target === backdrop) close();
  });

  document.addEventListener('keydown', e => {
    if (!backdrop.classList.contains('active')) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft')  move(-1);
    if (e.key === 'ArrowRight') move(1);
    if (e.key === '0') resetZoom();
    if (e.key === 'Delete') document.getElementById('lb-delete').click();
  });

  // ── ホイールズーム ────────────────────────────────────────────────────────
  backdrop.addEventListener('wheel', e => {
    const el = mediaEl();
    if (!el || el.tagName === 'VIDEO') return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    scale = Math.max(1, Math.min(10, scale * factor));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── ドラッグパン ──────────────────────────────────────────────────────────
  content.addEventListener('mousedown', e => {
    if (scale <= 1 || !mediaEl()) return;
    dragging = true; didDrag = false;
    drag0 = { x: e.clientX, y: e.clientY, tx, ty };
    applyTransform();
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const dx = e.clientX - drag0.x, dy = e.clientY - drag0.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) didDrag = true;
    tx = drag0.tx + dx; ty = drag0.ty + dy;
    applyTransform();
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    if (didDrag) closeCancelled = true;
    applyTransform();
  });

  content.addEventListener('dblclick', e => {
    if (scale === 1) return;
    resetZoom(); e.stopPropagation();
  });

  // ── ピンチズーム ──────────────────────────────────────────────────────────
  backdrop.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      pinch0.dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      pinch0.scale = scale;
      e.preventDefault();
    }
  }, { passive: false });

  backdrop.addEventListener('touchmove', e => {
    if (e.touches.length !== 2) return;
    e.preventDefault();
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    scale = Math.max(1, Math.min(10, pinch0.scale * (dist / pinch0.dist)));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── アコーディオン: 手動展開時に遅延読み込み ──────────────────────────────
  async function loadDate(accordion) {
    if (accordion.dataset.loaded === 'true') return;
    accordion.dataset.loaded = 'true';
    const body = accordion.querySelector('.lazy-body');
    if (!body) return;
    const date = body.dataset.date;
    const sort = body.dataset.sort || curSort;
    try {
      const res = await fetch(`/gallery/thumbs/${date}?sort=${sort}`);
      const html = await res.text();
      body.innerHTML = html;
      body.classList.remove('lazy-body');
    } catch {
      body.textContent = '読み込みに失敗しました';
    }
  }

  function setupAccordionListeners() {
    document.querySelectorAll('.date-accordion').forEach(acc => {
      acc.addEventListener('toggle', () => {
        if (acc.open) loadDate(acc);
      });
    });
  }
  setupAccordionListeners();

  // ── 無限スクロール (IntersectionObserver) ────────────────────────────────
  let scrollObserver = null;
  function setupInfiniteScroll() {
    if (scrollObserver) scrollObserver.disconnect();
    const sentinel = document.getElementById('scroll-sentinel');
    if (!sentinel) return;
    scrollObserver = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting) return;
      const next = document.querySelector('.date-accordion[data-loaded="false"]');
      if (!next) { scrollObserver.disconnect(); return; }
      next.open = true;
      loadDate(next);
    }, { rootMargin: '200px' });
    scrollObserver.observe(sentinel);
  }
  setupInfiniteScroll();

  // ── カレンダー描画 ────────────────────────────────────────────────────────
  async function buildCalendar(year, month) {
    const grid = document.getElementById('cal-grid');
    if (!grid) return;
    // 既存の曜日ヘッダ以外を削除
    Array.from(grid.children).forEach((el, i) => { if (i >= 7) el.remove(); });
    let counts = {};
    try {
      const res = await fetch(`/api/gallery/calendar?year=${year}&month=${month}`);
      counts = await res.json();
    } catch {}
    const today = new Date();
    const firstDay = new Date(year, month - 1, 1).getDay(); // 0=日
    const daysInMonth = new Date(year, month, 0).getDate();
    // 空白セル
    for (let i = 0; i < firstDay; i++) {
      const el = document.createElement('div'); el.className = 'cal-day';
      grid.appendChild(el);
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${String(year).padStart(4,'0')}-${String(month).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
      const count = counts[dateStr];
      const el = document.createElement('div');
      el.className = 'cal-day' + (count ? ' has-media' : '');
      if (today.getFullYear() === year && today.getMonth() + 1 === month && today.getDate() === d)
        el.classList.add('today');
      el.innerHTML = `<span>${d}</span>` + (count ? `<span class="cal-badge">${count}</span>` : '');
      if (count) {
        el.title = `${dateStr}: ${count} ファイル`;
        el.addEventListener('click', () => {
          const acc = document.querySelector(`.date-accordion[data-date="${dateStr}"]`);
          if (!acc) return;
          acc.open = true;
          loadDate(acc);
          acc.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      grid.appendChild(el);
    }
  }

  // 現在の年月・ソートを JS 変数として保持
  let curYear  = {{ year }};
  let curMonth = {{ month }};
  let curSort  = '{{ sort }}';

  // 初期カレンダー描画
  buildCalendar(curYear, curMonth);

  // ── 月切り替え + ソート: AJAX で更新 ─────────────────────────────────────
  function updateSortButtons(sort) {
    document.getElementById('btn-sort-new').className =
      'btn btn-sm ' + (sort === 'new' ? 'btn-primary' : 'btn-outline-secondary');
    document.getElementById('btn-sort-old').className =
      'btn btn-sm ' + (sort === 'old' ? 'btn-primary' : 'btn-outline-secondary');
  }

  function updateNavButtons(year, month) {
    const prevM = month === 1 ? {y: year-1, m: 12} : {y: year, m: month-1};
    const nextM = month === 12 ? {y: year+1, m: 1} : {y: year, m: month+1};
    const btnPrev = document.getElementById('btn-prev');
    const btnNext = document.getElementById('btn-next');
    if (btnPrev) { btnPrev.dataset.year = prevM.y; btnPrev.dataset.month = prevM.m; }
    if (btnNext) { btnNext.dataset.year = nextM.y; btnNext.dataset.month = nextM.m; }
  }

  async function switchMonth(year, month, sort, pushState = true) {
    const accordionWrap = document.getElementById('accordion-wrap');
    if (accordionWrap) accordionWrap.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-secondary" role="status"></div></div>';
    try {
      const res = await fetch(`/gallery/fragment?year=${year}&month=${month}&sort=${sort}`);
      const data = await res.json();
      if (accordionWrap) accordionWrap.innerHTML = data.accordion_html;
      // ラベル更新
      const label = document.getElementById('month-label');
      if (label) label.textContent = `${year}年${month}月`;
      const count = document.getElementById('date-count');
      if (count) count.textContent = `${data.count} 日分`;
      // ナビボタンのdata属性更新
      updateNavButtons(year, month);
      updateSortButtons(sort);
      // カレンダー再描画
      buildCalendar(year, month);
      // アコーディオン遅延読み込みイベント再登録
      document.querySelectorAll('.date-accordion').forEach(acc => {
        acc.addEventListener('toggle', () => { if (acc.open) loadDate(acc); });
      });
      // 無限スクロール再設定
      setupInfiniteScroll();
      curYear = year; curMonth = month; curSort = sort;
      if (pushState) {
        const url = `/gallery?year=${year}&month=${month}&sort=${sort}`;
        history.pushState({ year, month, sort }, '', url);
      }
    } catch (e) {
      if (accordionWrap) accordionWrap.innerHTML = '<p class="text-danger">読み込みに失敗しました: ' + e + '</p>';
    }
  }

  // 月ナビボタン
  document.getElementById('btn-prev')?.addEventListener('click', e => {
    const btn = e.currentTarget;
    switchMonth(+btn.dataset.year, +btn.dataset.month, curSort);
  });
  document.getElementById('btn-next')?.addEventListener('click', e => {
    const btn = e.currentTarget;
    switchMonth(+btn.dataset.year, +btn.dataset.month, curSort);
  });
  document.getElementById('btn-today')?.addEventListener('click', e => {
    const btn = e.currentTarget;
    switchMonth(+btn.dataset.year, +btn.dataset.month, curSort);
  });

  // ソートボタン
  document.getElementById('btn-sort-new')?.addEventListener('click', () => switchMonth(curYear, curMonth, 'new'));
  document.getElementById('btn-sort-old')?.addEventListener('click', () => switchMonth(curYear, curMonth, 'old'));

  // ブラウザ戻る/進む
  window.addEventListener('popstate', e => {
    if (!e.state) return;
    switchMonth(e.state.year, e.state.month, e.state.sort, false);
  });

  // ── AJAX 検索 ─────────────────────────────────────────────────────────────
  const searchForm   = document.getElementById('search-form');
  const searchQ      = document.getElementById('search-q');
  const resultsWrap  = document.getElementById('search-results-wrap');
  const resultsEl    = document.getElementById('search-results');
  const searchLabel  = document.getElementById('search-label');
  const clearBtn     = document.getElementById('btn-search-clear');
  const accordionWrap = document.getElementById('accordion-wrap');

  function showResults(html, q) {
    resultsEl.innerHTML = html;
    searchLabel.textContent = `🔍 "${q}" の検索結果`;
    resultsWrap.classList.add('active');
    if (accordionWrap) accordionWrap.style.display = 'none';
    clearBtn.style.display = '';
  }

  function clearSearch() {
    resultsWrap.classList.remove('active');
    resultsEl.innerHTML = '';
    searchLabel.textContent = '';
    if (accordionWrap) accordionWrap.style.display = '';
    clearBtn.style.display = 'none';
    searchQ.value = '';
  }

  searchForm.addEventListener('submit', async e => {
    e.preventDefault();
    const q = searchQ.value.trim();
    if (!q) { clearSearch(); return; }
    try {
      const res = await fetch(`/gallery/search?q=${encodeURIComponent(q)}&fragment=1`);
      const html = await res.text();
      showResults(html, q);
    } catch (err) {
      resultsEl.textContent = '検索に失敗しました: ' + err;
      resultsWrap.classList.add('active');
    }
  });

  clearBtn.addEventListener('click', clearSearch);

})();
</script>
</body></html>
"""
)

_THUMBS_FRAGMENT_HTML = """
{% if not files %}
<p class="text-muted small m-0">ファイルがありません。</p>
{% else %}
<div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
  {% for f in files %}
  <div class="col media-item" data-name="{{ f.name }}">
    <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
    {% if f.type == "image" %}
    <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
         style="width:100%;aspect-ratio:1/1;object-fit:cover"
         data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
         data-path="{{ f.path }}" alt="{{ f.name }}">
    {% elif f.type == "video" %}
    <div class="position-relative media-thumb"
         data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
         data-path="{{ f.path }}"
         style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
      <video muted preload="metadata"
             style="width:100%;height:100%;object-fit:cover;pointer-events:none">
        <source src="/media/{{ f.path }}">
      </video>
      <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
        <span style="font-size:2.5rem;opacity:.8">▶</span>
      </div>
    </div>
    {% elif f.type == "audio" %}
    <div class="p-2 bg-white rounded border">
      <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
      <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
    </div>
    {% else %}
    <div class="p-2 bg-white rounded border">
      <a href="/media/{{ f.path }}" target="_blank"
         class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}
"""

_ACCORDION_FRAGMENT_HTML = """
{% if not dates %}
<p class="text-muted">この月のメディアはありません。</p>
{% else %}
<div id="accordion-list" class="d-flex flex-column gap-2">
  {% for d in dates %}
  <details {% if d.preloaded %}open{% endif %}
           class="date-accordion" data-date="{{ d.name }}"
           data-loaded="{{ 'true' if d.preloaded else 'false' }}">
    <summary>
      <span class="fw-semibold font-monospace">{{ d.name }}</span>
      <span class="badge bg-secondary rounded-pill">{{ d.count }} ファイル</span>
    </summary>
    <div class="date-body">
      {% if d.preloaded and d.files %}
      <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
        {% for f in d.files %}
        <div class="col media-item" data-name="{{ f.name }}">
          <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
          {% if f.type == "image" %}
          <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
               style="width:100%;aspect-ratio:1/1;object-fit:cover"
               data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
               data-path="{{ f.path }}" alt="{{ f.name }}">
          {% elif f.type == "video" %}
          <div class="position-relative media-thumb"
               data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
               data-path="{{ f.path }}"
               style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
            <video muted preload="metadata"
                   style="width:100%;height:100%;object-fit:cover;pointer-events:none">
              <source src="/media/{{ f.path }}">
            </video>
            <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
              <span style="font-size:2.5rem;opacity:.8">▶</span>
            </div>
          </div>
          {% elif f.type == "audio" %}
          <div class="p-2 bg-white rounded border">
            <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
            <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
          </div>
          {% else %}
          <div class="p-2 bg-white rounded border">
            <a href="/media/{{ f.path }}" target="_blank"
               class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
          </div>
          {% endif %}
        </div>
        {% endfor %}
      </div>
      {% elif d.preloaded %}
      <p class="text-muted small m-0">ファイルがありません。</p>
      {% else %}
      <div class="lazy-body text-center py-3" data-date="{{ d.name }}" data-sort="{{ sort }}">
        <div class="spinner-border spinner-border-sm text-secondary" role="status">
          <span class="visually-hidden">読み込み中...</span>
        </div>
      </div>
      {% endif %}
    </div>
  </details>
  {% endfor %}
</div>
<div id="scroll-sentinel" style="height:1px;margin-top:40px"></div>
{% endif %}
"""

_GALLERY_DATE_HTML = (
    _BASE_STYLE
    + """
<style>
  .media-thumb { cursor:pointer; transition: opacity .15s; }
  .media-thumb:hover { opacity:.8; }
  /* 削除ボタン */
  .col.media-item { position:relative; }
  .del-btn {
    position:absolute; top:.3rem; right:.3rem; z-index:20;
    background:rgba(220,53,69,.85); color:#fff; border:none;
    border-radius:50%; width:1.7rem; height:1.7rem;
    font-size:.85rem; cursor:pointer; opacity:0;
    transition: opacity .15s; display:flex; align-items:center; justify-content:center;
    line-height:1;
  }
  .col.media-item:hover .del-btn { opacity:1; }
  .col.media-item.deleting { opacity:0; transform:scale(.88); transition: opacity .25s, transform .25s; }
  /* 複数選択 */
  .media-item.selected .media-thumb { outline:3px solid #1d9bf0; outline-offset:-3px; border-radius:.375rem; }
  .media-item.sel-hover  { background:rgba(29,155,240,.06); border-radius:.375rem; }
  #select-toolbar {
    display:none; position:sticky; top:0; z-index:200;
    background:#1e3a5f; border:1px solid #1d9bf0; border-radius:8px;
    padding:8px 16px; margin-bottom:12px; gap:12px; align-items:center;
  }
  #select-toolbar.active { display:flex; }
  #select-rect {
    position:fixed; pointer-events:none; z-index:499;
    border:2px solid #1d9bf0; background:rgba(29,155,240,.12); display:none;
  }
  /* ライトボックス取得元リンク */
  #lb-source { margin-top:4px; min-height:18px; }
  /* ライトボックス */
  #lb-backdrop {
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.88);
    z-index:1050; align-items:center; justify-content:center; flex-direction:column;
  }
  #lb-backdrop.active { display:flex; }
  #lb-content { display:flex; align-items:center; justify-content:center; }
  #lb-caption { color:#ccc; font-size:.8rem; margin-top:.5rem; max-width:92vw;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #lb-close  { position:fixed; top:1rem; right:1.25rem; font-size:2rem;
               color:#fff; cursor:pointer; line-height:1; z-index:1060; }
  #lb-delete { position:fixed; top:1rem; right:3.25rem; font-size:1.5rem;
               color:#f88; cursor:pointer; line-height:1; z-index:1060; }
  #lb-prev, #lb-next {
    position:fixed; top:50%; transform:translateY(-50%);
    font-size:2.5rem; color:#fff; cursor:pointer; z-index:1060;
    padding:.25rem .75rem; user-select:none;
  }
  #lb-prev { left:.5rem; }
  #lb-next { right:.5rem; }
  #lb-hint { position:fixed; bottom:1rem; left:50%; transform:translateX(-50%);
             color:#aaa; font-size:.75rem; pointer-events:none; z-index:1060; }
</style>

<!-- 複数選択ツールバー -->
<div id="select-toolbar">
  <span id="select-count" style="color:#90cdf4;font-weight:600"></span>
  <button id="btn-delete-selected" class="btn btn-sm btn-danger">まとめて削除</button>
  <button id="btn-clear-selection" class="btn btn-sm btn-outline-secondary ms-auto">選択解除</button>
</div>
<!-- ドラッグ選択矩形 -->
<div id="select-rect"></div>

<div class="container" style="max-width:1200px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <a href="/gallery" class="btn btn-sm btn-outline-secondary">← 戻る</a>
    <h5 class="mb-0 font-monospace">{{ date }}</h5>
    <span class="text-muted small">{{ files|length }} ファイル</span>
    <input type="text" id="file-search" class="form-control form-control-sm ms-auto"
           style="max-width:220px" placeholder="ファイル名で絞り込み">
  </div>
  {% if not files %}
  <p class="text-muted">ファイルがありません。</p>
  {% else %}
  <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2" id="file-grid">
    {% for f in files %}
    <div class="col media-item" data-name="{{ f.name }}">
      <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
      {% if f.type == "image" %}
      <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
           style="width:100%;aspect-ratio:1/1;object-fit:cover"
           data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
           data-path="{{ f.path }}" alt="{{ f.name }}">
      {% elif f.type == "video" %}
      <div class="position-relative media-thumb"
           data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
           data-path="{{ f.path }}"
           style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
        <video muted preload="metadata"
               style="width:100%;height:100%;object-fit:cover;pointer-events:none">
          <source src="/media/{{ f.path }}">
        </video>
        <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
          <span style="font-size:2.5rem;opacity:.8">▶</span>
        </div>
      </div>
      {% elif f.type == "audio" %}
      <div class="p-2 bg-white rounded border">
        <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
        <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
      </div>
      {% else %}
      <div class="p-2 bg-white rounded border">
        <a href="/media/{{ f.path }}" target="_blank"
           class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<!-- ライトボックス -->
<div id="lb-backdrop">
  <span id="lb-close"  title="閉じる (Esc)">✕</span>
  <span id="lb-delete" title="削除 (Del)">🗑</span>
  <span id="lb-prev"   title="前へ (←)">‹</span>
  <span id="lb-next"   title="次へ (→)">›</span>
  <div id="lb-content"></div>
  <div id="lb-caption"></div>
  <div id="lb-source"></div>
  <div id="lb-hint">ホイール / ピンチ: ズーム　ダブルクリック: リセット　Del: 削除</div>
</div>

<script>
(function () {
  const thumbs   = Array.from(document.querySelectorAll('.media-thumb'));
  const backdrop = document.getElementById('lb-backdrop');
  const content  = document.getElementById('lb-content');
  const caption  = document.getElementById('lb-caption');
  const lbSource = document.getElementById('lb-source');
  let cur = 0;

  // ── ズーム状態 ────────────────────────────────────────────────────────────
  let scale = 1, tx = 0, ty = 0;
  let dragging = false, didDrag = false;
  let drag0 = { x: 0, y: 0, tx: 0, ty: 0 };
  let pinch0 = { dist: 0, scale: 0 };
  let closeCancelled = false;

  function mediaEl() { return content.querySelector('img, video'); }

  function applyTransform() {
    const el = mediaEl();
    if (!el) return;
    el.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    if (el.tagName === 'IMG')
      el.style.cursor = scale > 1 ? (dragging ? 'grabbing' : 'grab') : '';
  }

  function resetZoom() {
    scale = 1; tx = 0; ty = 0;
    const el = mediaEl();
    if (el) { el.style.transform = ''; el.style.cursor = ''; }
  }

  // ── ナビゲーション ────────────────────────────────────────────────────────
  function visibleThumbs() {
    return thumbs.filter(el => el.closest('.media-item').style.display !== 'none');
  }

  /** ファイル名から元投稿 URL を推定する。対応しない場合は null を返す。 */
  function sourceUrl(filename) {
    // X/Twitter ファイル名テンプレート: username-tweetid-01.ext
    const mx = (filename || '').match(/-(\\d{10,20})-\\d{2,}\\.\\w+$/);
    if (mx) return `https://x.com/i/web/status/${mx[1]}`;
    // Pixiv ファイル名 (gallery-dl デフォルト): ARTWORKID_p0.ext
    const mp = (filename || '').match(/^(\\d{5,12})(?:_p\\d+)?\\./);
    if (mp) return `https://www.pixiv.net/artworks/${mp[1]}`;
    return null;
  }

  function open(idx) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    cur = ((idx % vt.length) + vt.length) % vt.length;
    const el = vt[cur];
    caption.textContent = el.dataset.caption || '';
    const url = sourceUrl(el.dataset.caption);
    lbSource.innerHTML = url
      ? `<a href="${url}" target="_blank" rel="noopener"
             style="color:#60a5fa;font-size:.75rem;text-decoration:none">🔗 元ポストを開く</a>`
      : '';
    content.innerHTML = '';
    scale = 1; tx = 0; ty = 0;
    if (el.dataset.type === 'image') {
      const img = document.createElement('img');
      img.src = el.dataset.src;
      img.style.cssText = 'max-width:92vw;max-height:84vh;object-fit:contain;border-radius:4px;display:block;transform-origin:center';
      content.appendChild(img);
    } else {
      const v = document.createElement('video');
      v.controls = true; v.autoplay = true;
      v.style.cssText = 'max-width:92vw;max-height:84vh;border-radius:4px;display:block';
      const s = document.createElement('source');
      s.src = el.dataset.src; v.appendChild(s);
      content.appendChild(v);
    }
    backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    content.innerHTML = '';
    backdrop.classList.remove('active');
    document.body.style.overflow = '';
    scale = 1; tx = 0; ty = 0;
  }

  function move(delta) { open(cur + delta); }

  // ── 削除 ──────────────────────────────────────────────────────────────────
  async function deleteOne(path) {
    const res = await fetch('/delete-media', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'path=' + encodeURIComponent(path),
    });
    return res.ok;
  }

  async function deleteFile(path, onSuccess) {
    const name = path.split('/').pop();
    if (!confirm(`「${name}」を削除しますか？\nこの操作は取り消せません。`)) return;
    try {
      if (!await deleteOne(path)) { alert('削除に失敗しました'); return; }
      onSuccess();
    } catch (e) {
      alert('削除に失敗しました: ' + e);
    }
  }

  // ── 複数選択 ──────────────────────────────────────────────────────────────
  const selectedPaths = new Set();

  function updateToolbar() {
    const toolbar = document.getElementById('select-toolbar');
    const countEl = document.getElementById('select-count');
    if (!toolbar || !countEl) return;
    if (selectedPaths.size > 0) {
      toolbar.classList.add('active');
      countEl.textContent = `${selectedPaths.size} 件選択中`;
    } else {
      toolbar.classList.remove('active');
    }
  }

  function toggleSelect(item) {
    const thumb = item.querySelector('.media-thumb');
    if (!thumb) return;
    if (item.classList.contains('selected')) {
      item.classList.remove('selected');
      selectedPaths.delete(thumb.dataset.path);
    } else {
      item.classList.add('selected');
      selectedPaths.add(thumb.dataset.path);
    }
    updateToolbar();
  }

  function clearSelection() {
    document.querySelectorAll('.media-item.selected').forEach(el => el.classList.remove('selected'));
    selectedPaths.clear();
    updateToolbar();
  }

  document.getElementById('btn-delete-selected')?.addEventListener('click', async () => {
    const paths = [...selectedPaths];
    if (!paths.length) return;
    if (!confirm(`${paths.length} 件をまとめて削除しますか？\nこの操作は取り消せません。`)) return;
    for (const path of paths) {
      try {
        if (!await deleteOne(path)) continue;
        const thumb = thumbs.find(t => t.dataset.path === path);
        if (thumb) {
          const idx = thumbs.indexOf(thumb);
          if (idx !== -1) thumbs.splice(idx, 1);
          const item = thumb.closest('.media-item');
          if (item) { item.classList.add('deleting'); setTimeout(() => item.remove(), 280); }
        }
      } catch { /* ネットワークエラーはスキップ */ }
    }
    clearSelection();
  });

  document.getElementById('btn-clear-selection')?.addEventListener('click', clearSelection);

  // ── ドラッグ選択 ──────────────────────────────────────────────────────────
  const selectRectEl = document.getElementById('select-rect');
  let dragSel = { triggered: false, x0: 0, y0: 0 };

  document.addEventListener('mousedown', e => {
    if (backdrop.classList.contains('active')) return;
    if (e.ctrlKey || e.metaKey) return;
    if (e.target.closest('.del-btn, #select-toolbar, #lb-backdrop')) return;
    if (!e.target.closest('#file-grid')) return;
    // ブラウザの画像ネイティブドラッグを抑制してカスタム矩形選択のみ動作させる
    e.preventDefault();
    dragSel = { triggered: false, x0: e.clientX, y0: e.clientY };
  });

  document.addEventListener('mousemove', e => {
    if (!dragSel.x0 && !dragSel.y0) return;
    const dx = e.clientX - dragSel.x0, dy = e.clientY - dragSel.y0;
    if (!dragSel.triggered && Math.hypot(dx, dy) > 5) {
      dragSel.triggered = true;
      selectRectEl.style.display = 'block';
    }
    if (!dragSel.triggered) return;
    const x = Math.min(e.clientX, dragSel.x0), y = Math.min(e.clientY, dragSel.y0);
    const w = Math.abs(dx), h = Math.abs(dy);
    Object.assign(selectRectEl.style, {
      left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px',
    });
    const rect = { left: x, top: y, right: x + w, bottom: y + h };
    document.querySelectorAll('.media-item').forEach(item => {
      const r = item.getBoundingClientRect();
      const inside = r.left < rect.right && r.right > rect.left
                  && r.top  < rect.bottom && r.bottom > rect.top;
      item.classList.toggle('sel-hover', inside);
    });
  });

  document.addEventListener('mouseup', () => {
    if (!dragSel.triggered) { dragSel = { triggered: false, x0: 0, y0: 0 }; return; }
    selectRectEl.style.display = 'none';
    document.querySelectorAll('.media-item.sel-hover').forEach(item => {
      item.classList.remove('sel-hover');
      toggleSelect(item);
    });
    dragSel = { triggered: false, x0: 0, y0: 0 };
  });

  // サムネイル削除ボタン
  document.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const item = btn.closest('.media-item');
      const thumb = item.querySelector('.media-thumb');
      deleteFile(btn.dataset.path, () => {
        if (thumb) {
          const idx = thumbs.indexOf(thumb);
          if (idx !== -1) thumbs.splice(idx, 1);
        }
        item.classList.add('deleting');
        setTimeout(() => item.remove(), 280);
      });
    });
  });

  thumbs.forEach(el => {
    el.addEventListener('click', e => {
      // Ctrl+クリックは選択トグル
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        toggleSelect(el.closest('.media-item'));
        return;
      }
      // ドラッグ後はクリックを無視する
      if (dragSel.triggered) return;
      open(visibleThumbs().indexOf(el));
    });
  });

  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', () => move(-1));
  document.getElementById('lb-next').addEventListener('click', () => move(1));

  // ライトボックス削除ボタン
  document.getElementById('lb-delete').addEventListener('click', () => {
    const vt = visibleThumbs();
    if (!vt.length) return;
    const el = vt[cur];
    const path = el.dataset.path;
    const item = el.closest('.media-item');
    deleteFile(path, () => {
      const idx = thumbs.indexOf(el);
      if (idx !== -1) thumbs.splice(idx, 1);
      close();
      item.classList.add('deleting');
      setTimeout(() => item.remove(), 280);
    });
  });

  backdrop.addEventListener('click', e => {
    if (closeCancelled) { closeCancelled = false; return; }
    if (e.target === backdrop) close();
  });

  document.addEventListener('keydown', e => {
    if (!backdrop.classList.contains('active')) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft')  move(-1);
    if (e.key === 'ArrowRight') move(1);
    if (e.key === '0') resetZoom();
    if (e.key === 'Delete') document.getElementById('lb-delete').click();
  });

  // ── ホイールズーム ────────────────────────────────────────────────────────
  backdrop.addEventListener('wheel', e => {
    const el = mediaEl();
    if (!el || el.tagName === 'VIDEO') return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    scale = Math.max(1, Math.min(10, scale * factor));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── ドラッグパン ──────────────────────────────────────────────────────────
  content.addEventListener('mousedown', e => {
    if (scale <= 1 || !mediaEl()) return;
    dragging = true; didDrag = false;
    drag0 = { x: e.clientX, y: e.clientY, tx, ty };
    applyTransform();
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const dx = e.clientX - drag0.x, dy = e.clientY - drag0.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) didDrag = true;
    tx = drag0.tx + dx; ty = drag0.ty + dy;
    applyTransform();
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    if (didDrag) closeCancelled = true;
    applyTransform();
  });

  // ダブルクリックでズームリセット
  content.addEventListener('dblclick', e => {
    if (scale === 1) return;
    resetZoom(); e.stopPropagation();
  });

  // ── ピンチズーム ──────────────────────────────────────────────────────────
  backdrop.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      pinch0.dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      pinch0.scale = scale;
      e.preventDefault();
    }
  }, { passive: false });

  backdrop.addEventListener('touchmove', e => {
    if (e.touches.length !== 2) return;
    e.preventDefault();
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    scale = Math.max(1, Math.min(10, pinch0.scale * (dist / pinch0.dist)));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── ファイル名フィルタ ────────────────────────────────────────────────────
  const searchEl = document.getElementById('file-search');
  if (searchEl) {
    searchEl.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll('.media-item').forEach(el => {
        el.style.display = el.dataset.name.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  }
})();
</script>
</body></html>
"""
)

_LOGS_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <h5 class="mb-0">処理ログ</h5>
    <span class="text-muted small">最新 100 件</span>
  </div>
  {% if not entries %}
  <p class="text-muted">ログがまだありません。</p>
  {% else %}
  <div class="table-responsive">
    <table class="table table-sm table-hover align-middle">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">時刻</th>
          <th></th>
          <th>URL</th>
          <th class="text-end">詳細</th>
        </tr>
      </thead>
      <tbody>
        {% for e in entries %}
        <tr class="{{ 'table-success' if e.status == 'success' else 'table-danger' }} bg-opacity-50">
          <td class="text-nowrap small font-monospace">{{ e.ts }}</td>
          <td class="fs-5">{{ '✅' if e.status == 'success' else '❌' }}</td>
          <td class="small">
            {% for url in e.urls %}
            <div class="text-truncate" style="max-width:340px">
              <a href="{{ url }}" target="_blank" rel="noopener" class="text-decoration-none">{{ url }}</a>
            </div>
            {% endfor %}
          </td>
          <td class="small text-end text-nowrap">
            {% if e.status == 'success' %}
            <span class="text-success">{{ e.file_count }} ファイル</span>
            {% else %}
            <span class="text-danger" title="{{ e.error }}">{{ e.error[:60] }}{% if e.error|length > 60 %}…{% endif %}</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>
</body></html>
"""
)

_QUEUE_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">

  {# ── 処理待ちキュー ─────────────────────────────────────────── #}
  <div class="d-flex align-items-center gap-3 mb-2">
    <h5 class="mb-0">処理待ちキュー</h5>
    <span class="text-muted small">{{ queue_items|length }} 件</span>
    {% if queue_items %}
    <button id="btn-clear-all" class="btn btn-sm btn-outline-danger ms-auto">全件クリア</button>
    {% endif %}
  </div>

  {% if not queue_items %}
  <p class="text-muted mb-4">処理待ちキューは空です。</p>
  {% else %}
  <div class="table-responsive mb-4">
    <table class="table table-sm align-middle" id="queue-table">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">追加時刻</th>
          <th>URL</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for item in queue_items %}
        <tr data-url="{{ item.url }}">
          <td class="text-nowrap small font-monospace">{{ item.queued_at }}</td>
          <td class="small">
            <a href="{{ item.url }}" target="_blank" rel="noopener"
               class="text-decoration-none text-truncate d-block" style="max-width:380px">{{ item.url }}</a>
          </td>
          <td class="text-end">
            <button class="btn btn-sm btn-outline-danger btn-del-item" data-url="{{ item.url }}">削除</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {# ── 失敗リスト ─────────────────────────────────────────────── #}
  <div class="d-flex align-items-center gap-3 mb-2">
    <h5 class="mb-0">失敗リスト</h5>
    <span class="text-muted small">{{ failure_entries|length }} 件</span>
  </div>
  {% if not failure_entries %}
  <p class="text-muted">失敗した処理はありません。</p>
  {% else %}
  <div class="table-responsive">
    <table class="table table-sm align-middle">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">時刻</th>
          <th>URL</th>
          <th>エラー</th>
        </tr>
      </thead>
      <tbody>
        {% for e in failure_entries %}
        <tr>
          <td class="text-nowrap small font-monospace">{{ e.ts }}</td>
          <td class="small">
            {% for url in e.urls %}
            <div class="text-truncate" style="max-width:260px">
              <a href="{{ url }}" target="_blank" rel="noopener" class="text-decoration-none">{{ url }}</a>
            </div>
            {% endfor %}
          </td>
          <td class="small text-danger">
            <span title="{{ e.error }}">{{ e.error[:80] }}{% if e.error|length > 80 %}…{% endif %}</span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>

<script>
// ── 処理待ちキュー操作 ────────────────────────────────────────────────
document.querySelectorAll('.btn-del-item').forEach(btn => {
  btn.addEventListener('click', async () => {
    const url = btn.dataset.url;
    btn.disabled = true;
    const res = await fetch('/api/queue/item', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url}),
    });
    if (res.ok) {
      btn.closest('tr').remove();
      const tbody = document.querySelector('#queue-table tbody');
      if (tbody && !tbody.querySelector('tr')) location.reload();
    } else {
      btn.disabled = false;
      alert('削除失敗');
    }
  });
});

const btnClearAll = document.getElementById('btn-clear-all');
if (btnClearAll) {
  btnClearAll.addEventListener('click', async () => {
    if (!confirm('処理待ちキューを全件削除しますか？')) return;
    btnClearAll.disabled = true;
    await fetch('/api/queue/clear', {method: 'POST'});
    location.reload();
  });
}
</script>
</body></html>
"""
)

_FAILURES_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <h5 class="mb-0">失敗リスト</h5>
    <span class="text-muted small">{{ entries|length }} 件</span>
  </div>
  {% if not entries %}
  <p class="text-muted">失敗した処理はありません。</p>
  {% else %}
  <div class="table-responsive">
    <table class="table table-sm align-middle">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">時刻</th>
          <th>URL</th>
          <th>エラー</th>
        </tr>
      </thead>
      <tbody>
        {% for e in entries %}
        <tr>
          <td class="text-nowrap small font-monospace">{{ e.ts }}</td>
          <td class="small">
            {% for url in e.urls %}
            <div class="text-truncate" style="max-width:260px">
              <a href="{{ url }}" target="_blank" rel="noopener" class="text-decoration-none">{{ url }}</a>
            </div>
            {% endfor %}
          </td>
          <td class="small text-danger">
            <span title="{{ e.error }}">{{ e.error[:80] }}{% if e.error|length > 80 %}…{% endif %}</span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>
</body></html>
"""
)


# ── ヘルパー ──────────────────────────────────────────────────────────────────


def _media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "gif", "webp", "avif"}:
        return "image"
    if ext in {"mp4", "mov", "mkv", "avi", "webm", "m4v"}:
        return "video"
    if ext in {"mp3", "ogg", "aac", "flac", "wav", "m4a", "opus"}:
        return "audio"
    return "other"


def _current_status() -> dict[str, bool]:
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    keys = ["GALLERY_DL_COOKIES_FILE", "PIXIV_REFRESH_TOKEN"]
    return {k: bool(env.get(k)) for k in keys}


def _prefill_values() -> dict[str, str]:
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    return {
        "cookies_file": env.get("GALLERY_DL_COOKIES_FILE", ""),
        "pixiv_token": env.get("PIXIV_REFRESH_TOKEN", ""),
        "retry_poll_interval": env.get("RETRY_POLL_INTERVAL", "30"),
        "gallery_thumb_count": env.get("GALLERY_THUMB_COUNT", "50"),
    }


# ── ルート ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    # ?setup=1 または Pixiv OAuth 中以外は常にギャラリーへリダイレクトする
    has_setup = request.args.get("setup") == "1"
    has_pixiv_oauth = bool(session.get("pixiv_auth_url"))
    has_flash = any(request.args.get(k) for k in {
        "error", "cookies_saved", "pixiv_saved", "pixiv_error", "bot_config_saved"
    })
    if not has_setup and not has_pixiv_oauth and not has_flash:
        return redirect("/gallery")
    return render_template_string(
        _INDEX_HTML,
        status=_current_status(),
        prefill=_prefill_values(),
        error=request.args.get("error"),
        cookies_saved=request.args.get("cookies_saved") == "1",
        pixiv_saved=request.args.get("pixiv_saved") == "1",
        pixiv_error=request.args.get("pixiv_error"),
        pixiv_auth_url=session.get("pixiv_auth_url"),
        bot_config_saved=request.args.get("bot_config_saved") == "1",
    )


@app.route("/save-cookies", methods=["POST"])
def save_cookies():
    cookies_file = request.form.get("cookies_file", "").strip()
    upsert_env_value("GALLERY_DL_COOKIES_FILE", cookies_file)
    return redirect("/?cookies_saved=1")


@app.route("/save-bot-config", methods=["POST"])
def save_bot_config():
    retry_poll_interval = request.form.get("retry_poll_interval", "30").strip()
    gallery_thumb_count = request.form.get("gallery_thumb_count", "50").strip()
    if not retry_poll_interval.isdigit() or not gallery_thumb_count.isdigit():
        return redirect("/?setup=1&error=数値を入力してください")
    upsert_env_value("RETRY_POLL_INTERVAL", retry_poll_interval)
    upsert_env_value("GALLERY_THUMB_COUNT", gallery_thumb_count)
    return redirect("/?setup=1&bot_config_saved=1")


@app.route("/save-pixiv-token", methods=["POST"])
def save_pixiv_token():
    token = request.form.get("pixiv_token", "").strip()
    upsert_env_value("PIXIV_REFRESH_TOKEN", token)
    return redirect("/?pixiv_saved=1")


@app.route("/pixiv-oauth/start")
def pixiv_oauth_start():
    """PKCE を生成してセッションに保存し、認証 URL を JSON で返す。"""
    code_verifier = os.urandom(32).hex()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = (
        base64.b64encode(digest)[:-1]
        .decode()
        .replace("+", "-")
        .replace("/", "_")
    )
    session["pixiv_code_verifier"] = code_verifier
    auth_url = (
        "https://app-api.pixiv.net/web/v1/login"
        f"?code_challenge={code_challenge}"
        "&code_challenge_method=S256"
        "&client=pixiv-android"
    )
    session["pixiv_auth_url"] = auth_url
    return json.dumps({"auth_url": auth_url}), 200, {"Content-Type": "application/json"}


@app.route("/pixiv-oauth/cancel")
def pixiv_oauth_cancel():
    """セッションをクリアしてトップに戻る。"""
    session.pop("pixiv_code_verifier", None)
    session.pop("pixiv_auth_url", None)
    return redirect("/")


@app.route("/pixiv-oauth/exchange", methods=["POST"])
def pixiv_oauth_exchange():
    """code 値または URL からコードを抽出してリフレッシュトークンに交換する。"""
    raw = request.form.get("code", "").strip()
    code_verifier = session.get("pixiv_code_verifier")

    if not code_verifier:
        msg = urllib.parse.quote("セッションが切れました。もう一度やり直してください。")
        return redirect(f"/?pixiv_error={msg}")

    # code 値・URL・クエリ文字列のいずれからでも抽出
    code = None
    if "?" not in raw and "code=" in raw:
        raw = "?" + raw
    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)
    codes = params.get("code", [])
    if codes:
        code = codes[0]
    elif re.fullmatch(r"[A-Za-z0-9_\-]+", raw.lstrip("?")) and len(raw.lstrip("?")) > 10:
        code = raw.lstrip("?")

    if not code:
        msg = urllib.parse.quote("code が見つかりません。Network タブの callback?state=... の行から code= の値をコピーしてください。")
        return redirect(f"/?pixiv_error={msg}")

    data = urllib.parse.urlencode({
        "client_id": _PIXIV_CLIENT_ID,
        "client_secret": _PIXIV_CLIENT_SECRET,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "include_policy": "true",
        "redirect_uri": _PIXIV_REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(
        "https://oauth.secure.pixiv.net/auth/token",
        data=data,
        headers={"User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        msg = urllib.parse.quote(f"トークン取得失敗 (HTTP {e.code})")
        return redirect(f"/?pixiv_error={msg}")
    except Exception as e:
        msg = urllib.parse.quote(f"トークン取得失敗: {e}")
        return redirect(f"/?pixiv_error={msg}")

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        msg = urllib.parse.quote("refresh_token が応答に含まれていませんでした。")
        return redirect(f"/?pixiv_error={msg}")

    # 成功時のみセッションをクリア
    session.pop("pixiv_code_verifier", None)
    session.pop("pixiv_auth_url", None)

    upsert_env_value("PIXIV_REFRESH_TOKEN", refresh_token)
    return redirect("/?pixiv_saved=1")


@app.route("/gallery")
def gallery():
    from dotenv import dotenv_values
    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    try:
        thumb_count = int(env.get("GALLERY_THUMB_COUNT", "50"))
    except ValueError:
        thumb_count = 50

    # sort=new (デフォルト): 新→古 / sort=old: 古→新
    sort = request.args.get("sort", "new")
    sort_reverse = sort != "old"

    # 月フィルタ (デフォルト: 当月)
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


@app.route("/gallery/<date_str>")
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


@app.route("/gallery/thumbs/<date_str>")
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


@app.route("/thumb/<path:filepath>")
def serve_thumb(filepath: str):
    """サムネイル JPEG を返す。未生成の場合は Pillow でリサイズしてキャッシュする。

    画像以外 (動画・音声・その他) のリクエストには 415 を返す。
    サムネイルは {SAVE_PATH}/_thumbs/{date}/{name}.jpg にキャッシュされる。
    """
    try:
        target = (Path(_SAVE_PATH) / filepath).resolve()
        save_root = Path(_SAVE_PATH).resolve()
    except Exception:
        return "invalid path", 400
    if save_root not in target.parents:
        return "forbidden", 403
    if not target.is_file():
        return "not found", 404
    if target.suffix.lower() not in _THUMB_IMAGE_EXTS:
        return "not an image", 415

    # キャッシュパス: {SAVE_PATH}/_thumbs/{date}/{name}.jpg
    thumb_rel = Path(filepath).with_suffix('.jpg')
    thumb_abs = Path(_SAVE_PATH) / _THUMBS_DIR / thumb_rel

    if not thumb_abs.exists():
        try:
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            logger.error(
                "Pillow がインストールされていません。pip install Pillow でインストールしてください。"
            )
            return "Pillow not installed", 500
        try:
            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(target) as img:
                img.thumbnail(_THUMB_MAX_SIZE, Image.LANCZOS)
                # JPEG は透過非対応のため白背景に合成する
                if img.mode in ('RGBA', 'LA'):
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1])
                    img = bg
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(thumb_abs, 'JPEG', quality=80, optimize=True)
        except Exception as exc:
            logger.error("サムネイル生成失敗: path=%s, error=%s", filepath, exc)
            return "thumbnail generation failed", 500

    response = send_from_directory(
        str(Path(_SAVE_PATH) / _THUMBS_DIR),
        thumb_rel.as_posix(),
    )
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.route("/media/<path:filepath>")
def serve_media(filepath: str):
    return send_from_directory(_SAVE_PATH, filepath)


@app.route("/delete-media", methods=["POST"])
def delete_media():
    filepath = request.form.get("path", "").strip()
    # パストラバーサル対策: SAVE_PATH 配下のみ許可
    try:
        target = (Path(_SAVE_PATH) / filepath).resolve()
        save_root = Path(_SAVE_PATH).resolve()
    except Exception:
        return "invalid path", 400
    if save_root not in target.parents and target != save_root:
        return "forbidden", 403
    if not target.is_file():
        return "not found", 404
    target.unlink()
    # サムネイルキャッシュも削除する
    thumb_cache = (Path(_SAVE_PATH) / _THUMBS_DIR / filepath).with_suffix('.jpg')
    if thumb_cache.exists():
        thumb_cache.unlink()
    return "ok", 200


@app.route("/gallery/search")
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


@app.route("/api/gallery/calendar")
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


@app.route("/gallery/fragment")
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


@app.route("/logs")
def logs():
    entries = _log_store.get_recent_logs(100) if _log_store else []
    return render_template_string(_LOGS_HTML, entries=entries)


@app.route("/queue")
def queue_page():
    queue_items = _log_store.peek_api_queue() if _log_store else []
    failure_entries = _log_store.get_failures() if _log_store else []
    return render_template_string(
        _QUEUE_HTML,
        queue_items=queue_items,
        failure_entries=failure_entries,
    )


@app.route("/failures")
def failures():
    return redirect("/queue")


# ── REST API (Chrome 拡張 / Android アプリ向け) ───────────────────────────────


@app.route("/api/update", methods=["POST", "OPTIONS"])
def api_update():
    """gallery-dl を最新バージョンに更新する。"""
    if request.method == "OPTIONS":
        return _cors_preflight()
    import subprocess
    import re as _re
    try:
        result = subprocess.run(
            ["pip", "install", "--upgrade", "gallery-dl"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        match = _re.search(r"Successfully installed gallery-dl-([\d.]+)", output)
        version = match.group(1) if match else None
        already = "already up-to-date" in output.lower() or "already satisfied" in output.lower()
        return jsonify({
            "ok": result.returncode == 0,
            "version": version,
            "already_up_to_date": already,
            "output": output[-2000:],
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "タイムアウト (120秒)"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/health")
def api_health():
    """サーバー疎通確認エンドポイント。クライアントが接続可能か確認するために使う。"""
    return jsonify({"status": "ok", "version": "1.0"})


@app.route("/api/queue", methods=["POST", "OPTIONS"])
def api_queue():
    """URL を直接ダウンロードキューに追加する。

    Request body (JSON):
        {"url": "https://x.com/user/status/123..."}

    Response (202):
        {"queued": true, "url": "https://..."}

    複数 URL を一括投入する場合は {"urls": ["https://...", ...]} でも受け付ける。
    """
    if request.method == "OPTIONS":
        return _cors_preflight()

    data = request.get_json(silent=True) or {}

    # 単一 URL または複数 URL のどちらにも対応する
    raw_urls: list[str] = []
    if "urls" in data:
        raw_urls = [u.strip() for u in data["urls"] if isinstance(u, str)]
    elif "url" in data:
        raw_urls = [data["url"].strip()]

    if not raw_urls:
        return jsonify({"error": "url or urls is required"}), 400

    accepted: list[str] = []
    rejected: list[str] = []
    for url in raw_urls:
        if _API_URL_PATTERN.match(url):
            if _log_store:
                _log_store.queue_url_download(url)
            accepted.append(url)
        else:
            rejected.append(url)

    if not accepted:
        return jsonify({"error": "no supported URLs", "rejected": rejected}), 400

    return jsonify({"queued": True, "accepted": accepted, "rejected": rejected}), 202


@app.route("/api/logs/recent")
def api_logs_recent():
    """直近のダウンロード処理結果を最新 5 件返す。

    Chrome 拡張のポップアップがサーバー側の処理状態を確認するために使用する。

    Response:
        [{"ts": "...", "status": "success"|"failure", "urls": [...],
          "file_count": N, "error": "..."}, ...]
    """
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    logs = _log_store.get_recent_logs(limit=5)
    result = [
        {
            "ts": entry.get("ts"),
            "status": entry.get("status"),
            "urls": entry.get("urls", []),
            "file_count": entry.get("file_count"),
            "error": entry.get("error"),
        }
        for entry in logs
    ]
    return jsonify(result)


@app.route("/api/history/count")
def api_history_count():
    """ダウンロード済み tweet ID の件数を返す。

    Response:
        {"count": N}
    """
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    return jsonify({"count": len(_log_store.get_downloaded_ids())})


@app.route("/api/history/ids")
def api_history_ids():
    """ダウンロード済み tweet ID の全件リストを返す。

    Chrome 拡張の Service Worker がポーリングでバッジ同期に使用する。
    SSE の代わりにこのエンドポイントを使うことで HTTPS ページからの Mixed Content 問題を回避する。

    Response:
        ["id1", "id2", ...]
    """
    if not _log_store:
        return jsonify([]), 503
    return jsonify(sorted(_log_store.get_downloaded_ids()))


@app.route("/api/history/urls/count")
def api_history_urls_count():
    """ダウンロード済み URL (Pixiv / Imgur 等) の件数を返す。

    Service Worker がポーリング変化検出に使用する。

    Response:
        {"count": N}
    """
    if not _log_store:
        return jsonify({"count": 0})
    return jsonify({"count": _log_store.count_downloaded_urls()})


@app.route("/api/history/urls")
def api_history_urls():
    """ダウンロード済み URL (Pixiv / Imgur 等) の全件リストを返す。

    Chrome 拡張の Service Worker がポーリングでバッジ同期に使用する。

    Response:
        ["https://www.pixiv.net/artworks/123...", ...]
    """
    if not _log_store:
        return jsonify([])
    return jsonify(sorted(_log_store.get_downloaded_urls()))


@app.route("/api/queue/status")
def api_queue_status():
    """直接ダウンロードキュー (処理待ち URL 一覧) を返す。

    Chrome 拡張のポップアップがキューの状況を確認するために使用する。

    Response:
        [{"url": "https://...", "queued_at": "2024-..."}, ...]
    """
    if not _log_store:
        return jsonify([])
    return jsonify(_log_store.peek_api_queue())


@app.route("/api/queue/item", methods=["DELETE", "OPTIONS"])
def api_queue_item():
    """直接ダウンロードキューから指定 URL を削除する。

    Request body (JSON):
        {"url": "https://..."}

    Response (200):
        {"deleted": true}
    Response (404):
        {"error": "not found"}
    """
    if request.method == "OPTIONS":
        return _cors_preflight()
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    if _log_store.remove_api_url(url):
        return jsonify({"deleted": True})
    return jsonify({"error": "not found"}), 404


@app.route("/api/queue/clear", methods=["POST", "OPTIONS"])
def api_queue_clear():
    """直接ダウンロードキューを全件削除する。

    Response (200):
        {"deleted": N}
    """
    if request.method == "OPTIONS":
        return _cors_preflight()
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503
    count = _log_store.clear_api_queue()
    return jsonify({"deleted": count})


@app.route("/api/history/export")
def api_history_export():
    """ダウンロード済み tweet ID を TwitterMediaHarvest 互換フォーマットでエクスポートする。

    Response:
        {
          "version": 1,
          "exportedAt": "2024-01-01T00:00:00+00:00",
          "records": [{"tweetId": "123...", "downloadedAt": null}, ...]
        }
    """
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503

    ids = sorted(_log_store.get_downloaded_ids())
    records = [{"tweetId": tid, "downloadedAt": None} for tid in ids]
    payload = {
        "version": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    return jsonify(payload)


@app.route("/api/history/import", methods=["POST", "OPTIONS"])
def api_history_import():
    """TwitterMediaHarvest 互換フォーマットで tweet ID をインポートする。

    Request body (JSON):
        TMH 形式: {"records": [{"tweetId": "123..."}, ...]}
        または単純リスト: ["123...", "456...", ...]

    Response:
        {"imported": N}
    """
    if request.method == "OPTIONS":
        return _cors_preflight()

    if not _log_store:
        return jsonify({"error": "log store not available"}), 503

    data = request.get_json(silent=True)
    if data is None:
        app.logger.warning("history/import: JSON 解析失敗 (Content-Type=%s)", request.content_type)
        return jsonify({"error": "invalid JSON body"}), 400

    tweet_ids = _extract_tweet_ids_from_import(data)
    if not tweet_ids:
        # フォーマット診断のためにトップレベルキーをログに出力する
        if isinstance(data, dict):
            app.logger.warning(
                "history/import: tweet ID が見つかりません。トップレベルキー: %s",
                list(data.keys()),
            )
        else:
            app.logger.warning(
                "history/import: tweet ID が見つかりません。データ型: %s, 先頭要素: %s",
                type(data).__name__,
                data[:3] if isinstance(data, list) else data,
            )
        return jsonify({"error": "no valid tweet IDs found in request body"}), 400

    added = _log_store.mark_downloaded(tweet_ids)
    return jsonify({"imported": added})


@app.route("/api/history/stream")
def api_history_stream():
    """SSE: ダウンロード済み tweet ID をリアルタイムでクライアントにプッシュする。

    接続時に全 ID リストを `snapshot` イベントとして送信し、
    以後は新規追加分のみを `update` イベントとして送信する。
    Chrome 拡張のコンテンツスクリプトがこのエンドポイントを購読する。

    Response: text/event-stream (SSE)
        event: snapshot  → data: ["id1", "id2", ...]  (接続時: 全件)
        event: update    → data: ["id3", "id4", ...]  (新規追加時)
        : keepalive      → 25 秒ごとのコメント行 (接続維持)
    """
    if not _log_store:
        return jsonify({"error": "log store not available"}), 503

    def event_stream():
        # 接続時: 現在の全 ID リストをスナップショットとして送信
        ids = sorted(_log_store.get_downloaded_ids())
        yield f"event: snapshot\ndata: {json.dumps(ids)}\n\n"

        # 新規ダウンロードを購読してストリーム送信
        q = _log_store.subscribe()
        try:
            while True:
                try:
                    new_ids = q.get(timeout=25)
                    yield f"event: update\ndata: {json.dumps(new_ids)}\n\n"
                except _queue_module.Empty:
                    # 接続維持用コメント (SSE 仕様: コロン始まり行はコメント)
                    yield ": keepalive\n\n"
        finally:
            _log_store.unsubscribe(q)

    response = Response(
        stream_with_context(event_stream()),
        content_type="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # nginx バッファリング無効化
    return response


# ── エントリーポイント ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"Web サーバーを起動しています: http://localhost:{_PORT}")
    app.run(host="0.0.0.0", port=_PORT, debug=False)
