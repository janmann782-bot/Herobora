from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000
MAX_PAGE_IMAGES = 10


ROLE_MARKERS = {
    "main": ("main", "main:", "главное", "главное:", "битва", "битва:", "image", "image:"),
    "side1": ("s1", "s1:", "side1", "side1:", "side 1", "side 1:", "ст1", "ст1:", "сторона1", "сторона1:", "сторона 1", "сторона 1:"),
    "side2": ("s2", "s2:", "side2", "side2:", "side 2", "side 2:", "ст2", "ст2:", "сторона2", "сторона2:", "сторона 2", "сторона 2:"),
    "extra": ("extra", "extra:", "доп", "доп:", "галерея", "галерея:")
}


def _norm_caption_marker(value: str) -> str:
    return value.casefold().replace("ё", "е").strip()


def split_image_role(caption: str | None) -> tuple[str | None, str]:
    text = str(caption or "").strip()
    if not text:
        return None, ""

    low = _norm_caption_marker(text)
    for role, markers in ROLE_MARKERS.items():
        for marker in markers:
            m = _norm_caption_marker(marker)
            if low == m:
                return role, ""
            if low.startswith(m):
                rest = text[len(marker):].lstrip(" :-—–|")
                return role, rest
    return None, text


def battle_image_groups(data: dict) -> tuple[tuple[str, str] | None, list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    items = []
    tagged = False
    for i, path in enumerate(page_images(data)):
        caption = image_caption(data, path, i)
        role, clean_caption = split_image_role(caption)
        if role:
            tagged = True
        items.append((role, path, clean_caption))

    if not items:
        return None, [], [], []

    if not tagged:
        main = (items[0][1], items[0][2])
        side1 = [(items[1][1], items[1][2])] if len(items) > 1 else []
        side2 = [(items[2][1], items[2][2])] if len(items) > 2 else []
        extras = [(path, cap) for _, path, cap in items[3:]]
        return main, side1, side2, extras

    main = None
    side1: list[tuple[str, str]] = []
    side2: list[tuple[str, str]] = []
    extras: list[tuple[str, str]] = []
    untagged: list[tuple[str, str]] = []

    for role, path, cap in items:
        item = (path, cap)
        if role == "main":
            if main is None:
                main = item
            else:
                extras.append(item)
        elif role == "side1":
            side1.append(item)
        elif role == "side2":
            side2.append(item)
        elif role == "extra":
            extras.append(item)
        else:
            untagged.append(item)

    if main is None and untagged:
        main = untagged.pop(0)
    extras.extend(untagged)
    return main, side1, side2, extras


class BadImage(ValueError):
    """Ожидаемая ошибка в загруженном пользователем изображении."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    width: int
    height: int
    size: int


def page_images(data: dict) -> list[str]:
    out = []
    for x in data.get("images") or []:
        if isinstance(x, str) and x and x not in out:
            out.append(x)
    old = data.get("image")
    if isinstance(old, str) and old and old not in out:
        out.insert(0, old)
    return out[:MAX_PAGE_IMAGES]


def image_caption(data: dict, path: str, index: int = 0) -> str:
    captions = data.get("image_captions")
    if isinstance(captions, dict):
        value = captions.get(path)
        if isinstance(value, str):
            return value
    if index == 0:
        return str(data.get("image_caption") or "")
    return ""


def set_image_caption(data: dict, path: str, caption: str) -> None:
    value = caption.strip()
    captions = data.get("image_captions")
    captions = dict(captions) if isinstance(captions, dict) else {}

    if value:
        captions[path] = value
    else:
        captions.pop(path, None)

    if captions:
        data["image_captions"] = captions
    else:
        data.pop("image_captions", None)

    images = page_images(data)
    if images and images[0] == path:
        if value:
            data["image_caption"] = value
        else:
            data.pop("image_caption", None)


def set_page_images(data: dict, images: list[str]) -> None:
    old = page_images(data)
    legacy_caption = str(data.get("image_caption") or "").strip()
    items = []
    for x in images:
        if isinstance(x, str) and x and x not in items:
            items.append(x)
    items = items[:MAX_PAGE_IMAGES]
    if items:
        data["images"] = items
        data["image"] = items[0]
    else:
        data.pop("images", None)
        data.pop("image", None)

    captions = data.get("image_captions")
    captions = {
        k: v
        for k, v in captions.items()
        if isinstance(k, str) and k in items and isinstance(v, str) and v.strip()
    } if isinstance(captions, dict) else {}
    if captions:
        data["image_captions"] = captions
    else:
        data.pop("image_captions", None)

    if not items:
        data.pop("image_caption", None)
    elif items[0] in captions:
        data["image_caption"] = captions[items[0]]
    elif not old and legacy_caption:
        captions[items[0]] = legacy_caption
        data["image_captions"] = captions
        data["image_caption"] = legacy_caption
    elif old and old[0] != items[0]:
        data.pop("image_caption", None)




def map_images(data: dict) -> list[str]:
    out = []
    for x in data.get("map_images") or []:
        if isinstance(x, str) and x and x not in out:
            out.append(x)
    return out[:MAX_PAGE_IMAGES]


def set_map_images(data: dict, images: list[str]) -> None:
    items = []
    for x in images:
        if isinstance(x, str) and x and x not in items:
            items.append(x)
    items = items[:MAX_PAGE_IMAGES]
    if items:
        data["map_images"] = items
    else:
        data.pop("map_images", None)

async def save_image(
    raw: bytes,
    owner_id: int,
    work_dir: str | Path,
    max_mb: int = 12,
) -> MediaInfo:
    return await asyncio.to_thread(_save_image, raw, owner_id, Path(work_dir), max_mb)


def _save_image(raw: bytes, owner_id: int, work_dir: Path, max_mb: int) -> MediaInfo:
    if not raw:
        raise BadImage("файл пустой")
    if len(raw) > max_mb * 1024 * 1024:
        raise BadImage(f"изображение больше {max_mb} МБ")

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
                    raise BadImage("изображение слишком маленькое")
                if img.width * img.height > 40_000_000:
                    raise BadImage("слишком большое разрешение изображения")

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
        raise BadImage("не получилось прочитать изображение, нужен PNG, JPEG или WEBP") from e
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
