from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message

from media import image_caption, page_images
from models import Page
from templates import get_template

TELEGRAM_TEXT_LIMIT = 3900


def _clean(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(str(x) for x in value).strip()
    return str(value).strip()


def page_to_text(page: Page) -> str:
    """Собирает только пользовательский текст страницы, без внутренних путей к файлам."""
    tpl = get_template(page.type)
    d = page.data
    lines = [tpl.label.upper()]

    for field in tpl.fields:
        if field.key == "image_caption":
            continue
        value = d.get(field.key)
        if field.key == "title" and value in (None, "", []):
            value = page.title
        if value in (None, "", []):
            continue
        lines.append(f"{field.label}: {_clean(value)}")

    custom = [
        x for x in d.get("custom_fields") or []
        if isinstance(x, dict) and x.get("value") not in (None, "", [])
    ]
    if custom:
        lines.append("")
        lines.append("ДОПОЛНИТЕЛЬНЫЕ СВЕДЕНИЯ")
        for item in custom:
            lines.append(f"{_clean(item.get('name') or 'Поле')}: {_clean(item.get('value', ''))}")

    for section in d.get("sections") or []:
        if not isinstance(section, dict):
            continue
        rows = [
            x for x in section.get("fields") or []
            if isinstance(x, dict) and x.get("value") not in (None, "", [])
        ]
        if not rows:
            continue
        lines.append("")
        lines.append(_clean(section.get("title") or "РАЗДЕЛ").upper())
        for item in rows:
            lines.append(f"{_clean(item.get('name') or 'Поле')}: {_clean(item.get('value', ''))}")

    captions = []
    for i, path in enumerate(page_images(d)):
        caption = image_caption(d, path, i)
        if caption:
            captions.append(f"Изображение {i + 1}: {caption}")
    if captions:
        lines.append("")
        lines.append("ПОДПИСИ К ИЗОБРАЖЕНИЯМ")
        lines.extend(captions)

    return "\n".join(lines).strip()


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = line if not current else current + "\n" + line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


async def send_page_text(
    msg: Message,
    page: Page,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    chunks = split_text(page_to_text(page))
    for i, chunk in enumerate(chunks):
        await msg.answer(chunk, reply_markup=markup if i == len(chunks) - 1 else None)
