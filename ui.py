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
SUPEREVENT = "‼️ Суперевент (БЕТА)"
T = TypeVar("T")

# типы с одной картинкой без своих полей
TFR_SIMPLE_TYPES = frozenset({"news", "superevent"})


def ib(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    # style: primary (синяя) / success (зелёная) / danger (красная) — Bot API 9.4+
    kwargs = {"text": text, "callback_data": data}
    if style:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        # старый aiogram без style
        return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE), KeyboardButton(text=MY_PAGES)],
            [KeyboardButton(text=THEMES_BTN), KeyboardButton(text=SETTINGS)],
            [KeyboardButton(text=STATS), KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Создать карточку или прислать данные текстом",
    )


def types_kb() -> InlineKeyboardMarkup:
    rows = []
    for x in TEMPLATES.values():
        style = "primary" if x.key in TFR_SIMPLE_TYPES else None
        rows.append([ib(f"{x.emoji} {x.label}", f"new:{x.key}", style=style)])
    rows.append([ib("❌ Отмена", "flow:cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wizard_kb(can_back: bool = True, can_skip: bool = True) -> InlineKeyboardMarkup:
    row = []
    if can_back:
        row.append(ib("⬅️ Назад", "wiz:back"))
    if can_skip:
        row.append(ib("⏭ Пропустить", "wiz:skip"))
    rows = []
    if row:
        rows.append(row)
    rows.append([ib("❌ Отмена", "flow:cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_kb(count: int = 0, page_type: str = "") -> InlineKeyboardMarkup:
    rows = []
    single = page_type in TFR_SIMPLE_TYPES
    if count:
        rows.append([ib(f"✅ Готово ({count})", "img:done", style="success")])
        for i in range(count):
            if single:
                rows.append([ib("🗑 Убрать картинку", f"img:rm:{i}")])
            else:
                rows.append(
                    [
                        ib(f"✏️ Подпись {i + 1}", f"img:cap:{i}"),
                        ib(f"🗑 Картинка {i + 1}", f"img:rm:{i}"),
                    ]
                )
    else:
        rows.append([ib("⏭ Без картинки" if single else "⏭ Без изображений", "img:done")])
    rows += [[ib("⬅️ Назад", "img:back")], [ib("❌ Отмена", "flow:cancel", style="danger")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def page_image_kb(page_id: int, count: int, page_type: str = "") -> InlineKeyboardMarkup:
    rows = [[ib(f"✅ Готово ({count})", f"pi:{page_id}:done", style="success")]]
    single = page_type in TFR_SIMPLE_TYPES
    for i in range(count):
        if single:
            rows.append([ib("🗑 Убрать картинку", f"pi:{page_id}:rm:{i}")])
        else:
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


def olddoc_options_kb(
    page_id: int | None,
    *,
    stain_count: int = 0,
    paper: int = 0,
    paper_total: int = 6,
    drunk: bool = False,
    drunk_flags: bool = False,
    substances: bool = False,
    window: bool = True,
    outline: bool = True,
    bw: bool = False,
) -> InlineKeyboardMarkup:
    paper_n = (paper % max(1, paper_total)) + 1
    text_label = f"🔤 Текст: {'пьяный' if drunk else 'обычный'}"
    flags_label = f"🏳️ Флаги: {'пьяные' if drunk_flags else 'обычные'}"
    sub_label = f"💊 Под веществами: {'вкл' if substances else 'выкл'}"
    win_label = f"🪟 Окошко: {'вкл' if window else 'выкл'}"
    out_label = f"✏️ Обводка: {'вкл' if outline else 'выкл'}"
    bw_label = f"⬛ ЧБ: {'вкл' if bw else 'выкл'}"
    if page_id is None:
        pfx = "old"
        back = "draft:back"
        back_label = "⬅️ К предпросмотру"
        apply = "old:apply"
    else:
        pfx = f"old:{page_id}"
        back = f"p:o:{page_id}"
        back_label = "⬅️ К странице"
        apply = f"old:{page_id}:apply"
    rows = [
        [ib("🔄 Новый сид", f"{pfx}:reseed")],
        [
            ib("◀️", f"{pfx}:paper_prev"),
            ib(f"📄 Бумага: {paper_n}/{paper_total}", f"{pfx}:paper"),
            ib("▶️", f"{pfx}:paper_next"),
        ],
        [
            ib("◀️", f"{pfx}:cups_prev"),
            ib(f"☕️ Кружки: {stain_count}", f"{pfx}:cups"),
            ib("▶️", f"{pfx}:cups_next"),
        ],
        [ib(text_label, f"{pfx}:text"), ib(flags_label, f"{pfx}:flags")],
        [ib(sub_label, f"{pfx}:sub")],
        [ib(win_label, f"{pfx}:window"), ib(out_label, f"{pfx}:outline")],
        [ib(bw_label, f"{pfx}:bw")],
        [ib("✅ Подтвердить изменения", apply)],
        [ib(back_label, back)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_kb(page_type: str | None = None, theme: str = "") -> InlineKeyboardMarkup:
    rows = [
        [ib("✅ Сохранить", "draft:save", style="success"), ib("✏️ Поля", "draft:fields")],
    ]
    if page_type in TFR_SIMPLE_TYPES:
        rows.append([ib("🖼 Картинка", "draft:image")])
    else:
        rows.append([ib("🎨 Сменить тему", "draft:theme"), ib("🖼 Изображения", "draft:image")])
    if page_type == "battle":
        rows.append([ib("⚔️ Редактор сторон", "draft:sides")])
    if theme == "olddoc" and page_type == "country":
        rows.append([ib("📜 Варианты документа", "draft:olddoc")])
    if page_type not in TFR_SIMPLE_TYPES:
        rows.append([ib("➕ Свое поле", "draft:custom"), ib("🧩 Свой раздел", "draft:section")])
    rows += [
        [ib("📤 Экспорт PNG", "draft:export"), ib("📋 Выслать текстом", "draft:text")],
        [ib("❌ Отмена", "draft:cancel", style="danger")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quick_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("👁 Предпросмотр", "quick:preview"), ib("✏️ Проверить поля", "quick:fields")],
            [ib("🎨 Выбрать тему", "quick:theme"), ib("📋 Выслать текстом", "quick:text")],
            [ib("❌ Отмена", "flow:cancel", style="danger")],
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

    is_news = tpl.key in TFR_SIMPLE_TYPES
    if page_id is None:
        extra = []
        if not is_news:
            extra.append([ib("➕ Свое поле", "draft:custom"), ib("🧩 Свой раздел", "draft:section")])
        extra.append([ib("🖼 Картинка" if is_news else "🖼 Изображения", "draft:image")])
        extra.append([ib("⬅️ К предпросмотру", "draft:back")])
        rows += extra
    else:
        extra = []
        if not is_news:
            extra.append([ib("➕ Свое поле", f"pa:{page_id}:custom"), ib("🧩 Свой раздел", f"pa:{page_id}:section")])
        extra.append([ib("🖼 Картинка" if is_news else "🖼 Изображения", f"pa:{page_id}:image")])
        extra.append([ib("⬅️ К странице", f"p:o:{page_id}")])
        rows += extra
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


DIV = "▬▬ι══════════════ι▬▬"


def box(text: str) -> str:
    """Рамка-разделитель вокруг блока текста."""
    body = (text or "").strip()
    return f"{DIV}\n{body}\n{DIV}"


def quote(text: str) -> str:
    """Цитата (HTML blockquote)."""
    body = (text or "").strip()
    if not body:
        return ""
    # экранируем только если вызывающий не прислал готовый HTML
    return f"<blockquote>{body}</blockquote>"


async def flow_show(
    target,
    state,
    text: str,
    reply_markup=None,
    parse_mode: str | None = "HTML",
    *,
    as_new: bool = False,
):
    """Обновляет одно сообщение мастера вместо спама новыми.

    target — Message или CallbackQuery.
    state  — FSMContext.
    """
    from aiogram.types import CallbackQuery, Message

    msg: Message | None = None
    if isinstance(target, CallbackQuery):
        msg = target.message
    elif isinstance(target, Message):
        msg = target

    d = await state.get_data()
    mid = d.get("flow_message_id")
    chat_id = d.get("flow_chat_id")

    # пробуем edit существующего
    if not as_new and msg is not None and mid and chat_id:
        try:
            if msg.message_id == mid and msg.text is not None:
                await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                return msg
            # другое сообщение — edit по id
            bot = msg.bot
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=mid,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return msg
        except TelegramBadRequest:
            pass
        except Exception:
            pass

    # fallback: новое сообщение
    if isinstance(target, CallbackQuery):
        sent = await target.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        sent = await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    await state.update_data(flow_message_id=sent.message_id, flow_chat_id=sent.chat.id)
    return sent

