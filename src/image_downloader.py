"""
メディアダウンローダーモジュール。
gallery-dl を subprocess で呼び出して画像・動画・音声を保存する。
Twitter API キーは不要。
"""

import logging
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from .log_store import LogStore
from .models import DownloadResult, SavedFile

logger = logging.getLogger(__name__)

# gallery-dl 失敗時のリトライ回数
_MAX_RETRIES = 3

# gallery-dl のタイムアウト (秒)
_DOWNLOAD_TIMEOUT = 300

# ユーザーメディアページのタイムアウト (秒) — ファイル数が膨大になりうるため長めに設定
_USER_MEDIA_TIMEOUT = 7200

# Twitter 用ファイル名テンプレート
# 例: AIUnajyu-2022329732306772314-01.jpg
_TWITTER_FILENAME_TEMPLATE = "{author[name]}-{tweet_id}-{num:02d}.{extension}"

# ファイル名から tweet_id を抽出するパターン (10〜20桁: 2010年代以降のツイートに対応)
_TWEET_ID_FROM_URL = re.compile(r"/status/(\d+)")
_TWEET_ID_FROM_FILENAME = re.compile(r"-(\d{10,20})-\d{2}\.\w+$")


class MediaDownloader:
    """gallery-dl を使って画像・動画・音声をダウンロードするクラス。

    X/Twitter と Pixiv に対応。ファイル名生成・最高解像度選択・リトライは gallery-dl に任せる。
    """

    def __init__(
        self,
        save_root: str,
        cookies_file: str | None,
        pixiv_refresh_token: str | None = None,
        log_store: LogStore | None = None,
    ) -> None:
        """初期化する。

        Args:
            save_root: メディア保存先のルートディレクトリパス。
                       日付ごとにサブフォルダ (YYYY-MM-DD) が自動作成される。
            cookies_file: gallery-dl に渡す Cookie ファイルパス。
                          不要なら None。
            pixiv_refresh_token: Pixiv OAuth リフレッシュトークン。不要なら None。
            log_store: ダウンロード済み tweet ID の参照・記録に使う LogStore。
                       None の場合は重複チェックを行わない。

        Raises:
            RuntimeError: 保存先ディレクトリの作成に失敗した場合。
        """
        self._save_root = Path(save_root)
        self._cookies_file = cookies_file
        self._pixiv_refresh_token = pixiv_refresh_token
        self._log_store = log_store
        logger.info(
            "MediaDownloader を初期化しました: save_root=%s", save_root
        )

    def download_all(self, tweet_urls: list[str]) -> DownloadResult:
        """ツイート URL リストを全てダウンロードして保存する。

        既にダウンロード済みの tweet ID は自動的にスキップする。
        スキップされた URL 数は DownloadResult.skipped_count で返す。

        Args:
            tweet_urls: ダウンロード対象のツイート URL リスト。

        Returns:
            DownloadResult: 新規保存ファイルのリストとスキップ件数。

        Raises:
            RuntimeError: 保存先ディレクトリの作成に失敗した場合。
        """
        today = date.today()
        dest_dir = self._save_root / today.isoformat()
        _ensure_directory(dest_dir)

        # 重複ダウンロード防止: 既ダウンロード済み tweet ID をスキップ
        downloaded_ids = (
            self._log_store.get_downloaded_ids() if self._log_store else frozenset()
        )
        pending: list[str] = []
        for url in tweet_urls:
            tid = _tweet_id_from_url(url)
            if tid and tid in downloaded_ids:
                logger.info("重複のためスキップ (ダウンロード済み): tweet_id=%s", tid)
            else:
                pending.append(url)

        skipped_count = len(tweet_urls) - len(pending)

        saved: list[SavedFile] = []
        existed_count = 0
        for url in pending:
            new_files, rc_ok = self._download_one(url, dest_dir, _TWITTER_FILENAME_TEMPLATE)
            tid = _tweet_id_from_url(url)
            for path in new_files:
                saved.append(
                    SavedFile(
                        source_url=url,
                        saved_path=str(path),
                        date_folder=today,
                    )
                )
            if tid and self._log_store:
                if new_files:
                    self._log_store.mark_downloaded([tid])
                elif rc_ok:
                    # gallery-dl 成功だがファイルが既存 → 次回スキップされるよう mark する
                    self._log_store.mark_downloaded([tid])
                    existed_count += 1
                    logger.info(
                        "既存ファイルのためスキップ (mark_downloaded): tweet_id=%s", tid
                    )

        logger.info(
            "ダウンロード完了: 対象=%d, 重複スキップ=%d, 既存=%d, 保存ファイル数=%d",
            len(tweet_urls),
            skipped_count,
            existed_count,
            len(saved),
        )
        return DownloadResult(saved=saved, skipped_count=skipped_count, existed_count=existed_count)

    def download_direct(self, urls: list[str]) -> list[SavedFile]:
        """Pixiv など Twitter 以外の URL を直接ダウンロードする。

        gallery-dl のデフォルトファイル名を使用する。

        Args:
            urls: ダウンロード対象の URL リスト。

        Returns:
            保存に成功した SavedFile のリスト。
        """
        today = date.today()
        dest_dir = self._save_root / today.isoformat()
        _ensure_directory(dest_dir)

        saved: list[SavedFile] = []
        for url in urls:
            new_files = self._download_one(url, dest_dir, filename_template=None)
            for path in new_files:
                saved.append(
                    SavedFile(
                        source_url=url,
                        saved_path=str(path),
                        date_folder=today,
                    )
                )

        logger.info(
            "ダウンロード完了: 動作対象URL数=%d, 保存ファイル数=%d",
            len(urls),
            len(saved),
        )
        return saved

    def download_user_media(self, url: str) -> list[SavedFile]:
        """X ユーザーのメディアタブ URL から全メディアをダウンロードする。

        例: https://x.com/user/media

        gallery-dl に URL をそのまま渡してダウンロードする。
        LogStore に記録済みの tweet ID は --filter で除外して重複を防ぐ。

        Args:
            url: ユーザーメディアタブの URL (例: https://x.com/user/media)。

        Returns:
            保存に成功した SavedFile のリスト。
        """
        today = date.today()
        dest_dir = self._save_root / today.isoformat()
        _ensure_directory(dest_dir)

        downloaded_ids = (
            self._log_store.get_downloaded_ids() if self._log_store else frozenset()
        )
        new_files = self._download_media_page(url, dest_dir, downloaded_ids)

        saved: list[SavedFile] = []
        new_tweet_ids: list[str] = []
        for path in new_files:
            saved.append(SavedFile(source_url=url, saved_path=str(path), date_folder=today))
            tid = _tweet_id_from_filename(path.name)
            if tid:
                new_tweet_ids.append(tid)

        if new_tweet_ids and self._log_store:
            self._log_store.mark_downloaded(new_tweet_ids)

        logger.info(
            "ユーザーメディアダウンロード完了: url=%s, 保存ファイル数=%d",
            url,
            len(saved),
        )
        return saved

    # ── private ─────────────────────────────────────────────────────────────────────

    def _download_one(
        self, url: str, dest_dir: Path, filename_template: str | None
    ) -> tuple[list[Path], bool]:
        """単一ツイートの全メディアを gallery-dl でダウンロードする。

        ディレクトリ差分により新規保存ファイルを特定する。

        Args:
            url: ダウンロード対象のツイート URL。
            dest_dir: 保存先ディレクトリ。
            filename_template: gallery-dl のファイル名テンプレート。

        Returns:
            (新規保存ファイルの Path リスト, gallery-dl が正常終了したか)。
            正常終了 = returncode 0 (ダウンロード済) または 1 (対象ファイルなし)。
            ファイルが既存のために new_files が空でも rc_ok=True の場合がある。
        """
        files_before: set[Path] = set(dest_dir.iterdir())

        cmd = [
            "gallery-dl",
            # -D: サブディレクトリを作らず指定ディレクトリに直接保存
            "-D", str(dest_dir),
        ]
        if filename_template:
            cmd += ["-o", f"filename={filename_template}"]
        cmd.append(url)
        if self._cookies_file:
            cmd += ["--cookies", self._cookies_file]
            # cookies あり = ログイン済み → conversations=true でスレッド全体を一括取得する
            cmd += ["--option", "extractor.twitter.conversations=true"]
        if self._pixiv_refresh_token:
            cmd += ["-o", f"extractor.pixiv.refresh-token={self._pixiv_refresh_token}"]

        logger.info("gallery-dl ダウンロード開始: url=%s", url)

        last_returncode = 0
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_DOWNLOAD_TIMEOUT,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"gallery-dl がタイムアウトしました ({_DOWNLOAD_TIMEOUT}s): url={url}"
                ) from exc

            last_returncode = result.returncode
            # returncode=0: 成功, returncode=1: 画像なし (正常系)
            if result.returncode in (0, 1):
                break

            if attempt < _MAX_RETRIES:
                logger.warning(
                    "gallery-dl 失敗 (%d/%d 回目): url=%s, stderr=%s",
                    attempt,
                    _MAX_RETRIES,
                    url,
                    result.stderr.strip(),
                )
            else:
                logger.error(
                    "gallery-dl がリトライ上限に達しました: url=%s, returncode=%d, stderr=%s",
                    url,
                    last_returncode,
                    result.stderr.strip(),
                )

        if result.stderr.strip():
            logger.debug("gallery-dl stderr: %s", result.stderr.strip())

        files_after: set[Path] = set(dest_dir.iterdir())
        new_files = sorted(files_after - files_before)
        rc_ok = last_returncode in (0, 1)
        logger.info(
            "新規保存ファイル数=%d rc_ok=%s: url=%s", len(new_files), rc_ok, url
        )
        return new_files, rc_ok

    def _download_media_page(
        self,
        url: str,
        dest_dir: Path,
        downloaded_ids: frozenset[str],
    ) -> list[Path]:
        """ユーザーメディアページを gallery-dl でダウンロードする。

        downloaded_ids が空でない場合はテンポラリファイルを使った --filter で
        既ダウンロード済み tweet をスキップする。

        Args:
            url: ユーザーメディアタブの URL。
            dest_dir: 保存先ディレクトリ。
            downloaded_ids: スキップする tweet ID のセット。

        Returns:
            新規保存されたファイルの Path リスト。
        """
        files_before: set[Path] = set(dest_dir.iterdir())

        cmd = [
            "gallery-dl",
            "-D", str(dest_dir),
            "-o", f"filename={_TWITTER_FILENAME_TEMPLATE}",
        ]
        if self._cookies_file:
            cmd += ["--cookies", self._cookies_file]

        ids_path: str | None = None
        if downloaded_ids:
            fd, ids_path = tempfile.mkstemp(suffix=".txt")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(downloaded_ids))
            except Exception:
                os.close(fd)
                raise
            filter_expr = (
                f"str(tweet_id) not in "
                f"open({repr(ids_path)}, encoding='utf-8').read().splitlines()"
            )
            cmd += ["--filter", filter_expr]

        cmd.append(url)
        logger.info("gallery-dl ユーザーメディアダウンロード開始: url=%s, スキップ対象=%d 件", url, len(downloaded_ids))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_USER_MEDIA_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"gallery-dl がタイムアウトしました ({_USER_MEDIA_TIMEOUT}s): url={url}"
            ) from exc
        finally:
            if ids_path and os.path.exists(ids_path):
                os.unlink(ids_path)

        if result.returncode not in (0, 1):
            logger.error(
                "gallery-dl エラー: url=%s, returncode=%d, stderr=%s",
                url,
                result.returncode,
                result.stderr.strip(),
            )
        if result.stderr.strip():
            logger.debug("gallery-dl stderr: %s", result.stderr.strip())

        files_after: set[Path] = set(dest_dir.iterdir())
        new_files = sorted(files_after - files_before)
        logger.info("新規保存ファイル数=%d: url=%s", len(new_files), url)
        return new_files


# ── module-level helpers ──────────────────────────────────────────────────────


def _tweet_id_from_url(url: str) -> str | None:
    """ツイート URL から tweet_id を抽出する。見つからなければ None を返す。"""
    m = _TWEET_ID_FROM_URL.search(url)
    return m.group(1) if m else None


def _tweet_id_from_filename(filename: str) -> str | None:
    """ファイル名から tweet_id を抽出する。

    ファイル名テンプレート ``{author}-{tweet_id}-{num:02d}.{ext}`` を前提とし、
    10〜20桁の数字を tweet_id として返す。
    """
    m = _TWEET_ID_FROM_FILENAME.search(filename)
    return m.group(1) if m else None


def _ensure_directory(path: Path) -> None:
    """ディレクトリが存在しなければ作成する。

    Args:
        path: 作成するディレクトリパス。

    Raises:
        RuntimeError: 作成に失敗した場合。
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"ディレクトリの作成に失敗しました: path={path}, error={exc}"
        ) from exc
