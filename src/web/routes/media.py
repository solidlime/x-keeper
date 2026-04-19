"""メディア配信・削除ルート。"""

from pathlib import Path

from flask import Blueprint, send_from_directory, request
from flask import current_app

from ..utils import _SAVE_PATH, _THUMBS_DIR, _THUMB_IMAGE_EXTS, _THUMB_MAX_SIZE

bp_media = Blueprint("bp_media", __name__)


@bp_media.route("/media/<path:filepath>")
def serve_media(filepath: str):
    return send_from_directory(_SAVE_PATH, filepath)


@bp_media.route("/thumb/<path:filepath>")
def serve_thumb(filepath: str):
    """サムネイル JPEG を返す。未生成の場合は Pillow でリサイズしてキャッシュする。

    画像以外 (動画・音声・その他) のリクエストには 415 を返す。
    サムネイルは {SAVE_PATH}/_thumbs/{date}/{name}.jpg にキャッシュされる。
    """
    try:
        target = (Path(_SAVE_PATH) / filepath).resolve()
        save_root = Path(_SAVE_PATH).resolve()
    except Exception:
        return "invalid path", 400
    if save_root not in target.parents:
        return "forbidden", 403
    if not target.is_file():
        return "not found", 404
    if target.suffix.lower() not in _THUMB_IMAGE_EXTS:
        return "not an image", 415

    thumb_rel = Path(filepath).with_suffix('.jpg')
    thumb_abs = Path(_SAVE_PATH) / _THUMBS_DIR / thumb_rel

    if not thumb_abs.exists():
        try:
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            current_app.logger.error(
                "Pillow がインストールされていません。pip install Pillow でインストールしてください。"
            )
            return "Pillow not installed", 500
        try:
            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(target) as img:
                img.thumbnail(_THUMB_MAX_SIZE, Image.LANCZOS)
                if img.mode in ('RGBA', 'LA'):
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1])
                    img = bg
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(thumb_abs, 'JPEG', quality=80, optimize=True)
        except Exception as exc:
            current_app.logger.error("サムネイル生成失敗: path=%s, error=%s", filepath, exc)
            return "thumbnail generation failed", 500

    response = send_from_directory(
        str(Path(_SAVE_PATH) / _THUMBS_DIR),
        thumb_rel.as_posix(),
    )
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@bp_media.route("/delete-media", methods=["POST"])
def delete_media():
    filepath = request.form.get("path", "").strip()
    try:
        target = (Path(_SAVE_PATH) / filepath).resolve()
        save_root = Path(_SAVE_PATH).resolve()
    except Exception:
        return "invalid path", 400
    if save_root not in target.parents and target != save_root:
        return "forbidden", 403
    if not target.is_file():
        return "not found", 404
    target.unlink()
    thumb_cache = (Path(_SAVE_PATH) / _THUMBS_DIR / filepath).with_suffix('.jpg')
    if thumb_cache.exists():
        thumb_cache.unlink()
    return "ok", 200
