"""src/image_downloader.py の tweet_id 抽出ロジックテスト。"""

import pytest

from src.patterns import TWEET_ID_FROM_FILENAME, TWEET_ID_FROM_URL


class TestTweetIdFromUrlExtraction:
    """URL から tweet_id を正しく抽出できること。"""

    @pytest.mark.parametrize("url, expected", [
        ("https://twitter.com/user/status/1234567890123456789", "1234567890123456789"),
        ("https://x.com/user/status/9999999999", "9999999999"),
        ("https://twitter.com/user/status/1000000000/photo/1", "1000000000"),
    ])
    def test_extract_from_valid_urls(self, url, expected):
        m = TWEET_ID_FROM_URL.search(url)
        assert m is not None
        assert m.group(1) == expected

    def test_no_match_for_media_url(self):
        url = "https://x.com/user/media"
        assert TWEET_ID_FROM_URL.search(url) is None

    def test_no_match_for_non_twitter(self):
        url = "https://pixiv.net/artworks/12345"
        assert TWEET_ID_FROM_URL.search(url) is None


class TestTweetIdFromFilenameExtraction:
    """ファイル名パターン {name}-{tweet_id}-{num}.{ext} から tweet_id を抽出できること。"""

    @pytest.mark.parametrize("filename, expected_id", [
        ("AIUnajyu-1234567890123-01.jpg", "1234567890123"),
        ("user_name-9876543210987654321-02.png", "9876543210987654321"),
        ("SomeAuthor-1111111111111-10.mp4", "1111111111111"),
        ("author123-1000000000-01.jpeg", "1000000000"),
    ])
    def test_extract_from_valid_filenames(self, filename, expected_id):
        m = TWEET_ID_FROM_FILENAME.search(filename)
        assert m is not None
        assert m.group(1) == expected_id

    @pytest.mark.parametrize("filename", [
        "plain_image.jpg",
        "nopattern.png",
        "short-123-01.jpg",  # tweet_id が 9桁以下は無視 (10桁未満)
    ])
    def test_no_match_for_invalid_filenames(self, filename):
        assert TWEET_ID_FROM_FILENAME.search(filename) is None
