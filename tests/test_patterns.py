"""src/patterns.py の URL パターンマッチングテスト。"""

import pytest

from src.patterns import (
    API_URL_PATTERN,
    IMGUR_URL_PATTERN,
    PIXIV_URL_PATTERN,
    TWEET_ID_FROM_FILENAME,
    TWEET_ID_FROM_URL,
    TWEET_ID_RE,
    X_MEDIA_PAGE_PATTERN,
    X_STATUS_URL_PATTERN,
    YT_DLP_URL_PATTERN,
)


class TestXStatusUrlPattern:
    @pytest.mark.parametrize("url", [
        "https://twitter.com/user123/status/1234567890123",
        "https://x.com/user_abc/status/9876543210987654321",
        "http://x.com/ABC_123/status/1111111111",
    ])
    def test_matches_valid(self, url):
        assert X_STATUS_URL_PATTERN.search(url)

    @pytest.mark.parametrize("url", [
        "https://twitter.com/user123/media",
        "https://example.com/status/123",
        "https://x.com/user/",
    ])
    def test_no_match_invalid(self, url):
        assert not X_STATUS_URL_PATTERN.search(url)


class TestXMediaPagePattern:
    @pytest.mark.parametrize("url", [
        "https://twitter.com/user123/media",
        "https://x.com/user_abc/media",
        "http://twitter.com/ABC/media",
    ])
    def test_matches_valid(self, url):
        assert X_MEDIA_PAGE_PATTERN.search(url)

    @pytest.mark.parametrize("url", [
        "https://twitter.com/user123/status/123",
        "https://x.com/user/likes",  # /media ではなく別ページ
    ])
    def test_no_match_invalid(self, url):
        assert not X_MEDIA_PAGE_PATTERN.search(url)


class TestPixivUrlPattern:
    @pytest.mark.parametrize("url", [
        "https://www.pixiv.net/artworks/12345678",
        "https://pixiv.net/artworks/12345678",
        "https://www.pixiv.net/en/artworks/98765432",
    ])
    def test_matches_valid(self, url):
        assert PIXIV_URL_PATTERN.search(url)

    @pytest.mark.parametrize("url", [
        "https://pixiv.net/users/12345",
        "https://example.com/artworks/123",
    ])
    def test_no_match_invalid(self, url):
        assert not PIXIV_URL_PATTERN.search(url)


class TestImgurUrlPattern:
    @pytest.mark.parametrize("url", [
        "https://imgur.com/a/abcd123",
        "https://i.imgur.com/abcdef.jpg",
        "https://imgur.com/gallery/xyz",
    ])
    def test_matches_valid(self, url):
        assert IMGUR_URL_PATTERN.search(url)

    @pytest.mark.parametrize("url", [
        "https://example.com/imgur/abc",
    ])
    def test_no_match_invalid(self, url):
        assert not IMGUR_URL_PATTERN.search(url)


class TestApiUrlPattern:
    @pytest.mark.parametrize("url", [
        "https://twitter.com/user/status/1234567890",
        "https://x.com/user/media",
        "https://www.pixiv.net/artworks/12345678",
        "https://imgur.com/a/abc123",
        "https://i.imgur.com/test.png",
    ])
    def test_matches_supported(self, url):
        assert API_URL_PATTERN.search(url)

    @pytest.mark.parametrize("url", [
        "https://example.com/",
        "",
    ])
    def test_no_match_unsupported(self, url):
        assert not API_URL_PATTERN.search(url)


class TestTweetIdFromUrl:
    def test_extracts_id(self):
        url = "https://twitter.com/user/status/1234567890123456789"
        m = TWEET_ID_FROM_URL.search(url)
        assert m
        assert m.group(1) == "1234567890123456789"

    def test_no_match_media_url(self):
        assert not TWEET_ID_FROM_URL.search("https://x.com/user/media")


class TestTweetIdFromFilename:
    @pytest.mark.parametrize("filename, expected_id", [
        ("AIUnajyu-1234567890123-01.jpg", "1234567890123"),
        ("user_name-9876543210987654321-02.png", "9876543210987654321"),
        ("SomeAuthor-1111111111111-10.mp4", "1111111111111"),
    ])
    def test_extracts_id(self, filename, expected_id):
        m = TWEET_ID_FROM_FILENAME.search(filename)
        assert m
        assert m.group(1) == expected_id

    def test_no_match_no_tweet_id(self):
        assert not TWEET_ID_FROM_FILENAME.search("plain_image.jpg")


class TestTweetIdRe:
    @pytest.mark.parametrize("tweet_id", [
        "1234567890",        # 10桁
        "12345678901234567890",  # 20桁
        "1766123456789012345",   # 19桁 (現代的)
    ])
    def test_valid_ids(self, tweet_id):
        assert TWEET_ID_RE.match(tweet_id)

    @pytest.mark.parametrize("tweet_id", [
        "123456789",         # 9桁 (短すぎ)
        "123456789012345678901",  # 21桁 (長すぎ)
        "123abc456",         # 英数字混在
        "",
    ])
    def test_invalid_ids(self, tweet_id):
        assert not TWEET_ID_RE.match(tweet_id)


class TestYtDlpUrlPattern:
    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/abcde12345A",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.tiktok.com/@user/video/1234567890123456789",
        "https://www.tiktok.com/t/ZTRaBcDeF",
        "https://www.nicovideo.jp/watch/sm12345678",
    ])
    def test_matches_valid(self, url):
        assert YT_DLP_URL_PATTERN.search(url)

    @pytest.mark.parametrize("url", [
        "https://twitter.com/user/status/123",
        "https://example.com/video/123",
        "https://vimeo.com/123456789",
    ])
    def test_not_match_invalid(self, url):
        assert not YT_DLP_URL_PATTERN.search(url)
