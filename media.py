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
MAX_SIDE_MEMBERS = 10


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


def battle_sides(data: dict) -> list[list[dict]]:
    raw = data.get("battle_sides")
    if isinstance(raw, list) and len(raw) >= 2:
        out = []
        for side in raw[:2]:
            members = []
            if isinstance(side, list):
                for x in side[:MAX_SIDE_MEMBERS]:
                    if not isinstance(x, dict):
                        continue
                    name = str(x.get("name") or "").strip()[:160]
                    if not name:
                        continue
                    flag = x.get("flag")
                    members.append(
                        {"name": name, "flag": flag if isinstance(flag, str) else ""}
                    )
            out.append(members)
        return out

    out = [[], []]
    for i, key in enumerate(("side_1", "side_2")):
        value = data.get(key)
        if not value:
            continue
        lines = [x.strip() for x in str(value).splitlines() if x.strip()]
        out[i] = [{"name": x[:160], "flag": ""} for x in lines[:MAX_SIDE_MEMBERS]]
    return out


def set_battle_sides(data: dict, sides: list[list[dict]]) -> None:
    clean = battle_sides({"battle_sides": sides})
    if any(clean):
        data["battle_sides"] = clean
    else:
        data.pop("battle_sides", None)

    for key, members in zip(("side_1", "side_2"), clean):
        names = [x["name"] for x in members]
        if names:
            data[key] = "\n".join(names)
        else:
            data.pop(key, None)


def side_flags(data: dict) -> list[str]:
    out = []
    for side in battle_sides(data):
        for x in side:
            path = x.get("flag")
            if isinstance(path, str) and path and path not in out:
                out.append(path)
    return out


def page_media(data: dict) -> list[str]:
    out = page_images(data)
    for path in side_flags(data):
        if path not in out:
            out.append(path)
    return out


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
