"""
ドメインモデル定義。
各クライアントやダウンローダー間でやり取りするデータ構造を定義する。
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class TweetThread:
    """1つのスレッド (会話) に含まれる全ツイートの情報をまとめたもの。"""

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
class DownloadResult:
    """download_all の処理結果。saved と skipped_count を分離して返す。"""

    saved: list[SavedFile]
    """新規保存されたファイルのリスト。"""

    skipped_count: int
    """重複のためスキップされたツイート URL 数 (既ダウンロード済み)。"""
