
import io
from pathlib import Path
from PIL import Image
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

BREAKPOINTS = (640, 1280)  # small, medium

def _ensure_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "P"):
        return img.convert("RGB")
    return img

def _make_thumb(img: Image.Image, max_width: int) -> Image.Image:
    img = _ensure_rgb(img.copy())
    w, h = img.size
    if w <= max_width:
        return img
    new_h = int(h * (max_width / float(w)))
    img.thumbnail((max_width, new_h), Image.Resampling.LANCZOS)
    return img

def _save_webp(img: Image.Image, base_path: str, suffix: str, quality: int = 82) -> str:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    buf.seek(0)
    name = f"{base_path}{suffix}.webp"
    default_storage.save(name, ContentFile(buf.read()))
    return name

def generate_thumbnails_and_return_paths(original_file, base_dir: str, stem: str) -> dict:
    """Saves two WEBP thumbnails inside MEDIA_ROOT to avoid SuspiciousFileOperation."""
    original_file.seek(0)
    img = Image.open(original_file)
    out = {}
    # always build path under MEDIA_ROOT
    media_base = Path(settings.MEDIA_ROOT) / "test_thumbs"
    media_base.mkdir(parents=True, exist_ok=True)
    base_path = str(media_base / stem)

    for size, suffix in [(640, "_sm"), (1280, "_md")]:
        thumb = img.copy()
        thumb.thumbnail((size, size))
        buf = io.BytesIO()
        thumb.save(buf, format="WEBP", quality=85)
        buf.seek(0)
        name = f"{base_path}{suffix}.webp"
        # save relative to MEDIA_ROOT
        rel_name = str(Path("test_thumbs") / f"{stem}{suffix}.webp")
        default_storage.save(rel_name, ContentFile(buf.read()))
        out[suffix.strip("_")] = rel_name
    return out
