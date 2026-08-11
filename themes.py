from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    key: str
    name: str
    background: str
    panel: str
    panel_alt: str
    text: str
    text_secondary: str
    accent: str
    border: str
    section_bg: str
    section_text: str
    link: str
    font: str
    heading_font: str
    border_width: int = 1
    radius: int = 4
    pixel_border: bool = False
    image_border: str = "#A2A9B1"
    row_alt: str | None = None

    def css_vars(self) -> str:
        d = {
            "background": self.background,
            "panel": self.panel,
            "panel-alt": self.panel_alt,
            "text": self.text,
            "text-secondary": self.text_secondary,
            "accent": self.accent,
            "border": self.border,
            "section-bg": self.section_bg,
            "section-text": self.section_text,
            "link": self.link,
            "font": self.font,
            "heading-font": self.heading_font,
            "border-width": f"{self.border_width}px",
            "radius": f"{self.radius}px",
            "image-border": self.image_border,
            "row-alt": self.row_alt or self.panel,
            "pixel-step": "3px" if self.pixel_border else "0px",
        }
        return ";".join(f"--{k}:{v}" for k, v in d.items())


LIGHT = Theme(
    key="light",
    name="Светлая",
    background="#eef1f4",
    panel="#ffffff",
    panel_alt="#f8f9fa",
    text="#202122",
    text_secondary="#54595d",
    accent="#4f6f91",
    border="#a2a9b1",
    section_bg="#dce8f4",
    section_text="#1f2d3d",
    link="#3366cc",
    font="'InfoBox Sans', Arial, sans-serif",
    heading_font="'InfoBox Sans', Arial, sans-serif",
    radius=5,
)


DARK = Theme(
    key="dark",
    name="Темная",
    background="#111419",
    panel="#1b2027",
    panel_alt="#242b34",
    text="#edf1f5",
    text_secondary="#aeb8c4",
    accent="#7ea6d8",
    border="#46515e",
    section_bg="#293747",
    section_text="#f3f6fa",
    link="#8ab4f8",
    font="'InfoBox Sans', Arial, sans-serif",
    heading_font="'InfoBox Sans', Arial, sans-serif",
    radius=5,
    image_border="#5d6976",
)


AURELIA = Theme(
    key="aurelia",
    name="Aurelia",
    background="#000000",
    panel="#000000",
    panel_alt="#000000",
    text="#a9f38f",
    text_secondary="#a9f38f",
    accent="#a9f38f",
    border="#a9f38f",
    section_bg="#000000",
    section_text="#a9f38f",
    link="#a9f38f",
    font="'Isaac Fill', 'InfoBox Mono', monospace",
    heading_font="'Isaac Fill', 'InfoBox Mono', monospace",
    border_width=3,
    radius=0,
    pixel_border=False,
    image_border="#a9f38f",
    row_alt="#132a18",
)


THEMES = {x.key: x for x in (LIGHT, DARK, AURELIA)}


def get_theme(key: str) -> Theme:
    return THEMES.get(key, LIGHT)
