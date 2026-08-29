"""Каталог шрифтов: в корне проекта (gf-*.ttf) + пользовательские."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_DISPLAY = {
    "roboto": "Roboto",
    "open-sans": "Open Sans",
    "montserrat": "Montserrat",
    "source-sans-3": "Source Sans 3",
    "nunito": "Nunito",
    "raleway": "Raleway",
    "pt-sans": "PT Sans",
    "ubuntu": "Ubuntu",
    "noto-sans": "Noto Sans",
    "rubik": "Rubik",
    "manrope": "Manrope",
    "inter": "Inter",
    "oswald": "Oswald",
    "mukta": "Mukta",
    "fira-sans": "Fira Sans",
    "josefin-sans": "Josefin Sans",
    "barlow": "Barlow",
    "dm-sans": "DM Sans",
    "outfit": "Outfit",
    "plus-jakarta-sans": "Plus Jakarta Sans",
    "merriweather": "Merriweather",
    "lora": "Lora",
    "pt-serif": "PT Serif",
    "source-serif-4": "Source Serif 4",
    "eb-garamond": "EB Garamond",
    "spectral": "Spectral",
    "crimson-pro": "Crimson Pro",
    "roboto-mono": "Roboto Mono",
    "source-code-pro": "Source Code Pro",
    "ibm-plex-mono": "IBM Plex Mono",
    "jetbrains-mono": "JetBrains Mono",
    "comfortaa": "Comfortaa",
    "orbitron": "Orbitron",
    "exo-2": "Exo 2",
    "russo-one": "Russo One",
    "unbounded": "Unbounded",
    "alegreya": "Alegreya",
    "alegreya-sans": "Alegreya Sans",
    "archivo": "Archivo",
    "bitter": "Bitter",
    "cabin": "Cabin",
    "cuprum": "Cuprum",
    "didact-gothic": "Didact Gothic",
    "ibm-plex-sans": "IBM Plex Sans",
    "jost": "Jost",
    "karla": "Karla",
    "lobster": "Lobster",
    "mulish": "Mulish",
    "philosopher": "Philosopher",
    "noto-serif": "Noto Serif",
    "literata": "Literata",
    "lexend": "Lexend",
    "commissioner": "Commissioner",
    "golos-text": "Golos Text",
    "onest": "Onest",
    "ysabeau": "Ysabeau",
    "martian-mono": "Martian Mono",
    "ubuntu-mono": "Ubuntu Mono",
    "noto-sans-mono": "Noto Sans Mono",
    "geologica": "Geologica",
    "neucha": "Neucha",
    "bad-script": "Bad Script",
    "marck-script": "Marck Script",
    "poiret-one": "Poiret One",
    "jura": "Jura",
    "underdog": "Underdog",
    "viaoda-libre": "Viaoda Libre",
    "yeseva-one": "Yeseva One",
    "cormorant": "Cormorant",
    "cormorant-garamond": "Cormorant Garamond",
    "ibm-plex-serif": "IBM Plex Serif",
    "newsreader": "Newsreader",
    "dejavu-sans": "DejaVu Sans",
    "liberation-serif": "Liberation Serif",
    "pixeloid-sans": "Pixeloid Sans",
    "default": "По умолчанию (тема)",
}


def _family_from_file(name: str) -> str:
    stem = name
    if stem.lower().startswith("gf-"):
        stem = stem[3:]
    m = re.match(r"^(.+)-(\d+)\.(ttf|otf)$", stem, re.I)
    if m:
        return m.group(1).lower()
    return Path(stem).stem.lower()


def _iter_root_font_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.glob("gf-*.ttf"):
        if p.stat().st_size >= 3000:
            out.append(p)
    for p in ROOT.glob("gf-*.otf"):
        if p.stat().st_size >= 3000:
            out.append(p)
    return out


def list_bundled_families() -> list[tuple[str, str]]:
    fams: dict[str, Path] = {}
    for p in _iter_root_font_files():
        key = _family_from_file(p.name)
        fams.setdefault(key, p)
    for local, key in [
        ("DejaVuSans.ttf", "dejavu-sans"),
        ("LiberationSerif-Regular.ttf", "liberation-serif"),
        ("PixeloidSans.otf", "pixeloid-sans"),
    ]:
        if (ROOT / local).is_file():
            fams.setdefault(key, ROOT / local)
    items = [("default", _DISPLAY["default"])]
    for k in sorted(fams.keys()):
        items.append((k, _DISPLAY.get(k, k.replace("-", " ").title())))
    return items


def resolve_font_files(family_key: str) -> tuple[Path | None, Path | None]:
    if not family_key or family_key == "default":
        return None, None
    regular = bold = None
    for w, target in [(400, "regular"), (700, "bold"), (500, "regular")]:
        for name in (f"gf-{family_key}-{w}.ttf", f"{family_key}-{w}.ttf"):
            p = ROOT / name
            if p.is_file() and p.stat().st_size > 3000:
                if target == "regular" and regular is None:
                    regular = p
                if target == "bold":
                    bold = p
    if regular is None:
        for p in sorted(ROOT.glob(f"gf-{family_key}-*.ttf")) + sorted(ROOT.glob(f"{family_key}-*.ttf")):
            if p.stat().st_size > 3000:
                regular = p
                break
    if family_key == "dejavu-sans":
        regular = regular or ROOT / "DejaVuSans.ttf"
        bold = bold or ROOT / "DejaVuSans-Bold.ttf"
    if family_key == "liberation-serif":
        regular = regular or ROOT / "LiberationSerif-Regular.ttf"
        bold = bold or ROOT / "LiberationSerif-Bold.ttf"
    if family_key == "pixeloid-sans":
        regular = regular or ROOT / "PixeloidSans.otf"
        bold = bold or ROOT / "PixeloidSans-Bold.otf"
    if bold is None:
        bold = regular
    return regular, bold


def user_fonts_dir(work_dir: str | Path, user_id: int) -> Path:
    d = Path(work_dir).resolve() / "user_fonts" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_user_fonts(work_dir: str | Path, user_id: int) -> list[tuple[str, str]]:
    d = user_fonts_dir(work_dir, user_id)
    out = []
    for p in sorted(d.glob("*")):
        if p.suffix.lower() in {".ttf", ".otf"} and p.stat().st_size > 1000:
            key = f"user:{p.name}"
            out.append((key, f"Свой: {p.stem}"))
    return out


def resolve_user_font(work_dir: str | Path, user_id: int, key: str) -> Path | None:
    if not key.startswith("user:"):
        return None
    name = key[5:]
    p = user_fonts_dir(work_dir, user_id) / name
    if p.is_file() and p.suffix.lower() in {".ttf", ".otf"}:
        return p
    return None


def all_font_choices(work_dir: str | Path, user_id: int | None) -> list[tuple[str, str]]:
    items = list_bundled_families()
    if user_id is not None:
        items.extend(list_user_fonts(work_dir, user_id))
    return items


def numbered_font_choices(work_dir: str | Path, user_id: int | None) -> list[tuple[int, str, str]]:
    return [(i + 1, k, n) for i, (k, n) in enumerate(all_font_choices(work_dir, user_id))]


def search_fonts(work_dir: str | Path, user_id: int | None, query: str) -> list[tuple[int, str, str]]:
    items = numbered_font_choices(work_dir, user_id)
    q = (query or "").strip()
    if not q:
        return items
    if q.isdigit():
        n = int(q)
        return [x for x in items if x[0] == n]
    low = q.casefold().replace("ё", "е")
    out = []
    for num, key, name in items:
        if low in name.casefold().replace("ё", "е") or low in key.casefold():
            out.append((num, key, name))
    return out


def font_css_for_family(family_key: str, work_dir: str | Path = ".", user_id: int | None = None) -> str:
    if not family_key or family_key == "default":
        return ""
    import base64

    if family_key.startswith("user:") and user_id is not None:
        path = resolve_user_font(work_dir, user_id, family_key)
        if not path:
            return ""
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        fmt = "opentype" if path.suffix.lower() == ".otf" else "truetype"
        return (
            f"@font-face{{font-family:'UserFont';src:url('data:font/{fmt};base64,{data}') format('{fmt}');"
            f"font-weight:400 700;font-style:normal;font-display:block}}"
        )
    reg, bold = resolve_font_files(family_key)
    if not reg:
        return ""
    parts = []
    for path, weight in ((reg, 400), (bold or reg, 700)):
        if not path or not path.is_file():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        fmt = "opentype" if path.suffix.lower() == ".otf" else "truetype"
        parts.append(
            f"@font-face{{font-family:'CustomCard';src:url('data:font/{fmt};base64,{data}') format('{fmt}');"
            f"font-weight:{weight};font-style:normal;font-display:block}}"
        )
    return "\n".join(parts)


def css_family_name(family_key: str) -> str:
    if not family_key or family_key == "default":
        return ""
    if family_key.startswith("user:"):
        return "UserFont"
    return "CustomCard"
