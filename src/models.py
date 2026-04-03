"""
ドメインモデル定義。
各クライアントやダウンローダー間でやり取りするデータ構造を定義する。
"""

from dataclasses import dataclass, field
from datetime import date


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

    existed_count: int = 0
    """gallery-dl が成功 (rc=0) したがファイルが既存だった URL 数。
    ダウンロード済みとしてマーク済みなので次回以降は skipped_count に計上される。"""
