from __future__ import annotations

import logging
from contextlib import suppress
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from battle_sides import MAX_SIDE_MEMBERS, member, members_text, normalize_sides, save_sides, side_label
from config import Config
from db import Db
from locales import tr
from media import BadImage, image_caption, page_images, safe_unlink, save_image
from renderer import render_page
from states import EditPage, NewPage
from ui import (
    battle_member_kb,
    battle_side_edit_kb,
    battle_sides_kb,
    draft_kb,
    page_actions_kb,
    render_progress,
    progress_text,
    send_png,
)
from themes import get_theme

router = Router(name="battle")
log = logging.getLogger(__name__)


def _base(page_id: int | None) -> str:
    return f"bs:p:{page_id}" if page_id is not None else "bs:d"


async def _render_saved(msg: Message, p, db: Db, cfg: Config) -> None:
    wait = await msg.answer(progress_text(8))
    try:
        s = await db.get_settings(p.owner_id)
        path = await render_progress(
            wait,
            render_page(p, cfg.work_dir, s.quality, watermark=s.watermark),
        )
        p.preview_path = path.name
        await db.update_page(p)
        await send_png(
            msg,
            path,
            tr("page_caption", title=p.title, theme=get_theme(p.theme).name),
            page_actions_kb(p.id, p.type),
        )
    except Exception as e:
        log.exception("battle side render failed page=%s", p.id)
        await msg.answer(tr("render_error", error=str(e)[:300]))
    finally:
        with suppress(TelegramBadRequest):
            await wait.delete()


def _side_text(sides: list[dict], i: int) -> str:
    side = sides[i]
    body = members_text(side)
    if body:
        return f"{side_label(sides, i)}\n{body}"
    return side_label(sides, i)


async def _show_sides(message: Message, data: dict, page_id: int | None) -> None:
    text = tr("battle_sides_title")
    sides = normalize_sides(data)
    text += f"\n\n1. {side_label(sides, 0)}"
    text += f"\n{members_text(sides[0]) or 'Пока пусто'}"
    text += f"\n\n2. {side_label(sides, 1)}"
    text += f"\n{members_text(sides[1]) or 'Пока пусто'}"
    await message.answer(text, reply_markup=battle_sides_kb("p" if page_id is not None else "d", page_id))


async def _show_side(message: Message, data: dict, side_i: int, page_id: int | None) -> None:
    sides = normalize_sides(data)
    side = sides[side_i]
    text = f"⚔️ {side_label(sides, side_i)}"
    if side.get("members"):
        text += "\n\n" + "\n".join(
            f"{i + 1}. {'🚩' if m.get('flag') else '▫️'} {m['name']}"
            for i, m in enumerate(side["members"])
        )
    else:
        text += "\n\nПока нет участников"
    await message.answer(
        text,
        reply_markup=battle_side_edit_kb("p" if page_id is not None else "d", side_i, side["members"], page_id),
    )


async def _open_member(message: Message, data: dict, side_i: int, member_i: int, page_id: int | None) -> None:
    sides = normalize_sides(data)
    m = member(sides, side_i, member_i)
    if not m:
        return
    flag = "есть" if m.get("flag") else "нет"
    text = f"{m['name']}\nФлаг: {flag}"
    await message.answer(text, reply_markup=battle_member_kb("p" if page_id is not None else "d", side_i, member_i, page_id))


async def _invalidate_saved(p, db: Db, cfg: Config) -> None:
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.preview_path = None
    await db.update_page(p)


async def _remove_flag(path: str | None, user_id: int, db: Db, cfg: Config, saved: bool) -> None:
    if not path:
        return
    ok = await (db.drop_media_if_unused(path, user_id) if saved else db.drop_unattached_media(path, user_id))
    if ok:
        safe_unlink(path, cfg.work_dir, "media_")


async def _save_sides_data(data: dict, sides: list[dict]) -> None:
    save_sides(data, sides)


async def _handle_cb(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot, page_id: int | None) -> None:
    prefix = _base(page_id)
    raw = q.data
    if not raw.startswith(prefix + ":"):
        return
    await q.answer()
    parts = raw.split(":")
    data = None
    p = None
    if page_id is not None:
        p = await db.get_page(page_id, q.from_user.id)
        if not p or p.type != "battle":
            return
        data = p.data
    else:
        data = (await state.get_data()).get("page_data") or {}
        if (await state.get_data()).get("type") != "battle":
            return

    action = parts[3] if page_id is not None else parts[2]
    args = parts[4:] if page_id is not None else parts[3:]
    if action == "back" and not args:
        if page_id is None:
            from create_handlers import show_preview
            await show_preview(q.message, state, db, cfg, bot, q.from_user)
        else:
            await _render_saved(q.message, p, db, cfg)
        return
    if action.isdigit() and not args:
        await _show_side(q.message, data, int(action), page_id)
        return
    if not args:
        return
    side_i = int(action)
    op = args[0]
    if op == "skip":
        await _skip_flag(q, state, db, cfg, bot, page_id is not None)
        return
    if op == "cancel":
        await q.message.answer(tr("cancelled"))
        await state.clear()
        return
    if op == "add":
        if len(normalize_sides(data)[side_i]["members"]) >= MAX_SIDE_MEMBERS:
            await q.message.answer(tr("battle_side_limit"))
            return
        await state.update_data(battle_side_i=side_i, battle_member_i=None)
        await state.set_state(EditPage.battle_text if page_id is not None else NewPage.battle_text)
        await state.update_data(battle_action="add_member", battle_page_id=page_id)
        await q.message.answer(tr("battle_member_name"))
        return
    if op == "name" and len(args) == 1:
        await state.update_data(battle_side_i=side_i, battle_page_id=page_id, battle_action="side_name")
        await state.set_state(EditPage.battle_text if page_id is not None else NewPage.battle_text)
        await q.message.answer(tr("battle_side_name"))
        return
    if op == "e" and len(args) == 2:
        await _open_member(q.message, data, side_i, int(args[1]), page_id)
        return
    if op == "r" and len(args) == 2:
        idx = int(args[1])
        sides = normalize_sides(data)
        m = member(sides, side_i, idx)
        if not m:
            return
        old_flag = m.get("flag")
        sides[side_i]["members"].pop(idx)
        await _save_sides_data(data, sides)
        if p:
            await _invalidate_saved(p, db, cfg)
        await _remove_flag(old_flag, q.from_user.id, db, cfg, page_id is not None)
        await _show_side(q.message, data, side_i, page_id)
        return
    if op == "flag" and len(args) == 2:
        idx = int(args[1])
        if not member(normalize_sides(data), side_i, idx):
            return
        await state.update_data(battle_side_i=side_i, battle_member_i=idx, battle_page_id=page_id, battle_action="flag")
        await state.set_state(EditPage.battle_flag if page_id is not None else NewPage.battle_flag)
        await q.message.answer(tr("battle_flag_prompt"), reply_markup=battle_flag_kb(prefix))
        return
    if op == "name" and len(args) == 2:
        idx = int(args[1])
        if not member(normalize_sides(data), side_i, idx):
            return
        await state.update_data(battle_side_i=side_i, battle_member_i=idx, battle_page_id=page_id, battle_action="member_name")
        await state.set_state(EditPage.battle_text if page_id is not None else NewPage.battle_text)
        await q.message.answer(tr("battle_member_name"))
        return


@router.callback_query(F.data == "draft:sides")
async def open_draft_sides(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if d.get("type") != "battle":
        return
    await _show_sides(q.message, d.get("page_data") or {}, None)


@router.callback_query(F.data.startswith("p:bs:"))
async def open_page_sides(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await db.get_page(page_id, q.from_user.id)
    if not p or p.type != "battle":
        return
    await _show_sides(q.message, p.data, p.id)


@router.callback_query(F.data.startswith("bs:d:"))
async def draft_battle_sides(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await _handle_cb(q, state, db, cfg, bot, None)


@router.callback_query(F.data.startswith("bs:p:"))
async def page_battle_sides(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    await _handle_cb(q, state, db, cfg, bot, int(parts[2]))


async def battle_text_input(msg: Message, state: FSMContext, db: Db, cfg: Config, saved: bool) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("text_only"))
        return
    d = await state.get_data()
    side_i = int(d.get("battle_side_i", 0))
    member_i = d.get("battle_member_i")
    action = d.get("battle_action")
    page_id = d.get("battle_page_id")
    data = None
    p = None
    if saved:
        p = await db.get_page(int(page_id), msg.from_user.id)
        if not p:
            await state.clear()
            await msg.answer(tr("page_not_found"))
            return
        data = p.data
    else:
        data = (await state.get_data()).get("page_data") or {}

    s = msg.text.strip()[:160]
    sides = normalize_sides(data)
    if action == "side_name":
        sides[side_i]["name"] = s
    elif action == "member_name" and member_i is not None:
        m = member(sides, side_i, int(member_i))
        if not m:
            return
        m["name"] = s
    elif action == "add_member":
        sides[side_i]["members"].append({"name": s, "flag": None})
        await state.update_data(battle_member_i=len(sides[side_i]["members"]) - 1, battle_action="add_member")
    else:
        return
    await _save_sides_data(data, sides)
    if p:
        await _invalidate_saved(p, db, cfg)
    if action == "add_member":
        await state.set_state(EditPage.battle_flag if saved else NewPage.battle_flag)
        await msg.answer(tr("battle_flag_prompt"), reply_markup=battle_flag_kb(_base(page_id)))
        return
    await state.clear()
    await _show_side(msg, data, side_i, page_id)


@router.message(EditPage.battle_text)
async def edit_battle_text(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    await battle_text_input(msg, state, db, cfg, True)


@router.message(NewPage.battle_text)
async def draft_battle_text(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    await battle_text_input(msg, state, db, cfg, False)


async def battle_flag_input(msg: Message, state: FSMContext, bot: Bot, db: Db, cfg: Config, saved: bool) -> None:
    d = await state.get_data()
    side_i = int(d.get("battle_side_i", 0))
    member_i = int(d.get("battle_member_i", 0))
    page_id = d.get("battle_page_id")
    p = None
    if saved:
        p = await db.get_page(int(page_id), msg.from_user.id)
        if not p:
            await state.clear()
            await msg.answer(tr("page_not_found"))
            return
        data = p.data
    else:
        data = d.get("page_data") or {}
    f = msg.photo[-1] if msg.photo else msg.document
    if not f:
        await msg.answer(tr("battle_flag_only"))
        return
    size = getattr(f, "file_size", 0) or 0
    if size > cfg.max_image_mb * 1024 * 1024:
        await msg.answer(tr("image_bad", error=f"файл больше {cfg.max_image_mb} МБ"))
        return
    buf = BytesIO()
    try:
        await bot.download(f, destination=buf)
        info = await save_image(buf.getvalue(), msg.from_user.id, cfg.work_dir, cfg.max_image_mb)
    except BadImage as e:
        await msg.answer(tr("image_bad", error=str(e)))
        return
    except Exception:
        log.exception("battle flag download failed user=%s", msg.from_user.id)
        await msg.answer(tr("image_bad", error="не удалось скачать файл"))
        return

    sides = normalize_sides(data)
    m = member(sides, side_i, member_i)
    if not m:
        safe_unlink(info.path, cfg.work_dir, "media_")
        return
    old_flag = m.get("flag")
    m["flag"] = info.path.name
    save_sides(data, sides)
    if p:
        safe_unlink(p.preview_path, cfg.work_dir, "preview_")
        p.preview_path = None
        await db.add_media(msg.from_user.id, info.path.name, info.width, info.height, p.id, "battle_flag")
        await db.update_page(p)
    else:
        await db.add_media(msg.from_user.id, info.path.name, info.width, info.height, None, "battle_flag")
        await state.update_data(page_data=data)
    if old_flag and old_flag != info.path.name:
        await _remove_flag(old_flag, msg.from_user.id, db, cfg, saved)
    if p:
        await state.clear()
        await _render_saved(msg, p, db, cfg)
    else:
        from create_handlers import show_preview
        await show_preview(msg, state, db, cfg, bot, msg.from_user)


@router.message(EditPage.battle_flag)
async def edit_battle_flag(msg: Message, state: FSMContext, bot: Bot, db: Db, cfg: Config) -> None:
    await battle_flag_input(msg, state, bot, db, cfg, True)


@router.message(NewPage.battle_flag)
async def draft_battle_flag(msg: Message, state: FSMContext, bot: Bot, db: Db, cfg: Config) -> None:
    await battle_flag_input(msg, state, bot, db, cfg, False)


def battle_flag_kb(prefix: str):
    from aiogram.types import InlineKeyboardMarkup
    from ui import ib
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("⏭ Без флага", f"{prefix}:skip")],
            [ib("❌ Отмена", f"{prefix}:cancel")],
        ]
    )


async def _skip_flag(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot, saved: bool) -> None:
    await q.answer()
    d = await state.get_data()
    side_i = int(d.get("battle_side_i", 0))
    member_i = int(d.get("battle_member_i", 0))
    page_id = d.get("battle_page_id")
    p = await db.get_page(int(page_id), q.from_user.id) if saved else None
    data = p.data if p else d.get("page_data") or {}
    sides = normalize_sides(data)
    m = member(sides, side_i, member_i)
    if d.get("battle_action") == "flag" and m and m.get("flag"):
        old_flag = m.get("flag")
        m["flag"] = None
        save_sides(data, sides)
        if p:
            await _invalidate_saved(p, db, cfg)
        await _remove_flag(old_flag, q.from_user.id, db, cfg, saved)
        if p:
            await db.update_page(p)
        else:
            await state.update_data(page_data=data)
    if p:
        await state.clear()
        await _render_saved(q.message, p, db, cfg)
    else:
        from create_handlers import show_preview
        await show_preview(q.message, state, db, cfg, bot, q.from_user)


