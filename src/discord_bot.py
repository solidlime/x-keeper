"""
Discord Bot - X (Twitter) / Pixiv メディアダウンローダー。

監視チャンネルに X/Twitter または Pixiv の URL が投稿されると自動的にメディアをダウンロードし、
✅ リアクションで処理済みを示す。エラー時は ❌ リアクションを付けて次回再試行。

起動時に未処理の過去メッセージ (最新 100 件) もスキャンして処理する。
"""

import asyncio
import logging
import re

import discord

from .image_downloader import MediaDownloader
from .log_store import LogStore
from .twitter_client import TwitterClient

logger = logging.getLogger(__name__)

TWITTER_URL_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/status/\d+"
)
# /media タブ: status URL より前に検出する (重複マッチ防止のため先行定義)
X_MEDIA_PAGE_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/media\b"
)
PIXIV_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+"
)
IMGUR_URL_PATTERN = re.compile(
    r"https?://(?:i\.)?imgur\.com/[A-Za-z0-9/_\-.]+"
)

_REACTION_OK = "✅"
_REACTION_PROCESSING = "⏳"
_REACTION_ERROR = "❌"
# 全ツイートが重複ダウンロード済みのためスキップされた場合に付与する
_REACTION_SKIPPED = "⏭️"


def _find_media_urls(content: str) -> list[str]:
    """メッセージ内の X/Twitter・Pixiv・Imgur の URL を全て返す。

    X_MEDIA_PAGE_PATTERN を先に検出することで /media URL が
    TWITTER_URL_PATTERN にマッチしないようにする。
    """
    return (
        X_MEDIA_PAGE_PATTERN.findall(content)
        + TWITTER_URL_PATTERN.findall(content)
        + PIXIV_URL_PATTERN.findall(content)
        + IMGUR_URL_PATTERN.findall(content)
    )


class XKeeperBot(discord.Client):
    def __init__(
        self,
        channel_ids: list[int],
        twitter: TwitterClient,
        downloader: MediaDownloader,
        log_store: LogStore,
        retry_poll_interval: int = 30,
        scan_interval: int = 0,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.channel_ids = channel_ids
        self.twitter = twitter
        self.downloader = downloader
        self._log_store = log_store
        self._retry_poll_interval = retry_poll_interval
        self._scan_interval = scan_interval

    async def setup_hook(self) -> None:
        self.loop.create_task(self._retry_queue_task())

    async def on_ready(self) -> None:
        logger.info("Discord Bot 起動: %s (ID: %s)", self.user, self.user.id)
        for channel_id in self.channel_ids:
            channel = self.get_channel(channel_id)
            if channel is None:
                logger.error(
                    "チャンネルが見つかりません (channel_id=%d)。"
                    "DISCORD_CHANNEL_ID / Bot の招待状態を確認してください。",
                    channel_id,
                )
            else:
                logger.info("監視チャンネル: #%s (id=%d)", channel.name, channel.id)
        await self._scan_pending_messages()

    async def on_message(self, message: discord.Message) -> None:
        if message.channel.id not in self.channel_ids:
            return
        if message.author.bot:
            return
        if not _find_media_urls(message.content):
            return
        await self._process_message(message)

    async def _scan_pending_messages(self) -> None:
        """起動時に未処理の過去メッセージを処理する (チャンネルごとに最新 100 件)。"""
        for channel_id in self.channel_ids:
            channel = self.get_channel(channel_id)
            if channel is None:
                continue
            logger.info("未処理メッセージをスキャン: #%s", channel.name)
            async for message in channel.history(limit=100):
                if message.author.bot:
                    continue
                reactions = [str(r.emoji) for r in message.reactions]
                # ✅ (処理済み) と ⏭️ (全重複スキップ済み) はどちらも再処理不要
                if _REACTION_OK in reactions or _REACTION_SKIPPED in reactions:
                    continue
                if not _find_media_urls(message.content):
                    continue
                logger.info("未処理メッセージを発見: message_id=%d", message.id)
                await self._process_message(message)

    async def _process_message(self, message: discord.Message) -> None:
        urls = _find_media_urls(message.content)
        logger.info("処理開始: message_id=%d, urls=%s", message.id, urls)

        await message.add_reaction(_REACTION_PROCESSING)

        loop = asyncio.get_running_loop()
        errors: list[str] = []
        total_files = 0
        # 全ツイートが重複ダウンロード済みでスキップされた URL の件数
        all_duplicate_skipped_urls = 0

        for url in urls:
            try:
                if X_MEDIA_PAGE_PATTERN.search(url):
                    saved = await loop.run_in_executor(
                        None, self.downloader.download_user_media, url
                    )
                    if not saved:
                        logger.info("新規メディアなし (全て取得済み): url=%s", url)
                    else:
                        total_files += len(saved)
                elif PIXIV_URL_PATTERN.search(url) or IMGUR_URL_PATTERN.search(url):
                    saved = await loop.run_in_executor(
                        None, self.downloader.download_direct, [url]
                    )
                    if not saved:
                        errors.append(f"ダウンロード失敗 (ファイルなし): {url}")
                    else:
                        total_files += len(saved)
                else:
                    thread = await loop.run_in_executor(
                        None, self.twitter.get_thread, url
                    )
                    if not thread.tweet_urls:
                        logger.info("メディアが見つかりませんでした: url=%s", url)
                        continue
                    result = await loop.run_in_executor(
                        None, self.downloader.download_all, thread.tweet_urls
                    )
                    if result.skipped_count == len(thread.tweet_urls):
                        # スレッド内の全ツイートが既ダウンロード済み → 重複のため中断
                        logger.info(
                            "重複のため中断: message_id=%d, url=%s, skipped=%d 件",
                            message.id,
                            url,
                            result.skipped_count,
                        )
                        all_duplicate_skipped_urls += 1
                    elif not result.saved:
                        errors.append(f"ダウンロード失敗 (ファイルなし): {url}")
                    else:
                        total_files += len(result.saved)
            except Exception as exc:
                logger.error("処理エラー: url=%s, error=%s", url, exc)
                errors.append(str(exc))

        try:
            await message.remove_reaction(_REACTION_PROCESSING, self.user)
        except discord.HTTPException:
            pass

        if errors:
            await message.add_reaction(_REACTION_ERROR)
            self._log_store.append_failure(
                message.id, message.channel.id, urls, "; ".join(errors)
            )
            logger.warning("処理失敗: message_id=%d, errors=%s", message.id, errors)
        elif total_files == 0 and all_duplicate_skipped_urls > 0:
            # 新規ファイルなし・かつ全URL重複スキップ → ⏭️ で完了扱い (再試行不要)
            try:
                await message.remove_reaction(_REACTION_ERROR, self.user)
            except discord.HTTPException:
                pass
            await message.add_reaction(_REACTION_SKIPPED)
            self._log_store.append_success(
                message.id, message.channel.id, urls, 0
            )
            logger.info(
                "重複のためスキップ完了: message_id=%d, skipped_urls=%d",
                message.id,
                all_duplicate_skipped_urls,
            )
        else:
            # 以前の ❌ があれば削除してから ✅ を追加
            try:
                await message.remove_reaction(_REACTION_ERROR, self.user)
            except discord.HTTPException:
                pass
            await message.add_reaction(_REACTION_OK)
            self._log_store.append_success(
                message.id, message.channel.id, urls, total_files
            )
            logger.info("処理完了: message_id=%d, files=%d", message.id, total_files)

    async def _retry_queue_task(self) -> None:
        """リトライキューのポーリングと定期スキャンを行う。"""
        await self.wait_until_ready()
        last_scan = asyncio.get_event_loop().time()
        while not self.is_closed():
            await asyncio.sleep(self._retry_poll_interval)

            # 定期スキャン (scan_interval > 0 の場合)
            if self._scan_interval > 0:
                now = asyncio.get_event_loop().time()
                if now - last_scan >= self._scan_interval:
                    last_scan = now
                    logger.info("定期スキャンを開始します (間隔: %d 秒)", self._scan_interval)
                    await self._scan_pending_messages()

            queued = self._log_store.pop_retry_queue()
            for item in queued:
                channel = self.get_channel(item["channel_id"])
                if channel is None:
                    logger.warning(
                        "リトライ対象チャンネルが見つかりません: channel_id=%d",
                        item["channel_id"],
                    )
                    continue
                try:
                    message = await channel.fetch_message(item["message_id"])
                    logger.info("リトライ処理: message_id=%d", item["message_id"])
                    await self._process_message(message)
                except discord.NotFound:
                    logger.warning(
                        "リトライ対象メッセージが見つかりません: message_id=%d",
                        item["message_id"],
                    )
                except Exception as exc:
                    logger.error("リトライ処理エラー: %s", exc)

            # Chrome 拡張 / Android アプリから直接投入された URL キューを処理する
            await self._process_api_queue()

    async def _process_api_queue(self) -> None:
        """API キューから URL を取り出し Discord コンテキストなしでダウンロードする。"""
        urls = self._log_store.pop_api_queue()
        if not urls:
            return
        logger.info("API キューを処理: %d 件", len(urls))
        loop = asyncio.get_running_loop()
        for url in urls:
            await self._download_url_direct(url, loop)

    async def _download_url_direct(
        self, url: str, loop: asyncio.AbstractEventLoop
    ) -> None:
        """URL を Discord コンテキストなしで直接ダウンロードする。

        Chrome 拡張や Android アプリから投入された URL を処理する。
        結果はログに出力するが Discord リアクションは行わない。
        """
        logger.info("直接ダウンロード開始: url=%s", url)
        try:
            if X_MEDIA_PAGE_PATTERN.search(url):
                saved = await loop.run_in_executor(
                    None, self.downloader.download_user_media, url
                )
                logger.info("直接ダウンロード完了: url=%s, files=%d", url, len(saved))
                self._log_store.append_api_success(url, len(saved))
            elif PIXIV_URL_PATTERN.search(url) or IMGUR_URL_PATTERN.search(url):
                saved = await loop.run_in_executor(
                    None, self.downloader.download_direct, [url]
                )
                logger.info("直接ダウンロード完了: url=%s, files=%d", url, len(saved))
                self._log_store.append_api_success(url, len(saved))
                # Pixiv / Imgur の場合は tweet_id がないため URL ベースで完了管理する
                self._log_store.mark_downloaded_url(url)
            else:
                thread = await loop.run_in_executor(
                    None, self.twitter.get_thread, url
                )
                if not thread.tweet_urls:
                    logger.info("メディアが見つかりませんでした: url=%s", url)
                    return
                result = await loop.run_in_executor(
                    None, self.downloader.download_all, thread.tweet_urls
                )
                logger.info(
                    "直接ダウンロード完了: url=%s, files=%d, skipped=%d",
                    url,
                    len(result.saved),
                    result.skipped_count,
                )
                self._log_store.append_api_success(url, len(result.saved))
        except Exception as exc:
            logger.error("直接ダウンロードエラー: url=%s, error=%s", url, exc)
            self._log_store.append_api_failure(url, str(exc))
