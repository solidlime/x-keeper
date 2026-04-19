"""
エントリーポイント。
X (Twitter) / Pixiv / Imgur メディアを API キュー経由でダウンロードするメインループ。
Chrome 拡張・Android アプリから直接 URL を投入する。
"""

import asyncio
import logging
import sys
import threading

from .config import Settings
from .image_downloader import MediaDownloader
from .log_store import LogStore
from .patterns import IMGUR_URL_PATTERN, PIXIV_URL_PATTERN, X_MEDIA_PAGE_PATTERN, YT_DLP_URL_PATTERN
from . import web_setup as _web_setup_module
from .web_setup import app as _setup_app

logger = logging.getLogger(__name__)

# URL パターンは src/patterns.py で一元管理
_X_MEDIA_PAGE_PATTERN = X_MEDIA_PAGE_PATTERN
_PIXIV_URL_PATTERN = PIXIV_URL_PATTERN
_IMGUR_URL_PATTERN = IMGUR_URL_PATTERN
_YT_DLP_URL_PATTERN = YT_DLP_URL_PATTERN


def _reconfigure_stdout_encoding() -> None:
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


async def _download_url_direct(
    url: str,
    downloader: MediaDownloader,
    log_store: LogStore,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """URL を直接ダウンロードしてログに記録する。"""
    logger.info("直接ダウンロード開始: url=%s", url)
    try:
        if _X_MEDIA_PAGE_PATTERN.search(url):
            saved = await loop.run_in_executor(
                None, downloader.download_user_media, url
            )
            logger.info("直接ダウンロード完了: url=%s, files=%d", url, len(saved))
            log_store.append_success([url], len(saved))
        elif _PIXIV_URL_PATTERN.search(url) or _IMGUR_URL_PATTERN.search(url):
            saved = await loop.run_in_executor(
                None, downloader.download_direct, [url]
            )
            logger.info("直接ダウンロード完了: url=%s, files=%d", url, len(saved))
            log_store.append_success([url], len(saved))
            log_store.mark_downloaded_url(url)
        elif _YT_DLP_URL_PATTERN.search(url):
            saved = await loop.run_in_executor(
                None, downloader.download_yt_dlp, url
            )
            logger.info("yt-dlp ダウンロード完了: url=%s, files=%d", url, len(saved))
            log_store.append_success([url], len(saved))
        else:
            result = await loop.run_in_executor(
                None, downloader.download_all, [url]
            )
            logger.info(
                "直接ダウンロード完了: url=%s, files=%d, skipped=%d",
                url, len(result.saved), result.skipped_count,
            )
            log_store.append_success([url], len(result.saved))
    except Exception as exc:
        logger.error("直接ダウンロードエラー: url=%s, error=%s", url, exc)
        log_store.append_failure([url], str(exc))


async def _api_queue_loop(
    downloader: MediaDownloader,
    log_store: LogStore,
    poll_interval: int,
) -> None:
    """API キューを定期的にポーリングしてダウンロードを実行する。"""
    loop = asyncio.get_running_loop()
    logger.info("API キューループ開始 (ポーリング間隔: %d 秒)", poll_interval)
    while True:
        await asyncio.sleep(poll_interval)
        urls = log_store.pop_api_queue()
        if urls:
            logger.info("API キューを処理: %d 件", len(urls))
            for url in urls:
                await _download_url_direct(url, downloader, log_store, loop)


async def async_main() -> None:
    _reconfigure_stdout_encoding()

    settings = Settings()  # type: ignore[call-arg]
    _setup_logging(settings.log_level)
    logger.info("x-keeper を起動します")

    log_store = LogStore(settings.save_path)
    _web_setup_module.set_log_store(log_store)

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

    downloader = MediaDownloader(
        settings.save_path,
        settings.gallery_dl_cookies_file,
        settings.pixiv_refresh_token,
        log_store,
    )

    await _api_queue_loop(downloader, log_store, settings.retry_poll_interval)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
