"""
アプリアイコン (assets/icon.png) を生成するスクリプト。

使い方:
    pip install Pillow
    python make_icon.py

生成後:
    dart run flutter_launcher_icons
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw


def _make_icon(size: int) -> Image.Image:
    """x-keeper アイコンを生成する。

    デザイン:
    - 背景: 濃紺 (#0f172a)
    - 外枠: 角丸の青グラデーション
    - 中央: ダウンロード矢印 (白)
    - 下部: 水平線 (白)
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = size * 0.08
    r = size * 0.22  # 角丸半径

    # 背景の角丸四角形 (濃紺)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=r,
        fill="#0f172a",
    )

    # 青いリング (縁取り)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=r,
        outline="#1d9bf0",
        width=max(2, size // 32),
    )

    # ── ダウンロード矢印を描画 ───────────────────────────────────────────────
    cx = size / 2
    top = size * 0.18
    stem_bottom = size * 0.58
    arrow_y = size * 0.68
    bar_y = size * 0.80
    bar_half = size * 0.28
    lw = max(3, size // 18)
    arrow_half = size * 0.22

    # 縦線 (矢印の軸)
    draw.line([(cx, top), (cx, stem_bottom)], fill="white", width=lw)

    # 矢印の左斜め線
    draw.line([(cx, arrow_y), (cx - arrow_half, stem_bottom - size * 0.01)], fill="white", width=lw)
    # 矢印の右斜め線
    draw.line([(cx, arrow_y), (cx + arrow_half, stem_bottom - size * 0.01)], fill="white", width=lw)

    # 水平バー (ダウンロード先を示す)
    draw.line([(cx - bar_half, bar_y), (cx + bar_half, bar_y)], fill="white", width=lw)

    return img


def main() -> None:
    assets_dir = Path(__file__).parent / "assets"
    assets_dir.mkdir(exist_ok=True)

    icon_path = assets_dir / "icon.png"
    icon_fg_path = assets_dir / "icon_foreground.png"

    # 通常アイコン (1024x1024)
    img = _make_icon(1024)
    img.save(icon_path, "PNG")
    print(f"生成: {icon_path}")

    # アダプティブアイコン用フォアグラウンド (透明背景、108dp = 432px 相当)
    fg = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(fg)
    cx, size = 512, 1024

    top = size * 0.20
    stem_bottom = size * 0.58
    arrow_y = size * 0.68
    bar_y = size * 0.80
    bar_half = size * 0.28
    arrow_half = size * 0.22
    lw = 52

    draw.line([(cx, top), (cx, stem_bottom)], fill="white", width=lw)
    draw.line([(cx, arrow_y), (cx - arrow_half, stem_bottom)], fill="white", width=lw)
    draw.line([(cx, arrow_y), (cx + arrow_half, stem_bottom)], fill="white", width=lw)
    draw.line([(cx - bar_half, bar_y), (cx + bar_half, bar_y)], fill="white", width=lw)

    fg.save(icon_fg_path, "PNG")
    print(f"生成: {icon_fg_path}")
    print("\n次のコマンドでアイコンを適用してください:")
    print("  dart run flutter_launcher_icons")


if __name__ == "__main__":
    main()
