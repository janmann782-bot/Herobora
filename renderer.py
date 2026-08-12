from __future__ import annotations

import asyncio
import base64
import html
import logging
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from media import battle_sides, image_caption, page_images
from models import Page
from paper import finish_old_document, paper_css
from templates import Field, Template, get_template
from themes import Theme, get_theme

QUALITY_SCALE = {"standard": 1.5, "high": 2.0, "ultra": 2.5}
_render_slots = asyncio.Semaphore(2)
log = logging.getLogger(__name__)


def esc(x: object) -> str:
    return html.escape(str(x), quote=True)


def value_html(x: object) -> str:
    if isinstance(x, (list, tuple)):
        x = "\n".join(str(i) for i in x)
    return esc(x).replace("\n", "<br>")


def image_uri(path: str | Path | None, work_dir: str | Path) -> str | None:
    if not path:
        return None

    root = Path(work_dir).resolve()
    raw = Path(path)
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_") or not p.is_file():
        return None

    mime = "image/webp"
    if p.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif p.suffix.lower() == ".png":
        mime = "image/png"
    raw = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"


@lru_cache(maxsize=1)
def font_css() -> str:
    root = Path(__file__).resolve().parent
    fonts = (
        ("Isaac Fill", "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF", 400),
        ("InfoBox Sans", "DejaVuSans.ttf", 400),
        ("InfoBox Sans", "DejaVuSans-Bold.ttf", 700),
        ("InfoBox Mono", "DejaVuSansMono.ttf", 400),
        ("InfoBox Mono", "DejaVuSansMono-Bold.ttf", 700),
        ("Old Document Serif", "NIMBUS_ROMAN_REGULAR.otf", 400),
        ("Old Document Serif", "NIMBUS_ROMAN_BOLD.otf", 700),
    )
    out = []
    for family, name, weight in fonts:
        p = root / name
        if not p.is_file():
            continue
        raw = base64.b64encode(p.read_bytes()).decode("ascii")
        is_otf = p.suffix.lower() == ".otf"
        mime = "font/otf" if is_otf else "font/ttf"
        fmt = "opentype" if is_otf else "truetype"
        out.append(
            f"@font-face{{font-family:'{family}';src:url(data:{mime};base64,{raw}) "
            f"format('{fmt}');font-style:normal;font-weight:{weight};}}"
        )
    return "".join(out)


def row(label: str, value: object) -> str:
    return (
        '<div class="row">'
        f'<div class="label">{esc(label)}</div>'
        f'<div class="value">{value_html(value)}</div>'
        "</div>"
    )


def normal_section(title: str, fields: list[Field], data: dict) -> str:
    rows = [row(f.label, data[f.key]) for f in fields if data.get(f.key) not in (None, "", [])]
    if not rows:
        return ""
    return f'<section><h2>{esc(title)}</h2>{"".join(rows)}</section>'


def side_section(title: str, fields: list[Field], data: dict) -> str:
    cells = []
    for col in (1, 2):
        body = []
        for f in fields:
            if f.column == col and data.get(f.key) not in (None, "", []):
                body.append(
                    '<div class="side-item">'
                    f'<div class="side-label">{esc(f.label)}</div>'
                    f'<div>{value_html(data[f.key])}</div>'
                    "</div>"
                )
        cells.append(f'<div class="side-col">{"".join(body)}</div>')

    if not any(data.get(f.key) not in (None, "", []) for f in fields):
        return ""
    return f'<section><h2>{esc(title)}</h2><div class="side-grid">{"".join(cells)}</div></section>'


def battle_side_section(data: dict, work_dir: str | Path) -> str:
    sides = battle_sides(data)
    if not any(sides):
        return ""

    cols = []
    for side in sides:
        members = []
        for x in side:
            flag = image_uri(x.get("flag"), work_dir)
            flag_html = f'<img class="side-flag" src="{flag}" alt="">' if flag else ""
            members.append(
                '<div class="side-member">'
                f'{flag_html}<div>{value_html(x["name"])}</div>'
                "</div>"
            )
        cols.append(f'<div class="side-col">{"".join(members)}</div>')
    return f'<section><h2>Стороны</h2><div class="side-grid battle-sides">{"".join(cols)}</div></section>'


def custom_fields(data: dict) -> str:
    items = data.get("custom_fields") or []
    rows = [
        row(x.get("name", "Поле"), x.get("value", ""))
        for x in items
        if isinstance(x, dict) and x.get("value") not in (None, "")
    ]
    if not rows:
        return ""
    return f'<section><h2>Дополнительные сведения</h2>{"".join(rows)}</section>'


def custom_sections(data: dict) -> str:
    out = []
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        rows = [
            row(x.get("name", "Поле"), x.get("value", ""))
            for x in sec.get("fields") or []
            if isinstance(x, dict) and x.get("value") not in (None, "")
        ]
        if rows:
            out.append(f'<section><h2>{esc(sec.get("title", "Раздел"))}</h2>{"".join(rows)}</section>')
    return "".join(out)


def standard_sections(tpl: Template, data: dict, work_dir: str | Path = ".") -> str:
    skip = {"title", "description", "image_caption"}
    if tpl.subtitle_key:
        skip.add(tpl.subtitle_key)

    names = []
    for f in tpl.fields:
        if f.key not in skip and f.section not in names:
            names.append(f.section)

    out = []
    for name in names:
        fields = [f for f in tpl.fields if f.section == name and f.key not in skip]
        if tpl.key == "battle" and name == "Стороны":
            out.append(battle_side_section(data, work_dir))
        elif any(f.column for f in fields):
            out.append(side_section(name, fields, data))
        else:
            out.append(normal_section(name, fields, data))
    return "".join(out)


def make_html(
    page: Page,
    theme: Theme | None = None,
    work_dir: str | Path = ".",
    watermark: bool = True,
) -> str:
    tpl = get_template(page.type)
    theme = theme or get_theme(page.theme)
    if theme.key == "old_document" and page.type != "country":
        theme = get_theme("light")
    d = page.data
    title = d.get("title") or page.title or "Без названия"
    subtitle = d.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    images = []
    for i, path in enumerate(page_images(d)):
        uri = image_uri(path, work_dir)
        if uri:
            images.append((uri, image_caption(d, path, i)))
    description = d.get("description", "")

    gallery = ""
    if images:
        figures = []
        for img, caption in images:
            cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ""
            figures.append(f'<figure><img src="{img}" alt="">{cap}</figure>')
        mode = "single" if len(figures) == 1 else "multi"
        gallery = f'<div class="gallery {mode}">{"".join(figures)}</div>'

    subtitle_html = f'<div class="subtitle">{value_html(subtitle)}</div>' if subtitle else ""
    desc_html = ""
    if description:
        desc_html = (
            '<section class="description"><h2>Описание</h2>'
            f'<div class="description-text">{value_html(description)}</div></section>'
        )

    body = standard_sections(tpl, d, work_dir) + custom_fields(d) + custom_sections(d) + desc_html
    vars_ = theme.css_vars()
    paper_class = " old-document" if theme.key == "old_document" else ""
    if paper_class:
        vars_ += ";" + paper_css(d)
    footer = '<div class="footer">INFOBOX BOT</div>' if watermark else ""

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'">
<style>
{font_css()}
:root {{{vars_}}}
* {{ box-sizing: border-box; box-shadow: none !important; text-shadow: none !important; }}
html, body {{ margin: 0; padding: 0; background: var(--background); color: var(--text); }}
body {{ padding: 26px; font-family: var(--font); font-size: 20px; line-height: 1.42; }}
.sheet {{
  position: relative; width: 820px; overflow: hidden; margin: 0 auto;
  background: var(--panel); border: var(--border-width) solid var(--border);
  border-radius: var(--radius);
}}
header {{ padding: 24px 28px 20px; text-align: center; background: var(--panel-alt); border-bottom: var(--border-width) solid var(--border); }}
.kind {{ color: var(--accent); font-size: 14px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }}
h1 {{ margin: 5px 0 0; overflow-wrap: anywhere; font: 700 36px/1.16 var(--heading-font); }}
.subtitle {{ margin-top: 9px; color: var(--text-secondary); font-size: 19px; }}
.gallery {{ margin: 20px; }}
.gallery.multi {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.gallery.multi figure:last-child:nth-child(odd) {{ grid-column: 1 / -1; }}
figure {{ min-width: 0; margin: 0; }}
figure img {{
  display: block; width: 100%; max-height: 650px; object-fit: contain;
  background: var(--panel-alt); border: var(--border-width) solid var(--image-border);
  border-radius: var(--radius);
}}
.gallery.multi img {{ height: 360px; }}
figcaption {{ padding: 8px 8px 0; text-align: center; color: var(--text-secondary); font-size: 16px; }}
section {{ margin: 0; border-top: var(--border-width) solid var(--border); }}
section h2 {{
  margin: 0; padding: 9px 22px; overflow-wrap: anywhere; text-align: center;
  background: var(--section-bg); color: var(--section-text);
  font: 700 22px/1.25 var(--heading-font); letter-spacing: .01em;
}}
.row {{ display: grid; grid-template-columns: minmax(170px, 36%) 1fr; border-top: var(--border-width) solid var(--border); }}
.row:first-of-type {{ border-top: 0; }}
.label, .value {{ padding: 11px 15px; min-width: 0; overflow-wrap: anywhere; }}
.label {{ color: var(--text-secondary); font-weight: 650; background: var(--panel-alt); border-right: var(--border-width) solid var(--border); }}
.side-grid {{ display: grid; grid-template-columns: 1fr 1fr; }}
.side-col {{ min-width: 0; padding: 13px 16px 15px; overflow-wrap: anywhere; }}
.side-col + .side-col {{ border-left: var(--border-width) solid var(--border); }}
.side-item + .side-item {{ margin-top: 12px; padding-top: 10px; border-top: var(--border-width) solid var(--border); }}
.side-label {{ margin-bottom: 3px; color: var(--text-secondary); font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }}
.battle-sides .side-col {{ padding: 10px 14px; }}
.side-member {{ display: flex; min-height: 44px; align-items: center; gap: 11px; padding: 7px 0; }}
.side-member + .side-member {{ border-top: var(--border-width) solid var(--border); }}
.side-flag {{
  width: 54px; height: 36px; flex: 0 0 54px; object-fit: contain;
  background: var(--panel-alt); border: var(--border-width) solid var(--image-border);
}}
.description-text {{ padding: 18px 22px 22px; overflow-wrap: anywhere; }}
.footer {{ padding: 12px 18px; text-align: right; color: var(--text-secondary); background: var(--panel-alt); border-top: var(--border-width) solid var(--border); font-size: 13px; letter-spacing: .04em; }}
.sheet.old-document {{ overflow: hidden; }}
.old-document header {{
  padding: 34px 42px 28px; padding-left: calc(42px + var(--paper-header-x));
  text-align: left; background: transparent; border-bottom-style: double;
  border-bottom-width: 4px;
}}
.old-document .kind {{ font-size: 13px; letter-spacing: .18em; }}
.old-document h1 {{
  margin-top: 13px; font-size: 40px; font-weight: 700;
  transform: rotate(var(--paper-title-angle)); transform-origin: left center;
}}
.old-document .subtitle {{ margin-top: 12px; font-size: 20px; font-style: italic; }}
.old-document .gallery {{ margin: 24px 31px 27px; transform: translateX(var(--paper-row-x)); }}
.old-document figure img {{ filter: sepia(.13) contrast(.97); }}
.old-document figcaption {{ font-size: 17px; font-style: italic; }}
.old-document section {{ border-top-color: color-mix(in srgb, var(--border) 72%, transparent); }}
.old-document section h2 {{
  padding: 11px 30px; padding-left: calc(30px + var(--paper-section-x));
  text-align: left; background: transparent; border-bottom: 1px solid var(--border);
  font-size: 23px; letter-spacing: .035em; text-transform: uppercase;
}}
.old-document section:nth-of-type(even) h2 {{ padding-left: calc(36px + var(--paper-section-x)); }}
.old-document .row {{
  grid-template-columns: minmax(170px, var(--paper-label-width)) 1fr;
  transform: translateX(var(--paper-row-x));
}}
.old-document .row:nth-of-type(3n) {{ transform: translateX(calc(var(--paper-row-x) * -.65)); }}
.old-document .row:nth-of-type(4n) {{ transform: translateX(calc(var(--paper-row-x) * .35)); }}
.old-document .label {{
  padding-left: 22px; background: transparent; border-right-style: dotted;
  font-style: italic; font-weight: 700;
}}
.old-document .value {{ padding-left: 19px; }}
.old-document .description-text {{ padding: 21px 33px 27px; text-indent: 22px; }}
.old-document .footer {{ background: transparent; font-family: var(--font); }}
</style>
</head>
<body>
<article class="sheet{paper_class}" id="infobox">
  <header><div class="kind">{esc(tpl.emoji)} {esc(tpl.label)}</div><h1>{esc(title)}</h1>{subtitle_html}</header>
  {gallery}
  {body}
  {footer}
</article>
</body>
</html>"""


async def render_page(
    page: Page,
    work_dir: str | Path = ".",
    quality: str = "high",
    output: str | Path | None = None,
    watermark: bool = True,
) -> Path:
    root = Path(work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if output:
        raw_path = Path(output)
        path = raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()
    else:
        path = root / f"preview_{uuid4().hex}.png"
    if path.parent != root:
        raise ValueError("PNG можно сохранять только в рабочую директорию бота.")

    scale = QUALITY_SCALE.get(quality, QUALITY_SCALE["high"])

    try:
        from playwright.async_api import async_playwright

        async with _render_slots, async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=p.chromium.executable_path,
                args=["--disable-dev-shm-usage"],
            )
            try:
                markup = make_html(page, get_theme(page.theme), root, watermark)
                ctx = await browser.new_context(
                    viewport={"width": 880, "height": 900},
                    device_scale_factor=scale,
                    service_workers="block",
                )
                tab = await ctx.new_page()
                await tab.set_content(markup, wait_until="load")
                await tab.evaluate("document.fonts.ready")
                await tab.wait_for_function("Array.from(document.images).every(x => x.complete)")
                card = tab.locator("#infobox")
                await card.screenshot(path=str(path), type="png", animations="disabled")
                await ctx.close()
            finally:
                await browser.close()
        if page.type == "country" and page.theme == "old_document":
            await asyncio.to_thread(finish_old_document, path, page.data)
    except Exception as chromium_error:
        log.warning("Chromium renderer недоступен, использую Pillow: %s", chromium_error)
        try:
            from pillow_renderer import render_pillow

            await asyncio.to_thread(render_pillow, page, root, quality, path, watermark)
        except Exception as pillow_error:
            a = " ".join(str(chromium_error).split())[:180]
            b = " ".join(str(pillow_error).split())[:180]
            raise RuntimeError(
                f"Не сработали оба renderer. Chromium: {type(chromium_error).__name__}: {a}; "
                f"Pillow: {type(pillow_error).__name__}: {b}"
            ) from pillow_error

    return path


def render_error_text(e: Exception) -> str:
    s = " ".join(str(e).split())
    if not s:
        s = type(e).__name__
    return s[:350]
