from __future__ import annotations

from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from models import Page
from templates import TEMPLATES, Template
from themes import THEMES

CREATE = "➕ Создать"
MY_PAGES = "📚 Мои страницы"
THEMES_BTN = "🎨 Темы"
SETTINGS = "⚙️ Настройки"
HELP = "ℹ️ Помощь"


def ib(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE), KeyboardButton(text=MY_PAGES)],
            [KeyboardButton(text=THEMES_BTN), KeyboardButton(text=SETTINGS)],
            [KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Создать карточку или отправить быстрый текст",
    )


def types_kb() -> InlineKeyboardMarkup:
    rows = [
        [ib(f"{x.emoji} {x.label}", f"new:{x.key}")]
        for x in TEMPLATES.values()
    ]
    rows.append([ib("❌ Отмена", "flow:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wizard_kb(can_back: bool = True, can_skip: bool = True) -> InlineKeyboardMarkup:
    row = []
    if can_back:
        row.append(ib("⬅️ Назад", "wiz:back"))
    if can_skip:
        row.append(ib("⏭ Пропустить", "wiz:skip"))
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [ib("❌ Отмена", "flow:cancel")]]
    )


def image_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("⬅️ Назад", "img:back"), ib("⏭ Без изображения", "img:skip")],
            [ib("❌ Отмена", "flow:cancel")],
        ]
    )


def themes_kb(prefix: str, selected: str = "") -> InlineKeyboardMarkup:
    rows = []
    for x in THEMES.values():
        mark = "✓ " if x.key == selected else ""
        rows.append([ib(f"{mark}{x.name}", f"{prefix}:{x.key}")])
    rows.append([ib("⬅️ Назад", f"{prefix}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("✅ Сохранить", "draft:save"), ib("✏️ Поля", "draft:fields")],
            [ib("🎨 Сменить тему", "draft:theme"), ib("🖼 Изображение", "draft:image")],
            [ib("➕ Свое поле", "draft:custom"), ib("🧩 Свой раздел", "draft:section")],
            [ib("📤 Экспорт PNG", "draft:export")],
            [ib("❌ Отмена", "draft:cancel")],
        ]
    )


def quick_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("👁 Предпросмотр", "quick:preview"), ib("✏️ Проверить поля", "quick:fields")],
            [ib("🎨 Выбрать тему", "quick:theme")],
            [ib("❌ Отмена", "flow:cancel")],
        ]
    )


def fields_kb(tpl: Template, data: dict, page_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    btns = []
    for i, f in enumerate(tpl.fields):
        mark = "✓ " if data.get(f.key) not in (None, "", []) else ""
        cb = f"df:{i}" if page_id is None else f"pe:{page_id}:s:{i}"
        btns.append(ib(f"{mark}{f.label}"[:32], cb))
        if len(btns) == 2:
            rows.append(btns)
            btns = []
    if btns:
        rows.append(btns)

    for i, x in enumerate(data.get("custom_fields") or []):
        name = str(x.get("name", "Свое поле"))[:27]
        cb = f"dc:{i}" if page_id is None else f"pe:{page_id}:c:{i}"
        rows.append([ib(f"✓ ✦ {name}", cb)])

    for i, sec in enumerate(data.get("sections") or []):
        title = str(sec.get("title", "Раздел"))[:25]
        if page_id is not None:
            rows.append([ib(f"🧩 {title}", f"pe:{page_id}:h:{i}")])
        for j, x in enumerate(sec.get("fields") or []):
            name = str(x.get("name", "Поле"))[:25]
            cb = f"dx:{i}:{j}" if page_id is None else f"pe:{page_id}:x:{i}:{j}"
            rows.append([ib(f"↳ ✓ {name}", cb)])

    if page_id is None:
        rows += [
            [ib("➕ Свое поле", "draft:custom"), ib("🧩 Свой раздел", "draft:section")],
            [ib("🖼 Изображение", "draft:image")],
            [ib("⬅️ К предпросмотру", "draft:back")],
        ]
    else:
        rows += [
            [ib("➕ Свое поле", f"pa:{page_id}:custom"), ib("🧩 Свой раздел", f"pa:{page_id}:section")],
            [ib("🖼 Изображение", f"pa:{page_id}:image")],
            [ib("⬅️ К странице", f"p:o:{page_id}")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_value_kb(back: str, cancel: str = "flow:cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("⬅️ Назад", back)],
            [ib("❌ Отмена", cancel)],
        ]
    )


def page_actions_kb(page_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("✏️ Изменить", f"p:e:{page_id}"), ib("🎨 Тема", f"p:t:{page_id}")],
            [ib("📤 Экспорт", f"p:x:{page_id}"), ib("📄 Копия", f"p:c:{page_id}")],
            [ib("🗑 Удалить", f"p:d:{page_id}")],
            [ib("⬅️ Мои страницы", "pages:list")],
        ]
    )


def pages_kb(pages: list[Page]) -> InlineKeyboardMarkup:
    rows = []
    for p in pages:
        tpl = TEMPLATES.get(p.type)
        icon = tpl.emoji if tpl else "📄"
        rows.append([ib(f"{icon} {p.title}"[:48], f"p:o:{p.id}")])
    rows.append([ib("🏠 Главное меню", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_kb(page_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("🗑 Да, удалить", f"pd:{page_id}:yes")],
            [ib("⬅️ Нет", f"p:o:{page_id}")],
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("🎨 Тема по умолчанию", "settings:theme")],
            [ib("🖼 Качество PNG", "settings:quality")],
            [ib("🌐 Язык интерфейса", "settings:language")],
            [ib("📤 Формат экспорта", "settings:format")],
            [ib("🏠 Главное меню", "menu:home")],
        ]
    )


def quality_kb(selected: str) -> InlineKeyboardMarkup:
    names = {"standard": "Обычное", "high": "Высокое", "ultra": "Очень высокое"}
    rows = [
        [ib(("✓ " if k == selected else "") + v, f"quality:{k}")]
        for k, v in names.items()
    ]
    rows.append([ib("⬅️ Назад", "settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_png(
    msg: Message,
    path: str | Path,
    caption: str,
    markup: InlineKeyboardMarkup | None = None,
    document: bool = False,
) -> Message:
    f = FSInputFile(path)
    if document:
        return await msg.answer_document(f, caption=caption[:1024], reply_markup=markup)
    try:
        return await msg.answer_photo(f, caption=caption[:1024], reply_markup=markup)
    except TelegramBadRequest:
        return await msg.answer_document(
            FSInputFile(path), caption=caption[:1024], reply_markup=markup
        )
