"""
Web サーバー。Discord セットアップ UI + /gallery メディアビューア。

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
        <div class="form-text">数字のみ。Discord の開発者モードでチャンネルを右クリックして取得。</div>
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
      Pixiv の画像をダウンロードするために必要です。Cookie ではなく OAuth トークンが必要です。
    </p>

    {% if pixiv_saved %}
    <div class="alert alert-success py-2 small">Pixiv リフレッシュトークンを保存しました。</div>
    {% endif %}
    {% if pixiv_error %}
    <div class="alert alert-danger py-2 small">{{ pixiv_error }}</div>
    {% endif %}

    <button type="button" class="btn btn-outline-danger mb-3" id="pixiv-login-btn"
            onclick="startPixivOAuth(this)">
      Pixiv にログインしてトークンを取得
    </button>
    <div id="pixiv-callback-section" style="display:none">
      <div class="alert alert-warning py-2 small mb-2">
        <strong>⚠️ コピーするタイミングに注意</strong><br>
        ログイン後、ブラウザは数回リダイレクトします。<br>
        アドレスバーが <strong><code>app-api.pixiv.net/…/callback?code=</code></strong>
        で始まる URL になるまで待ってから コピーしてください。<br>
        （ページ自体はエラーや真っ白でも構いません。URL に <code>?code=</code> が入っていれば OK）
      </div>
      <div class="alert alert-secondary py-2 small mb-2">
        ❌ 間違い例: <code>accounts.pixiv.net/post-redirect?return_to=…</code><br>
        ✅ 正しい例: <code>app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=XXXXX</code>
      </div>
      <form method="post" action="/pixiv-oauth/exchange">
        <div class="input-group mb-1">
          <input type="text" class="form-control form-control-sm font-monospace"
                 name="callback_url" required
                 placeholder="https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=...">
          <button type="submit" class="btn btn-primary btn-sm">取得して保存</button>
        </div>
      </form>
    </div>

    <script>
    async function startPixivOAuth(btn) {
      btn.disabled = true;
      btn.textContent = '認証 URL を生成中...';
      try {
        const res = await fetch('/pixiv-oauth/start');
        const data = await res.json();
        window.open(data.auth_url, '_blank');
        document.getElementById('pixiv-callback-section').style.display = 'block';
        btn.textContent = 'もう一度開く';
      } catch (e) {
        btn.textContent = 'エラーが発生しました。再試行してください。';
      }
      btn.disabled = false;
    }
    </script>

    <details class="mt-3">
      <summary class="small text-muted">手動でトークンを入力する</summary>
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
  </div>
</div>
</body></html>
"""
)

_PIXIV_CONTINUE_HTML = (
    _BASE_STYLE
    + """
<div class="card shadow-sm">
  <div class="card-body p-4">
    <h5 class="card-title mb-3">Pixiv 認証 — ステップ 2/2</h5>

    <div class="alert alert-info small mb-3">
      ログインは完了しています。<br>
      下のボタンで<strong>認証の続き</strong>を新しいタブで開いてください。<br>
      ページが表示されたら、アドレスバーの URL をコピーして下のフォームに貼り付けてください。<br>
      <span class="text-muted">（ページが真っ白やエラーでも OK。URL に <code>?code=</code> が入っていれば成功）</span>
    </div>

    <a href="{{ return_to_url }}" target="_blank" class="btn btn-danger w-100 mb-4">
      認証を続ける（新しいタブで開く）
    </a>

    <p class="small text-muted mb-1">
      コピーする URL の例:<br>
      <code>https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=XXXXX…</code>
    </p>

    <form method="post" action="/pixiv-oauth/exchange">
      <div class="input-group">
        <input type="text" class="form-control form-control-sm font-monospace"
               name="callback_url" required
               placeholder="https://app-api.pixiv.net/…/callback?code=...">
        <button type="submit" class="btn btn-primary btn-sm">取得して保存</button>
      </div>
    </form>

    <div class="mt-3">
      <a href="/" class="small text-muted">← セットアップに戻る</a>
    </div>
  </div>
</div>
</body></html>
"""
)

_GALLERY_INDEX_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:900px">
  <h5 class="mb-3">ダウンロード済みメディア</h5>
  {% if not dirs %}
  <p class="text-muted">まだメディアがありません。</p>
  {% else %}
  <div class="list-group">
    {% for d in dirs %}
    <a href="/gallery/{{ d.name }}" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
      <span class="fw-semibold font-monospace">{{ d.name }}</span>
      <span class="badge bg-secondary rounded-pill">{{ d.count }} ファイル</span>
    </a>
    {% endfor %}
  </div>
  {% endif %}
</div>
</body></html>
"""
)

_GALLERY_DATE_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:1200px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <a href="/gallery" class="btn btn-sm btn-outline-secondary">← 戻る</a>
    <h5 class="mb-0 font-monospace">{{ date }}</h5>
    <span class="text-muted small">{{ files|length }} ファイル</span>
  </div>
  {% if not files %}
  <p class="text-muted">ファイルがありません。</p>
  {% else %}
  <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
    {% for f in files %}
    <div class="col">
      {% if f.type == "image" %}
      <a href="/media/{{ f.path }}" target="_blank" title="{{ f.name }}">
        <img src="/media/{{ f.path }}" class="rounded"
             style="width:100%;aspect-ratio:1/1;object-fit:cover" alt="{{ f.name }}">
      </a>
      {% elif f.type == "video" %}
      <div>
        <video controls class="rounded" style="width:100%;aspect-ratio:16/9;object-fit:cover"
               title="{{ f.name }}">
          <source src="/media/{{ f.path }}">
        </video>
        <div class="small text-muted text-truncate mt-1" title="{{ f.name }}">{{ f.name }}</div>
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
    )


@app.route("/save-discord", methods=["POST"])
def save_discord():
    bot_token = request.form.get("bot_token", "").strip()
    channel_id = request.form.get("channel_id", "").strip()

    if not bot_token or not channel_id:
        return redirect("/?error=Bot+Token+と+Channel+ID+は必須です")
    if not channel_id.isdigit():
        return redirect("/?error=Channel+ID+は数字のみで入力してください")

    upsert_env_value("DISCORD_BOT_TOKEN", bot_token)
    upsert_env_value("DISCORD_CHANNEL_ID", channel_id)
    return redirect("/?saved=1")


@app.route("/save-cookies", methods=["POST"])
def save_cookies():
    cookies_file = request.form.get("cookies_file", "").strip()
    upsert_env_value("GALLERY_DL_COOKIES_FILE", cookies_file)
    return redirect("/?cookies_saved=1")


@app.route("/save-pixiv-token", methods=["POST"])
def save_pixiv_token():
    token = request.form.get("pixiv_token", "").strip()
    upsert_env_value("PIXIV_REFRESH_TOKEN", token)
    return redirect("/?pixiv_saved=1")


@app.route("/pixiv-oauth/start")
def pixiv_oauth_start():
    """PKCE コードを生成して Pixiv 認証 URL を返す。"""
    # gallery-dl と同じ方法で生成 (hex 文字列)
    code_verifier = os.urandom(32).hex()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.b64encode(digest)[:-1].decode().replace("+", "-").replace("/", "_")
    session["pixiv_code_verifier"] = code_verifier

    # gallery-dl の oauth.py に合わせたパラメーター
    auth_url = (
        "https://app-api.pixiv.net/web/v1/login"
        f"?code_challenge={code_challenge}"
        "&code_challenge_method=S256"
        "&client=pixiv-android"
    )
    return json.dumps({"auth_url": auth_url}), 200, {"Content-Type": "application/json"}


@app.route("/pixiv-oauth/exchange", methods=["POST"])
def pixiv_oauth_exchange():
    """コールバック URL からコードを取り出してリフレッシュトークンに交換する。"""
    callback_url = request.form.get("callback_url", "").strip()
    code_verifier = session.get("pixiv_code_verifier")

    if not code_verifier:
        return redirect("/?pixiv_error=セッションが切れました。もう一度やり直してください。")

    parsed = urllib.parse.urlparse(callback_url)
    params = urllib.parse.parse_qs(parsed.query)
    codes = params.get("code", [])

    # post-redirect URL が貼られた場合は return_to を取り出して中継ページへ
    if not codes and ("post-redirect" in callback_url or "return_to" in params):
        return_to = params.get("return_to", [""])[0]
        if return_to:
            return render_template_string(_PIXIV_CONTINUE_HTML, return_to_url=return_to)
        msg = "URLを解析できませんでした。ページをリロードして最初からやり直してください。"
        return redirect(f"/?pixiv_error={urllib.parse.quote(msg)}")

    if not codes:
        msg = "URLにcodeが含まれていません。アドレスバーのURLをそのままコピーしてください。"
        return redirect(f"/?pixiv_error={urllib.parse.quote(msg)}")

    session.pop("pixiv_code_verifier", None)

    data = urllib.parse.urlencode({
        "client_id": _PIXIV_CLIENT_ID,
        "client_secret": _PIXIV_CLIENT_SECRET,
        "code": codes[0],
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
        return redirect(f"/?pixiv_error=トークン取得失敗 (HTTP+{e.code})")
    except Exception as e:
        return redirect(f"/?pixiv_error=トークン取得失敗:+{e}")

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return redirect("/?pixiv_error=refresh_token+が応答に含まれていませんでした。")

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


# ── エントリーポイント ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"Web サーバーを起動しています: http://localhost:{_PORT}")
    app.run(host="0.0.0.0", port=_PORT, debug=False)
