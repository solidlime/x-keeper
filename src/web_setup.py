"""
Web サーバー。Discord セットアップ UI + /gallery メディアビューア + ログ/失敗管理。

起動方法:
    python -m src.web_setup

または main.py からデーモンスレッドで自動起動される。
ブラウザで http://localhost:8989 を開いてセットアップを進めてください。
"""

import base64
import hashlib
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, send_from_directory, session

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
      <a class="nav-link" href="/">セットアップ</a>
      <a class="nav-link" href="/gallery">ギャラリー</a>
      <a class="nav-link" href="/logs">ログ</a>
      <a class="nav-link" href="/failures">失敗</a>
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
    <p class="text-muted mb-4">Discord Bot の設定を行います。</p>

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

    <!-- Discord Bot セットアップ手順 -->
    <h6 class="fw-bold">Bot Token / Channel ID の取得方法</h6>
    <details class="mb-4">
      <summary>Discord Developer Portal での設定手順を見る</summary>
      <div class="details-body small">
        <p class="fw-semibold mb-1">Bot Token の取得</p>
        <ol class="mb-3 ps-3">
          <li class="mb-1">
            <a href="https://discord.com/developers/applications" target="_blank" rel="noopener">
              Discord Developer Portal
            </a> を開き「New Application」でアプリを作成する
          </li>
          <li class="mb-1">「Bot」タブ → 「Reset Token」でトークンを取得してコピー</li>
          <li class="mb-1">同じ画面の「Privileged Gateway Intents」で
            <strong>「Message Content Intent」を ON</strong> にして保存</li>
          <li class="mb-1">「OAuth2」タブ → 「URL Generator」→ スコープ <code>bot</code> を選択<br>
            Bot Permissions: <code>Read Messages/View Channels</code>・<code>Add Reactions</code>・<code>Read Message History</code><br>
            生成された URL でサーバーに招待する</li>
        </ol>
        <p class="fw-semibold mb-1">Channel ID の取得</p>
        <ol class="mb-0 ps-3">
          <li class="mb-1">Discord アプリの「設定」→「詳細設定」→「開発者モード」を ON にする</li>
          <li class="mb-1">監視したいチャンネルを右クリック →「チャンネル ID をコピー」</li>
        </ol>
      </div>
    </details>

    <!-- 設定フォーム -->
    <h6 class="fw-bold">設定を入力</h6>
    {% if saved %}
    <div class="alert alert-success py-2 small">設定を保存しました。</div>
    {% endif %}
    {% if error %}
    <div class="alert alert-danger py-2 small">{{ error }}</div>
    {% endif %}

    <form method="post" action="/save-discord">
      <div class="mb-3">
        <label class="form-label fw-semibold">Bot Token <span class="text-danger">*</span></label>
        <input type="password" class="form-control font-monospace"
               name="bot_token" required
               placeholder="MTxxxxxxxxxxxxxxxxxxxxxxxx.Gxxxxx.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx">
      </div>
      <div class="mb-4">
        <label class="form-label fw-semibold">Channel ID <span class="text-danger">*</span></label>
        <input type="text" class="form-control font-monospace"
               name="channel_id" required
               placeholder="1234567890123456789"
               value="{{ prefill.channel_id }}">
        <div class="form-text">
          数字のみ。複数チャンネルを監視する場合はカンマ区切りで入力。<br>
          例: <code>111222333444555666,777888999000111222</code>
        </div>
      </div>
      <button type="submit" class="btn btn-primary w-100">保存する</button>
    </form>

    <hr class="my-4">

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

    <!-- Bot 動作設定 -->
    <h6 class="fw-bold">
      Bot 動作設定
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      再試行・定期スキャンのタイミングを調整します。変更は Bot の再起動後に反映されます。
    </p>

    {% if bot_config_saved %}
    <div class="alert alert-success py-2 small">Bot 動作設定を保存しました。</div>
    {% endif %}

    <form method="post" action="/save-bot-config">
      <div class="mb-3">
        <label class="form-label fw-semibold">リトライキュー処理間隔 (秒)</label>
        <input type="number" class="form-control" name="retry_poll_interval"
               min="5" max="300" value="{{ prefill.retry_poll_interval }}">
        <div class="form-text">
          Web UI の「リトライ」ボタンを押してから Bot が処理を開始するまでの最大待機時間。<br>
          推奨: <code>30</code>（デフォルト）
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold">未処理メッセージの定期スキャン間隔</label>
        <select class="form-select" name="scan_interval">
          <option value="0"    {% if prefill.scan_interval == "0"     %}selected{% endif %}>起動時のみ（デフォルト）</option>
          <option value="3600" {% if prefill.scan_interval == "3600"  %}selected{% endif %}>1 時間ごと</option>
          <option value="10800"{% if prefill.scan_interval == "10800" %}selected{% endif %}>3 時間ごと</option>
          <option value="21600"{% if prefill.scan_interval == "21600" %}selected{% endif %}>6 時間ごと</option>
          <option value="86400"{% if prefill.scan_interval == "86400" %}selected{% endif %}>24 時間ごと</option>
        </select>
        <div class="form-text">
          ✅ 未付与のメッセージを自動で再ダウンロードする頻度。<br>
          「起動時のみ」は安全ですが、長期稼働時に取りこぼしが残ることがあります。
        </div>
      </div>
      <button type="submit" class="btn btn-outline-primary">保存する</button>
    </form>
  </div>
</div>
</body></html>
"""
)

_GALLERY_INDEX_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:900px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <h5 class="mb-0">ダウンロード済みメディア</h5>
    <span class="text-muted small">{{ dirs|length }} 日分</span>
  </div>
  <form method="get" action="/gallery/search" class="d-flex gap-2 mb-2">
    <input type="text" name="q" class="form-control form-control-sm"
           placeholder="ファイル名で全日付を横断検索">
    <button type="submit" class="btn btn-sm btn-primary text-nowrap">検索</button>
  </form>
  <input type="text" id="date-search" class="form-control form-control-sm mb-3"
         placeholder="日付で絞り込み　例: 2026-02">
  {% if not dirs %}
  <p class="text-muted">まだメディアがありません。</p>
  {% else %}
  <div class="list-group">
    {% for d in dirs %}
    <a href="/gallery/{{ d.name }}"
       class="list-group-item list-group-item-action d-flex justify-content-between align-items-center date-item"
       data-date="{{ d.name }}">
      <span class="fw-semibold font-monospace">{{ d.name }}</span>
      <span class="badge bg-secondary rounded-pill">{{ d.count }} ファイル</span>
    </a>
    {% endfor %}
  </div>
  {% endif %}
</div>
<script>
document.getElementById('date-search').addEventListener('input', function() {
  const q = this.value.toLowerCase();
  document.querySelectorAll('.date-item').forEach(el => {
    el.style.display = el.dataset.date.includes(q) ? '' : 'none';
  });
});
</script>
</body></html>
"""
)

_GALLERY_DATE_HTML = (
    _BASE_STYLE
    + """
<style>
  .media-thumb { cursor:pointer; transition: opacity .15s; }
  .media-thumb:hover { opacity:.8; }
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
      {% if f.type == "image" %}
      <img src="/media/{{ f.path }}" class="rounded media-thumb"
           style="width:100%;aspect-ratio:1/1;object-fit:cover"
           data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
           alt="{{ f.name }}">
      {% elif f.type == "video" %}
      <div class="position-relative media-thumb"
           data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
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
  <span id="lb-close" title="閉じる (Esc)">✕</span>
  <span id="lb-prev" title="前へ (←)">‹</span>
  <span id="lb-next" title="次へ (→)">›</span>
  <div id="lb-content"></div>
  <div id="lb-caption"></div>
  <div id="lb-hint">ホイール / ピンチ: ズーム　ダブルクリック: リセット</div>
</div>

<script>
(function () {
  const thumbs  = Array.from(document.querySelectorAll('.media-thumb'));
  const backdrop = document.getElementById('lb-backdrop');
  const content  = document.getElementById('lb-content');
  const caption  = document.getElementById('lb-caption');
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

  function open(idx) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    cur = ((idx % vt.length) + vt.length) % vt.length;
    const el = vt[cur];
    caption.textContent = el.dataset.caption || '';
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

  thumbs.forEach(el => {
    el.addEventListener('click', () => open(visibleThumbs().indexOf(el)));
  });

  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', () => move(-1));
  document.getElementById('lb-next').addEventListener('click', () => move(1));

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

_FAILURES_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <h5 class="mb-0">失敗リスト</h5>
    <span class="text-muted small">{{ entries|length }} 件</span>
  </div>
  {% if queued %}
  <div class="alert alert-success py-2 small">
    リトライをキューに追加しました。Bot が数秒以内に処理します。
  </div>
  {% endif %}
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
          <th></th>
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
          <td>
            <form method="post" action="/retry/{{ e.message_id }}/{{ e.channel_id }}">
              <button type="submit" class="btn btn-sm btn-outline-primary text-nowrap">リトライ</button>
            </form>
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
    keys = ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", "GALLERY_DL_COOKIES_FILE", "PIXIV_REFRESH_TOKEN"]
    return {k: bool(env.get(k)) for k in keys}


def _prefill_values() -> dict[str, str]:
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    return {
        "channel_id": env.get("DISCORD_CHANNEL_ID", ""),
        "cookies_file": env.get("GALLERY_DL_COOKIES_FILE", ""),
        "pixiv_token": env.get("PIXIV_REFRESH_TOKEN", ""),
        "retry_poll_interval": env.get("RETRY_POLL_INTERVAL", "30"),
        "scan_interval": env.get("SCAN_INTERVAL", "0"),
    }


# ── ルート ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template_string(
        _INDEX_HTML,
        status=_current_status(),
        prefill=_prefill_values(),
        saved=request.args.get("saved") == "1",
        error=request.args.get("error"),
        cookies_saved=request.args.get("cookies_saved") == "1",
        pixiv_saved=request.args.get("pixiv_saved") == "1",
        pixiv_error=request.args.get("pixiv_error"),
        pixiv_auth_url=session.get("pixiv_auth_url"),
        bot_config_saved=request.args.get("bot_config_saved") == "1",
    )


@app.route("/save-discord", methods=["POST"])
def save_discord():
    bot_token = request.form.get("bot_token", "").strip()
    channel_id = request.form.get("channel_id", "").strip()

    if not bot_token or not channel_id:
        return redirect("/?error=Bot+Token+と+Channel+ID+は必須です")

    ids = [x.strip() for x in channel_id.split(",") if x.strip()]
    if not ids or not all(x.isdigit() for x in ids):
        return redirect("/?error=Channel+ID+は数字のみで入力してください（複数の場合はカンマ区切り）")

    upsert_env_value("DISCORD_BOT_TOKEN", bot_token)
    upsert_env_value("DISCORD_CHANNEL_ID", channel_id)
    return redirect("/?saved=1")


@app.route("/save-cookies", methods=["POST"])
def save_cookies():
    cookies_file = request.form.get("cookies_file", "").strip()
    upsert_env_value("GALLERY_DL_COOKIES_FILE", cookies_file)
    return redirect("/?cookies_saved=1")


@app.route("/save-bot-config", methods=["POST"])
def save_bot_config():
    retry_poll_interval = request.form.get("retry_poll_interval", "30").strip()
    scan_interval = request.form.get("scan_interval", "0").strip()
    if not retry_poll_interval.isdigit() or not scan_interval.isdigit():
        return redirect("/?error=数値を入力してください")
    upsert_env_value("RETRY_POLL_INTERVAL", retry_poll_interval)
    upsert_env_value("SCAN_INTERVAL", scan_interval)
    return redirect("/?bot_config_saved=1")


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
    save_path = Path(_SAVE_PATH)
    if not save_path.exists():
        dirs = []
    else:
        dirs = [
            {"name": d.name, "count": sum(1 for f in d.iterdir() if f.is_file())}
            for d in sorted(save_path.iterdir(), reverse=True)
            if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", d.name)
        ]
    return render_template_string(_GALLERY_INDEX_HTML, dirs=dirs)


@app.route("/gallery/<date_str>")
def gallery_date(date_str: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return redirect("/gallery")
    target = Path(_SAVE_PATH) / date_str
    if not target.exists() or not target.is_dir():
        return redirect("/gallery")
    files = [
        {"name": f.name, "type": _media_type(f.name), "path": f"{date_str}/{f.name}"}
        for f in sorted(target.iterdir())
        if f.is_file()
    ]
    return render_template_string(_GALLERY_DATE_HTML, date=date_str, files=files)


@app.route("/media/<path:filepath>")
def serve_media(filepath: str):
    return send_from_directory(_SAVE_PATH, filepath)


@app.route("/gallery/search")
def gallery_search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return redirect("/gallery")
    save_path = Path(_SAVE_PATH)
    files = []
    if save_path.exists():
        for date_dir in sorted(save_path.iterdir(), reverse=True):
            if not date_dir.is_dir() or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_dir.name):
                continue
            for f in sorted(date_dir.iterdir()):
                if f.is_file() and q in f.name.lower():
                    files.append({
                        "name": f.name,
                        "type": _media_type(f.name),
                        "path": f"{date_dir.name}/{f.name}",
                    })
    return render_template_string(_GALLERY_DATE_HTML, date=f"🔍 {q}", files=files)


@app.route("/logs")
def logs():
    entries = _log_store.get_recent_logs(100) if _log_store else []
    return render_template_string(_LOGS_HTML, entries=entries)


@app.route("/failures")
def failures():
    entries = _log_store.get_failures() if _log_store else []
    return render_template_string(
        _FAILURES_HTML,
        entries=entries,
        queued=request.args.get("queued") == "1",
    )


@app.route("/retry/<int:message_id>/<int:channel_id>", methods=["POST"])
def retry(message_id: int, channel_id: int):
    if _log_store:
        _log_store.queue_retry(message_id, channel_id)
    return redirect("/failures?queued=1")


# ── エントリーポイント ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"Web サーバーを起動しています: http://localhost:{_PORT}")
    app.run(host="0.0.0.0", port=_PORT, debug=False)
