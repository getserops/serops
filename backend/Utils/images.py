"""Small uploaded images (organisation logos, user avatars).

They are stored in the database rather than on disk: a Helm install runs
several backend pods with no shared volume, and Django does not serve
media with DEBUG off.
"""
import io

from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class ImageRejected(ValueError):
    pass


def to_small_png(upload, max_side):
    """Return ``upload`` as PNG bytes no larger than ``max_side`` a side.

    Re-encoding drops metadata and anything that is not pixels, so the
    stored image is always a plain PNG whatever was uploaded.
    """
    if getattr(upload, 'size', 0) > MAX_UPLOAD_BYTES:
        raise ImageRejected('Image must be less than 2MB')
    try:
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageRejected('Upload a PNG, JPEG, GIF or WebP image')
    image = image.convert('RGBA')
    image.thumbnail((max_side, max_side))
    out = io.BytesIO()
    image.save(out, format='PNG', optimize=True)
    return out.getvalue()
