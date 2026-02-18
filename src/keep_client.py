"""
Google Keep クライアントモジュール。
ノートの取得・X (Twitter) URL の検出・処理済みノートの削除を担う。
"""

import logging
import re
from collections.abc import Generator
from uuid import getnode

import gkeepapi
import google.oauth2.credentials
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# Google Keep API と Reminders API に必要な OAuth2 スコープ
_KEEP_SCOPES = (
    "https://www.googleapis.com/auth/memento",
    "https://www.googleapis.com/auth/reminders",
)


class _OAuth2Auth(gkeepapi.APIAuth):
    """google-auth の Credentials を gkeepapi に注入するアダプタ。

    gpsoauth の Android デバイス認証 (perform_master_login) に依存せず、
    標準の OAuth2 ブラウザフローで取得したリフレッシュトークンを使って
    gkeepapi のアクセストークンを供給する。
    """

    def __init__(
        self,
        credentials: google.oauth2.credentials.Credentials,
        email: str,
    ) -> None:
        """認証アダプタを初期化してアクセストークンを取得する。

        Args:
            credentials: google-auth の Credentials オブジェクト (refresh_token 設定済みであること)。
            email: Google アカウントのメールアドレス。
        """
        # 親の __init__ に渡す scopes はオーバーライドで使われないためダミーでよい
        super().__init__(gkeepapi.Keep.OAUTH_SCOPES)
        self._credentials = credentials
        self._email = email
        # gkeepapi 内部と合わせて MAC アドレスの hex を device_id に使う
        self._device_id = f"{getnode():x}"
        # 初回アクセストークンを取得して注入する
        self._refresh_credentials()

    def _refresh_credentials(self) -> None:
        """google-auth でアクセストークンを更新し、_auth_token にセットする。"""
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        self._auth_token = self._credentials.token

    def refresh(self) -> str:
        """gkeepapi がトークン期限切れ時に呼ぶ refresh をオーバーライドする。

        Returns:
            新しいアクセストークン文字列。
        """
        self._refresh_credentials()
        return self._auth_token

# X (Twitter) の URL にマッチする正規表現。
# https://twitter.com/user/status/ID および https://x.com/user/status/ID 両方に対応。
TWITTER_URL_PATTERN = re.compile(
    r"https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/status/(\d+)"
)


class KeepClient:
    """Google Keep との通信を管理するクライアント。

    gkeepapi は非公式ライブラリであり、Google の仕様変更により
    動作しなくなる可能性がある点に注意。
    """

    def __init__(
        self,
        email: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        """初期化してログインを試みる。

        Args:
            email: Google アカウントのメールアドレス。
            client_id: Google OAuth2 クライアント ID。
            client_secret: Google OAuth2 クライアントシークレット。
            refresh_token: Google OAuth2 リフレッシュトークン。

        Raises:
            RuntimeError: ログインに失敗した場合。
        """
        self._keep = gkeepapi.Keep()
        logger.info("Google Keep へのログインを試みています: email=%s", email)
        credentials = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        try:
            auth = _OAuth2Auth(credentials, email)
            # sync=True で初回同期まで実行する
            self._keep.load(auth, state=None, sync=True)
        except Exception as exc:
            raise RuntimeError(f"Google Keep へのログインに失敗しました: {exc}") from exc

        logger.info("Google Keep へのログインに成功しました")

    def sync(self) -> None:
        """Keep を最新状態に同期する。ポーリング毎に呼び出す。"""
        self._keep.sync()
        logger.debug("Google Keep の同期が完了しました")

    def iter_notes_with_twitter_urls(
        self,
    ) -> Generator[tuple[gkeepapi.node.TopLevelNode, list[str]], None, None]:
        """X (Twitter) URL を1件以上含むノートを順番に返すジェネレーター。

        Yields:
            (note, urls): ノートオブジェクトと、そのノート内の Twitter URL リスト。
        """
        for note in self._keep.all():
            # 削除済みノートは対象外
            if note.trashed or note.archived:
                continue

            text = note.title + "\n" + (note.text if hasattr(note, "text") else "")
            urls = TWITTER_URL_PATTERN.findall(text)
            if not urls:
                continue

            # findall は tweet ID を返すので URL 形式に戻す
            full_urls = [
                _rebuild_url(m) for m in TWITTER_URL_PATTERN.finditer(text)
            ]
            logger.debug(
                "Twitter URL を含むノートを検出しました: note_id=%s, urls=%s",
                note.id,
                full_urls,
            )
            yield note, full_urls

    def delete_note(self, note: gkeepapi.node.TopLevelNode) -> None:
        """指定されたノートをゴミ箱に移動 (trashed) してサーバーに同期する。

        完全削除ではなく trashed 状態にすることで、誤操作に備えた復元ができる。

        Args:
            note: 削除対象のノートオブジェクト。
        """
        note.trash()
        self._keep.sync()
        logger.info("ノートをゴミ箱に移動しました: note_id=%s", note.id)


def _rebuild_url(match: re.Match) -> str:
    """正規表現マッチオブジェクトから元の URL を再構築する。"""
    return match.group(0)
