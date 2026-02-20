"""
X (Twitter) スレッド収集モジュール。
gallery-dl の JSON 出力を使って Twitter API キー不要でスレッドを遡り、
全ツイートの URL を収集する。
"""

import json
import logging
import re
import subprocess

from .models import TweetThread

logger = logging.getLogger(__name__)

# ツイート URL から tweet ID を抽出するパターン
_TWEET_URL_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/status/(\d+)"
)

# 1スレッドあたりの遡り上限 (無限ループ防止)
_MAX_THREAD_DEPTH = 50


class TwitterClient:
    """gallery-dl を使って Twitter のスレッドを遡り、全ツイート URL を収集するクライアント。

    Twitter API キーは不要。
    """

    def __init__(self, cookies_file: str | None) -> None:
        """初期化する。

        Args:
            cookies_file: gallery-dl に渡す Cookie ファイルのパス (Netscape 形式)。
                          非公開アカウントのツイートにアクセスする場合のみ指定する。
                          不要なら None を渡す。

        Raises:
            RuntimeError: gallery-dl が PATH 上に見つからない場合。
        """
        self._cookies_file = cookies_file
        _assert_gallery_dl_available()
        logger.info("TwitterClient を初期化しました (gallery-dl モード, cookies=%s)", cookies_file)

    def get_thread(self, tweet_url: str) -> TweetThread:
        """指定されたツイート URL を起点にスレッド全体の URL 一覧を収集する。

        gallery-dl の JSON メタデータ出力 (--dump-json) から reply_id フィールドを読み取り、
        親ツイートを再帰的に遡ることでスレッドを構築する。
        cookies なし環境では上方向 (親ツイート) への遡りのみ対応。

        Args:
            tweet_url: 起点となるツイートの URL。

        Returns:
            スレッド内の全ツイート URL を含む TweetThread。

        Raises:
            ValueError: URL から tweet ID を抽出できない場合。
        """
        conversation_id = _extract_tweet_id(tweet_url)
        visited: set[str] = set()
        tweet_urls: list[str] = []

        self._collect_thread_urls(tweet_url, visited, tweet_urls, depth=0)

        logger.info(
            "スレッド収集完了: conversation_id=%s, ツイート数=%d",
            conversation_id,
            len(tweet_urls),
        )
        return TweetThread(conversation_id=conversation_id, tweet_urls=tweet_urls)

    # ── private ─────────────────────────────────────────────────────────────────────

    def _collect_thread_urls(
        self,
        url: str,
        visited: set[str],
        tweet_urls: list[str],
        depth: int,
        author_filter: str | None = None,
    ) -> None:
        """指定された URL のツイートを収集し、reply_id を辿って親ツイートへ再帰する。

        depth=0 (起点ツイート) の著者を author_filter として記録し、
        異なる著者のツイートに到達した時点で遡りを止める。

        Args:
            url: 処理対象のツイート URL。
            visited: 処理済み tweet_id のセット (重複排除)。
            tweet_urls: URL を追記するリスト。
            depth: 現在の再帰深度。
            author_filter: 収集対象の著者名。None の場合は起点ツイートから取得する。
        """
        if depth >= _MAX_THREAD_DEPTH:
            logger.warning(
                "スレッド遡り上限 (%d) に達しました。途中で終了します。",
                _MAX_THREAD_DEPTH,
            )
            return

        tweet_id = _extract_tweet_id(url)
        if tweet_id in visited:
            return
        visited.add(tweet_id)

        reply_id, author_name = self._get_tweet_info(url)

        # 起点ツイートの著者を filter として確定する
        if author_filter is None:
            author_filter = author_name
            logger.debug("著者フィルターを設定: %s", author_filter)
        elif author_name and author_name != author_filter:
            logger.info(
                "別ユーザーのツイートをスキップ: tweet_id=%s, author=%s (filter=%s)",
                tweet_id, author_name, author_filter,
            )
        else:
            tweet_urls.append(url)
            logger.debug("ツイートを追加しました: tweet_id=%s (depth=%d)", tweet_id, depth)

        if reply_id is None:
            return

        # /i/status/{id} 形式は認証なしでもアクセス可能
        parent_url = f"https://x.com/i/status/{reply_id}"
        logger.debug(
            "親ツイートを発見しました: tweet_id=%s -> reply_to=%s", tweet_id, reply_id
        )
        self._collect_thread_urls(parent_url, visited, tweet_urls, depth + 1, author_filter)

    def _get_tweet_info(self, url: str) -> tuple[str | None, str | None]:
        """gallery-dl --dump-json で取得したメタデータから reply_id と author_name を返す。

        Args:
            url: メタデータを取得するツイートの URL。

        Returns:
            (reply_id, author_name) のタプル。取得できない場合は None。

        Raises:
            RuntimeError: gallery-dl の実行がタイムアウトした場合。
        """
        cmd = ["gallery-dl", "--dump-json", url]
        if self._cookies_file:
            cmd += ["--cookies", self._cookies_file]

        logger.debug("gallery-dl でメタデータを取得します: url=%s", url)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"gallery-dl がタイムアウトしました (30s): url={url}"
            ) from exc

        if result.returncode not in (0, 1):
            # returncode=1 は "no images found" の正常系なので無視する
            logger.warning(
                "gallery-dl が予期しない終了コードを返しました: code=%d, stderr=%s",
                result.returncode,
                result.stderr.strip(),
            )

        return _parse_tweet_info(result.stdout)


# ── module-level helpers ──────────────────────────────────────────────────────


def _assert_gallery_dl_available() -> None:
    """gallery-dl が PATH 上に存在することを確認する。

    Raises:
        RuntimeError: gallery-dl が見つからない場合。
    """
    result = subprocess.run(
        ["gallery-dl", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "gallery-dl が見つかりません。pip install gallery-dl を実行してください。"
        )
    logger.debug("gallery-dl バージョン確認: %s", result.stdout.strip())


def _extract_tweet_id(url: str) -> str:
    """URL から tweet ID (数字列) を取り出す。

    twitter.com/user/status/ID 形式と x.com/i/status/ID 形式の両方に対応する。

    Args:
        url: ツイートの URL。

    Returns:
        tweet ID の文字列。

    Raises:
        ValueError: URL から tweet ID を抽出できない場合。
    """
    m = _TWEET_URL_PATTERN.search(url)
    if m is not None:
        return m.group(1)

    # /i/status/{id} 形式 (親ツイート参照用 URL) にも対応
    m2 = re.search(r"/status/(\d+)", url)
    if m2 is not None:
        return m2.group(1)

    raise ValueError(f"URL から tweet ID を抽出できませんでした: url={url}")


def _parse_tweet_info(stdout: str) -> tuple[str | None, str | None]:
    """gallery-dl の --dump-json 出力から reply_id と author_name を返す。

    gallery-dl の JSON 行フォーマット: [msg_type, url_or_zero, metadata_dict]
    - msg_type=1: バージョン情報 (無視)
    - msg_type=2: ダウンロード対象アイテム → metadata_dict にフィールドが含まれる
    - msg_type=4: エラー (無視)

    Args:
        stdout: gallery-dl の標準出力。

    Returns:
        (reply_id, author_name) のタプル。取得できない場合は None。
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # [msg_type, url_or_zero, {metadata}] の形式を想定
        metadata: dict | None = None
        if isinstance(data, list) and len(data) >= 3 and isinstance(data[2], dict):
            metadata = data[2]
        elif isinstance(data, dict):
            # 将来の gallery-dl バージョンで形式が変わった場合のフォールバック
            metadata = data

        if metadata is None:
            continue

        # author_name を取得
        author_name: str | None = None
        author = metadata.get("author")
        if isinstance(author, dict):
            author_name = author.get("name")

        # reply_id はツイートID整数 (0 = ルートツイート、非0 = 親ツイートのID)
        # reply_to はリプライ先のユーザー名 (文字列) なので使用しないこと
        reply_id: str | None = None
        reply_id_val = metadata.get("reply_id")
        if reply_id_val is not None and int(reply_id_val) != 0:
            reply_id = str(reply_id_val)

        # author_name が取得できたエントリで確定
        if author_name is not None:
            return reply_id, author_name

    return None, None
