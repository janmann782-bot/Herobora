from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Awaitable, TypeVar

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
from locales import tr
from templates import TEMPLATES, Template
from themes import THEMES

CREATE = "➕ Создать"
MY_PAGES = "📚 Мои страницы"
THEMES_BTN = "🎨 Темы"
SETTINGS = "⚙️ Настройки"
HELP = "ℹ️ Помощь"
STATS = "🥰Статистика"
NEWS = "📰 Новость"
T = TypeVar("T")


def ib(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE), KeyboardButton(text=MY_PAGES)],
            [KeyboardButton(text=THEMES_BTN), KeyboardButton(text=SETTINGS)],
            [KeyboardButton(text=STATS), KeyboardButton(text=HELP)],
            [KeyboardButton(text=NEWS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Создать карточку или прислать данные текстом",
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


def image_kb(count: int = 0) -> InlineKeyboardMarkup:
    rows = []
    if count:
        rows.append([ib(f"✅ Готово ({count})", "img:done")])
        for i in range(count):
            rows.append(
                [
                    ib(f"✏️ Подпись {i + 1}", f"img:cap:{i}"),
                    ib(f"🗑 Картинка {i + 1}", f"img:rm:{i}"),
                ]
            )
    else:
        rows.append([ib("⏭ Без изображений", "img:done")])
    rows += [[ib("⬅️ Назад", "img:back")], [ib("❌ Отмена", "flow:cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def page_image_kb(page_id: int, count: int) -> InlineKeyboardMarkup:
    rows = [[ib(f"✅ Готово ({count})", f"pi:{page_id}:done")]]
    for i in range(count):
        rows.append(
            [
                ib(f"✏️ Подпись {i + 1}", f"pi:{page_id}:cap:{i}"),
                ib(f"🗑 Картинка {i + 1}", f"pi:{page_id}:rm:{i}"),
            ]
        )
    rows.append([ib("⬅️ К странице", f"p:o:{page_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_caption_kb(page_id: int | None = None) -> InlineKeyboardMarkup:
    if page_id is None:
        skip, back = "imgcap:skip", "imgcap:back"
    else:
        skip, back = f"pc:{page_id}:skip", f"pc:{page_id}:back"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("⏭ Без подписи", skip)],
            [ib("⬅️ К изображениям", back)],
            [ib("❌ Отмена", "flow:cancel" if page_id is None else f"p:o:{page_id}")],
        ]
    )


def themes_kb(prefix: str, selected: str = "", page_type: str = "") -> InlineKeyboardMarkup:
    from themes import theme_allowed

    rows = []
    for x in THEMES.values():
        if page_type and not theme_allowed(x.key, page_type):
            continue
        mark = "▼ " if x.key == selected else ""
        rows.append([ib(f"{mark}{x.name}", f"{prefix}:{x.key}")])
    rows.append([ib("⬅️ Назад", f"{prefix}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def olddoc_options_kb(page_id: int | None, stains: bool) -> InlineKeyboardMarkup:
    stain_label = "☕️ Следы кружки: вкл" if stains else "☕️ Следы кружки: выкл"
    if page_id is None:
        rows = [
            [ib("🔄 Новый вариант (сид)", "old:reseed")],
            [ib(stain_label, "old:stains")],
            [ib("⬅️ К предпросмотру", "draft:back")],
        ]
    else:
        rows = [
            [ib("🔄 Новый вариант (сид)", f"old:{page_id}:reseed")],
            [ib(stain_label, f"old:{page_id}:stains")],
            [ib("⬅️ К странице", f"p:o:{page_id}")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_kb(page_type: str | None = None, theme: str = "") -> InlineKeyboardMarkup:
    rows = [
        [ib("✅ Сохранить", "draft:save"), ib("✏️ Поля", "draft:fields")],
        [ib("🎨 Сменить тему", "draft:theme"), ib("🖼 Изображения", "draft:image")],
    ]
    if page_type == "battle":
        rows.append([ib("⚔️ Редактор сторон", "draft:sides")])
    if theme == "olddoc" and page_type == "country":
        rows.append([ib("📜 Варианты документа", "draft:olddoc")])
    rows += [
        [ib("➕ Свое поле", "draft:custom"), ib("🧩 Свой раздел", "draft:section")],
        [ib("📤 Экспорт PNG", "draft:export"), ib("📋 Выслать текстом", "draft:text")],
        [ib("❌ Отмена", "draft:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quick_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("👁 Предпросмотр", "quick:preview"), ib("✏️ Проверить поля", "quick:fields")],
            [ib("🎨 Выбрать тему", "quick:theme"), ib("📋 Выслать текстом", "quick:text")],
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
            [ib("🖼 Изображения", "draft:image")],
            [ib("⬅️ К предпросмотру", "draft:back")],
        ]
    else:
        rows += [
            [ib("➕ Свое поле", f"pa:{page_id}:custom"), ib("🧩 Свой раздел", f"pa:{page_id}:section")],
            [ib("🖼 Изображения", f"pa:{page_id}:image")],
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


def page_actions_kb(page_id: int, page_type: str | None = None, theme: str = "") -> InlineKeyboardMarkup:
    rows = [
        [ib("✏️ Изменить", f"p:e:{page_id}"), ib("🎨 Тема", f"p:t:{page_id}")],
    ]
    if page_type == "battle":
        rows.append([ib("⚔️ Редактор сторон", f"p:bs:{page_id}")])
    if theme == "olddoc" and page_type == "country":
        rows.append([ib("📜 Варианты документа", f"p:old:{page_id}")])
    rows += [
        [ib("📤 Экспорт", f"p:x:{page_id}"), ib("📋 Выслать текстом", f"p:txt:{page_id}")],
        [ib("📄 Копия", f"p:c:{page_id}")],
        [ib("🗑 Удалить", f"p:d:{page_id}")],
        [ib("⬅️ Мои страницы", "pages:list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_sides_kb(prefix: str, page_id: int | None = None) -> InlineKeyboardMarkup:
    base = f"bs:{'p:' + str(page_id) if page_id is not None else 'd'}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("◀️ Сторона 1", f"{base}:0"), ib("Сторона 2 ▶️", f"{base}:1")],
            [ib("⬅️ Назад", f"{base}:back")],
        ]
    )


def battle_side_edit_kb(prefix: str, side_i: int, members: list[dict], page_id: int | None = None) -> InlineKeyboardMarkup:
    base = f"bs:{'p:' + str(page_id) if page_id is not None else 'd'}"
    rows = []
    for i, m in enumerate(members):
        name = str(m.get("name") or "Участник")[:22]
        flag = "🚩" if m.get("flag") else "▫️"
        rows.append([
            ib(f"{flag} {name}", f"{base}:{side_i}:e:{i}"),
            ib("🗑", f"{base}:{side_i}:r:{i}"),
        ])
    if len(members) < 10:
        rows.append([ib("➕ Добавить участника", f"{base}:{side_i}:add")])
    rows.append([ib("✏️ Название стороны", f"{base}:{side_i}:name")])
    rows.append([ib("⬅️ К сторонам", f"{base}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_member_kb(prefix: str, side_i: int, member_i: int, page_id: int | None = None) -> InlineKeyboardMarkup:
    base = f"bs:{'p:' + str(page_id) if page_id is not None else 'd'}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("✏️ Имя", f"{base}:{side_i}:name:{member_i}"), ib("🚩 Флаг", f"{base}:{side_i}:flag:{member_i}")],
            [ib("🗑 Удалить", f"{base}:{side_i}:r:{member_i}")],
            [ib("⬅️ К стороне", f"{base}:{side_i}")],
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


def settings_kb(watermark: bool | None = None) -> InlineKeyboardMarkup:
    mark = ""
    if watermark is not None:
        mark = ": вкл" if watermark else ": выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("🎨 Тема по умолчанию", "settings:theme")],
            [ib("🖼 Качество PNG", "settings:quality")],
            [ib(f"🏷 Подпись INFOBOX BOT{mark}", "settings:watermark")],
            [ib("🌐 Язык интерфейса", "settings:language")],
            [ib("📤 Формат экспорта", "settings:format")],
            [ib("🏠 Главное меню", "menu:home")],
        ]
    )


def quality_kb(selected: str) -> InlineKeyboardMarkup:
    names = {"standard": "Обычное", "high": "Высокое", "ultra": "Очень высокое"}
    rows = [
        [ib(("▼ " if k == selected else "") + v, f"quality:{k}")]
        for k, v in names.items()
    ]
    rows.append([ib("⬅️ Назад", "settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def progress_text(percent: int) -> str:
    n = min(100, max(0, percent))
    filled = min(10, max(1, round(n / 10))) if n else 0
    bar = "▓" * filled + "░" * (10 - filled)
    return tr("rendering", bar=bar, percent=n)


async def render_progress(msg: Message, job: Awaitable[T]) -> T:
    task = asyncio.create_task(job)
    for n in (18, 31, 47, 64, 78, 89, 96):
        try:
            res = await asyncio.wait_for(asyncio.shield(task), timeout=0.7)
            with suppress(TelegramBadRequest):
                await msg.edit_text(progress_text(100))
            return res
        except TimeoutError:
            with suppress(TelegramBadRequest):
                await msg.edit_text(progress_text(n))

    res = await task
    with suppress(TelegramBadRequest):
        await msg.edit_text(progress_text(100))
    return res


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
