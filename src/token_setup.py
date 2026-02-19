"""
Google OAuth2 認証セットアップユーティリティ。

初回起動時にブラウザを開いて Google アカウントの認証を行い、
リフレッシュトークンを .env に保存する。

【事前準備 (初回のみ)】
1. https://console.cloud.google.com/ でプロジェクトを作成
2. 「APIとサービス > 認証情報 > OAuth2クライアントID」を作成:
     - アプリケーションの種類: デスクトップアプリ
   ※ ライブラリで API を有効化する必要はない
     (memento/reminders スコープは一般 Google アカウントの内部スコープであり
      Cloud Console のライブラリには存在しない)
3. client_secrets.json をダウンロードして以下のいずれかを実施:
     - プロジェクトルートに配置 (デフォルト)
     - 任意の場所に配置して .env に GOOGLE_CLIENT_SECRETS_FILE=パス を設定
   または .env に GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET を設定

単独実行:
    python -m src.token_setup

または Docker 経由:
    docker compose run --rm -it keep-image-saver python -m src.token_setup
"""

import json
import re
import sys
from pathlib import Path

# .env ファイルの場所 (プロジェクトルート基準)
_ENV_FILE = Path(".env")


def _read_env_lines() -> list[str]:
    """既存の .env を行リストとして読み込む。ファイルがなければ空リストを返す。"""
    if _ENV_FILE.exists():
        return _ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    return []


def upsert_env_value(key: str, value: str) -> None:
    """.env ファイルに key=value を上書き追加する。

    既にキーが存在する場合は値を上書きし、存在しない場合は末尾に追記する。
    .env ファイルが存在しない場合は新規作成する。

    Args:
        key: 環境変数のキー名。
        value: 設定する値。
    """
    lines = _read_env_lines()
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    new_line = f"{key}={value}\n"

    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            _ENV_FILE.write_text("".join(lines), encoding="utf-8")
            return

    # キーが見つからなければ末尾に追記
    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    lines.append(new_line)
    _ENV_FILE.write_text("".join(lines), encoding="utf-8")


def _load_client_credentials() -> tuple[str, str]:
    """client_id と client_secret を解決する。

    優先順位:
      1. client_secrets.json
         - GOOGLE_CLIENT_SECRETS_FILE 環境変数で指定したパス
         - 未指定の場合はプロジェクトルートの client_secrets.json
      2. .env の GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET

    Returns:
        (client_id, client_secret) のタプル。

    Raises:
        RuntimeError: 認証情報が見つからない、または形式が不正な場合。
    """
    import os

    from dotenv import load_dotenv

    load_dotenv(_ENV_FILE)

    # ファイルパスの解決: 環境変数 GOOGLE_CLIENT_SECRETS_FILE > デフォルト位置
    secrets_file_env = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
    if secrets_file_env:
        secrets_file = Path(secrets_file_env)
    else:
        secrets_file = _ENV_FILE.parent / "client_secrets.json"


    if secrets_file.exists():
        data = json.loads(secrets_file.read_text(encoding="utf-8"))
        info: dict | None = data.get("installed") or data.get("web")
        if info is None:
            raise RuntimeError(
                f"{secrets_file} の形式が不正です: "
                "'installed' または 'web' キーが必要です。"
            )
        return info["client_id"], info["client_secret"]

    # .env から直接読む
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret

    raise RuntimeError(
        "Google OAuth2 認証情報が見つかりません。\n\n"
        "【セットアップ手順】\n"
        "1. https://console.cloud.google.com/ でプロジェクトを作成\n"
        "2. 「APIとサービス > 認証情報 > OAuth2クライアントID」を作成\n"
        "     アプリケーションの種類: デスクトップアプリ\n"
        "   ※ ライブラリで API を有効化する手順は不要\n"
        "3. client_secrets.json をダウンロードして以下のいずれかを実施:\n"
        f"   - {_ENV_FILE.parent.resolve()} に配置 (デフォルト)\n"
        "   - 任意の場所に配置して .env に GOOGLE_CLIENT_SECRETS_FILE=パス を設定\n"
        "   または .env に以下を追加:\n"
        "     GOOGLE_OAUTH_CLIENT_ID=your-client-id\n"
        "     GOOGLE_OAUTH_CLIENT_SECRET=your-client-service\n"
    )


def run_interactive_setup(port: int = 8989) -> None:
    """OAuth2 認証を実行し、リフレッシュトークンを .env に保存する。

    コンテナ内ではブラウザを自動起動せず、0.0.0.0 にバインドすることで
    ホストのブラウザから http://localhost:<port> 経由でアクセスできる。

    Args:
        port: コールバック HTTP サーバが使用するポート番号。

    Raises:
        RuntimeError: 認証情報が見つからない、または認証フローが失敗した場合。
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "google-auth-oauthlib が見つかりません。"
            "pip install google-auth-oauthlib を実行してください。"
        ) from exc

    client_id, client_secret = _load_client_credentials()

    # InstalledAppFlow に渡す client_config (Google の client_secrets.json と同形式)
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    # Google Keep + Reminders に必要なスコープ
    scopes = [
        "https://www.googleapis.com/auth/memento",
        "https://www.googleapis.com/auth/reminders",
    ]

    print()
    print("=" * 60)
    print(" Google Keep OAuth2 認証")
    print("=" * 60)
    print(f"認証サーバをポート {port} で起動します。")
    print("以下の手順で認証を完了してください:")
    print()
    print("  1. 下に表示される Google 認証 URL をブラウザで開く")
    print(f"  2. Google アカウントでログインしてアクセスを許可する")
    print(f"  3. ブラウザが http://localhost:{port}/ へリダイレクトされ")
    print(f"     「認証成功」と表示されたら完了")
    print()
    print("  ※ Docker 経由の場合はホスト側のブラウザで上記を実行してください")
    print("=" * 60)
    print()

    flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
    # bind_addr=0.0.0.0 でコンテナ外からアクセス可能にする
    # host=localhost はリダイレクト URI に使用 (ホストブラウザが解決できる必要がある)
    # open_browser=False: コンテナ内にブラウザがないため手動アクセス
    creds = flow.run_local_server(
        host="localhost",
        bind_addr="0.0.0.0",
        port=port,
        open_browser=False,
    )

    # リフレッシュトークンと認証情報を .env に保存する
    upsert_env_value("GOOGLE_OAUTH_CLIENT_ID", client_id)
    upsert_env_value("GOOGLE_OAUTH_CLIENT_SECRET", client_secret)
    upsert_env_value("GOOGLE_OAUTH_REFRESH_TOKEN", creds.refresh_token)

    print()
    print("認証に成功しました。リフレッシュトークンを .env に保存しました。")
    print("=" * 60)
    print()


def ensure_token_available(
    client_id: str | None,
    client_secret: str | None,
    refresh_token: str | None,
    port: int = 8989,
) -> None:
    """OAuth2 リフレッシュトークンが未設定の場合に認証フローを実行する。

    既に client_id / client_secret / refresh_token が全て設定済みの場合は何もしない。
    TTY の有無にかかわらず認証サーバを起動し、ホスト側ブラウザからアクセスできる。

    Args:
        client_id: Google OAuth2 クライアント ID。
        client_secret: Google OAuth2 クライアントシークレット。
        refresh_token: Google OAuth2 リフレッシュトークン。
        port: コールバック HTTP サーバが使用するポート番号。

    Raises:
        RuntimeError: 認証情報の取得に失敗した場合。
    """
    if client_id and client_secret and refresh_token:
        return  # 既に揃っている。何もしない。

    if not sys.stdin.isatty():
        print(
            f"[INFO] Google OAuth2 認証情報が未設定です。\n"
            f"認証サーバをポート {port} で起動します。\n"
            f"ホスト側ブラウザで下に表示される URL を開いて認証を完了してください。",
            file=sys.stderr,
        )

    run_interactive_setup(port=port)


if __name__ == "__main__":
    import os

    # stdin / stdout / stderr を UTF-8 に設定する（Windows 文字化け対策）
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    _port = int(os.environ.get("OAUTH_CALLBACK_PORT", "8989"))

    try:
        ensure_token_available(None, None, None, port=_port)
        print("セットアップが完了しました。")
        print("次のコマンドでコンテナを起動してください: docker compose up -d")
    except RuntimeError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
