from __future__ import annotations

import asyncio
import base64
import html
import logging
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from media import battle_image_groups, image_caption, page_images
from models import Page
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

    def find_font(name: str) -> Path | None:
        candidates = (
            root / name,
            Path("/usr/share/fonts/truetype/liberation") / name,
            Path("/usr/local/share/fonts") / name,
            Path("C:/Windows/Fonts") / name,
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    fonts = (
        ("Isaac Fill", "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF", 400),
        ("Wikipedia Sans", "LiberationSans-Regular.ttf", 400),
        ("Wikipedia Sans", "LiberationSans-Bold.ttf", 700),
        ("Wikipedia Serif", "LiberationSerif-Regular.ttf", 400),
        ("Wikipedia Serif", "LiberationSerif-Bold.ttf", 700),
        ("InfoBox Mono", "LiberationMono-Regular.ttf", 400),
        ("InfoBox Mono", "LiberationMono-Bold.ttf", 700),
    )
    out = []
    for family, name, weight in fonts:
        p = find_font(name)
        if p is None:
            continue
        raw = base64.b64encode(p.read_bytes()).decode("ascii")
        out.append(
            f"@font-face{{font-family:'{family}';src:url(data:font/ttf;base64,{raw}) "
            f"format('truetype');font-style:normal;font-weight:{weight};}}"
        )
    return "".join(out)




def battle_media(data: dict, work_dir: str | Path) -> tuple[tuple[str, str] | None, list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    main_item, side1_items, side2_items, extra_items = battle_image_groups(data)

    def to_uri_list(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        out = []
        for path, cap in items:
            uri = image_uri(path, work_dir)
            if uri:
                out.append((uri, cap))
        return out

    main = None
    if main_item:
        uri = image_uri(main_item[0], work_dir)
        if uri:
            main = (uri, main_item[1])
    extras = []
    for path, caption in extra_items:
        uri = image_uri(path, work_dir)
        if uri:
            extras.append((uri, caption))
    return main, to_uri_list(side1_items), to_uri_list(side2_items), extras


def battle_side_cell(value: object, flags: list[tuple[str, str]], mirror: bool = False) -> str:
    """Each text line is its own row. Flag on left (side1) or right (side2/mirror)."""
    if value in (None, '', []):
        parts = ["—"]
    elif isinstance(value, (list, tuple)):
        parts = [str(x).strip() for x in value if str(x).strip()] or ["—"]
    else:
        parts = [ln.strip() for ln in str(value).splitlines() if ln.strip()] or ["—"]

    uris = [uri for uri, _cap in flags if uri]
    # more lines than flags → title without flag, flags on trailing member lines
    offset = max(0, len(parts) - len(uris))

    row_cls = "side-row side-row-mirror" if mirror else "side-row"
    rows_html = []
    for i, part in enumerate(parts):
        fi = i - offset
        uri = uris[fi] if 0 <= fi < len(uris) else None
        flag_html = f'<img class="mini-flag" src="{uri}" alt="">' if uri else ""
        text_html = f'<div class="battle-text">{value_html(part)}</div>'
        if mirror:
            # text then flag (flag on the right)
            rows_html.append(f'<div class="{row_cls}">{text_html}{flag_html}</div>')
        else:
            rows_html.append(f'<div class="{row_cls}">{flag_html}{text_html}</div>')
    cell_cls = "battle-cell battle-side-name battle-side-mirror" if mirror else "battle-cell battle-side-name"
    return f'<div class="{cell_cls}">' + "".join(rows_html) + "</div>"


def battle_text_cell(value: object) -> str:
    if value in (None, '', []):
        value = '—'
    return f'<div class="battle-cell"><div class="battle-text">{value_html(value)}</div></div>'


def battle_side_section(title: str, left: object, right: object, flags1: list[tuple[str, str]], flags2: list[tuple[str, str]]) -> str:
    if left in (None, '', []) and right in (None, '', []):
        return ''
    return (
        f'<section><h2>{esc(title)}</h2>'
        '<div class="battle-table">'
        f'{battle_side_cell(left, flags1, mirror=False)}'
        f'{battle_side_cell(right, flags2, mirror=True)}'
        '</div></section>'
    )


def battle_two_col_section(title: str, left: object, right: object) -> str:
    if left in (None, '', []) and right in (None, '', []):
        return ''
    return (
        f'<section><h2>{esc(title)}</h2>'
        '<div class="battle-table">'
        f'{battle_text_cell(left)}'
        f'{battle_text_cell(right)}'
        '</div></section>'
    )


def battle_sections(data: dict, work_dir: str | Path) -> tuple[str, str]:
    main, flags1, flags2, extras = battle_media(data, work_dir)
    gallery = ''
    if main:
        img, caption = main
        cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ''
        gallery = f'<div class="gallery single"><figure><img src="{img}" alt="">{cap}</figure></div>'

    top = []
    for label, key in (("Дата", "date"), ("Место", "place"), ("Результат", "result")):
        if data.get(key) not in (None, '', []):
            top.append(row(label, data[key]))

    body = ''.join(top)
    body += battle_side_section('Стороны конфликта', data.get('side_1'), data.get('side_2'), flags1, flags2)
    body += battle_two_col_section('Командующие и лидеры', data.get('commander_1'), data.get('commander_2'))
    body += battle_two_col_section('Силы', data.get('strength_1'), data.get('strength_2'))
    body += battle_two_col_section('Потери', data.get('losses_1'), data.get('losses_2'))

    if extras:
        figures = []
        for img, caption in extras:
            cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ''
            figures.append(f'<figure><img src="{img}" alt="">{cap}</figure>')
        gallery += f'<section><h2>Дополнительные изображения</h2><div class="gallery multi">{"".join(figures)}</div></section>'
    return gallery, body




def resolve_kind_label(tpl: Template, data: dict) -> str:
    value = str(data.get("card_type_label") or "").strip()
    if not value:
        return f"{tpl.emoji} {tpl.label}"
    low = value.casefold().replace("ё", "е").strip()
    if low in {"none", "hide", "hidden", "скрыть", "убрать", "нет", "off", "-"}:
        return ""
    return value.upper()


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


def standard_sections(tpl: Template, data: dict, work_dir: str | Path = ".") -> tuple[str, str]:
    if tpl.key == "battle":
        return battle_sections(data, work_dir)

    skip = {"card_type_label", "title", "description", "image_caption"}
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
    return "", "".join(out)


def stripe_rows(body: str) -> str:
    """Marks every second normal field row across the whole card, not per section."""
    marker = '<div class="row">'
    parts = body.split(marker)
    if len(parts) == 1:
        return body
    out = [parts[0]]
    for i, part in enumerate(parts[1:], start=1):
        cls = 'row row-alt' if i % 2 == 0 else 'row'
        out.append(f'<div class="{cls}">' + part)
    return ''.join(out)

def make_mirotorets_html(
    page: Page,
    theme: Theme,
    work_dir: str | Path = ".",
    watermark: bool = False,
) -> str:
    """Карточка точь-в-точь как на сайте Миротворец, без водяных знаков."""
    d = page.data
    title = str(d.get("title") or page.title or "").strip()
    birth = str(d.get("birth_date") or "").strip()
    country = str(d.get("country") or "Россия").strip()
    rank = str(d.get("rank") or "").strip()
    unit = str(d.get("unit") or "").strip()
    position = str(d.get("position") or "").strip()
    personal = str(d.get("personal_number") or "").strip()
    passport = str(d.get("passport") or "").strip()
    birth_place = str(d.get("birth_place") or "").strip()
    desc = str(
        d.get("description")
        or (
            "Российский военный преступник.\n"
            "Участник нападения фашистской россии на Украину 24.02.2022.\n"
            "В/служащий вооруженных сил российской федерации."
        )
    ).strip()
    hashtags = str(d.get("hashtags") or "#StopRussianAggression").strip()
    footer_text = str(
        d.get("footer")
        or (
            "Центр «Миротворец» просит правоохранительные органы рассматривать данную "
            "публикацию на сайте как заявление о совершении этим гражданином осознанных деяний "
            "против национальной безопасности Украины, мира, безопасности человечества и "
            "международного правопорядка, а также иных правонарушений."
        )
    ).strip()

    # верхний блок: только дата + страна (как на скрине)
    top_meta = []
    if birth:
        top_meta.append(
            f'<div class="top-line"><span class="tl">Дата рождения:</span> '
            f'<span class="tv">{esc(birth)}</span></div>'
        )
    if country:
        top_meta.append(
            f'<div class="top-line"><span class="tl">Страна:</span> '
            f'<span class="tv">{esc(country)}</span></div>'
        )

    # основной текст: описание + поля в том же порядке что на скрине
    body_lines = []
    if title:
        body_lines.append(f'<div class="name-line">{esc(title)}</div>')
    for line in desc.split("\n"):
        line = line.strip()
        if line:
            body_lines.append(f'<div class="line">{esc(line)}</div>')
    if unit:
        body_lines.append(
            f'<div class="line"><span class="lab">Подразделение:</span> {esc(unit)}</div>'
        )
    if position:
        body_lines.append(
            f'<div class="line"><span class="lab">Должность:</span> {esc(position)}</div>'
        )
    if rank:
        body_lines.append(
            f'<div class="line"><span class="lab">Звание:</span> {esc(rank)}</div>'
        )
    if personal:
        body_lines.append(
            f'<div class="line"><span class="lab">Личный номер:</span> {esc(personal)}</div>'
        )
    # дата рождения ещё раз в теле (как на оригинале)
    if birth:
        body_lines.append(
            f'<div class="line"><span class="lab">Дата рождения:</span> {esc(birth)}</div>'
        )
    if passport:
        body_lines.append(
            f'<div class="line"><span class="lab">Паспорт:</span> {esc(passport)}</div>'
        )
    if birth_place:
        body_lines.append(
            f'<div class="line"><span class="lab">Место рождения:</span> {esc(birth_place)}</div>'
        )
    body_lines.append('<div class="line">Источник</div>')

    tags = [t for t in hashtags.split() if t.startswith("#")]
    tags_html = "".join(f'<div class="tag">{esc(t)}</div>' for t in tags)

    # SVG наручники (без emoji)
    cuffs_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 100" width="88" height="74">
  <g fill="none" stroke="#111" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="32" cy="62" r="22"/>
    <circle cx="88" cy="62" r="22"/>
    <path d="M50 48 C58 28 72 28 80 48"/>
    <circle cx="60" cy="36" r="5" fill="#111" stroke="none"/>
  </g>
</svg>"""

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'">
<style>
{font_css()}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  background: #f4f6f9;
  color: #1a1a1a;
  font-family: 'DejaVu Sans', Arial, Helvetica, sans-serif;
}}
body {{ padding: 16px; }}
.card {{
  width: 780px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #b8c0cc;
  overflow: hidden;
}}
.header {{
  height: 36px;
  background: #1a5fb4;
}}
.top-row {{
  display: flex;
  gap: 0;
  border-bottom: 1px solid #c5cdd8;
  background: #fff;
}}
.icon-box {{
  width: 130px;
  flex: 0 0 130px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-right: 1px solid #c5cdd8;
  padding: 14px 10px;
  background: #fff;
}}
.meta-box {{
  flex: 1;
  padding: 16px 18px 14px;
  position: relative;
  background: #fff;
}}
.top-line {{
  font-size: 17px;
  line-height: 1.45;
  margin-bottom: 2px;
}}
.tl {{ color: #222; font-weight: 600; }}
.tv {{ color: #222; }}
.dash {{
  margin-top: 10px;
  border-bottom: 1px dashed #9aa3b0;
  width: 100%;
}}
.body {{
  padding: 16px 20px 18px;
  background: #fff;
  font-size: 16.5px;
  line-height: 1.48;
}}
.name-line {{
  font-weight: 700;
  font-size: 17.5px;
  margin-bottom: 6px;
  color: #111;
}}
.line {{
  margin: 1px 0;
  color: #1a1a1a;
}}
.lab {{ font-weight: 600; }}
.tag {{
  color: #1a1a1a;
  margin: 2px 0;
}}
.footer-red {{
  margin-top: 14px;
  padding-top: 4px;
  color: #c41e3a;
  font-size: 14.5px;
  line-height: 1.42;
  font-weight: 500;
}}
</style>
</head>
<body>
<article class="card" id="infobox">
  <div class="header"></div>
  <div class="top-row">
    <div class="icon-box">{cuffs_svg}</div>
    <div class="meta-box">
      {"".join(top_meta)}
      <div class="dash"></div>
    </div>
  </div>
  <div class="body">
    {"".join(body_lines)}
    {tags_html}
    <div class="footer-red">{esc(footer_text)}</div>
  </div>
</article>
</body>
</html>"""


def make_html(
    page: Page,
    theme: Theme | None = None,
    work_dir: str | Path = ".",
    watermark: bool = True,
) -> str:
    if page.type == "mirotorets" or (theme and theme.key == "mirotorets"):
        return make_mirotorets_html(page, theme or get_theme("mirotorets"), work_dir, watermark=False)

    tpl = get_template(page.type)
    theme = theme or get_theme(page.theme)
    d = page.data
    title = d.get("title") or page.title or "Без названия"
    subtitle = d.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    description = d.get("description", "")

    gallery_extra, body = standard_sections(tpl, d, work_dir)

    gallery = gallery_extra
    if tpl.key != "battle":
        images = []
        for i, path in enumerate(page_images(d)):
            uri = image_uri(path, work_dir)
            if uri:
                images.append((uri, image_caption(d, path, i)))
        if images:
            figures = []
            for img, caption in images:
                cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ""
                figures.append(f'<figure><img src="{img}" alt="">{cap}</figure>')
            mode = "single" if len(figures) == 1 else "multi"
            gallery = f'<div class="gallery {mode}">{"".join(figures)}</div>'

    subtitle_html = f'<div class="subtitle">{value_html(subtitle)}</div>' if subtitle else ""
    kind_label = resolve_kind_label(tpl, d)
    kind_html = f'<div class="kind">{esc(kind_label)}</div>' if kind_label else ""
    desc_html = ""
    if description:
        desc_html = (
            '<section class="description"><h2>Описание</h2>'
            f'<div class="description-text">{value_html(description)}</div></section>'
        )

    body = body + custom_fields(d) + custom_sections(d) + desc_html
    body = stripe_rows(body)
    vars_ = theme.css_vars()
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
h1 {{ margin: 5px 0 0; overflow-wrap: anywhere; font: 700 36px/1.16 var(--heading-font); color: var(--link); }}
.subtitle {{ margin-top: 9px; color: var(--text-secondary); font-size: 19px; }}
a, .wiki-link {{ color: var(--link); text-decoration: none; }}
a:hover, .wiki-link:hover {{ text-decoration: underline; }}
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
.sheet[data-theme="aurelia"] section > .row .label,
.sheet[data-theme="aurelia"] section > .row .value {{ background: var(--panel); }}
.sheet[data-theme="aurelia"] section > .row.row-alt .label,
.sheet[data-theme="aurelia"] section > .row.row-alt .value {{ background: var(--row-alt); }}
.side-grid {{ display: grid; grid-template-columns: 1fr 1fr; }}
.side-col {{ min-width: 0; padding: 13px 16px 15px; overflow-wrap: anywhere; }}
.side-col + .side-col {{ border-left: var(--border-width) solid var(--border); }}
.side-item + .side-item {{ margin-top: 12px; padding-top: 10px; border-top: var(--border-width) solid var(--border); }}
.side-label {{ margin-bottom: 3px; color: var(--text-secondary); font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }}
.battle-table {{ display: grid; grid-template-columns: 1fr 1fr; }}
.battle-cell {{ min-width: 0; padding: 12px 16px 14px; overflow-wrap: anywhere; text-align: left; }}
.battle-cell + .battle-cell {{ border-left: var(--border-width) solid var(--border); }}
.battle-side-name {{
  display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start;
  gap: 8px; text-align: left; font-weight: 700; font-size: 20px; min-height: 0;
}}
.battle-side-mirror {{
  align-items: stretch; text-align: right;
}}
.side-row {{
  display: flex; flex-direction: row; align-items: center; gap: 10px;
  text-align: left; justify-content: flex-start;
}}
.side-row-mirror {{
  justify-content: flex-end; text-align: right;
}}
.side-row-mirror .battle-text {{ text-align: right; }}
.mini-flag {{ width: 34px; height: 22px; object-fit: cover; flex: 0 0 auto; border: 1px solid var(--image-border); background: var(--panel-alt); }}
.battle-text {{ min-width: 0; text-align: left; }}
.description-text {{ padding: 18px 22px 22px; overflow-wrap: anywhere; }}
.footer {{ padding: 12px 18px; text-align: right; color: var(--text-secondary); background: var(--panel-alt); border-top: var(--border-width) solid var(--border); font-size: 13px; letter-spacing: .04em; }}
</style>
</head>
<body>
<article class="sheet" id="infobox" data-theme="{esc(theme.key)}">
  <header>{kind_html}<h1>{esc(title)}</h1>{subtitle_html}</header>
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

    if page.theme == "olddoc":
        from olddoc import render_olddoc

        await asyncio.to_thread(render_olddoc, page, root, quality, path, watermark)
        return path

    if page.type in ("news", "superevent"):
        from pillow_renderer import render_pillow

        await asyncio.to_thread(render_pillow, page, root, quality, path, watermark)
        return path

    if page.type == "mirotorets" or page.theme == "mirotorets":
        watermark = False

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
