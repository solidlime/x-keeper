"""
Google OAuth2 認証情報 Web セットアップサーバー。

ブラウザから Google OAuth2 の認証情報 (Client ID, Client Secret) を入力し、
OAuth2 フローを実行してリフレッシュトークンを .env に保存する。

起動方法:
    python -m src.web_setup

または Docker 経由:
    docker compose --profile setup up setup

ブラウザで http://localhost:8080 を開いてセットアップを進めてください。
"""

import os
import re
import secrets
from pathlib import Path

# ローカル HTTP でも OAuth2 フローを通すために必要 (本番環境では使用しないこと)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from flask import Flask, redirect, render_template_string, request, send_from_directory, session, url_for

from src.token_setup import _ENV_FILE, upsert_env_value

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

_PORT = int(os.getenv("WEB_SETUP_PORT", "8989"))
_SAVE_PATH = os.getenv("SAVE_PATH", "/data/images")

_SCOPES = [
    "https://www.googleapis.com/auth/memento",
    "https://www.googleapis.com/auth/reminders",
]

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
    <p class="text-muted mb-4">Google OAuth2 認証情報を設定します。</p>

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

    <!-- 取得手順ガイド -->
    <h6 class="fw-bold">Client ID / Client Secret の取得方法</h6>
    <details class="mb-4">
      <summary>Google Cloud Console での作成手順を見る</summary>
      <div class="details-body small">
        <ol class="mb-0 ps-3">
          <li class="mb-2">
            <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">
              Google Cloud Console
            </a>
            を開き、画面上部のプロジェクト選択メニューから
            <strong>「新しいプロジェクト」</strong> を作成するか、既存のプロジェクトを選択します。
          </li>
          <li class="mb-2">
            左メニューから <strong>「APIとサービス」→「OAuth 同意画面」</strong> を開きます。<br>
            User Type は <strong>「外部」</strong> を選択して「作成」をクリックします。<br>
            アプリ名・サポートメールを入力して「保存して次へ」を繰り返し、最後に「ダッシュボードに戻る」をクリックします。<br>
            <span class="text-muted">※ スコープの追加・テストユーザーの登録は不要です。</span>
          </li>
          <li class="mb-2">
            左メニューから <strong>「APIとサービス」→「認証情報」</strong> を開きます。
          </li>
          <li class="mb-2">
            画面上部の <strong>「+ 認証情報を作成」→「OAuth クライアント ID」</strong> をクリックします。
          </li>
          <li class="mb-2">
            アプリケーションの種類で <strong>「デスクトップアプリ」</strong> を選択し、
            任意の名前（例: <code>x-keeper</code>）を入力して <strong>「作成」</strong> をクリックします。
          </li>
          <li class="mb-2">
            ダイアログに表示される <strong>クライアント ID</strong> と
            <strong>クライアント シークレット</strong> をコピーして、
            下のフォームに貼り付けます。<br>
            <span class="text-muted">
              ※ ダイアログを閉じた後は認証情報一覧の
              <strong>「編集」（鉛筆アイコン）</strong>
              から再確認できます。
            </span>
          </li>
        </ol>
      </div>
    </details>

    <!-- セットアップフォーム -->
    <h6 class="fw-bold">認証情報を入力</h6>

    {% if error %}
    <div class="alert alert-danger">{{ error }}</div>
    {% endif %}

    <form method="post" action="/start">
      <div class="mb-3">
        <label class="form-label fw-semibold">Client ID <span class="text-danger">*</span></label>
        <input type="text" class="form-control font-monospace"
               name="client_id" required
               placeholder="123456789-abc....apps.googleusercontent.com"
               value="{{ prefill.client_id }}">
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold">Client Secret <span class="text-danger">*</span></label>
        <input type="password" class="form-control font-monospace"
               name="client_secret" required
               placeholder="GOCSPX-..."
               value="{{ prefill.client_secret }}">
      </div>
      <div class="mb-4">
        <label class="form-label fw-semibold">Google アカウントのメールアドレス</label>
        <input type="email" class="form-control"
               name="email"
               placeholder="you@gmail.com"
               value="{{ prefill.email }}">
        <div class="form-text">省略可。設定するとログイン先を固定できます。</div>
      </div>
      <button type="submit" class="btn btn-primary w-100">
        Google 認証ページへ進む →
      </button>
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
      x.com のクッキーを書き出し、<code>data/</code> フォルダに配置してください。<br>
      コンテナ内では <code>/data/</code> にマウントされているため、
      例えば <code>data/x.com_cookies.txt</code> に置いたファイルは
      <code>/data/x.com_cookies.txt</code> と指定します。
    </p>

    {% if cookies_saved %}
    <div class="alert alert-success py-2 small">Cookie ファイルのパスを保存しました。</div>
    {% endif %}

    <form method="post" action="/save-cookies">
      <div class="mb-3">
        <label class="form-label fw-semibold">Cookie ファイルのパス</label>
        <input type="text" class="form-control font-monospace"
               name="cookies_file"
               placeholder="/data/x.com_cookies.txt"
               value="{{ prefill.cookies_file }}">
        <div class="form-text">空のまま保存すると設定を削除します。</div>
      </div>
      <button type="submit" class="btn btn-outline-primary">保存する</button>
    </form>
  </div>
</div>
</body></html>
"""
)

_SUCCESS_HTML = (
    _BASE_STYLE
    + """
<div class="card shadow-sm">
  <div class="card-body p-4 text-center">
    <div class="display-4 mb-3">✅</div>
    <h4 class="card-title mb-2">認証が完了しました</h4>
    <p class="text-muted mb-4">
      リフレッシュトークンを <code>.env</code> に保存しました。<br>
      このウィンドウを閉じてコンテナを起動してください。
    </p>
    <div class="alert alert-success text-start">
      <code>docker compose up -d</code>
    </div>
    <a href="/" class="btn btn-outline-secondary mt-2">設定ページに戻る</a>
  </div>
</div>
</body></html>
"""
)

_ERROR_HTML = (
    _BASE_STYLE
    + """
<div class="card shadow-sm">
  <div class="card-body p-4 text-center">
    <div class="display-4 mb-3">❌</div>
    <h4 class="card-title mb-2">エラーが発生しました</h4>
    <p class="text-muted">{{ message }}</p>
    <a href="/" class="btn btn-primary mt-3">最初からやり直す</a>
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
    """ファイル名からメディア種別を返す。"""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "gif", "webp", "avif"}:
        return "image"
    if ext in {"mp4", "mov", "mkv", "avi", "webm", "m4v"}:
        return "video"
    if ext in {"mp3", "ogg", "aac", "flac", "wav", "m4a", "opus"}:
        return "audio"
    return "other"


def _current_status() -> dict[str, bool]:
    """現在の .env から各設定値の有無を返す。"""
    # dotenv で .env を読み込み、設定済みかチェック
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    keys = [
        "GOOGLE_EMAIL",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
        "GALLERY_DL_COOKIES_FILE",
    ]
    return {k: bool(env.get(k)) for k in keys}


def _prefill_values() -> dict[str, str]:
    """フォームの初期値として .env の既存値を返す。シークレット値は空にする。"""
    from dotenv import dotenv_values

    env = dotenv_values(_ENV_FILE) if _ENV_FILE.exists() else {}
    return {
        "client_id": env.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        "client_secret": "",  # セキュリティのため表示しない
        "email": env.get("GOOGLE_EMAIL", ""),
        "cookies_file": env.get("GALLERY_DL_COOKIES_FILE", ""),
    }


def _build_flow(client_id: str, client_secret: str, redirect_uri: str):
    """google_auth_oauthlib の Flow インスタンスを生成する。"""
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=_SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


# ── ルート ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    error = request.args.get("error")
    cookies_saved = request.args.get("cookies_saved") == "1"
    return render_template_string(
        _INDEX_HTML,
        status=_current_status(),
        prefill=_prefill_values(),
        error=error,
        cookies_saved=cookies_saved,
    )


@app.route("/start", methods=["POST"])
def start():
    client_id = request.form.get("client_id", "").strip()
    client_secret = request.form.get("client_secret", "").strip()
    email = request.form.get("email", "").strip()

    if not client_id or not client_secret:
        return redirect("/?error=Client+ID+と+Client+Secret+は必須です")

    # セッションに保存 (コールバック時に使用)
    session["client_id"] = client_id
    session["client_secret"] = client_secret
    session["email"] = email

    redirect_uri = url_for("callback", _external=True)
    flow = _build_flow(client_id, client_secret, redirect_uri)

    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # 毎回 refresh_token を発行させる
    )
    session["oauth_state"] = state

    return redirect(auth_url)


@app.route("/callback")
def callback():
    state = session.get("oauth_state")
    client_id = session.get("client_id")
    client_secret = session.get("client_secret")
    email = session.get("email", "")

    if not state or not client_id or not client_secret:
        return render_template_string(
            _ERROR_HTML,
            message="セッションが無効です。最初からやり直してください。",
        )

    redirect_uri = url_for("callback", _external=True)
    flow = _build_flow(client_id, client_secret, redirect_uri)

    try:
        flow.fetch_token(
            authorization_response=request.url,
            state=state,
        )
    except Exception as exc:
        return render_template_string(_ERROR_HTML, message=str(exc))

    creds = flow.credentials
    if not creds.refresh_token:
        return render_template_string(
            _ERROR_HTML,
            message=(
                "リフレッシュトークンが取得できませんでした。"
                "Google アカウントの「アクセス権を付与したアプリ」から"
                "このアプリを削除してから再試行してください。"
            ),
        )

    # .env に保存
    upsert_env_value("GOOGLE_OAUTH_CLIENT_ID", client_id)
    upsert_env_value("GOOGLE_OAUTH_CLIENT_SECRET", client_secret)
    upsert_env_value("GOOGLE_OAUTH_REFRESH_TOKEN", creds.refresh_token)
    if email:
        upsert_env_value("GOOGLE_EMAIL", email)

    # セッションを削除
    session.clear()

    return render_template_string(_SUCCESS_HTML)


@app.route("/save-cookies", methods=["POST"])
def save_cookies():
    cookies_file = request.form.get("cookies_file", "").strip()
    upsert_env_value("GALLERY_DL_COOKIES_FILE", cookies_file)
    return redirect("/?cookies_saved=1")


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

    print(f"セットアップサーバーを起動しています: http://localhost:{_PORT}")
    print("ブラウザで上記 URL を開いてセットアップを進めてください。")
    print("Ctrl+C で終了します。")
    print()

    # Docker 内で外部からアクセスできるよう 0.0.0.0 にバインド
    app.run(host="0.0.0.0", port=_PORT, debug=False)
