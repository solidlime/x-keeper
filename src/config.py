"""
アプリケーション設定モジュール。
環境変数 / .env ファイルから設定を読み込む。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション全体の設定。

    すべての値は環境変数 (または .env ファイル) で上書きできる。
    デフォルト値がない項目は必須。
    """

    # ── Google Keep ──────────────────────────────────────────────────────────
    google_email: str | None = None
    """Google アカウントのメールアドレス。

    未設定の場合は起動時の対話セットアップで入力を促す。
    """

    google_client_secrets_file: str | None = None
    """Google OAuth2 client_secrets.json のファイルパス。

    未設定の場合はプロジェクトルートの client_secrets.json を探す。
    絶対パスまたは実行ディレクトリからの相対パスで指定する。
    """

    google_oauth_client_id: str | None = None
    """Google OAuth2 クライアント ID。Google Cloud Console から取得する。"""

    google_oauth_client_secret: str | None = None
    """Google OAuth2 クライアントシークレット。"""

    google_oauth_refresh_token: str | None = None
    """Google OAuth2 リフレッシュトークン。

    python -m src.token_setup を実行すると自動取得・保存される。
    """

    # ── X (Twitter) / gallery-dl ─────────────────────────────────────────────
    gallery_dl_cookies_file: str | None = None
    """gallery-dl に渡すブラウザ Cookie ファイルのパス (Netscape 形式)。

    鍵垢など認証が必要なツイートにアクセスするときだけ設定する。
    不要なら設定しなくてよい。
    """

    # ── 保存先 ───────────────────────────────────────────────────────────────
    save_path: str = "/data/images"
    """画像の保存先ルートディレクトリ。日付サブフォルダが自動作成される。"""

    # ── ポーリング ────────────────────────────────────────────────────────────
    poll_interval_seconds: int = 60
    """Google Keep の確認間隔 (秒)。"""

    # ── Web セットアップサーバ ────────────────────────────────────────────────
    web_setup_port: int = 8989
    """Web セットアップサーバ (Flask) のポート番号。

    docker-compose.yml のポートマッピングと一致させること。デフォルト: 8989
    """

    # ── ロギング ──────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    """ログレベル。DEBUG / INFO / WARNING / ERROR のいずれか。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
