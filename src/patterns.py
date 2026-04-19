"""URL パターン・正規表現の一元管理。

各モジュールからここを import して使うこと。
同じパターンを複数ファイルに定義しない。
"""

import re

# ── X (Twitter) ──────────────────────────────────────────────────────────────

# ツイート個別ページ (status URL)
X_STATUS_URL_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/status/\d+"
)

# ユーザーメディアページ (/media)
X_MEDIA_PAGE_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/media\b"
)

# ── Pixiv ─────────────────────────────────────────────────────────────────────

PIXIV_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+"
)

# ── Imgur ─────────────────────────────────────────────────────────────────────

IMGUR_URL_PATTERN = re.compile(
    r"https?://(?:i\.)?imgur\.com/[A-Za-z0-9/_\-.]+"
)

# ── yt-dlp 対応サイト ─────────────────────────────────────────────────────────

# YouTube (通常動画・ショート・youtu.be 短縮)
YOUTUBE_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/(?:watch|shorts/[A-Za-z0-9_-]+)|youtu\.be/[A-Za-z0-9_-]+)"
)

# TikTok (ユーザー投稿動画・短縮リンク)
TIKTOK_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?tiktok\.com/(?:@[^/\s]+/video/\d+|t/[A-Za-z0-9]+)"
)

# NicoNico 動画
NICOVIDEO_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?nicovideo\.jp/watch/[A-Za-z0-9]+"
)

# yt-dlp 対応サイト統合パターン (追加サイトが増えたらここへ追記)
YT_DLP_URL_PATTERN = re.compile(
    r"https?://(?:"
    r"(?:www\.)?youtube\.com/(?:watch|shorts/[A-Za-z0-9_-]+)"
    r"|youtu\.be/[A-Za-z0-9_-]+"
    r"|(?:www\.)?tiktok\.com/(?:@[^/\s]+/video/\d+|t/[A-Za-z0-9]+)"
    r"|(?:www\.)?nicovideo\.jp/watch/[A-Za-z0-9]+"
    r")"
)

# ── 複合パターン ──────────────────────────────────────────────────────────────

# X/Pixiv/Imgur/yt-dlp URL を受け付ける統合パターン (API キュー・バリデーション用)
API_URL_PATTERN = re.compile(
    r"https?://(?:"
    r"(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/(?:status/\d+|media)"
    r"|(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+"
    r"|(?:i\.)?imgur\.com/[A-Za-z0-9/_\-.]+"
    r"|(?:www\.)?youtube\.com/(?:watch|shorts/[A-Za-z0-9_-]+)"
    r"|youtu\.be/[A-Za-z0-9_-]+"
    r"|(?:www\.)?tiktok\.com/(?:@[^/\s]+/video/\d+|t/[A-Za-z0-9]+)"
    r"|(?:www\.)?nicovideo\.jp/watch/[A-Za-z0-9]+"
    r")"
)

# ── tweet_id ──────────────────────────────────────────────────────────────────

# URL から tweet_id を抽出する (/status/123... 形式)
TWEET_ID_FROM_URL = re.compile(r"/status/(\d+)")

# ファイル名から tweet_id を抽出する ({name}-{tweet_id}-{num}.{ext} 形式)
TWEET_ID_FROM_FILENAME = re.compile(r"-(\d{10,20})-\d{2}\.\w+$")

# tweet_id として有効かチェックする (10〜20 桁)
TWEET_ID_RE = re.compile(r"^\d{10,20}$")
