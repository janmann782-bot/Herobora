from __future__ import annotations

import logging
from contextlib import suppress
from io import BytesIO
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Config
from db import Db
from locales import tr
from media import (
    MAX_PAGE_IMAGES,
    MAX_SIDE_MEMBERS,
    BadImage,
    battle_sides,
    image_caption,
    page_media,
    page_images,
    safe_unlink,
    save_image,
    set_image_caption,
    set_battle_sides,
    set_page_images,
)
from models import Page
from paper import PAPER_COFFEE, ensure_paper, new_paper_seed, paper_status, seed_from_text
from parser import ParsedPage, parse_section, parse_text
from renderer import render_error_text, render_page
from states import NewPage, clear_flow
from templates import get_template
from themes import get_theme, theme_allowed
from ui import (
    CREATE,
    HELP,
    MY_PAGES,
    SETTINGS,
    THEMES_BTN,
    battle_sides_kb,
    draft_kb,
    edit_value_kb,
    fields_kb,
    image_caption_kb,
    image_kb,
    main_menu,
    page_actions_kb,
    paper_kb,
    progress_text,
    quick_kb,
    render_progress,
    send_png,
    side_flag_kb,
    themes_kb,
    types_kb,
    wizard_kb,
)

router = Router(name="create")
log = logging.getLogger(__name__)
IMAGE_CAPTION_LIMIT = 500


async def ask_field(msg: Message, state: FSMContext) -> None:
    d = await state.get_data()
    tpl = get_template(d["type"])
    i = int(d.get("i", 0))

    if i >= len(tpl.wizard):
        await state.set_state(NewPage.image)
        await state.update_data(image_mode="initial")
        count = len(page_images(d.get("page_data") or {}))
        await msg.answer(
            tr(
                "send_image",
                label=tpl.image_label.lower(),
                max_mb=d.get("max_image_mb", 12),
                count=count,
                max_count=MAX_PAGE_IMAGES,
            ),
            reply_markup=image_kb(count),
        )
        return

    f = tpl.get_field(tpl.wizard[i])
    hint = tr("field_hint") if f.multiline else ""
    s = tr("field_prompt", label=f.label, hint=hint, step=i + 1, total=len(tpl.wizard))
    current = (d.get("page_data") or {}).get(f.key)
    if current:
        s += "\n\n" + tr("current_value", value=str(current)[:500])
    await state.set_state(NewPage.field)
    await msg.answer(s, reply_markup=wizard_kb(can_skip=f.key != "title"))


def make_draft(d: dict, user_id: int) -> Page:
    data = d.get("page_data") or {}
    title = str(data.get("title") or "Без названия").strip()
    page_type = d["type"]
    theme = d.get("theme", "light")
    if not theme_allowed(theme, page_type):
        theme = "light"
    if theme == "old_document":
        ensure_paper(data)
    return Page(
        owner_id=user_id,
        type=page_type,
        title=title,
        theme=theme,
        data=data,
        preview_path=d.get("preview_path"),
    )


async def show_preview(
    msg: Message,
    state: FSMContext,
    db: Db,
    cfg: Config,
    user_id: int,
) -> Page | None:
    d = await state.get_data()
    if not d.get("type"):
        await msg.answer(tr("draft_missing"), reply_markup=main_menu())
        await state.clear()
        return None

    p = make_draft(d, user_id)
    await state.update_data(page_data=p.data, theme=p.theme)
    settings = await db.get_settings(user_id)
    wait = await msg.answer(progress_text(8))

    try:
        safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
        path = await render_progress(
            wait,
            render_page(
                p,
                cfg.work_dir,
                settings.quality,
                watermark=settings.watermark,
            ),
        )
        p.preview_path = path.name
        await state.update_data(preview_path=path.name)
        await state.set_state(NewPage.review)
        await send_png(
            msg,
            path,
            tr("draft_caption", title=p.title, theme=get_theme(p.theme).name),
            draft_kb(p.type, p.theme),
        )
        return p
    except Exception as e:
        log.exception("draft render failed for user %s", user_id)
        await msg.answer(
            tr("render_error", error=render_error_text(e)),
            reply_markup=draft_kb(p.type, p.theme),
        )
        return None
    finally:
        with suppress(TelegramBadRequest):
            await wait.delete()


def quick_summary(parsed: ParsedPage) -> str:
    tpl = get_template(parsed.type)
    labels = {f.key: f.label for f in tpl.fields}
    lines = []
    for k, v in parsed.data.items():
        if k == "custom_fields":
            continue
        lines.append(f"{labels.get(k, k)}: {str(v)[:260]}")
    for x in parsed.data.get("custom_fields") or []:
        lines.append(f"{x.get('name', 'Поле')}: {str(x.get('value', ''))[:260]}")
    return "\n".join(lines)[:3200]


async def show_quick(msg: Message, state: FSMContext) -> None:
    d = await state.get_data()
    await state.set_state(NewPage.quick)
    await msg.answer(d.get("quick_text", tr("draft_missing")), reply_markup=quick_kb())


async def show_draft_sides(msg: Message, state: FSMContext) -> None:
    d = await state.get_data()
    if d.get("type") != "battle":
        await msg.answer(tr("battle_only"))
        return
    data = d.get("page_data") or {}
    sides = battle_sides(data)
    set_battle_sides(data, sides)
    await state.update_data(page_data=data)
    await state.set_state(NewPage.review)
    await msg.answer(
        tr("sides_title", side_1=len(sides[0]), side_2=len(sides[1])),
        reply_markup=battle_sides_kb(data),
    )


def paper_text(data: dict) -> str:
    seed, brightness, coffee = paper_status(data)
    return tr(
        "paper_settings",
        seed=seed,
        brightness=brightness,
        coffee="включен" if coffee else "отключен",
    )


async def show_draft_paper(msg: Message, state: FSMContext) -> None:
    d = await state.get_data()
    if d.get("type") != "country" or d.get("theme") != "old_document":
        await msg.answer(tr("paper_only"))
        return
    data = d.get("page_data") or {}
    ensure_paper(data)
    await state.update_data(page_data=data)
    await state.set_state(NewPage.review)
    await msg.answer(paper_text(data), reply_markup=paper_kb(data))


@router.callback_query(F.data.startswith("new:"))
async def start_new(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    kind = q.data.split(":", 1)[1]
    if kind == "news":
        await q.message.answer(tr("news_later"), reply_markup=types_kb())
        return
    try:
        get_template(kind)
    except ValueError:
        return

    s = await db.get_settings(q.from_user.id)
    await clear_flow(state, q.from_user.id, db, cfg)
    await state.update_data(
        type=kind,
        page_data={},
        i=0,
        theme=s.theme if theme_allowed(s.theme, kind) else "light",
        preview_path=None,
        max_image_mb=cfg.max_image_mb,
    )
    await state.set_state(NewPage.field)
    await ask_field(q.message, state)


@router.message(NewPage.field)
async def take_field(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        await msg.answer(tr("text_only"))
        return

    d = await state.get_data()
    tpl = get_template(d["type"])
    i = int(d.get("i", 0))
    if i >= len(tpl.wizard):
        await ask_field(msg, state)
        return

    f = tpl.get_field(tpl.wizard[i])
    s = msg.text.strip()
    limit = 3800 if f.multiline else 700
    if f.key == "title":
        limit = 250
    if not s:
        await msg.answer(tr("title_required") if f.key == "title" else tr("empty_value"))
        return
    if len(s) > limit:
        await msg.answer(tr("too_long", limit=limit))
        return

    data = d.get("page_data") or {}
    data[f.key] = s
    await state.update_data(page_data=data, i=i + 1)
    await ask_field(msg, state)


@router.callback_query(NewPage.field, F.data == "wiz:skip")
async def skip_field(q: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    tpl = get_template(d["type"])
    i = int(d.get("i", 0))
    f = tpl.get_field(tpl.wizard[i])
    if f.key == "title":
        await q.answer(tr("title_required"), show_alert=True)
        return
    await q.answer()
    await state.update_data(i=i + 1)
    await ask_field(q.message, state)


@router.callback_query(NewPage.field, F.data == "wiz:back")
async def back_field(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    i = int(d.get("i", 0))
    if i <= 0:
        await state.clear()
        await q.message.answer(tr("choose_type"), reply_markup=types_kb())
        return
    await state.update_data(i=i - 1)
    await ask_field(q.message, state)


async def after_image(msg: Message, state: FSMContext, db: Db, cfg: Config, user_id: int) -> None:
    d = await state.get_data()
    if d.get("image_mode") == "draft":
        await show_preview(msg, state, db, cfg, user_id)
        return
    await state.set_state(NewPage.theme)
    await msg.answer(
        tr("choose_theme"),
        reply_markup=themes_kb("dt", d.get("theme", "light"), d.get("type", "")),
    )


@router.callback_query(NewPage.image, F.data.in_({"img:skip", "img:done"}))
async def skip_image(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await after_image(q.message, state, db, cfg, q.from_user.id)


@router.callback_query(NewPage.image, F.data == "img:back")
async def back_image(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    d = await state.get_data()
    if d.get("image_mode") == "draft":
        await show_preview(q.message, state, db, cfg, q.from_user.id)
        return
    tpl = get_template(d["type"])
    await state.update_data(i=max(0, len(tpl.wizard) - 1))
    await ask_field(q.message, state)


@router.callback_query(NewPage.image, F.data.startswith("img:rm:"))
async def remove_draft_image(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    d = await state.get_data()
    data = d.get("page_data") or {}
    images = page_images(data)
    i = int(q.data.rsplit(":", 1)[1])
    if not 0 <= i < len(images):
        return
    old = images.pop(i)
    set_page_images(data, images)
    await state.update_data(page_data=data)
    if await db.drop_unattached_media(old, q.from_user.id):
        safe_unlink(old, cfg.work_dir, "media_")
    await q.message.answer(
        tr("image_removed", number=i + 1, count=len(images)),
        reply_markup=image_kb(len(images)),
    )


@router.callback_query(NewPage.image, F.data.startswith("img:cap:"))
async def edit_draft_image_caption(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    data = d.get("page_data") or {}
    images = page_images(data)
    i = int(q.data.rsplit(":", 1)[1])
    if not 0 <= i < len(images):
        return

    path = images[i]
    await state.update_data(caption_path=path, caption_i=i)
    await state.set_state(NewPage.image_caption)
    s = tr("image_caption_prompt", number=i + 1, limit=IMAGE_CAPTION_LIMIT)
    current = image_caption(data, path, i)
    if current:
        s += "\n\n" + tr("current_value", value=current[:500])
    await q.message.answer(s, reply_markup=image_caption_kb())


@router.message(NewPage.image)
async def take_image(msg: Message, state: FSMContext, bot: Bot, db: Db, cfg: Config) -> None:
    d = await state.get_data()
    data = d.get("page_data") or {}
    images = page_images(data)
    if len(images) >= MAX_PAGE_IMAGES:
        await msg.answer(
            tr("image_limit", max_count=MAX_PAGE_IMAGES),
            reply_markup=image_kb(len(images)),
        )
        return

    f = msg.photo[-1] if msg.photo else msg.document
    if not f:
        await msg.answer(tr("image_only"), reply_markup=image_kb(len(images)))
        return

    size = getattr(f, "file_size", 0) or 0
    if size > cfg.max_image_mb * 1024 * 1024:
        await msg.answer(
            tr("image_bad", error=f"файл больше {cfg.max_image_mb} МБ"),
            reply_markup=image_kb(len(images)),
        )
        return

    buf = BytesIO()
    try:
        await bot.download(f, destination=buf)
        info = await save_image(buf.getvalue(), msg.from_user.id, cfg.work_dir, cfg.max_image_mb)
    except BadImage as e:
        await msg.answer(tr("image_bad", error=str(e)), reply_markup=image_kb(len(images)))
        return
    except Exception:
        log.exception("telegram image download failed for user %s", msg.from_user.id)
        await msg.answer(
            tr("image_bad", error="не удалось скачать файл"),
            reply_markup=image_kb(len(images)),
        )
        return

    await db.add_media(msg.from_user.id, info.path.name, info.width, info.height)
    images.append(info.path.name)
    set_page_images(data, images)
    await state.update_data(
        page_data=data,
        caption_path=info.path.name,
        caption_i=len(images) - 1,
    )
    await state.set_state(NewPage.image_caption)
    await msg.answer(
        tr("image_saved", count=len(images), max_count=MAX_PAGE_IMAGES)
        + "\n\n"
        + tr("image_caption_prompt", number=len(images), limit=IMAGE_CAPTION_LIMIT),
        reply_markup=image_caption_kb(),
    )


@router.message(NewPage.image_caption)
async def take_draft_image_caption(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        await msg.answer(tr("text_only"), reply_markup=image_caption_kb())
        return
    s = msg.text.strip()
    if not s:
        await msg.answer(tr("empty_value"), reply_markup=image_caption_kb())
        return
    if len(s) > IMAGE_CAPTION_LIMIT:
        await msg.answer(
            tr("too_long", limit=IMAGE_CAPTION_LIMIT),
            reply_markup=image_caption_kb(),
        )
        return

    d = await state.get_data()
    data = d.get("page_data") or {}
    images = page_images(data)
    path = str(d.get("caption_path") or "")
    if path not in images:
        await state.set_state(NewPage.image)
        await msg.answer(tr("images_continue"), reply_markup=image_kb(len(images)))
        return

    set_image_caption(data, path, s)
    await state.update_data(page_data=data, caption_path=None, caption_i=None)
    await state.set_state(NewPage.image)
    await msg.answer(tr("image_caption_saved"), reply_markup=image_kb(len(images)))


@router.callback_query(NewPage.image_caption, F.data.startswith("imgcap:"))
async def draft_image_caption_action(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    action = q.data.split(":", 1)[1]
    d = await state.get_data()
    data = d.get("page_data") or {}
    images = page_images(data)
    path = str(d.get("caption_path") or "")

    if action == "skip" and path in images:
        set_image_caption(data, path, "")
        await state.update_data(page_data=data)
        text = tr("image_caption_skipped")
    else:
        text = tr("images_continue")

    await state.update_data(caption_path=None, caption_i=None)
    await state.set_state(NewPage.image)
    await q.message.answer(text, reply_markup=image_kb(len(images)))


@router.callback_query(F.data.startswith("dt:"))
async def draft_theme(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    value = q.data.split(":", 1)[1]
    cur = await state.get_state()
    d = await state.get_data()

    if value == "back":
        if cur == NewPage.field.state or not d.get("type"):
            return
        if cur == NewPage.theme.state:
            await state.set_state(NewPage.image)
            await state.update_data(image_mode="initial")
            tpl = get_template(d["type"])
            await q.message.answer(
                tr(
                    "send_image",
                    label=tpl.image_label.lower(),
                    max_mb=cfg.max_image_mb,
                    count=len(page_images(d.get("page_data") or {})),
                    max_count=MAX_PAGE_IMAGES,
                ),
                reply_markup=image_kb(len(page_images(d.get("page_data") or {}))),
            )
        elif cur == NewPage.quick.state:
            await show_quick(q.message, state)
        else:
            await show_preview(q.message, state, db, cfg, q.from_user.id)
        return

    if not theme_allowed(value, d.get("type", "")):
        return
    data = d.get("page_data") or {}
    if value == "old_document":
        ensure_paper(data)
    await state.update_data(theme=value, page_data=data)
    await show_preview(q.message, state, db, cfg, q.from_user.id)


@router.callback_query(F.data == "draft:theme")
async def choose_draft_theme(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    await q.message.answer(
        tr("choose_theme"),
        reply_markup=themes_kb("dt", d.get("theme", "light"), d.get("type", "")),
    )


@router.callback_query(F.data == "draft:paper")
async def draft_paper(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    await show_draft_paper(q.message, state)


@router.callback_query(F.data.startswith("paper:"))
async def draft_paper_action(
    q: CallbackQuery,
    state: FSMContext,
    db: Db,
    cfg: Config,
) -> None:
    await q.answer()
    d = await state.get_data()
    if d.get("type") != "country" or d.get("theme") != "old_document":
        await q.message.answer(tr("paper_only"))
        return

    action = q.data.split(":", 1)[1]
    if action == "back":
        await show_preview(q.message, state, db, cfg, q.from_user.id)
        return
    if action == "input":
        await state.set_state(NewPage.paper_seed)
        await q.message.answer(
            tr("paper_seed_prompt"),
            reply_markup=edit_value_kb("draft:paper"),
        )
        return

    data = d.get("page_data") or {}
    ensure_paper(data)
    if action == "new":
        new_paper_seed(data)
    elif action == "coffee":
        data[PAPER_COFFEE] = not data[PAPER_COFFEE]
    else:
        return

    safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
    await state.update_data(page_data=data, preview_path=None)
    await state.set_state(NewPage.review)
    await q.message.answer(paper_text(data), reply_markup=paper_kb(data))


@router.message(NewPage.paper_seed)
async def take_draft_paper_seed(msg: Message, state: FSMContext, cfg: Config) -> None:
    if not msg.text:
        await msg.answer(tr("text_only"))
        return
    s = msg.text.strip()
    if not s:
        await msg.answer(tr("empty_value"))
        return
    if len(s) > 40:
        await msg.answer(tr("too_long", limit=40))
        return

    d = await state.get_data()
    if d.get("type") != "country" or d.get("theme") != "old_document":
        await state.clear()
        await msg.answer(tr("paper_only"))
        return
    data = d.get("page_data") or {}
    data["paper_seed"] = seed_from_text(s)
    data.setdefault(PAPER_COFFEE, True)
    safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
    await state.update_data(page_data=data, preview_path=None)
    await state.set_state(NewPage.review)
    await msg.answer(paper_text(data), reply_markup=paper_kb(data))


@router.callback_query(F.data == "draft:fields")
async def draft_fields(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    await q.message.answer(
        tr("fields_title"),
        reply_markup=fields_kb(get_template(d["type"]), d.get("page_data") or {}),
    )


@router.callback_query(F.data == "draft:sides")
async def draft_sides(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    await show_draft_sides(q.message, state)


@router.callback_query(F.data.startswith("bs:"))
async def draft_side_action(
    q: CallbackQuery,
    state: FSMContext,
    db: Db,
    cfg: Config,
) -> None:
    await q.answer()
    d = await state.get_data()
    if d.get("type") != "battle":
        await q.message.answer(tr("battle_only"))
        return
    if q.data == "bs:d":
        await show_preview(q.message, state, db, cfg, q.from_user.id)
        return

    parts = q.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    side_i = int(parts[2])
    data = d.get("page_data") or {}
    sides = battle_sides(data)
    if side_i not in (0, 1):
        return

    if action == "a":
        if len(sides[side_i]) >= MAX_SIDE_MEMBERS:
            await q.message.answer(tr("side_limit", limit=MAX_SIDE_MEMBERS))
            return
        await state.update_data(side_i=side_i, member_i=None)
        await state.set_state(NewPage.side_name)
        await q.message.answer(
            tr("side_name_prompt", side=side_i + 1),
            reply_markup=edit_value_kb("draft:sides"),
        )
        return

    if len(parts) != 4:
        return
    member_i = int(parts[3])
    if not 0 <= member_i < len(sides[side_i]):
        return

    if action == "n":
        await state.update_data(side_i=side_i, member_i=member_i)
        await state.set_state(NewPage.side_name)
        await q.message.answer(
            tr("side_name_prompt", side=side_i + 1)
            + "\n\n"
            + tr("current_value", value=sides[side_i][member_i]["name"]),
            reply_markup=edit_value_kb("draft:sides"),
        )
    elif action == "f":
        member = sides[side_i][member_i]
        await state.update_data(side_i=side_i, member_i=member_i)
        await state.set_state(NewPage.side_flag)
        await q.message.answer(
            tr(
                "side_flag_prompt",
                name=member["name"],
                max_mb=cfg.max_image_mb,
            ),
            reply_markup=side_flag_kb(bool(member.get("flag"))),
        )
    elif action == "r":
        member = sides[side_i].pop(member_i)
        old = member.get("flag")
        set_battle_sides(data, sides)
        safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
        await state.update_data(page_data=data, preview_path=None)
        if old and await db.drop_unattached_media(old, q.from_user.id):
            safe_unlink(old, cfg.work_dir, "media_")
        await q.message.answer(tr("side_removed"))
        await show_draft_sides(q.message, state)


@router.message(NewPage.side_name)
async def take_draft_side_name(msg: Message, state: FSMContext, cfg: Config) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("empty_value"))
        return
    name = " ".join(msg.text.split())
    if len(name) > 160:
        await msg.answer(tr("too_long", limit=160))
        return

    d = await state.get_data()
    if d.get("type") != "battle":
        await state.clear()
        await msg.answer(tr("battle_only"))
        return
    data = d.get("page_data") or {}
    sides = battle_sides(data)
    side_i = int(d.get("side_i", -1))
    member_i = d.get("member_i")
    if side_i not in (0, 1):
        return

    if member_i is None:
        if len(sides[side_i]) >= MAX_SIDE_MEMBERS:
            await msg.answer(tr("side_limit", limit=MAX_SIDE_MEMBERS))
            return
        sides[side_i].append({"name": name, "flag": ""})
    else:
        member_i = int(member_i)
        if not 0 <= member_i < len(sides[side_i]):
            await show_draft_sides(msg, state)
            return
        sides[side_i][member_i]["name"] = name

    set_battle_sides(data, sides)
    safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
    await state.update_data(
        page_data=data,
        preview_path=None,
        side_i=None,
        member_i=None,
    )
    await msg.answer(tr("side_name_saved"))
    await show_draft_sides(msg, state)


@router.message(NewPage.side_flag)
async def take_draft_side_flag(
    msg: Message,
    state: FSMContext,
    bot: Bot,
    db: Db,
    cfg: Config,
) -> None:
    d = await state.get_data()
    data = d.get("page_data") or {}
    sides = battle_sides(data)
    side_i = int(d.get("side_i", -1))
    member_i = int(d.get("member_i", -1))
    if side_i not in (0, 1) or not 0 <= member_i < len(sides[side_i]):
        await show_draft_sides(msg, state)
        return

    f = msg.photo[-1] if msg.photo else msg.document
    if not f:
        await msg.answer(
            tr("image_only"),
            reply_markup=side_flag_kb(bool(sides[side_i][member_i].get("flag"))),
        )
        return
    size = getattr(f, "file_size", 0) or 0
    if size > cfg.max_image_mb * 1024 * 1024:
        await msg.answer(
            tr("image_bad", error=f"файл больше {cfg.max_image_mb} МБ"),
            reply_markup=side_flag_kb(bool(sides[side_i][member_i].get("flag"))),
        )
        return

    buf = BytesIO()
    try:
        await bot.download(f, destination=buf)
        info = await save_image(buf.getvalue(), msg.from_user.id, cfg.work_dir, cfg.max_image_mb)
    except BadImage as e:
        await msg.answer(tr("image_bad", error=str(e)))
        return
    except Exception:
        log.exception("side flag download failed for user %s", msg.from_user.id)
        await msg.answer(tr("image_bad", error="не удалось скачать файл"))
        return

    old = sides[side_i][member_i].get("flag")
    sides[side_i][member_i]["flag"] = info.path.name
    set_battle_sides(data, sides)
    safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
    await db.add_media(
        msg.from_user.id,
        info.path.name,
        info.width,
        info.height,
        kind="side_flag",
    )
    await state.update_data(
        page_data=data,
        preview_path=None,
        side_i=None,
        member_i=None,
    )
    if old and await db.drop_unattached_media(old, msg.from_user.id):
        safe_unlink(old, cfg.work_dir, "media_")
    await msg.answer(tr("side_flag_saved"))
    await show_draft_sides(msg, state)


@router.callback_query(NewPage.side_flag, F.data.startswith("bf:"))
async def draft_side_flag_action(
    q: CallbackQuery,
    state: FSMContext,
    db: Db,
    cfg: Config,
) -> None:
    await q.answer()
    d = await state.get_data()
    data = d.get("page_data") or {}
    sides = battle_sides(data)
    side_i = int(d.get("side_i", -1))
    member_i = int(d.get("member_i", -1))
    if side_i not in (0, 1) or not 0 <= member_i < len(sides[side_i]):
        await show_draft_sides(q.message, state)
        return

    if q.data == "bf:rm":
        old = sides[side_i][member_i].get("flag")
        sides[side_i][member_i]["flag"] = ""
        set_battle_sides(data, sides)
        safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
        await state.update_data(page_data=data, preview_path=None)
        if old and await db.drop_unattached_media(old, q.from_user.id):
            safe_unlink(old, cfg.work_dir, "media_")
        await q.message.answer(tr("side_flag_removed"))

    await state.update_data(side_i=None, member_i=None)
    await show_draft_sides(q.message, state)


@router.callback_query(F.data == "draft:back")
async def draft_back(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await show_preview(q.message, state, db, cfg, q.from_user.id)


@router.callback_query(F.data.startswith("df:"))
async def edit_draft_standard(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    tpl = get_template(d["type"])
    i = int(q.data.split(":")[1])
    if not 0 <= i < len(tpl.fields):
        return
    f = tpl.fields[i]
    await state.update_data(edit_kind="standard", edit_key=f.key, edit_label=f.label)
    await state.set_state(NewPage.edit_value)
    await q.message.answer(tr("edit_value", label=f.label), reply_markup=edit_value_kb("draft:fields"))


@router.callback_query(F.data.startswith("dc:"))
async def edit_draft_custom(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    i = int(q.data.split(":")[1])
    items = (d.get("page_data") or {}).get("custom_fields") or []
    if not 0 <= i < len(items):
        return
    label = items[i].get("name", "Свое поле")
    await state.update_data(edit_kind="custom", edit_i=i, edit_label=label)
    await state.set_state(NewPage.edit_value)
    await q.message.answer(tr("edit_value", label=label), reply_markup=edit_value_kb("draft:fields"))


@router.callback_query(F.data.startswith("dx:"))
async def edit_draft_section(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    _, a, b = q.data.split(":")
    i, j = int(a), int(b)
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    sections = (d.get("page_data") or {}).get("sections") or []
    if not 0 <= i < len(sections) or not 0 <= j < len(sections[i].get("fields") or []):
        return
    label = sections[i]["fields"][j].get("name", "Поле")
    await state.update_data(edit_kind="section", edit_i=i, edit_j=j, edit_label=label)
    await state.set_state(NewPage.edit_value)
    await q.message.answer(tr("edit_value", label=label), reply_markup=edit_value_kb("draft:fields"))


@router.message(NewPage.edit_value)
async def take_draft_edit(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    if not msg.text:
        await msg.answer(tr("text_only"))
        return
    s = msg.text.strip()
    if len(s) > 3800:
        await msg.answer(tr("too_long", limit=3800))
        return

    d = await state.get_data()
    data = d.get("page_data") or {}
    kind = d.get("edit_kind")
    value = "" if s == "-" else s

    if kind == "standard":
        key = d["edit_key"]
        if key == "title" and not value:
            await msg.answer(tr("title_required"))
            return
        if key == "image_caption" and page_images(data):
            set_image_caption(data, page_images(data)[0], value)
        else:
            data[key] = value
    elif kind == "custom":
        data["custom_fields"][int(d["edit_i"])]["value"] = value
    elif kind == "section":
        data["sections"][int(d["edit_i"])]["fields"][int(d["edit_j"])]["value"] = value
    else:
        await msg.answer(tr("draft_missing"))
        return

    await state.update_data(page_data=data)
    await msg.answer(tr("field_saved"))
    await show_preview(msg, state, db, cfg, msg.from_user.id)


@router.callback_query(F.data == "draft:custom")
async def add_draft_custom(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    if len((d.get("page_data") or {}).get("custom_fields") or []) >= 20:
        await q.message.answer(tr("limit_reached"))
        return
    await state.set_state(NewPage.custom_name)
    await q.message.answer(tr("custom_name"), reply_markup=edit_value_kb("draft:fields"))


@router.message(NewPage.custom_name)
async def draft_custom_name(msg: Message, state: FSMContext) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("custom_name"))
        return
    name = msg.text.strip()[:100]
    await state.update_data(custom_name=name)
    await state.set_state(NewPage.custom_value)
    await msg.answer(tr("custom_value", name=name), reply_markup=edit_value_kb("draft:fields"))


@router.message(NewPage.custom_value)
async def draft_custom_value(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("empty_value"))
        return
    d = await state.get_data()
    data = d.get("page_data") or {}
    items = data.setdefault("custom_fields", [])
    items.append({"name": d["custom_name"], "value": msg.text.strip()[:3800]})
    await state.update_data(page_data=data)
    await msg.answer(tr("custom_added"))
    await show_preview(msg, state, db, cfg, msg.from_user.id)


@router.callback_query(F.data == "draft:section")
async def add_draft_section(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    if len((d.get("page_data") or {}).get("sections") or []) >= 6:
        await q.message.answer(tr("limit_reached"))
        return
    await state.set_state(NewPage.section)
    await q.message.answer(tr("section_prompt"), reply_markup=edit_value_kb("draft:fields"))


@router.message(NewPage.section)
async def draft_section(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    sec = parse_section(msg.text or "")
    if not sec:
        await msg.answer(tr("section_bad"))
        return
    d = await state.get_data()
    data = d.get("page_data") or {}
    total = sum(len(x.get("fields") or []) for x in data.get("sections") or [])
    if total + len(sec["fields"]) > 40:
        await msg.answer(tr("limit_reached"))
        return
    data.setdefault("sections", []).append(sec)
    await state.update_data(page_data=data)
    await msg.answer(tr("section_added"))
    await show_preview(msg, state, db, cfg, msg.from_user.id)


@router.callback_query(F.data == "draft:image")
async def replace_draft_image(q: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    tpl = get_template(d["type"])
    count = len(page_images(d.get("page_data") or {}))
    await state.update_data(image_mode="draft")
    await state.set_state(NewPage.image)
    await q.message.answer(
        tr(
            "send_image",
            label=tpl.image_label.lower(),
            max_mb=cfg.max_image_mb,
            count=count,
            max_count=MAX_PAGE_IMAGES,
        ),
        reply_markup=image_kb(count),
    )


@router.callback_query(F.data == "draft:save")
async def save_draft(q: CallbackQuery, state: FSMContext, db: Db) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    p = make_draft(d, q.from_user.id)
    if not p.data.get("title"):
        await q.message.answer(tr("title_required"))
        return
    p = await db.save_page(p)
    for path in page_media(p.data):
        await db.attach_media(path, p.id, q.from_user.id)
    await state.clear()
    await q.message.answer(
        tr("saved", title=p.title),
        reply_markup=page_actions_kb(p.id, p.type, p.theme),
    )


@router.callback_query(F.data == "draft:export")
async def export_draft(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return

    raw = Path(d.get("preview_path") or "")
    path = raw.resolve() if raw.is_absolute() else (cfg.work_dir / raw).resolve()
    if path.parent != cfg.work_dir.resolve() or not path.name.startswith("preview_") or not path.is_file():
        p = await show_preview(q.message, state, db, cfg, q.from_user.id)
        if not p:
            return
        d = await state.get_data()
        path = (cfg.work_dir / d["preview_path"]).resolve()

    p = make_draft(await state.get_data(), q.from_user.id)
    await send_png(q.message, path, p.title, document=True)


@router.callback_query(F.data.in_({"draft:cancel", "flow:cancel"}))
async def cancel_flow(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await clear_flow(state, q.from_user.id, db, cfg)
    await q.message.answer(tr("cancelled"), reply_markup=main_menu())


@router.callback_query(F.data == "quick:preview")
async def quick_preview(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await show_preview(q.message, state, db, cfg, q.from_user.id)


@router.callback_query(F.data == "quick:fields")
async def quick_fields(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    await q.message.answer(
        tr("fields_title"),
        reply_markup=fields_kb(get_template(d["type"]), d.get("page_data") or {}),
    )


@router.callback_query(F.data == "quick:theme")
async def quick_theme(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    await q.message.answer(
        tr("choose_theme"),
        reply_markup=themes_kb("dt", d.get("theme", "light"), d.get("type", "")),
    )


@router.message(StateFilter(None), F.text)
async def quick_input(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    text = msg.text.strip()
    if text in {CREATE, MY_PAGES, THEMES_BTN, SETTINGS, HELP}:
        return
    if text.startswith("/"):
        await msg.answer(tr("quick_hint"), reply_markup=main_menu())
        return

    parsed = parse_text(text)
    if parsed.recognized < 2:
        await msg.answer(tr("quick_hint"), reply_markup=main_menu())
        return

    s = await db.get_settings(msg.from_user.id)
    data = parsed.data
    data.setdefault("title", "Без названия")
    extra = ""
    if parsed.unknown:
        extra = tr("quick_unknown", lines="\n".join(parsed.unknown[:8])[:700])
    if parsed.warnings:
        extra += tr("quick_warnings", lines="\n".join(parsed.warnings[:6])[:600])
    summary = quick_summary(parsed)
    quick_text = tr(
        "quick_found",
        count=parsed.recognized,
        type=get_template(parsed.type).label,
        summary=summary,
        extra=extra,
    )[:4000]
    await state.update_data(
        type=parsed.type,
        page_data=data,
        theme=s.theme if theme_allowed(s.theme, parsed.type) else "light",
        preview_path=None,
        quick_text=quick_text,
        max_image_mb=cfg.max_image_mb,
    )
    await show_quick(msg, state)
