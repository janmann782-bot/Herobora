from __future__ import annotations

import asyncio
import base64
import html
from pathlib import Path
from uuid import uuid4

from models import Page
from templates import Field, Template, get_template
from themes import Theme, get_theme

QUALITY_SCALE = {"standard": 1.5, "high": 2.0, "ultra": 2.5}
_render_slots = asyncio.Semaphore(2)


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


def standard_sections(tpl: Template, data: dict) -> str:
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
        if any(f.column for f in fields):
            out.append(side_section(name, fields, data))
        else:
            out.append(normal_section(name, fields, data))
    return "".join(out)


def make_html(page: Page, theme: Theme | None = None, work_dir: str | Path = ".") -> str:
    tpl = get_template(page.type)
    theme = theme or get_theme(page.theme)
    d = page.data
    title = d.get("title") or page.title or "Без названия"
    subtitle = d.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    img = image_uri(d.get("image"), work_dir)
    caption = d.get("image_caption", "")
    description = d.get("description", "")

    hero_img = ""
    if img:
        hero_img = f'<figure><img src="{img}" alt=""><figcaption>{value_html(caption)}</figcaption></figure>'
        if not caption:
            hero_img = hero_img.replace("<figcaption></figcaption>", "")

    subtitle_html = f'<div class="subtitle">{value_html(subtitle)}</div>' if subtitle else ""
    desc_html = ""
    if description:
        desc_html = (
            '<section class="description"><h2>Описание</h2>'
            f'<div class="description-text">{value_html(description)}</div></section>'
        )

    body = standard_sections(tpl, d) + custom_fields(d) + custom_sections(d) + desc_html
    vars_ = theme.css_vars()

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<style>
:root {{{vars_}}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: var(--background); color: var(--text); }}
body {{ padding: 26px; font-family: var(--font); font-size: 20px; line-height: 1.42; }}
.sheet {{
  position: relative; width: 820px; overflow: hidden; margin: 0 auto;
  background: var(--panel); border: var(--border-width) solid var(--border);
  border-radius: var(--radius);
}}
.sheet::before {{
  content: ""; position: absolute; inset: 4px; pointer-events: none;
  border: var(--pixel-step) solid var(--accent);
}}
header {{ padding: 24px 28px 20px; text-align: center; background: var(--panel-alt); border-bottom: var(--border-width) solid var(--border); }}
.kind {{ color: var(--accent); font-size: 14px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }}
h1 {{ margin: 5px 0 0; overflow-wrap: anywhere; font: 700 36px/1.16 var(--heading-font); }}
.subtitle {{ margin-top: 9px; color: var(--text-secondary); font-size: 19px; }}
figure {{ margin: 20px 20px 14px; }}
figure img {{
  display: block; width: 100%; max-height: 650px; object-fit: contain;
  background: var(--panel-alt); border: var(--border-width) solid var(--image-border);
  border-radius: var(--radius);
}}
figcaption {{ padding: 8px 8px 0; text-align: center; color: var(--text-secondary); font-size: 16px; }}
section {{ margin: 0; border-top: var(--border-width) solid var(--border); }}
section h2 {{
  margin: 0; padding: 9px 22px; overflow-wrap: anywhere; text-align: center;
  background: var(--section-bg); color: var(--section-text);
  font: 700 22px/1.25 var(--heading-font); letter-spacing: .01em;
}}
.row {{ display: grid; grid-template-columns: minmax(170px, 36%) 1fr; border-top: 1px solid color-mix(in srgb, var(--border), transparent 42%); }}
.row:first-of-type {{ border-top: 0; }}
.label, .value {{ padding: 11px 15px; min-width: 0; overflow-wrap: anywhere; }}
.label {{ color: var(--text-secondary); font-weight: 650; background: var(--panel-alt); border-right: 1px solid var(--border); }}
.side-grid {{ display: grid; grid-template-columns: 1fr 1fr; }}
.side-col {{ min-width: 0; padding: 13px 16px 15px; overflow-wrap: anywhere; }}
.side-col + .side-col {{ border-left: 1px solid var(--border); }}
.side-item + .side-item {{ margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }}
.side-label {{ margin-bottom: 3px; color: var(--text-secondary); font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }}
.description-text {{ padding: 18px 22px 22px; overflow-wrap: anywhere; }}
.footer {{ padding: 12px 18px; text-align: right; color: var(--text-secondary); background: var(--panel-alt); border-top: var(--border-width) solid var(--border); font-size: 13px; letter-spacing: .04em; }}
</style>
</head>
<body>
<article class="sheet" id="infobox">
  <header><div class="kind">{esc(tpl.emoji)} {esc(tpl.label)}</div><h1>{esc(title)}</h1>{subtitle_html}</header>
  {hero_img}
  {body}
  <div class="footer">INFOBOX BOT</div>
</article>
</body>
</html>"""


async def render_page(
    page: Page,
    work_dir: str | Path = ".",
    quality: str = "high",
    output: str | Path | None = None,
) -> Path:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright не установлен. Выполни: pip install -r requirements.txt && playwright install chromium"
        ) from e

    root = Path(work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if output:
        raw_path = Path(output)
        path = raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()
    else:
        path = root / f"preview_{uuid4().hex}.png"
    if path.parent != root:
        raise ValueError("PNG можно сохранять только в рабочую директорию бота.")

    markup = make_html(page, get_theme(page.theme), root)
    scale = QUALITY_SCALE.get(quality, QUALITY_SCALE["high"])

    async with _render_slots, async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=p.chromium.executable_path,
            args=["--disable-dev-shm-usage"],
        )
        try:
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

    return path
