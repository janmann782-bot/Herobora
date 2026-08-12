from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from media import battle_sides, image_caption, page_images
from models import Page
from templates import Field, Template, get_template
from themes import Theme, get_theme


PILLOW_SCALE = {"standard": 1.25, "high": 1.5, "ultra": 2.0}


def _font(theme: Theme, size: int, bold: bool = False, heading: bool = False):
    here = Path(__file__).resolve().parent
    if theme.key == "aurelia":
        fallback_name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
        fallback = _load_font(here, fallback_name, size)
        isaac = here / "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF"
        if isaac.is_file():
            return ImageFont.truetype(str(isaac), size), fallback
        return fallback

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return _load_font(here, name, size)


def _load_font(here: Path, name: str, size: int):
    paths = [
        here / name,
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/local/share/fonts") / name,
        Path("C:/Windows/Fonts") / name,
    ]
    for p in paths:
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def _font_runs(text: str, font):
    if not isinstance(font, tuple):
        return [(text, font)]

    primary, fallback = font
    out = []
    buf = ""
    cur = None
    extra = "—–…«»№ "
    for ch in text:
        n = ord(ch)
        use_primary = 32 <= n <= 126 or 0x0410 <= n <= 0x044F or n in {0x0401, 0x0451} or ch in extra
        f = primary if use_primary else fallback
        if cur is not None and f is not cur:
            out.append((buf, cur))
            buf = ""
        buf += ch
        cur = f
    if buf:
        out.append((buf, cur))
    return out or [("", primary)]


def _size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    width = 0
    height = 0
    for s, f in _font_runs(text or "Ag", font):
        box = draw.textbbox((0, 0), s, font=f)
        width += box[2] - box[0]
        height = max(height, box[3] - box[1])
    return width, height


def _split_word(draw: ImageDraw.ImageDraw, word: str, font, max_w: int) -> list[str]:
    out = []
    s = ""
    for ch in word:
        x = s + ch
        if s and _size(draw, x, font)[0] > max_w:
            out.append(s)
            s = ch
        else:
            s = x
    if s:
        out.append(s)
    return out or [""]


def _wrap(draw: ImageDraw.ImageDraw, value: object, font, max_w: int) -> list[str]:
    text = "\n".join(str(x) for x in value) if isinstance(value, (list, tuple)) else str(value)
    out = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            out.append("")
            continue
        line = ""
        for word in words:
            parts = _split_word(draw, word, font, max_w)
            for part in parts:
                x = part if not line else f"{line} {part}"
                if line and _size(draw, x, font)[0] > max_w:
                    out.append(line)
                    line = part
                else:
                    line = x
        if line:
            out.append(line)
    return out or [""]


def _line_h(draw: ImageDraw.ImageDraw, font) -> int:
    return int(_size(draw, "Аg", font)[1] * 1.42)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    font,
    fill: str,
    line_h: int,
    width: int | None = None,
    align: str = "left",
) -> None:
    x, y = xy
    for line in lines:
        xx = x
        if width and align != "left":
            w = _size(draw, line, font)[0]
            xx = x + (width - w if align == "right" else (width - w) // 2)
        for s, f in _font_runs(line, font):
            draw.text((xx, y), s, font=f, fill=fill)
            xx += _size(draw, s, f)[0]
        y += line_h


def _header(w: int, s: float, tpl: Template, page: Page, theme: Theme) -> Image.Image:
    tmp = Image.new("RGB", (w, 10), theme.panel_alt)
    draw = ImageDraw.Draw(tmp)
    kind_font = _font(theme, max(12, int(14 * s)), bold=True)
    title_font = _font(theme, max(24, int(36 * s)), bold=True, heading=True)
    sub_font = _font(theme, max(15, int(19 * s)))
    pad = int(28 * s)
    title = page.data.get("title") or page.title or "Без названия"
    subtitle = page.data.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    kind = tpl.label.upper()
    kind_lines = _wrap(draw, kind, kind_font, w - pad * 2)
    title_lines = _wrap(draw, title, title_font, w - pad * 2)
    sub_lines = _wrap(draw, subtitle, sub_font, w - pad * 2) if subtitle else []
    kh = _line_h(draw, kind_font)
    th = _line_h(draw, title_font)
    sh = _line_h(draw, sub_font)
    gap = int(7 * s)
    h = pad + len(kind_lines) * kh + gap + len(title_lines) * th + pad
    if sub_lines:
        h += gap + len(sub_lines) * sh

    img = Image.new("RGB", (w, h), theme.panel_alt)
    draw = ImageDraw.Draw(img)
    y = pad
    _draw_lines(draw, kind_lines, (pad, y), kind_font, theme.accent, kh, w - pad * 2, "center")
    y += len(kind_lines) * kh + gap
    _draw_lines(draw, title_lines, (pad, y), title_font, theme.text, th, w - pad * 2, "center")
    y += len(title_lines) * th
    if sub_lines:
        y += gap
        _draw_lines(
            draw, sub_lines, (pad, y), sub_font, theme.text_secondary, sh, w - pad * 2, "center"
        )
    return img


def _media_path(value: object, root: Path) -> Path | None:
    if not value:
        return None
    raw = Path(str(value))
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_") or not p.is_file():
        return None
    return p


def _picture(
    w: int,
    s: float,
    path: Path,
    caption: object,
    theme: Theme,
) -> Image.Image | None:
    try:
        src = ImageOps.exif_transpose(Image.open(path))
        src.load()
    except Exception:
        return None

    pad = int(20 * s)
    max_h = int(650 * s)
    src.thumbnail((w - pad * 2, max_h), Image.Resampling.LANCZOS)
    if src.mode in {"RGBA", "LA"}:
        base = Image.new("RGBA", src.size, theme.panel_alt)
        base.alpha_composite(src.convert("RGBA"))
        src = base.convert("RGB")
    else:
        src = src.convert("RGB")

    cap_font = _font(theme, max(13, int(16 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = _wrap(tmp, caption, cap_font, w - pad * 2) if caption else []
    lh = _line_h(tmp, cap_font)
    cap_gap = int(8 * s) if lines else 0
    h = pad + src.height + cap_gap + len(lines) * lh + pad
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    x = (w - src.width) // 2
    img.paste(src, (x, pad))
    bw = max(1, int(theme.border_width * s))
    draw.rectangle((x, pad, x + src.width - 1, pad + src.height - 1), outline=theme.image_border, width=bw)
    if lines:
        _draw_lines(
            draw,
            lines,
            (pad, pad + src.height + cap_gap),
            cap_font,
            theme.text_secondary,
            lh,
            w - pad * 2,
            "center",
        )
    return img


def _gallery(
    w: int,
    s: float,
    items: list[tuple[Path, str]],
    theme: Theme,
) -> Image.Image | None:
    pad = int(20 * s)
    gap = int(12 * s)
    cell_w = (w - pad * 2 - gap) // 2
    max_h = int(360 * s)
    pics = []
    for path, caption in items:
        try:
            src = ImageOps.exif_transpose(Image.open(path))
            src.load()
        except Exception:
            continue
        src.thumbnail((cell_w, max_h), Image.Resampling.LANCZOS)
        if src.mode in {"RGBA", "LA"}:
            base = Image.new("RGBA", src.size, theme.panel_alt)
            base.alpha_composite(src.convert("RGBA"))
            src = base.convert("RGB")
        else:
            src = src.convert("RGB")
        pics.append((src, caption, path))

    if not pics:
        return None
    if len(pics) == 1:
        _, caption, path = pics[0]
        return _picture(w, s, path, caption, theme)

    cap_font = _font(theme, max(13, int(16 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lh = _line_h(tmp, cap_font)
    text_pad = int(8 * s)
    prepared = []
    for src, caption, _ in pics:
        lines = _wrap(tmp, caption, cap_font, cell_w - text_pad * 2) if caption else []
        cap_gap = int(8 * s) if lines else 0
        prepared.append((src, lines, src.height + cap_gap + len(lines) * lh))

    rows = [prepared[i : i + 2] for i in range(0, len(prepared), 2)]
    heights = [max(x[2] for x in row) for row in rows]
    h = pad * 2 + sum(heights) + gap * (len(rows) - 1)
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    bw = max(1, int(theme.border_width * s))
    y = pad
    for row, row_h in zip(rows, heights):
        for i, (src, lines, item_h) in enumerate(row):
            if len(row) == 1:
                cell_x = (w - cell_w) // 2
            else:
                cell_x = pad + i * (cell_w + gap)
            x = cell_x + (cell_w - src.width) // 2
            yy = y + (row_h - item_h) // 2
            img.paste(src, (x, yy))
            draw.rectangle(
                (x, yy, x + src.width - 1, yy + src.height - 1),
                outline=theme.image_border,
                width=bw,
            )
            if lines:
                cap_y = yy + src.height + int(8 * s)
                _draw_lines(
                    draw,
                    lines,
                    (cell_x + text_pad, cap_y),
                    cap_font,
                    theme.text_secondary,
                    lh,
                    cell_w - text_pad * 2,
                    "center",
                )
        y += row_h + gap
    return img


def _section_title(w: int, s: float, title: str, theme: Theme) -> Image.Image:
    font = _font(theme, max(17, int(22 * s)), bold=True, heading=True)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad_x = int(22 * s)
    pad_y = int(9 * s)
    lines = _wrap(tmp, title, font, w - pad_x * 2)
    lh = _line_h(tmp, font)
    img = Image.new("RGB", (w, pad_y * 2 + lh * len(lines)), theme.section_bg)
    draw = ImageDraw.Draw(img)
    _draw_lines(draw, lines, (pad_x, pad_y), font, theme.section_text, lh, w - pad_x * 2, "center")
    return img


def _row(w: int, s: float, label: object, value: object, theme: Theme) -> Image.Image:
    label_w = int(w * 0.36)
    pad_x = int(15 * s)
    pad_y = int(11 * s)
    label_font = _font(theme, max(15, int(18 * s)), bold=True)
    value_font = _font(theme, max(16, int(20 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    left = _wrap(tmp, label, label_font, label_w - pad_x * 2)
    right = _wrap(tmp, value, value_font, w - label_w - pad_x * 2)
    lh1 = _line_h(tmp, label_font)
    lh2 = _line_h(tmp, value_font)
    h = max(len(left) * lh1, len(right) * lh2) + pad_y * 2
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, label_w, h), fill=theme.panel_alt)
    draw.line(
        (label_w, 0, label_w, h),
        fill=theme.border,
        width=max(1, int(theme.border_width * s)),
    )
    _draw_lines(draw, left, (pad_x, pad_y), label_font, theme.text_secondary, lh1)
    _draw_lines(draw, right, (label_w + pad_x, pad_y), value_font, theme.text, lh2)
    return img


def _side_rows(w: int, s: float, fields: list[Field], data: dict, theme: Theme) -> Image.Image:
    col_w = w // 2
    pad_x = int(16 * s)
    pad_y = int(13 * s)
    gap = int(10 * s)
    label_font = _font(theme, max(12, int(15 * s)), bold=True)
    value_font = _font(theme, max(16, int(20 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lh1 = _line_h(tmp, label_font)
    lh2 = _line_h(tmp, value_font)
    cols: list[list[tuple[list[str], list[str], int]]] = [[], []]
    heights = [pad_y, pad_y]

    for col in (1, 2):
        for f in fields:
            value = data.get(f.key)
            if f.column != col or value in (None, "", []):
                continue
            labels = _wrap(tmp, f.label.upper(), label_font, col_w - pad_x * 2)
            values = _wrap(tmp, value, value_font, col_w - pad_x * 2)
            h = len(labels) * lh1 + int(3 * s) + len(values) * lh2
            cols[col - 1].append((labels, values, h))
            heights[col - 1] += h + gap

    h = max(max(heights), int(52 * s)) + pad_y
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    draw.line(
        (col_w, 0, col_w, h),
        fill=theme.border,
        width=max(1, int(theme.border_width * s)),
    )
    for i, items in enumerate(cols):
        y = pad_y
        x = i * col_w + pad_x
        for n, (labels, values, item_h) in enumerate(items):
            if n:
                draw.line(
                    (i * col_w + pad_x, y - gap // 2, (i + 1) * col_w - pad_x, y - gap // 2),
                    fill=theme.border,
                    width=max(1, int(theme.border_width * s)),
                )
            _draw_lines(draw, labels, (x, y), label_font, theme.text_secondary, lh1)
            y += len(labels) * lh1 + int(3 * s)
            _draw_lines(draw, values, (x, y), value_font, theme.text, lh2)
            y += len(values) * lh2 + gap
    return img


def _battle_side_rows(
    w: int,
    s: float,
    data: dict,
    root: Path,
    theme: Theme,
) -> Image.Image:
    sides = battle_sides(data)
    col_w = w // 2
    pad = int(14 * s)
    row_pad = int(7 * s)
    gap = int(11 * s)
    flag_w = int(54 * s)
    flag_h = int(36 * s)
    font = _font(theme, max(16, int(20 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lh = _line_h(tmp, font)
    cols = [[], []]
    heights = [pad * 2, pad * 2]

    for i, side in enumerate(sides):
        for member in side:
            flag = None
            path = _media_path(member.get("flag"), root)
            if path:
                try:
                    flag = ImageOps.exif_transpose(Image.open(path))
                    flag.load()
                    flag.thumbnail((flag_w, flag_h), Image.Resampling.LANCZOS)
                    if flag.mode in {"RGBA", "LA"}:
                        base = Image.new("RGBA", flag.size, theme.panel_alt)
                        base.alpha_composite(flag.convert("RGBA"))
                        flag = base.convert("RGB")
                    else:
                        flag = flag.convert("RGB")
                except Exception:
                    flag = None
            text_w = col_w - pad * 2
            if flag:
                text_w -= flag_w + gap
            lines = _wrap(tmp, member["name"], font, max(40, text_w))
            h = max(flag_h if flag else 0, len(lines) * lh) + row_pad * 2
            cols[i].append((flag, lines, h))
            heights[i] += h

    h = max(max(heights), int(64 * s))
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    bw = max(1, int(theme.border_width * s))
    draw.line((col_w, 0, col_w, h), fill=theme.border, width=bw)

    for i, items in enumerate(cols):
        y = pad
        left = i * col_w
        for n, (flag, lines, item_h) in enumerate(items):
            if n:
                draw.line(
                    (left + pad, y, left + col_w - pad, y),
                    fill=theme.border,
                    width=bw,
                )
            yy = y + row_pad
            x = left + pad
            if flag:
                fx = x + (flag_w - flag.width) // 2
                fy = yy + (item_h - row_pad * 2 - flag.height) // 2
                img.paste(flag, (fx, fy))
                draw.rectangle(
                    (fx, fy, fx + flag.width - 1, fy + flag.height - 1),
                    outline=theme.image_border,
                    width=bw,
                )
                x += flag_w + gap
            text_h = len(lines) * lh
            ty = yy + (item_h - row_pad * 2 - text_h) // 2
            _draw_lines(draw, lines, (x, ty), font, theme.text, lh)
            y += item_h
    return img


def _description(w: int, s: float, value: object, theme: Theme) -> Image.Image:
    font = _font(theme, max(16, int(20 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad_x = int(22 * s)
    pad_y = int(18 * s)
    lines = _wrap(tmp, value, font, w - pad_x * 2)
    lh = _line_h(tmp, font)
    img = Image.new("RGB", (w, pad_y * 2 + len(lines) * lh), theme.panel)
    _draw_lines(ImageDraw.Draw(img), lines, (pad_x, pad_y), font, theme.text, lh)
    return img


def _footer(w: int, s: float, theme: Theme) -> Image.Image:
    font = _font(theme, max(11, int(13 * s)), bold=True)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad = int(12 * s)
    lh = _line_h(tmp, font)
    img = Image.new("RGB", (w, pad * 2 + lh), theme.panel_alt)
    _draw_lines(
        ImageDraw.Draw(img),
        ["INFOBOX BOT"],
        (pad, pad),
        font,
        theme.text_secondary,
        lh,
        w - pad * 2,
        "right",
    )
    return img


def _standard_groups(tpl: Template, data: dict):
    skip = {"title", "description", "image_caption"}
    if tpl.subtitle_key:
        skip.add(tpl.subtitle_key)
    names = []
    for f in tpl.fields:
        if f.key not in skip and f.section not in names:
            names.append(f.section)
    for name in names:
        fields = [
            f for f in tpl.fields if f.section == name and f.key not in skip and data.get(f.key) not in (None, "", [])
        ]
        if fields or (tpl.key == "battle" and name == "Стороны" and any(battle_sides(data))):
            yield name, fields


def render_pillow(
    page: Page,
    work_dir: str | Path,
    quality: str,
    output: str | Path,
    watermark: bool = True,
) -> Path:
    root = Path(work_dir).resolve()
    path = Path(output).resolve()
    theme = get_theme(page.theme)
    tpl = get_template(page.type)
    d = page.data
    s = PILLOW_SCALE.get(quality, PILLOW_SCALE["high"])
    card_w = int(820 * s)
    bw = max(1, int(theme.border_width * s))
    inner_w = card_w - bw * 2
    blocks = [_header(inner_w, s, tpl, page, theme)]

    media = []
    for i, value in enumerate(page_images(d)):
        media_path = _media_path(value, root)
        if media_path:
            media.append((media_path, image_caption(d, value, i)))
    if media:
        pic = _gallery(inner_w, s, media, theme)
        if pic:
            blocks.append(pic)

    for title, fields in _standard_groups(tpl, d):
        blocks.append(_section_title(inner_w, s, title, theme))
        if tpl.key == "battle" and title == "Стороны":
            blocks.append(_battle_side_rows(inner_w, s, d, root, theme))
        elif any(f.column for f in fields):
            blocks.append(_side_rows(inner_w, s, fields, d, theme))
        else:
            blocks.extend(_row(inner_w, s, f.label, d[f.key], theme) for f in fields)

    custom = [
        x
        for x in d.get("custom_fields") or []
        if isinstance(x, dict) and x.get("value") not in (None, "")
    ]
    if custom:
        blocks.append(_section_title(inner_w, s, "Дополнительные сведения", theme))
        blocks.extend(_row(inner_w, s, x.get("name", "Поле"), x.get("value", ""), theme) for x in custom)

    for sec in d.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        rows = [
            x
            for x in sec.get("fields") or []
            if isinstance(x, dict) and x.get("value") not in (None, "")
        ]
        if not rows:
            continue
        blocks.append(_section_title(inner_w, s, str(sec.get("title") or "Раздел"), theme))
        blocks.extend(_row(inner_w, s, x.get("name", "Поле"), x.get("value", ""), theme) for x in rows)

    if d.get("description"):
        blocks.append(_section_title(inner_w, s, "Описание", theme))
        blocks.append(_description(inner_w, s, d["description"], theme))
    if watermark:
        blocks.append(_footer(inner_w, s, theme))

    outer = int(26 * s)
    content_h = sum(x.height for x in blocks) + bw * (len(blocks) - 1)
    img = Image.new("RGB", (card_w + outer * 2, content_h + outer * 2 + bw * 2), theme.background)
    draw = ImageDraw.Draw(img)
    x = outer
    y = outer
    draw.rectangle((x, y, x + card_w - 1, y + content_h + bw * 2 - 1), fill=theme.panel, outline=theme.border, width=bw)
    x += bw
    y += bw
    for i, block in enumerate(blocks):
        img.paste(block, (x, y))
        y += block.height
        if i < len(blocks) - 1:
            draw.line((x, y, x + inner_w - 1, y), fill=theme.border, width=bw)
            y += bw

    img.save(path, "PNG", compress_level=6, dpi=(144, 144))
    return path
