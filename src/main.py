"""
エントリーポイント。
Discord Bot で X (Twitter) のメディアを自動ダウンロードするメインループ。
"""

import asyncio
import logging
import sys
import threading

from .config import Settings
from .discord_bot import XKeeperBot
from .image_downloader import MediaDownloader
from .twitter_client import TwitterClient
from .web_setup import app as _setup_app


def _reconfigure_stdout_encoding() -> None:
    """stdout / stderr の文字コードを UTF-8 に強制する。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _setup_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"無効なログレベルです: {level}")
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


_REQUIRED_SETTING_KEYS = ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"]
_CHECK_INTERVAL = 30


def _missing_settings(settings: Settings) -> list[str]:
    return [
        name
        for name, value in zip(
            _REQUIRED_SETTING_KEYS,
            [settings.discord_bot_token, settings.discord_channel_id],
        )
        if not value
    ]


async def _wait_for_required_settings(
    settings: Settings, logger: logging.Logger
) -> Settings:
    missing = _missing_settings(settings)
    if not missing:
        return settings

    logger.error(
        "必須の設定が未設定です: %s\n"
        "  → ブラウザで http://localhost:%d を開いてセットアップしてください。\n"
        "  → 設定が完了すると自動的に起動します (%d 秒ごとに再確認)。",
        ", ".join(missing),
        settings.web_setup_port,
        _CHECK_INTERVAL,
    )
    while True:
        await asyncio.sleep(_CHECK_INTERVAL)
        settings = Settings()  # type: ignore[call-arg]
        missing = _missing_settings(settings)
        if not missing:
            logger.info("必須設定が揃いました。起動を続行します。")
            return settings
        logger.warning(
            "まだ未設定の項目があります: %s (%d 秒後に再確認)",
            ", ".join(missing),
            _CHECK_INTERVAL,
        )


async def async_main() -> None:
    _reconfigure_stdout_encoding()

    settings = Settings()  # type: ignore[call-arg]
    _setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info("x-keeper を起動します")

    # Flask をデーモンスレッドで起動 (ギャラリー UI)
    threading.Thread(
        target=_setup_app.run,
        kwargs={
            "host": "0.0.0.0",
            "port": settings.web_setup_port,
            "debug": False,
            "use_reloader": False,
        },
        daemon=True,
    ).start()
    logger.info("Web サーバーを起動しました (http://localhost:%d)", settings.web_setup_port)

    settings = await _wait_for_required_settings(settings, logger)

    twitter = TwitterClient(settings.gallery_dl_cookies_file)
    downloader = MediaDownloader(settings.save_path, settings.gallery_dl_cookies_file, settings.pixiv_refresh_token)

    bot = XKeeperBot(settings.discord_channel_id, twitter, downloader)  # type: ignore[arg-type]
    logger.info("Discord Bot を起動します (チャンネル ID: %d)...", settings.discord_channel_id)
    await bot.start(settings.discord_bot_token)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
