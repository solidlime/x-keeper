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

    discord_channel_id: str | None = None
    """監視する Discord チャンネルの ID。カンマ区切りで複数指定可。
    例: 1234567890123456789
    例: 1234567890123456789,9876543210987654321
    """

    # ── X (Twitter) / gallery-dl ─────────────────────────────────────────────
    gallery_dl_cookies_file: str | None = None
    """gallery-dl に渡すブラウザ Cookie ファイルのパス (Netscape 形式)。

    鍵垢など認証が必要なツイートにアクセスするときだけ設定する。
    """

    pixiv_refresh_token: str | None = None
    """Pixiv の OAuth リフレッシュトークン。

    Web UI の Pixiv セクションから取得する。
    """

    # ── 保存先 ───────────────────────────────────────────────────────────────
    save_path: str = "./data"
    """画像の保存先ルートディレクトリ。日付サブフォルダが自動作成される。"""

    # ── Web サーバー ──────────────────────────────────────────────────────────
    web_setup_port: int = 8989
    """Web サーバー (Flask) のポート番号。デフォルト: 8989"""

    # ── Bot 動作 ──────────────────────────────────────────────────────────────
    retry_poll_interval: int = 30
    """リトライキューのポーリング間隔 (秒)。デフォルト: 30"""

    scan_interval: int = 0
    """未処理メッセージの定期スキャン間隔 (秒)。0 = 起動時のみ。デフォルト: 0"""

    # ── ロギング ──────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    """ログレベル。DEBUG / INFO / WARNING / ERROR のいずれか。"""

    @property
    def channel_ids(self) -> list[int]:
        """監視チャンネル ID のリスト。カンマ区切り文字列をパースして返す。"""
        if not self.discord_channel_id:
            return []
        return [
            int(x.strip())
            for x in self.discord_channel_id.split(",")
            if x.strip().isdigit()
        ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
