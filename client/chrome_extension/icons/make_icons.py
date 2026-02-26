"""
Chrome 拡張用アイコン (16x16, 48x48, 128x128) を生成する。

使い方:
    pip install Pillow
    python icons/make_icons.py
"""

from pathlib import Path
from PIL import Image, ImageDraw


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景: 角丸四角形 (濃紺)
    pad = max(1, size // 12)
    r = max(2, size // 5)
    draw.rounded_rectangle([pad, pad, size - pad - 1, size - pad - 1], radius=r, fill="#0f172a")

    # ダウンロード矢印
    cx = size / 2
    lw = max(1, size // 10)
    top = size * 0.20
    mid = size * 0.58
    tip = size * 0.70
    bar = size * 0.82
    hw = size * 0.22  # 矢印の横幅の半分

    draw.line([(cx, top), (cx, mid)], fill="#1d9bf0", width=lw)
    draw.line([(cx, tip), (cx - hw, mid)], fill="#1d9bf0", width=lw)
    draw.line([(cx, tip), (cx + hw, mid)], fill="#1d9bf0", width=lw)
    draw.line([(cx - hw, bar), (cx + hw, bar)], fill="#1d9bf0", width=lw)

    return img


def main() -> None:
    out = Path(__file__).parent
    for size in (16, 48, 128):
        path = out / f"icon{size}.png"
        make_icon(size).save(path, "PNG")
        print(f"生成: {path}")


if __name__ == "__main__":
    main()
