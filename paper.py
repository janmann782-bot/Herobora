from __future__ import annotations

import hashlib
import random
import secrets
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps


MAX_SEED = 2**64 - 1
PAPER_SEED = "paper_seed"
PAPER_COFFEE = "paper_coffee"
PAPER_TEXTURES = ("PAPER_TEXTURE_WARM.png", "PAPER_TEXTURE_PALE.png")
COFFEE_RINGS = ("COFFEE_RING_LIGHT.png", "COFFEE_RING_DARK.png")


def seed_from_text(value: object) -> int:
    s = str(value or "").strip()
    if not s:
        raise ValueError("Сид не может быть пустым")
    try:
        return int(s) & MAX_SEED
    except ValueError:
        raw = hashlib.blake2s(s.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(raw, "big")


def paper_seed(data: dict) -> int:
    value = data.get(PAPER_SEED)
    if isinstance(value, int) and not isinstance(value, bool):
        return value & MAX_SEED
    if isinstance(value, str) and value.strip():
        try:
            return seed_from_text(value)
        except ValueError:
            pass
    title = data.get("title") or data.get("official_name") or "Без названия"
    return seed_from_text(f"infobox:{title}")


def ensure_paper(data: dict) -> int:
    value = data.get(PAPER_SEED)
    if value in (None, "") or isinstance(value, bool):
        data[PAPER_SEED] = secrets.randbits(64)
    else:
        data[PAPER_SEED] = seed_from_text(value)
    if not isinstance(data.get(PAPER_COFFEE), bool):
        data[PAPER_COFFEE] = True
    return data[PAPER_SEED]


def new_paper_seed(data: dict) -> int:
    old = paper_seed(data)
    n = secrets.randbits(64)
    if n == old:
        n = (n + 1) & MAX_SEED
    data[PAPER_SEED] = n
    data.setdefault(PAPER_COFFEE, True)
    return n


def coffee_enabled(data: dict) -> bool:
    return data.get(PAPER_COFFEE, True) is not False


def paper_profile(seed: int) -> dict:
    r = random.Random(seed & MAX_SEED)
    return {
        "texture": PAPER_TEXTURES[r.randrange(len(PAPER_TEXTURES))],
        "texture_x": r.random(),
        "texture_y": r.random(),
        "flip_x": r.choice((False, True)),
        "flip_y": r.choice((False, False, True)),
        "brightness": r.uniform(0.88, 1.07),
        "contrast": r.uniform(0.94, 1.08),
        "texture_mix": r.uniform(0.24, 0.38),
        "angle": r.uniform(-0.55, 0.55),
        "ring": COFFEE_RINGS[r.randrange(len(COFFEE_RINGS))],
        "ring_scale": r.uniform(0.27, 0.48),
        "ring_angle": r.uniform(0, 360),
        "ring_x": r.uniform(-0.06, 0.66),
        "ring_y": r.uniform(0.04, 0.72),
        "ring_alpha": r.uniform(0.28, 0.56),
        "header_x": r.randint(-5, 9),
        "title_angle": r.uniform(-0.22, 0.22),
        "section_x": r.randint(-4, 10),
        "row_x": r.randint(-3, 5),
        "label_width": r.uniform(33.5, 38.5),
    }


def paper_css(data: dict) -> str:
    p = paper_profile(paper_seed(data))
    return ";".join(
        (
            f"--paper-header-x:{p['header_x']}px",
            f"--paper-title-angle:{p['title_angle']:.3f}deg",
            f"--paper-section-x:{p['section_x']}px",
            f"--paper-row-x:{p['row_x']}px",
            f"--paper-label-width:{p['label_width']:.2f}%",
        )
    )


def paper_status(data: dict) -> tuple[int, int, bool]:
    seed = paper_seed(data)
    brightness = round(paper_profile(seed)["brightness"] * 100)
    return seed, brightness, coffee_enabled(data)


def _paper_texture(size: tuple[int, int], root: Path, p: dict) -> Image.Image:
    path = root / p["texture"]
    with Image.open(path) as src:
        src = src.convert("RGB")
        if p["flip_x"]:
            src = ImageOps.mirror(src)
        if p["flip_y"]:
            src = ImageOps.flip(src)
        return ImageOps.fit(
            src,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(p["texture_x"], p["texture_y"]),
        )


def _stain_layer(size: tuple[int, int], seed: int) -> Image.Image:
    w, h = size
    r = random.Random(seed ^ 0xA11CE5)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    n = r.randint(5, 11)
    for _ in range(n):
        x = r.randint(-w // 10, w + w // 10)
        y = r.randint(-h // 20, h + h // 20)
        rx = r.randint(max(10, w // 90), max(20, w // 18))
        ry = r.randint(max(8, rx // 3), max(12, rx))
        color = (91, 55, 21, r.randint(5, 15))
        draw.ellipse((x - rx, y - ry, x + rx, y + ry), fill=color)
    blur = max(6, w // 85)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _add_coffee(img: Image.Image, root: Path, p: dict) -> Image.Image:
    w, h = img.size
    path = root / p["ring"]
    with Image.open(path) as src:
        ring = src.convert("RGBA")
    target = max(120, int(w * p["ring_scale"]))
    ratio = target / ring.width
    ring = ring.resize(
        (target, max(1, int(ring.height * ratio))),
        Image.Resampling.LANCZOS,
    )
    ring = ring.rotate(p["ring_angle"], expand=True, resample=Image.Resampling.BICUBIC)
    alpha = ring.getchannel("A").point(lambda x: round(x * p["ring_alpha"]))
    ring.putalpha(alpha)
    x = int(w * p["ring_x"])
    max_y = max(0, h - ring.height // 2)
    y = min(max_y, int(h * p["ring_y"]))
    out = img.convert("RGBA")
    out.alpha_composite(ring, (x, y))
    return out


def _torn_mask(size: tuple[int, int], seed: int) -> Image.Image:
    w, h = size
    r = random.Random(seed ^ 0x7EAF5EED)
    amp = max(3, round(min(w, h) * 0.006))

    def points(length: int, reverse: bool = False) -> list[tuple[int, int]]:
        step = max(28, length // 25)
        xs = list(range(0, length, step)) + [length - 1]
        if reverse:
            xs.reverse()
        out = []
        deep = set(r.sample(range(1, max(2, len(xs) - 1)), k=min(2, max(1, len(xs) - 2))))
        for i, x in enumerate(xs):
            n = r.randint(0, amp)
            if i in deep:
                n += r.randint(amp, amp * 3)
            out.append((x, n))
        return out

    top = points(w)
    right = [(w - 1 - n, y) for y, n in points(h)]
    bottom = [(x, h - 1 - n) for x, n in points(w, True)]
    left = [(n, y) for y, n in points(h, True)]
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(top + right + bottom + left, fill=255)
    return mask


def finish_old_document(path: str | Path, data: dict) -> Path:
    path = Path(path).resolve()
    root = Path(__file__).resolve().parent
    seed = paper_seed(data)
    p = paper_profile(seed)

    with Image.open(path) as src:
        img = src.convert("RGB")

    texture = _paper_texture(img.size, root, p)
    texture = ImageEnhance.Brightness(texture).enhance(p["brightness"])
    printed = ImageChops.multiply(img, texture)
    img = Image.blend(img, printed, p["texture_mix"])
    img = ImageEnhance.Brightness(img).enhance(p["brightness"])
    img = ImageEnhance.Contrast(img).enhance(p["contrast"])
    img = ImageEnhance.Color(img).enhance(0.88)
    img = Image.alpha_composite(img.convert("RGBA"), _stain_layer(img.size, seed))

    if coffee_enabled(data):
        img = _add_coffee(img, root, p)

    img.putalpha(_torn_mask(img.size, seed))
    img = img.rotate(
        p["angle"],
        expand=True,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )

    margin = max(24, round(img.width * 0.035))
    canvas = Image.new(
        "RGBA",
        (img.width + margin * 2, img.height + margin * 2),
        (62, 56, 49, 255),
    )
    alpha = img.getchannel("A")
    shadow = Image.new("RGBA", img.size, (20, 16, 12, 0))
    shadow.putalpha(
        alpha.filter(ImageFilter.GaussianBlur(max(5, margin // 4))).point(lambda x: x // 3)
    )
    x = margin
    y = margin
    canvas.alpha_composite(shadow, (x + max(3, margin // 7), y + max(4, margin // 6)))
    canvas.alpha_composite(img, (x, y))
    canvas.convert("RGB").save(path, "PNG", compress_level=6, dpi=(144, 144))
    return path
