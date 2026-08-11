from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000


class BadImage(ValueError):
    """Ожидаемая ошибка в загруженном пользователем изображении."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    width: int
    height: int
    size: int


async def save_image(
    raw: bytes,
    owner_id: int,
    work_dir: str | Path,
    max_mb: int = 12,
) -> MediaInfo:
    return await asyncio.to_thread(_save_image, raw, owner_id, Path(work_dir), max_mb)


def _save_image(raw: bytes, owner_id: int, work_dir: Path, max_mb: int) -> MediaInfo:
    if not raw:
        raise BadImage("Файл пустой.")
    if len(raw) > max_mb * 1024 * 1024:
        raise BadImage(f"Изображение больше {max_mb} МБ.")

    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    tmp: Path | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as probe:
                probe.verify()
            with Image.open(BytesIO(raw)) as src:
                src.seek(0)
                img = ImageOps.exif_transpose(src)
                img.load()
                if img.width < 16 or img.height < 16:
                    raise BadImage("Изображение слишком маленькое.")
                if img.width * img.height > 40_000_000:
                    raise BadImage("Слишком большое разрешение изображения.")

                if max(img.size) > 5000:
                    img.thumbnail((5000, 5000), Image.Resampling.LANCZOS)

                mode = "RGBA" if "A" in img.getbands() else "RGB"
                img = img.convert(mode)
                name = f"media_{owner_id}_{uuid4().hex}.webp"
                path = work_dir / name
                tmp = work_dir / f"tmp_{uuid4().hex}.webp"
                img.save(tmp, "WEBP", quality=92, method=6)
                tmp.replace(path)
                return MediaInfo(path, img.width, img.height, path.stat().st_size)
    except BadImage:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as e:
        raise BadImage("Не получилось прочитать изображение. Нужен PNG, JPEG или WEBP.") from e
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)


def safe_media_path(path: str | Path, work_dir: str | Path) -> Path | None:
    root = Path(work_dir).resolve()
    raw = Path(path)
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_"):
        return None
    return p if p.is_file() else None


def safe_unlink(path: str | Path | None, work_dir: str | Path, prefix: str) -> bool:
    if not path:
        return False
    root = Path(work_dir).resolve()
    raw = Path(path)
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith(prefix):
        return False
    if p.exists():
        p.unlink()
        return True
    return False
