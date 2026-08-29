from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from config import Config
from db import Db
from locales import tr
from log_sink import spawn_user_start
from media import safe_unlink
from states import clear_flow
from stats import format_count
from themes import THEMES, get_theme
from ui import (
    CREATE,
    HELP,
    SETTINGS,
    STATS,
    THEMES_BTN,
    main_menu,
    quality_kb,
    fonts_kb,
    settings_kb,
    themes_kb,
    types_kb,
    flow_show,
)

router = Router(name="common")
log = logging.getLogger(__name__)


QUALITY_NAMES = {"standard": "обычное", "high": "высокое", "ultra": "очень высокое"}


async def show_settings(msg: Message, db: Db, user_id: int) -> None:
    s = await db.get_settings(user_id)
    await msg.answer(
        tr(
            "settings",
            theme=get_theme(s.theme).name,
            language="Русский",
            quality=QUALITY_NAMES.get(s.quality, s.quality),
            format=s.export_format.upper(),
            watermark="включена" if s.watermark else "отключена",
            font=getattr(s, "font", "default") or "default",
        ),
        reply_markup=settings_kb(s.watermark),
        parse_mode="HTML",
    )


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await clear_flow(state, msg.from_user.id, db, cfg)
    await db.touch_user(
        msg.from_user.id,
        msg.from_user.first_name or "",
        msg.from_user.username or "",
    )
    spawn_user_start(bot, cfg, msg.from_user)
    await msg.answer(tr("welcome"), reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("help"))
@router.message(F.text == HELP)
async def help_message(msg: Message) -> None:
    await msg.answer(tr("help"), reply_markup=main_menu(), parse_mode="HTML")




@router.message(Command("create"))
@router.message(F.text == CREATE)
async def create(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    from admin import is_admin
    await clear_flow(state, msg.from_user.id, db, cfg)
    await flow_show(msg, state, tr("choose_type"), types_kb(admin=is_admin(msg.from_user.id)), as_new=True)


@router.message(Command("cancel"))
async def cancel(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    await clear_flow(state, msg.from_user.id, db, cfg)
    await msg.answer(tr("cancelled"), reply_markup=main_menu())


@router.message(Command("stats"))
@router.message(F.text == STATS)
async def statistics(msg: Message, db: Db) -> None:
    await db.touch_user(
        msg.from_user.id,
        msg.from_user.first_name or "",
        msg.from_user.username or "",
    )
    total, own = await db.get_generation_stats(msg.from_user.id)
    await msg.answer(
        "🥰 <b>Статистика</b>\n\n"
        f"Всего генераций: <b>{format_count(total)}</b>\n"
        f"Твои генерации: <b>{format_count(own)}</b>\n\n"
        "<i>Считается первое успешное создание новой карточки даже если её потом не сохранять</i>",
        parse_mode="HTML",
    )


@router.message(Command("settings"))
@router.message(F.text == SETTINGS)
async def settings(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    await clear_flow(state, msg.from_user.id, db, cfg)
    await show_settings(msg, db, msg.from_user.id)


@router.message(Command("themes"))
@router.message(F.text == THEMES_BTN)
async def themes(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    await clear_flow(state, msg.from_user.id, db, cfg)
    s = await db.get_settings(msg.from_user.id)
    await msg.answer(tr("settings_theme"), reply_markup=themes_kb("st", s.theme), parse_mode="HTML")


@router.callback_query(F.data == "menu:home")
async def home(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await clear_flow(state, q.from_user.id, db, cfg)
    await q.message.answer(tr("welcome"), reply_markup=main_menu(), parse_mode="HTML")


@router.callback_query(F.data == "settings:back")
async def settings_back(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    await show_settings(q.message, db, q.from_user.id)


@router.callback_query(F.data == "settings:theme")
async def settings_theme(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    s = await db.get_settings(q.from_user.id)
    await q.message.answer(tr("settings_theme"), reply_markup=themes_kb("st", s.theme), parse_mode="HTML")


@router.callback_query(F.data.startswith("st:"))
async def save_default_theme(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    value = q.data.split(":", 1)[1]
    if value == "back":
        await show_settings(q.message, db, q.from_user.id)
        return
    if value not in THEMES:
        return
    s = await db.get_settings(q.from_user.id)
    s.theme = value
    await db.save_settings(s)
    await q.message.answer(tr("settings_saved"))
    await show_settings(q.message, db, q.from_user.id)


@router.callback_query(F.data == "settings:quality")
async def settings_quality(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    s = await db.get_settings(q.from_user.id)
    await q.message.answer(tr("settings_quality"), reply_markup=quality_kb(s.quality), parse_mode="HTML")


@router.callback_query(F.data.startswith("quality:"))
async def save_quality(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    value = q.data.split(":", 1)[1]
    if value not in QUALITY_NAMES:
        return
    s = await db.get_settings(q.from_user.id)
    s.quality = value
    await db.save_settings(s)
    await q.message.answer(tr("settings_saved"))
    await show_settings(q.message, db, q.from_user.id)


@router.callback_query(F.data == "settings:watermark")
async def toggle_watermark(q: CallbackQuery, db: Db, cfg: Config) -> None:
    await q.answer()
    s = await db.get_settings(q.from_user.id)
    s.watermark = not s.watermark
    await db.save_settings(s)
    for path in await db.clear_previews(q.from_user.id):
        safe_unlink(path, cfg.work_dir, "preview_")
    state = "включена" if s.watermark else "отключена"
    await q.message.answer(tr("watermark_saved", state=state))
    await show_settings(q.message, db, q.from_user.id)


@router.callback_query(F.data == "settings:language")
async def language_info(q: CallbackQuery) -> None:
    await q.answer(tr("only_ru"), show_alert=True)


@router.callback_query(F.data == "settings:format")
async def format_info(q: CallbackQuery) -> None:
    await q.answer(tr("only_png"), show_alert=True)


async def on_error(event: ErrorEvent) -> bool:
    e = event.exception
    log.error(
        "unhandled update error",
        exc_info=(type(e), e, e.__traceback__),
    )
    msg = event.update.message
    if not msg and event.update.callback_query:
        msg = event.update.callback_query.message
    if msg:
        try:
            await msg.answer(tr("unexpected_error"), reply_markup=main_menu())
        except Exception:
            log.exception("could not report error to telegram")
    return True


@router.callback_query(F.data == "settings:font")
async def settings_font(q: CallbackQuery, db: Db, cfg: Config) -> None:
    await q.answer()
    s = await db.get_settings(q.from_user.id)
    from fonts_catalog import all_font_choices
    choices = all_font_choices(cfg.work_dir, q.from_user.id)
    cur = getattr(s, "font", "default") or "default"
    name = next((n for k, n in choices if k == cur), cur)
    await q.message.answer(
        f"▬▬ι══════════════ι▬▬\nШрифт карточек\n▬▬ι══════════════ι▬▬\nСейчас: {name}\nВыбери из списка, ищи по имени/номеру или загрузи свой TTF/OTF",
        reply_markup=fonts_kb(choices, cur, 0),
    )


@router.callback_query(F.data.startswith("font:page:"))
async def font_page(q: CallbackQuery, db: Db, cfg: Config) -> None:
    await q.answer()
    try:
        page = int(q.data.split(":")[-1])
    except ValueError:
        return
    s = await db.get_settings(q.from_user.id)
    from fonts_catalog import all_font_choices
    choices = all_font_choices(cfg.work_dir, q.from_user.id)
    cur = getattr(s, "font", "default") or "default"
    await q.message.edit_reply_markup(reply_markup=fonts_kb(choices, cur, page))


@router.callback_query(F.data == "font:noop")
async def font_noop(q: CallbackQuery) -> None:
    await q.answer()


@router.callback_query(F.data.startswith("font:set:"))
async def font_set(q: CallbackQuery, db: Db, cfg: Config) -> None:
    key = q.data.split(":", 2)[-1]
    s = await db.get_settings(q.from_user.id)
    s.font = key
    await db.save_settings(s)
    from fonts_catalog import all_font_choices
    choices = all_font_choices(cfg.work_dir, q.from_user.id)
    name = next((n for k, n in choices if k == key), key)
    await q.answer(f"Шрифт: {name}")
    await q.message.answer(f"Шрифт карточек: {name}")


@router.callback_query(F.data == "font:upload")
async def font_upload_start(q: CallbackQuery, state: FSMContext) -> None:
    from states import FontUpload
    await q.answer()
    await state.set_state(FontUpload.wait)
    await q.message.answer(
        "▬▬ι══════════════ι▬▬\nСвой шрифт\n▬▬ι══════════════ι▬▬\nКинь файл .ttf или .otf (до 5 МБ)\nИли /cancel"
    )


@router.message(F.document)
async def font_upload_file(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    from states import FontUpload
    cur = await state.get_state()
    if cur != FontUpload.wait.state:
        return  # not in upload mode - ignore
    doc = msg.document
    if not doc:
        return
    name = (doc.file_name or "").lower()
    if not (name.endswith(".ttf") or name.endswith(".otf")):
        await msg.answer("Нужен файл .ttf или .otf")
        return
    if (doc.file_size or 0) > 5 * 1024 * 1024:
        await msg.answer("Слишком большой файл (макс 5 МБ)")
        return
    from io import BytesIO
    from fonts_catalog import user_fonts_dir
    buf = BytesIO()
    await msg.bot.download(doc, destination=buf)
    folder = user_fonts_dir(cfg.work_dir, msg.from_user.id)
    # safe name
    safe = "".join(c for c in (doc.file_name or "font.ttf") if c.isalnum() or c in "._-")[:80]
    if not safe.lower().endswith((".ttf", ".otf")):
        safe += ".ttf"
    path = folder / safe
    path.write_bytes(buf.getvalue())
    key = f"user:{safe}"
    s = await db.get_settings(msg.from_user.id)
    s.font = key
    await db.save_settings(s)
    await state.clear()
    await msg.answer(f"Шрифт загружен и выбран: {safe}")


@router.callback_query(F.data == "font:search")
async def font_search_start(q: CallbackQuery, state: FSMContext) -> None:
    from states import FontSearch
    await q.answer()
    await state.set_state(FontSearch.wait)
    await q.message.answer(
        "▬▬ι══════════════ι▬▬\nПоиск шрифта\n▬▬ι══════════════ι▬▬\nНапиши название (roboto, noto) или номер из списка\nИли /cancel"
    )


from states import FontSearch as _FontSearch


@router.message(_FontSearch.wait, F.text)
async def font_search_query(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    text = (msg.text or "").strip()
    if not text or text.startswith("/"):
        await msg.answer("Напиши название или номер")
        return
    from fonts_catalog import search_fonts
    found = search_fonts(cfg.work_dir, msg.from_user.id, text)
    await state.clear()
    if not found:
        await msg.answer("Ничего не нашёл. Попробуй другое имя или номер")
        return
    if text.isdigit() and len(found) == 1:
        _num, key, name = found[0]
        s = await db.get_settings(msg.from_user.id)
        s.font = key
        await db.save_settings(s)
        await msg.answer(f"Шрифт: {name}")
        return
    choices = [(k, name) for n, k, name in found]
    s = await db.get_settings(msg.from_user.id)
    cur_font = getattr(s, "font", "default") or "default"
    await msg.answer(
        f"Найдено: {len(found)}\nВыбери:",
        reply_markup=fonts_kb(choices, cur_font, 0, per_page=10),
    )

