"""
アプリケーション設定モジュール。
環境変数 / .env ファイルから設定を読み込む。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション全体の設定。

    すべての値は環境変数 (または .env ファイル) で上書きできる。
    """

    # ── Discord ───────────────────────────────────────────────────────────────
    discord_bot_token: str | None = None
    """Discord Bot のトークン。Developer Portal から取得する。"""

    discord_channel_id: int | None = None
    """監視する Discord チャンネルの ID。"""

    # ── X (Twitter) / gallery-dl ─────────────────────────────────────────────
    gallery_dl_cookies_file: str | None = None
    """gallery-dl に渡すブラウザ Cookie ファイルのパス (Netscape 形式)。

    鍵垢など認証が必要なツイートにアクセスするときだけ設定する。
    """

    # ── 保存先 ───────────────────────────────────────────────────────────────
    save_path: str = "./data"
    """画像の保存先ルートディレクトリ。日付サブフォルダが自動作成される。"""

    # ── Web サーバー ──────────────────────────────────────────────────────────
    web_setup_port: int = 8989
    """Web サーバー (Flask) のポート番号。デフォルト: 8989"""

    # ── ロギング ──────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    """ログレベル。DEBUG / INFO / WARNING / ERROR のいずれか。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
