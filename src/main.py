"""
エントリーポイント。
Google Keep をポーリングして X (Twitter) の画像を保存するメインループ。
"""

import logging
import sys
import time

from .config import Settings
from .image_downloader import ImageDownloader
from .keep_client import KeepClient
from .models import ProcessResult
from .twitter_client import TwitterClient


def _reconfigure_stdout_encoding() -> None:
    """stdout / stderr の文字コードを UTF-8 に強制する。

    Windows のデフォルトコンソールエンコーディング (cp932) では日本語ログが
    文字化けするため、エントリーポイントの先頭で呼び出す。
    Docker コンテナでは PYTHONUTF8=1 が設定されるので実質的なノーオペレーション。
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _setup_logging(level: str) -> None:
    """ルートロガーを設定する。

    Args:
        level: ログレベル文字列 (例: "INFO", "DEBUG")。

    Raises:
        ValueError: 無効なログレベル文字列が指定された場合。
    """
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"無効なログレベルです: {level}")

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def process_note(
    note,
    urls: list[str],
    twitter: TwitterClient,
    downloader: ImageDownloader,
    keep: KeepClient,
) -> ProcessResult:
    """1件の Keep ノートを処理する。

    URL ごとにスレッドを取得 → 画像をダウンロード → ノートを削除する。
    いずれかのステップで失敗した場合はエラーを記録して処理を継続する。
    全 URL の画像保存が成功した場合のみ Keep ノートを削除する。

    Args:
        note: 処理対象の gkeepapi ノートオブジェクト。
        urls: ノートから検出された X (Twitter) URL リスト。
        twitter: Twitter クライアント。
        downloader: 画像ダウンローダー。
        keep: Google Keep クライアント。

    Returns:
        処理結果をまとめた ProcessResult。
    """
    logger = logging.getLogger(__name__)
    result = ProcessResult(note_id=note.id, tweet_urls=urls)

    for url in urls:
        try:
            thread = twitter.get_thread(url)
        except (ValueError, RuntimeError) as exc:
            result.errors.append(f"スレッド取得失敗: url={url}, error={exc}")
            logger.error("スレッド取得に失敗しました: url=%s, error=%s", url, exc)
            continue

        if not thread.tweet_urls:
            logger.info("処理対象のツイートが見つかりませんでした: url=%s", url)
            continue

        saved = downloader.download_all(thread.tweet_urls)
        result.saved_images.extend(saved)

        if not saved:
            result.errors.append(f"画像を保存できませんでした: url={url}")

    # エラーなしに全画像を保存できた場合のみ Keep ノートを削除する
    if result.success:
        try:
            keep.delete_note(note)
        except Exception as exc:
            result.errors.append(f"Keep ノートの削除に失敗しました: error={exc}")
            logger.error(
                "Keep ノートの削除に失敗しました: note_id=%s, error=%s", note.id, exc
            )
    else:
        logger.warning(
            "エラーがあるためノートを削除しませんでした: note_id=%s, errors=%s",
            note.id,
            result.errors,
        )

    return result


def run_once(
    keep: KeepClient,
    twitter: TwitterClient,
    downloader: ImageDownloader,
) -> list[ProcessResult]:
    """Keep を1回同期して、対象ノートを全て処理する。

    Args:
        keep: Google Keep クライアント。
        twitter: Twitter クライアント。
        downloader: 画像ダウンローダー。

    Returns:
        処理したノートの ProcessResult リスト。
    """
    logger = logging.getLogger(__name__)
    keep.sync()

    results: list[ProcessResult] = []
    for note, urls in keep.iter_notes_with_twitter_urls():
        logger.info("ノートを処理します: note_id=%s, url_count=%d", note.id, len(urls))
        result = process_note(note, urls, twitter, downloader, keep)
        results.append(result)
        logger.info(
            "ノート処理完了: note_id=%s, 保存画像数=%d, エラー数=%d",
            result.note_id,
            len(result.saved_images),
            len(result.errors),
        )

    return results


_REQUIRED_SETTINGS_CHECK_INTERVAL = 30
"""必須設定が揃っているか確認する間隔 (秒)。"""

_REQUIRED_SETTING_KEYS = [
    "GOOGLE_EMAIL",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
]


def _missing_settings(settings: Settings) -> list[str]:
    """未設定の必須項目名リストを返す。全て設定済みなら空リスト。"""
    return [
        name
        for name, value in zip(
            _REQUIRED_SETTING_KEYS,
            [
                settings.google_email,
                settings.google_oauth_client_id,
                settings.google_oauth_client_secret,
                settings.google_oauth_refresh_token,
            ],
        )
        if not value
    ]


def _wait_for_required_settings(settings: Settings, logger: logging.Logger) -> Settings:
    """必須設定が揃うまで .env を再読み込みしながら待機する。

    リフレッシュトークン等の認証情報が未設定の場合、コンテナを落とさずに
    30 秒ごとに .env を再チェックする。セットアップサービス経由で
    .env が更新されたタイミングで自動的に次のステップへ進む。

    Args:
        settings: 起動時に読み込んだ Settings インスタンス。
        logger: ロガー。

    Returns:
        必須設定が揃った Settings インスタンス。
    """
    missing = _missing_settings(settings)
    if not missing:
        return settings

    logger.warning(
        "必須の設定が未設定のため待機します: %s — "
        "ブラウザで http://localhost:8080 を開いてセットアップを完了してください "
        "(起動コマンド: docker compose --profile setup up setup)",
        ", ".join(missing),
    )
    while True:
        time.sleep(_REQUIRED_SETTINGS_CHECK_INTERVAL)
        settings = Settings()  # type: ignore[call-arg]
        missing = _missing_settings(settings)
        if not missing:
            logger.info("必須設定が揃いました。起動を続行します。")
            return settings
        logger.warning(
            "まだ未設定の項目があります: %s — 引き続き待機中 (次回確認まで %d 秒)",
            ", ".join(missing),
            _REQUIRED_SETTINGS_CHECK_INTERVAL,
        )


def main() -> None:
    """アプリケーションのエントリーポイント。設定を読み込んでポーリングループを開始する。

    Raises:
        RuntimeError: 初期化に失敗した場合 (ログ出力後にプロセスを終了する)。
    """
    # ログ設定より先に実行して、全ログ出力を UTF-8 にする
    _reconfigure_stdout_encoding()

    settings = Settings()  # type: ignore[call-arg]
    _setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("keep-image-saver を起動します")

    logger.info(
        "設定: poll_interval=%ds, save_path=%s",
        settings.poll_interval_seconds,
        settings.save_path,
    )

    # 必須設定が揃うまで待機する (未設定の場合はコンテナを落とさず待機)
    settings = _wait_for_required_settings(settings, logger)

    # クライアントの初期化 (認証情報が間違っている場合は .env 更新を待ってリトライ)
    while True:
        try:
            keep = KeepClient(
                settings.google_email,  # type: ignore[arg-type]
                settings.google_oauth_client_id,  # type: ignore[arg-type]
                settings.google_oauth_client_secret,  # type: ignore[arg-type]
                settings.google_oauth_refresh_token,  # type: ignore[arg-type]
            )
            twitter = TwitterClient(settings.gallery_dl_cookies_file)
            downloader = ImageDownloader(settings.save_path, settings.gallery_dl_cookies_file)
            break
        except RuntimeError as exc:
            logger.critical(
                "初期化に失敗しました: %s — "
                "認証情報が間違っている可能性があります。"
                "セットアップ画面 (http://localhost:8080) で修正してください。"
                "(起動: docker compose --profile setup up setup) "
                "%d 秒後に再試行します。",
                exc,
                _REQUIRED_SETTINGS_CHECK_INTERVAL,
            )
            time.sleep(_REQUIRED_SETTINGS_CHECK_INTERVAL)
            settings = Settings()  # type: ignore[call-arg]  # .env を再読み込み

    logger.info(
        "ポーリングループを開始します (間隔: %d 秒)", settings.poll_interval_seconds
    )

    while True:
        try:
            results = run_once(keep, twitter, downloader)
            if results:
                success_count = sum(1 for r in results if r.success)
                logger.info(
                    "処理サマリー: 合計=%d, 成功=%d, 失敗=%d",
                    len(results),
                    success_count,
                    len(results) - success_count,
                )
        except Exception as exc:
            # ポーリングループ自体は止めない。次回ポーリングで再試行する。
            logger.error("ポーリング中に予期しないエラーが発生しました: %s", exc, exc_info=True)

        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
