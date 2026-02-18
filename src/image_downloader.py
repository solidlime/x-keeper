"""
画像ダウンローダーモジュール。
gallery-dl を subprocess で呼び出して画像・動画を保存する。
Twitter API キーは不要。
"""

import logging
import subprocess
from datetime import date
from pathlib import Path

from .models import SavedImage

logger = logging.getLogger(__name__)

# gallery-dl 失敗時のリトライ回数
_MAX_RETRIES = 3

# gallery-dl のタイムアウト (秒)
_DOWNLOAD_TIMEOUT = 300


class ImageDownloader:
    """gallery-dl を使ってツイートの画像・動画をダウンロードするクラス。

    ファイル名生成・最高解像度選択・リトライは gallery-dl に任せる。
    """

    def __init__(self, save_root: str, cookies_file: str | None) -> None:
        """初期化する。

        Args:
            save_root: 画像保存先のルートディレクトリパス。
                       日付ごとにサブフォルダ (YYYY-MM-DD) が自動作成される。
            cookies_file: gallery-dl に渡す Cookie ファイルパス。
                          不要なら None。

        Raises:
            RuntimeError: 保存先ディレクトリの作成に失敗した場合。
        """
        self._save_root = Path(save_root)
        self._cookies_file = cookies_file
        logger.info(
            "ImageDownloader を初期化しました: save_root=%s", save_root
        )

    def download_all(self, tweet_urls: list[str]) -> list[SavedImage]:
        """ツイート URL リストを全てダウンロードして保存する。

        Args:
            tweet_urls: ダウンロード対象のツイート URL リスト。

        Returns:
            保存に成功した SavedImage のリスト。

        Raises:
            RuntimeError: 保存先ディレクトリの作成に失敗した場合。
        """
        today = date.today()
        dest_dir = self._save_root / today.isoformat()
        _ensure_directory(dest_dir)

        saved: list[SavedImage] = []
        for url in tweet_urls:
            new_files = self._download_one(url, dest_dir)
            for path in new_files:
                saved.append(
                    SavedImage(
                        source_url=url,
                        saved_path=str(path),
                        date_folder=today,
                    )
                )

        logger.info(
            "ダウンロード完了: 動作対象URL数=%d, 保存ファイル数=%d",
            len(tweet_urls),
            len(saved),
        )
        return saved

    # ── private ─────────────────────────────────────────────────────────────────────

    def _download_one(self, url: str, dest_dir: Path) -> list[Path]:
        """単一ツイートの全メディアを gallery-dl でダウンロードする。

        ディレクトリ半差分析により新規保存ファイルを特定する。

        Args:
            url: ダウンロード対象のツイート URL。
            dest_dir: 保存先ディレクトリ。

        Returns:
            新規保存されたファイルの Path リスト。
        """
        files_before: set[Path] = set(dest_dir.iterdir())

        cmd = [
            "gallery-dl",
            # -D: サブディレクトリを作らず指定ディレクトリに直接保存
            "-D", str(dest_dir),
            # ファイル名テンプレート: {ユーザーID}-{ツイートID}-{連番2桁}.{拡張子}
            # 例: AIUnajyu-2022329732306772314-01.jpg
            "-o", "filename={author[name]}-{tweet_id}-{num:02d}.{extension}",
            url,
        ]
        if self._cookies_file:
            cmd += ["--cookies", self._cookies_file]
            # cookies あり = ログイン済み → conversations=true でスレッド全体を一括取得する
            cmd += ["--option", "extractor.twitter.conversations=true"]

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

        files_after: set[Path] = set(dest_dir.iterdir())
        new_files = sorted(files_after - files_before)
        logger.info("新規保存ファイル数=%d: url=%s", len(new_files), url)
        return new_files


# ── module-level helpers ──────────────────────────────────────────────────────


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
