"""セットアップ・Pixiv OAuth ルート。"""

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, redirect, render_template_string, request, session

from ..templates import _INDEX_HTML
from ..utils import _current_status, _prefill_values, upsert_env_value

bp_setup = Blueprint("bp_setup", __name__)

# Pixiv OAuth (gallery-dl と同じ公式アプリ資格情報)
_PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
_PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
_PIXIV_REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"


@bp_setup.route("/")
def index():
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


@bp_setup.route("/save-cookies", methods=["POST"])
def save_cookies():
    cookies_file = request.form.get("cookies_file", "").strip()
    upsert_env_value("GALLERY_DL_COOKIES_FILE", cookies_file)
    return redirect("/?cookies_saved=1")


@bp_setup.route("/save-bot-config", methods=["POST"])
def save_bot_config():
    retry_poll_interval = request.form.get("retry_poll_interval", "30").strip()
    gallery_thumb_count = request.form.get("gallery_thumb_count", "50").strip()
    if not retry_poll_interval.isdigit() or not gallery_thumb_count.isdigit():
        return redirect("/?setup=1&error=数値を入力してください")
    upsert_env_value("RETRY_POLL_INTERVAL", retry_poll_interval)
    upsert_env_value("GALLERY_THUMB_COUNT", gallery_thumb_count)
    return redirect("/?setup=1&bot_config_saved=1")


@bp_setup.route("/save-pixiv-token", methods=["POST"])
def save_pixiv_token():
    token = request.form.get("pixiv_token", "").strip()
    upsert_env_value("PIXIV_REFRESH_TOKEN", token)
    return redirect("/?pixiv_saved=1")


@bp_setup.route("/pixiv-oauth/start")
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


@bp_setup.route("/pixiv-oauth/cancel")
def pixiv_oauth_cancel():
    """セッションをクリアしてトップに戻る。"""
    session.pop("pixiv_code_verifier", None)
    session.pop("pixiv_auth_url", None)
    return redirect("/")


@bp_setup.route("/pixiv-oauth/exchange", methods=["POST"])
def pixiv_oauth_exchange():
    """code 値または URL からコードを抽出してリフレッシュトークンに交換する。"""
    raw = request.form.get("code", "").strip()
    code_verifier = session.get("pixiv_code_verifier")

    if not code_verifier:
        msg = urllib.parse.quote("セッションが切れました。もう一度やり直してください。")
        return redirect(f"/?pixiv_error={msg}")

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

    session.pop("pixiv_code_verifier", None)
    session.pop("pixiv_auth_url", None)

    upsert_env_value("PIXIV_REFRESH_TOKEN", refresh_token)
    return redirect("/?pixiv_saved=1")
