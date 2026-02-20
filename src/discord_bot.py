"""
Discord Bot - X (Twitter) / Pixiv メディアダウンローダー。

監視チャンネルに X/Twitter または Pixiv の URL が投稿されると自動的にメディアをダウンロードし、
✅ リアクションで処理済みを示す。エラー時はリアクションなし (次回再試行)。

起動時に未処理の過去メッセージ (最新 100 件) もスキャンして処理する。
"""

import logging
import re

import discord

from .image_downloader import MediaDownloader
from .twitter_client import TwitterClient

logger = logging.getLogger(__name__)

TWITTER_URL_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/status/\d+"
)
PIXIV_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+"
)

_REACTION_OK = "✅"
_REACTION_PROCESSING = "⏳"


def _find_media_urls(content: str) -> list[str]:
    """メッセージ内の X/Twitter および Pixiv の URL を全て返す。"""
    return TWITTER_URL_PATTERN.findall(content) + PIXIV_URL_PATTERN.findall(content)


class XKeeperBot(discord.Client):
    def __init__(
        self,
        channel_id: int,
        twitter: TwitterClient,
        downloader: MediaDownloader,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.channel_id = channel_id
        self.twitter = twitter
        self.downloader = downloader

    async def on_ready(self) -> None:
        logger.info("Discord Bot 起動: %s (ID: %s)", self.user, self.user.id)
        channel = self.get_channel(self.channel_id)
        if channel is None:
            logger.error(
                "チャンネルが見つかりません (channel_id=%d)。"
                "以下を確認してください:\n"
                "  1. DISCORD_CHANNEL_ID が正しいか\n"
                "  2. Bot がそのサーバーに招待されているか\n"
                "  3. Bot にチャンネルの閲覧権限があるか",
                self.channel_id,
            )
            return
        logger.info("監視チャンネル: #%s (id=%d)", channel.name, channel.id)
        await self._scan_pending_messages()

    async def on_message(self, message: discord.Message) -> None:
        if message.channel.id != self.channel_id:
            return
        if message.author.bot:
            return
        if not _find_media_urls(message.content):
            return
        await self._process_message(message)

    async def _scan_pending_messages(self) -> None:
        """起動時に未処理の過去メッセージを処理する (最新 100 件)。"""
        channel = self.get_channel(self.channel_id)
        if channel is None:
            return  # on_ready でエラー済み

        logger.info("未処理メッセージをスキャンしています...")
        async for message in channel.history(limit=100):
            if message.author.bot:
                continue
            reactions = [str(r.emoji) for r in message.reactions]
            if _REACTION_OK in reactions:
                continue
            if not _find_media_urls(message.content):
                continue
            logger.info("未処理メッセージを発見: message_id=%d", message.id)
            await self._process_message(message)

    async def _process_message(self, message: discord.Message) -> None:
        urls = _find_media_urls(message.content)
        logger.info("処理開始: message_id=%d, urls=%s", message.id, urls)

        await message.add_reaction(_REACTION_PROCESSING)

        errors = []
        for url in urls:
            try:
                if PIXIV_URL_PATTERN.search(url):
                    # Pixiv: そのまま直接ダウンロード
                    saved = self.downloader.download_direct([url])
                    if not saved:
                        errors.append(f"ダウンロード失敗 (ファイルが保存されませんでした): url={url}")
                else:
                    # X/Twitter: スレッドを遡って全ツイートをダウンロード
                    thread = self.twitter.get_thread(url)
                    if not thread.tweet_urls:
                        logger.info("メディアが見つかりませんでした: url=%s", url)
                        continue
                    saved = self.downloader.download_all(thread.tweet_urls)
                    if not saved:
                        errors.append(f"ダウンロード失敗 (ファイルが保存されませんでした): url={url}")
            except Exception as exc:
                logger.error("処理エラー: url=%s, error=%s", url, exc)
                errors.append(str(exc))

        try:
            await message.remove_reaction(_REACTION_PROCESSING, self.user)
        except discord.HTTPException:
            pass

        if errors:
            logger.warning(
                "処理失敗 (リアクションなし・次回再試行): message_id=%d, errors=%s",
                message.id,
                errors,
            )
        else:
            await message.add_reaction(_REACTION_OK)
            logger.info("処理完了: message_id=%d", message.id)
