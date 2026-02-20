"""
ドメインモデル定義。
各クライアントやダウンローダー間でやり取りするデータ構造を定義する。
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class TweetThread:
    """1つのスレッド (会話) に含まれる全ツイートの情報をまとめたもの。

    gallery-dl でダウンロードするため、tweet URL のリストだけを保持する。
    """

    conversation_id: str
    """スレッドの起点となる会話 ID (起点ツイートの tweet_id)。"""

    tweet_urls: list[str] = field(default_factory=list)
    """スレッド内で検出した全ツイートの URL 一覧。"""


@dataclass
class SavedFile:
    """1ファイルの保存結果を表す。"""

    source_url: str
    """ダウンロード元 URL。"""

    saved_path: str
    """保存先の絶対パス。"""

    date_folder: date
    """保存されたサブフォルダの日付。"""


@dataclass
class ProcessResult:
    """1件の Keep ノートを処理した結果をまとめたもの。"""

    note_id: str
    """処理した Keep ノートの ID。"""

    tweet_urls: list[str]
    """ノート内で検出された X (Twitter) URL 一覧。"""

    saved_files: list[SavedFile] = field(default_factory=list)
    """実際に保存されたファイル一覧。"""

    errors: list[str] = field(default_factory=list)
    """処理中に発生したエラーメッセージ一覧。"""

    @property
    def success(self) -> bool:
        """エラーなしに全ファイルを保存できた場合 True。"""
        return len(self.errors) == 0 and len(self.saved_files) > 0
