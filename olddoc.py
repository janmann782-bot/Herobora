"""Old document theme: aged paper, optional coffee stains, seed-based variations."""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from media import image_caption, page_images
from models import Page
from templates import Field, Template, get_template
from themes import Theme, get_theme

HERE = Path(__file__).resolve().parent
# Textures live next to the bot sources (root folder), not in a subfolder.
PAPERS = [HERE / "paper1.png", HERE / "paper2.png"]
STAINS = [HERE / "stain1.png", HERE / "stain2.png"]

SCALE = {"standard": 1.25, "high": 1.5, "ultra": 2.0}


STAIN_COUNT_MAX = 5
PAPER_COUNT = 2


def ensure_old_meta(data: dict) -> dict:
    """Ensure old-document options exist; mutate and return data."""
    if "_old_seed" not in data:
        raw = f"{data.get('title', '')}|{random.randint(1, 10**9)}"
        data["_old_seed"] = int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)
    if "_old_stains" not in data:
        data["_old_stains"] = True
    # 0..STAIN_COUNT_MAX cups; if stains off, treated as 0 at render
    if "_old_stain_count" not in data:
        data["_old_stain_count"] = 1
    data["_old_stain_count"] = max(0, min(STAIN_COUNT_MAX, int(data.get("_old_stain_count", 1) or 0)))
    # paper variant index 0..PAPER_COUNT-1
    if "_old_paper" not in data:
        data["_old_paper"] = 0
    data["_old_paper"] = int(data.get("_old_paper", 0) or 0) % PAPER_COUNT
    # drunk (jittery) text off by default
    if "_old_drunk" not in data:
        data["_old_drunk"] = False
    data["_old_drunk"] = bool(data.get("_old_drunk", False))
    return data


def new_seed(data: dict) -> int:
    data["_old_seed"] = random.randint(1, 2**31 - 1)
    return data["_old_seed"]


def cycle_stain_count(data: dict) -> int:
    ensure_old_meta(data)
    data["_old_stain_count"] = (int(data["_old_stain_count"]) + 1) % (STAIN_COUNT_MAX + 1)
    data["_old_stains"] = data["_old_stain_count"] > 0
    return data["_old_stain_count"]


def cycle_paper(data: dict) -> int:
    ensure_old_meta(data)
    data["_old_paper"] = (int(data["_old_paper"]) + 1) % PAPER_COUNT
    return data["_old_paper"]


def toggle_drunk(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_drunk"] = not bool(data["_old_drunk"])
    return data["_old_drunk"]


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _serif(size: int, bold: bool = False, italic: bool = False):
    if bold and italic:
        name = "LiberationSerif-Bold.ttf"  # no bold-italic bundled; fall back
    elif bold:
        name = "LiberationSerif-Bold.ttf"
    elif italic:
        name = "LiberationSerif-Italic.ttf"
    else:
        name = "LiberationSerif-Regular.ttf"
    paths = [
        HERE / name,
        Path("/usr/share/fonts/truetype/liberation") / name,
        HERE / "DejaVuSerif.ttf" if not bold else HERE / "DejaVuSerif-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"),
    ]
    for p in paths:
        if p and p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def _size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text or "Ag", font=font)
    return box[2] - box[0], box[3] - box[1]


def _wrap(draw: ImageDraw.ImageDraw, value: object, font, max_w: int) -> list[str]:
    text = "\n".join(str(x) for x in value) if isinstance(value, (list, tuple)) else str(value)
    out: list[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            out.append("")
            continue
        line = ""
        for word in words:
            cand = word if not line else f"{line} {word}"
            if line and _size(draw, cand, font)[0] > max_w:
                out.append(line)
                line = word
            else:
                line = cand
        if line:
            out.append(line)
    return out or [""]


def _line_h(draw: ImageDraw.ImageDraw, font) -> int:
    return int(_size(draw, "Аg", font)[1] * 1.38)


def _paper_bg(w: int, h: int, rng: random.Random, paper_index: int = 0) -> Image.Image:
    papers = [p for p in PAPERS if p.is_file()]
    if not papers:
        img = Image.new("RGB", (w, h), (232, 220, 190))
        return img

    idx = paper_index % len(papers)
    src = Image.open(papers[idx]).convert("RGB")
    # tile / cover
    sw, sh = src.size
    scale = max(w / sw, h / sh) * (1.0 + rng.uniform(0.02, 0.12))
    nw, nh = max(w, int(sw * scale)), max(h, int(sh * scale))
    src = src.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = rng.randint(0, max(0, nw - w))
    oy = rng.randint(0, max(0, nh - h))
    img = src.crop((ox, oy, ox + w, oy + h))

    # brightness / contrast — keep texture readable
    bright = rng.uniform(0.92, 1.08)
    contrast = rng.uniform(1.05, 1.25)
    img = ImageEnhance.Brightness(img).enhance(bright)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.85, 1.05))
    # slight color shift toward sepia/yellow
    r, g, b = img.split()
    r = r.point(lambda x: min(255, int(x * rng.uniform(1.0, 1.05))))
    b = b.point(lambda x: max(0, int(x * rng.uniform(0.88, 0.97))))
    img = Image.merge("RGB", (r, g, b))
    # fine grain so flat regions still look like paper (no numpy)
    grain = Image.new("RGB", img.size)
    px = grain.load()
    w, h = img.size
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            v = rng.randint(-7, 8)
            c = (128 + v, 128 + v, 128 + v)
            px[x, y] = c
            if x + 1 < w:
                px[x + 1, y] = c
            if y + 1 < h:
                px[x, y + 1] = c
                if x + 1 < w:
                    px[x + 1, y + 1] = c
    grain = grain.filter(ImageFilter.GaussianBlur(radius=0.6))
    img = Image.blend(img, grain, 0.07)
    return img


def _torn_mask(w: int, h: int, rng: random.Random, depth: int = 18) -> Image.Image:
    """Hard irregular torn edge — no soapy soft feather."""
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)
    depth = max(10, depth)

    def edge_points(length: int, axis: str, side: str) -> list[tuple[int, int]]:
        pts = []
        # dense steps → fiber-like jags, not smooth waves
        step = max(3, length // 90)
        n = max(8, length // step)
        base = depth * 0.45
        for i in range(n + 1):
            t = i / n
            pos = int(t * (length - 1))
            # occasional deeper rips
            spike = depth * rng.uniform(0.2, 1.15) if rng.random() < 0.22 else depth * rng.uniform(0.05, 0.45)
            jitter = rng.uniform(-depth * 0.25, depth * 0.25)
            off = int(max(2, min(depth + 6, base + spike + jitter)))
            if axis == "x":
                y = off if side == "top" else h - 1 - off
                pts.append((pos, y))
            else:
                x = off if side == "left" else w - 1 - off
                pts.append((x, pos))
        return pts

    for axis, side, corner_a, corner_b in (
        ("x", "top", (0, 0), (w - 1, 0)),
        ("x", "bottom", (0, h - 1), (w - 1, h - 1)),
        ("y", "left", (0, 0), (0, h - 1)),
        ("y", "right", (w - 1, 0), (w - 1, h - 1)),
    ):
        pts = edge_points(w if axis == "x" else h, axis, side)
        poly = [corner_a] + pts + [corner_b]
        draw.polygon(poly, fill=0)

    # crisp binary edge — no soft soap halo
    return mask


def _apply_stains(img: Image.Image, rng: random.Random, count: int = 1) -> Image.Image:
    """Place `count` cup stains of a fixed size (position/rotation still vary by seed)."""
    stains = [p for p in STAINS if p.is_file()]
    if not stains or count <= 0:
        return img
    out = img.convert("RGBA")
    w, h = out.size
    # fixed relative size of the cup ring
    fixed_frac = 0.32
    for i in range(count):
        stain = Image.open(stains[i % len(stains)]).convert("RGBA")
        target = max(40, int(min(w, h) * fixed_frac))
        scale = target / max(stain.size)
        nw = max(20, int(stain.width * scale))
        nh = max(20, int(stain.height * scale))
        stain = stain.resize((nw, nh), Image.Resampling.LANCZOS)
        if rng.random() < 0.5:
            stain = stain.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if rng.random() < 0.5:
            stain = stain.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        angle = rng.uniform(-35, 35)
        # keep alpha hard on expand
        rgb = stain.convert("RGB")
        alpha = stain.split()[3]
        rgb_r = rgb.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
        a_r = alpha.rotate(angle, expand=True, resample=Image.Resampling.NEAREST, fillcolor=0)
        a_r = a_r.point(lambda v: 255 if v > 180 else 0)
        # fixed-ish opacity
        a_r = a_r.point(lambda v: int(v * 0.7) if v else 0)
        stain = rgb_r.convert("RGBA")
        stain.putalpha(a_r)
        nw, nh = stain.size
        x = rng.randint(-nw // 5, max(0, w - nw * 4 // 5))
        y = rng.randint(-nh // 5, max(0, h - nh * 4 // 5))
        layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
        layer.paste(stain, (x, y), stain)
        out = Image.alpha_composite(out, layer)
    return out.convert("RGB")


def _ink_color(rng: random.Random) -> tuple[int, int, int]:
    # dark brown / faded ink
    base = rng.randint(28, 55)
    return (base + rng.randint(10, 30), base + rng.randint(5, 20), base)


def _draw_text_messy(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font,
    fill,
    rng: random.Random,
    max_jitter: float = 1.8,
) -> None:
    x, y = xy
    # slight per-character jitter for "not perfectly neat"
    for ch in text:
        jx = rng.uniform(-max_jitter, max_jitter)
        jy = rng.uniform(-max_jitter * 0.6, max_jitter * 0.6)
        draw.text((x + jx, y + jy), ch, font=font, fill=fill)
        x += _size(draw, ch, font)[0]


def _draw_lines_messy(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    font,
    fill,
    line_h: int,
    rng: random.Random,
    width: int | None = None,
    align: str = "left",
    max_jitter: float = 1.6,
    drunk: bool = False,
) -> None:
    x0, y = xy
    for line in lines:
        xx = x0
        if width and align != "left":
            w = _size(draw, line, font)[0]
            xx = x0 + (width - w if align == "right" else (width - w) // 2)
        if drunk:
            xx += int(rng.uniform(-2.5, 2.5))
            yy = y + int(rng.uniform(-1.2, 1.2))
            _draw_text_messy(draw, line, (xx, yy), font, fill, rng, max_jitter)
            y += line_h + int(rng.uniform(-0.8, 1.5))
        else:
            # straight, sober text
            draw.text((xx, y), line, font=font, fill=fill)
            y += line_h


def _media_path(value: object, root: Path) -> Path | None:
    if not value:
        return None
    raw = Path(str(value))
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_") or not p.is_file():
        return None
    return p


def render_olddoc(
    page: Page,
    work_dir: str | Path,
    quality: str,
    output: str | Path,
    watermark: bool = True,
) -> Path:
    root = Path(work_dir).resolve()
    path = Path(output).resolve()
    theme = get_theme("olddoc")
    tpl = get_template(page.type)
    data = ensure_old_meta(dict(page.data))
    page.data = data  # keep seed stable for this render session
    seed = int(data["_old_seed"])
    stain_count = int(data.get("_old_stain_count", 1) or 0)
    if not bool(data.get("_old_stains", True)):
        stain_count = 0
    paper_index = int(data.get("_old_paper", 0) or 0)
    drunk = bool(data.get("_old_drunk", False))
    rng = _rng(seed)

    def draw_lines(draw, lines, xy, font, fill, line_h, width=None, align="left", max_jitter=1.6):
        _draw_lines_messy(draw, lines, xy, font, fill, line_h, rng, width, align, max_jitter, drunk=drunk)

    s = SCALE.get(quality, SCALE["high"])
    card_w = int(780 * s)
    pad = int(36 * s)
    content_w = card_w - pad * 2
    ink = _ink_color(rng)
    ink_sec = tuple(min(255, c + 40) for c in ink)
    sep = tuple(min(255, c + 70) for c in ink)

    blocks: list[Image.Image] = []
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # --- header ---
    kind_font = _serif(max(13, int(15 * s)), bold=True)
    title_font = _serif(max(26, int(34 * s)), bold=True)
    sub_font = _serif(max(14, int(17 * s)), italic=True)
    title = data.get("title") or page.title or "Без названия"
    subtitle = data.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    kind = tpl.label.upper()
    kind_lines = _wrap(tmp, kind, kind_font, content_w)
    title_lines = _wrap(tmp, title, title_font, content_w)
    sub_lines = _wrap(tmp, subtitle, sub_font, content_w) if subtitle else []
    kh, th, sh = _line_h(tmp, kind_font), _line_h(tmp, title_font), _line_h(tmp, sub_font)
    hh = pad // 2 + len(kind_lines) * kh + 8 + len(title_lines) * th
    if sub_lines:
        hh += 6 + len(sub_lines) * sh
    hh += pad // 2
    header = Image.new("RGBA", (card_w, hh), (0, 0, 0, 0))
    hd = ImageDraw.Draw(header)
    y = pad // 2
    draw_lines(hd, kind_lines, (pad, y), kind_font, sep, kh, content_w, "center", 1.2)
    y += len(kind_lines) * kh + 8
    draw_lines(hd, title_lines, (pad, y), title_font, ink, th, content_w, "center", 2.0)
    y += len(title_lines) * th
    if sub_lines:
        y += 6
        draw_lines(hd, sub_lines, (pad, y), sub_font, ink_sec, sh, content_w, "center", 1.4)
    blocks.append(header)

    # --- images ---
    media_items = []
    for i, value in enumerate(page_images(data)):
        mp = _media_path(value, root)
        if mp:
            media_items.append((mp, image_caption(data, value, i)))
    if media_items:
        gap = int(10 * s)
        cell_w = content_w if len(media_items) == 1 else (content_w - gap) // 2
        max_h = int(320 * s)
        prepared = []
        for mp, cap in media_items:
            try:
                src = ImageOps.exif_transpose(Image.open(mp))
                src.load()
                src.thumbnail((cell_w, max_h), Image.Resampling.LANCZOS)
                if src.mode != "RGBA":
                    src = src.convert("RGBA")
                prepared.append((src, cap))
            except Exception:
                continue
        if prepared:
            cap_font = _serif(max(12, int(14 * s)), italic=True)
            lh = _line_h(tmp, cap_font)
            rows = [prepared[i : i + (1 if len(prepared) == 1 else 2)] for i in range(0, len(prepared), 2 if len(prepared) > 1 else 1)]
            heights = []
            for row in rows:
                rh = max(p[0].height for p in row)
                for _, cap in row:
                    if cap:
                        rh += int(6 * s) + len(_wrap(tmp, cap, cap_font, cell_w)) * lh
                heights.append(rh)
            gh = pad // 2 + sum(heights) + gap * (len(rows) - 1) + pad // 2
            gal = Image.new("RGBA", (card_w, gh), (0, 0, 0, 0))
            gd = ImageDraw.Draw(gal)
            yy = pad // 2
            for row, rh in zip(rows, heights):
                for i, (src, cap) in enumerate(row):
                    if len(row) == 1:
                        cx = (card_w - src.width) // 2
                    else:
                        cx = pad + i * (cell_w + gap) + (cell_w - src.width) // 2
                    # slight tilt; alpha rotated NEAREST so no soapy white corners
                    ang = rng.uniform(-2.8, 2.8)
                    rgb = src.convert("RGB")
                    alpha = src.split()[3] if src.mode == "RGBA" else Image.new("L", src.size, 255)
                    rgb_r = rgb.rotate(ang, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
                    a_r = alpha.rotate(ang, expand=True, resample=Image.Resampling.NEAREST, fillcolor=0)
                    # kill any residual semi-transparent fringe from RGB bleed
                    a_r = a_r.point(lambda v: 255 if v > 200 else 0)
                    rotated = rgb_r.convert("RGBA")
                    rotated.putalpha(a_r)
                    ox = cx + rng.randint(-3, 3) - (rotated.width - src.width) // 2
                    oy = yy + rng.randint(-2, 2) - (rotated.height - src.height) // 2
                    gal.paste(rotated, (ox, oy), rotated)
                    if cap:
                        lines = _wrap(tmp, cap, cap_font, cell_w - 8)
                        draw_lines(
                            gd,
                            lines,
                            (cx, yy + src.height + int(6 * s)),
                            cap_font,
                            ink_sec,
                            lh,
                            cell_w,
                            "center",
                            1.0,
                        )
                yy += rh + gap
            blocks.append(gal)

    label_font = _serif(max(13, int(15 * s)), bold=True)
    value_font = _serif(max(13, int(15 * s)))
    sec_font = _serif(max(15, int(18 * s)), bold=True)
    lh_l = _line_h(tmp, label_font)
    lh_v = _line_h(tmp, value_font)

    def section_title(text: str) -> Image.Image:
        lines = _wrap(tmp, text, sec_font, content_w)
        h = int(10 * s) + len(lines) * _line_h(tmp, sec_font) + int(8 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw_lines(d, lines, (pad, int(10 * s)), sec_font, ink, _line_h(tmp, sec_font), content_w, "left", 1.5)
        # underline
        uy = h - int(6 * s)
        d.line((pad + rng.randint(-2, 2), uy, pad + content_w // 2 + rng.randint(-10, 20), uy + rng.randint(-1, 1)), fill=sep, width=max(1, int(s)))
        return img

    def field_row(label: str, value: object) -> Image.Image:
        lab_lines = _wrap(tmp, label, label_font, int(content_w * 0.38))
        val_lines = _wrap(tmp, value, value_font, int(content_w * 0.55))
        h = max(len(lab_lines) * lh_l, len(val_lines) * lh_v) + int(12 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        col1 = int(content_w * 0.38)
        draw_lines(d, lab_lines, (pad, int(6 * s)), label_font, ink_sec, lh_l, col1, "left", 1.4)
        draw_lines(
            d,
            val_lines,
            (pad + col1 + int(12 * s), int(6 * s)),
            value_font,
            ink,
            lh_v,
            int(content_w * 0.55),
            "left",
            1.5,
        )
        return img

    skip = {"title", "description", "image_caption"}
    if tpl.subtitle_key:
        skip.add(tpl.subtitle_key)
    sections_order = []
    for f in tpl.fields:
        if f.key not in skip and f.section not in sections_order:
            sections_order.append(f.section)

    for sec_name in sections_order:
        fields = [f for f in tpl.fields if f.section == sec_name and f.key not in skip and data.get(f.key) not in (None, "", [])]
        if not fields:
            continue
        blocks.append(section_title(sec_name))
        for f in fields:
            blocks.append(field_row(f.label, data[f.key]))

    custom = [x for x in data.get("custom_fields") or [] if isinstance(x, dict) and x.get("value") not in (None, "")]
    if custom:
        blocks.append(section_title("Дополнительные сведения"))
        for x in custom:
            blocks.append(field_row(str(x.get("name", "Поле")), x.get("value", "")))

    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        rows = [x for x in sec.get("fields") or [] if isinstance(x, dict) and x.get("value") not in (None, "")]
        if not rows:
            continue
        blocks.append(section_title(str(sec.get("title") or "Раздел")))
        for x in rows:
            blocks.append(field_row(str(x.get("name", "Поле")), x.get("value", "")))

    if data.get("description"):
        blocks.append(section_title("Описание"))
        desc_font = _serif(max(13, int(15 * s)))
        lines = _wrap(tmp, data["description"], desc_font, content_w)
        lh = _line_h(tmp, desc_font)
        h = int(8 * s) + len(lines) * lh + int(12 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw_lines(d, lines, (pad, int(8 * s)), desc_font, ink, lh, content_w, "left", 1.3)
        blocks.append(img)

    if watermark:
        wf = _serif(max(11, int(12 * s)), italic=True)
        h = int(28 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw_lines(d, ["INFOBOX BOT"], (pad, int(6 * s)), wf, sep, _line_h(tmp, wf), content_w, "right", 1.0)
        blocks.append(img)

    content_h = sum(b.height for b in blocks)
    margin = int(28 * s)
    total_w = card_w + margin * 2
    total_h = content_h + margin * 2

    # paper background
    bg = _paper_bg(total_w, total_h, rng, paper_index=paper_index)

    # compose content
    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    yy = margin
    for b in blocks:
        canvas.paste(b, (margin, yy), b if b.mode == "RGBA" else None)
        yy += b.height

    # stains under or over text? typically on paper, semi-over
    composed = Image.alpha_composite(bg.convert("RGBA"), canvas)
    if stain_count > 0:
        composed = _apply_stains(composed.convert("RGB"), rng, count=stain_count).convert("RGBA")

    # torn edges + transparent outside the paper
    depth = int(14 * s) + rng.randint(0, 8)
    mask = _torn_mask(total_w, total_h, rng, depth=depth)

    # keep stains/content RGB, then apply torn alpha so outside is fully transparent
    paper = composed.convert("RGBA")
    paper.putalpha(mask)

    # small transparent padding around the sheet
    pad_out = 8
    final = Image.new("RGBA", (total_w + pad_out * 2, total_h + pad_out * 2), (0, 0, 0, 0))
    final.paste(paper, (pad_out, pad_out), paper)

    final.save(path, "PNG", compress_level=6, dpi=(144, 144))
    return path