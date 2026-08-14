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
from log_sink import send_created_page_log
from media import (
    MAX_PAGE_IMAGES,
    BadImage,
    image_caption,
    page_images,
    safe_unlink,
    save_image,
    set_image_caption,
    set_page_images,
)
from models import Page
from parser import ParsedPage, parse_section, parse_text
from renderer import render_error_text, render_page
from states import NewPage, clear_flow
from stats import spawn_milestone_broadcast
from templates import get_template
from text_export import send_page_text
from themes import get_theme
from ui import (
    CREATE,
    HELP,
    NEWS,
    STATS,
    MY_PAGES,
    SETTINGS,
    THEMES_BTN,
    draft_kb,
    olddoc_options_kb,
    edit_value_kb,
    fields_kb,
    image_caption_kb,
    image_kb,
    main_menu,
    page_actions_kb,
    progress_text,
    quick_kb,
    render_progress,
    send_png,
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
        ptype = d.get("type") or ""
        max_count = 1 if ptype == "news" else MAX_PAGE_IMAGES
        if ptype == "news":
            text = (
                f"Кинь одну картинку к новости\n"
                f"PNG JPEG или WEBP до {d.get('max_image_mb', 12)} МБ\n\n"
                f"Сейчас: {count}/{max_count}"
            )
        else:
            text = tr(
                "send_image",
                label=tpl.image_label.lower(),
                max_mb=d.get("max_image_mb", 12),
                count=count,
                max_count=max_count,
            )
        await msg.answer(text, reply_markup=image_kb(count, ptype))
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
    return Page(
        owner_id=user_id,
        type=d["type"],
        title=title,
        theme=d.get("theme", "light"),
        data=data,
        preview_path=d.get("preview_path"),
    )


async def show_preview(
    msg: Message,
    state: FSMContext,
    db: Db,
    cfg: Config,
    bot: Bot,
    user,
) -> Page | None:
    d = await state.get_data()
    if not d.get("type"):
        await msg.answer(tr("draft_missing"), reply_markup=main_menu())
        await state.clear()
        return None

    user_id = user.id
    p = make_draft(d, user_id)
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

        # Новая карточка считается один раз при первом успешном рендере.
        # Сохранение не требуется, а повторные предпросмотры этот счётчик не крутят.
        if not d.get("generation_counted"):
            _, _, milestone = await db.count_generation(user_id)
            await state.update_data(generation_counted=True)
            if milestone is not None:
                spawn_milestone_broadcast(bot, db, milestone)

        await state.set_state(NewPage.review)
        await send_png(
            msg,
            path,
            tr("draft_caption", title=p.title, theme=get_theme(p.theme).name),
            draft_kb(p.type, p.theme),
        )

        # В лог-группу отправляем именно в момент первого реального рендера
        # карточки, а не при сохранении страницы. Повторные предпросмотры
        # этого же черновика лог не засоряют.
        if not d.get("creation_log_sent"):
            sent = await send_created_page_log(
                bot, cfg, db, p, user, preview_path=path, stage="render"
            )
            if sent:
                await state.update_data(creation_log_sent=True)
        return p
    except Exception as e:
        log.exception("draft render failed for user %s", user_id)
        await msg.answer(tr("render_error", error=render_error_text(e)), reply_markup=draft_kb((d.get("type") or ""), d.get("theme", "")))
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


@router.callback_query(F.data.startswith("new:"))
async def start_new(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    kind = q.data.split(":", 1)[1]
    try:
        get_template(kind)
    except ValueError:
        return

    s = await db.get_settings(q.from_user.id)
    await clear_flow(state, q.from_user.id, db, cfg)
    theme = "fire_rises" if kind == "news" else s.theme
    await state.update_data(
        type=kind,
        page_data={},
        i=0,
        theme=theme,
        preview_path=None,
        max_image_mb=cfg.max_image_mb,
        creation_log_sent=False,
        generation_counted=False,
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
        await q.message.answer(tr("choose_type"), reply_markup=types_kb(), parse_mode="HTML")
        return
    await state.update_data(i=i - 1)
    await ask_field(q.message, state)


async def after_image(msg: Message, state: FSMContext, db: Db, cfg: Config, bot: Bot, user) -> None:
    d = await state.get_data()
    if d.get("image_mode") == "draft":
        await show_preview(msg, state, db, cfg, bot, user)
        return
    await state.set_state(NewPage.theme)
    await msg.answer(tr("choose_theme"), reply_markup=themes_kb("dt", d.get("theme", "light"), d.get("type", "")), parse_mode="HTML")


@router.callback_query(NewPage.image, F.data.in_({"img:skip", "img:done"}))
async def skip_image(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await q.answer()
    await after_image(q.message, state, db, cfg, bot, q.from_user)


@router.callback_query(NewPage.image, F.data == "img:back")
async def back_image(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await q.answer()
    d = await state.get_data()
    if d.get("image_mode") == "draft":
        await show_preview(q.message, state, db, cfg, bot, q.from_user)
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
        reply_markup=image_kb(len(images), d.get("type") or ""),
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
    ptype = d.get("type") or ""
    max_count = 1 if ptype == "news" else MAX_PAGE_IMAGES
    if len(images) >= max_count:
        await msg.answer(
            tr("image_limit", max_count=max_count),
            reply_markup=image_kb(len(images), ptype),
        )
        return

    f = msg.photo[-1] if msg.photo else msg.document
    if not f:
        await msg.answer(tr("image_only"), reply_markup=image_kb(len(images), ptype))
        return

    size = getattr(f, "file_size", 0) or 0
    if size > cfg.max_image_mb * 1024 * 1024:
        await msg.answer(
            tr("image_bad", error=f"файл больше {cfg.max_image_mb} МБ"),
            reply_markup=image_kb(len(images), ptype),
        )
        return

    buf = BytesIO()
    try:
        await bot.download(f, destination=buf)
        info = await save_image(buf.getvalue(), msg.from_user.id, cfg.work_dir, cfg.max_image_mb)
    except BadImage as e:
        await msg.answer(tr("image_bad", error=str(e)), reply_markup=image_kb(len(images), ptype))
        return
    except Exception:
        log.exception("telegram image download failed for user %s", msg.from_user.id)
        await msg.answer(
            tr("image_bad", error="не удалось скачать файл"),
            reply_markup=image_kb(len(images), ptype),
        )
        return

    await db.add_media(msg.from_user.id, info.path.name, info.width, info.height)
    # news — только одна картинка, старую выкидываем
    if ptype == "news":
        images = [info.path.name]
    else:
        images.append(info.path.name)
    set_page_images(data, images)
    await state.update_data(page_data=data)

    if ptype == "news":
        await state.update_data(caption_path=None, caption_i=None)
        await msg.answer(
            f"Картинку поставил {len(images)}/{max_count}\nМожешь нажать Готово",
            reply_markup=image_kb(len(images), ptype),
        )
        return

    await state.update_data(
        caption_path=info.path.name,
        caption_i=len(images) - 1,
    )
    await state.set_state(NewPage.image_caption)
    await msg.answer(
        tr("image_saved", count=len(images), max_count=max_count)
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
    ptype = d.get("type") or ""
    if path not in images:
        await state.set_state(NewPage.image)
        await msg.answer(tr("images_continue"), reply_markup=image_kb(len(images), ptype))
        return

    set_image_caption(data, path, s)
    await state.update_data(page_data=data, caption_path=None, caption_i=None)
    await state.set_state(NewPage.image)
    await msg.answer(tr("image_caption_saved"), reply_markup=image_kb(len(images), ptype))


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
    await q.message.answer(text, reply_markup=image_kb(len(images), d.get("type") or ""))


@router.callback_query(F.data.startswith("dt:"))
async def draft_theme(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
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
            ptype = d.get("type") or ""
            cnt = len(page_images(d.get("page_data") or {}))
            max_c = 1 if ptype == "news" else MAX_PAGE_IMAGES
            await q.message.answer(
                tr(
                    "send_image",
                    label=tpl.image_label.lower(),
                    max_mb=cfg.max_image_mb,
                    count=cnt,
                    max_count=max_c,
                ),
                reply_markup=image_kb(cnt, ptype),
            )
        elif cur == NewPage.quick.state:
            await show_quick(q.message, state)
        else:
            await show_preview(q.message, state, db, cfg, bot, q.from_user)
        return

    from themes import theme_allowed, THEMES
    if value not in THEMES:
        return
    page_type = d.get("type") or ""
    if not theme_allowed(value, page_type):
        await q.message.answer("Тема «Старый документ» пока доступна только для стран")
        return
    await state.update_data(theme=value)
    await show_preview(q.message, state, db, cfg, bot, q.from_user)


@router.callback_query(F.data == "draft:theme")
async def choose_draft_theme(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    await q.message.answer(tr("choose_theme"), reply_markup=themes_kb("dt", d.get("theme", "light"), d.get("type", "")), parse_mode="HTML")


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


@router.callback_query(F.data == "draft:back")
async def draft_back(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await q.answer()
    await show_preview(q.message, state, db, cfg, bot, q.from_user)


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
    await q.message.answer(tr("edit_value", label=f.label), reply_markup=edit_value_kb("draft:fields"), parse_mode="HTML")


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
    await q.message.answer(tr("edit_value", label=label), reply_markup=edit_value_kb("draft:fields"), parse_mode="HTML")


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
    await q.message.answer(tr("edit_value", label=label), reply_markup=edit_value_kb("draft:fields"), parse_mode="HTML")


@router.message(NewPage.edit_value)
async def take_draft_edit(msg: Message, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
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
    await show_preview(msg, state, db, cfg, bot, msg.from_user)


@router.callback_query(F.data == "draft:custom")
async def add_draft_custom(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    if d.get("type") == "news":
        await q.message.answer("В новостях свои поля не нужны")
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
async def draft_custom_value(msg: Message, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("empty_value"))
        return
    d = await state.get_data()
    data = d.get("page_data") or {}
    items = data.setdefault("custom_fields", [])
    items.append({"name": d["custom_name"], "value": msg.text.strip()[:3800]})
    await state.update_data(page_data=data)
    await msg.answer(tr("custom_added"))
    await show_preview(msg, state, db, cfg, bot, msg.from_user)


@router.callback_query(F.data == "draft:section")
async def add_draft_section(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    if d.get("type") == "news":
        await q.message.answer("В новостях свои разделы не нужны")
        return
    if len((d.get("page_data") or {}).get("sections") or []) >= 6:
        await q.message.answer(tr("limit_reached"))
        return
    await state.set_state(NewPage.section)
    await q.message.answer(tr("section_prompt"), reply_markup=edit_value_kb("draft:fields"))


@router.message(NewPage.section)
async def draft_section(msg: Message, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
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
    await show_preview(msg, state, db, cfg, bot, msg.from_user)


@router.callback_query(F.data == "draft:image")
async def replace_draft_image(q: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    tpl = get_template(d["type"])
    ptype = d.get("type") or ""
    count = len(page_images(d.get("page_data") or {}))
    max_c = 1 if ptype == "news" else MAX_PAGE_IMAGES
    await state.update_data(image_mode="draft")
    await state.set_state(NewPage.image)
    if ptype == "news":
        text = (
            f"Кинь одну картинку к новости\n"
            f"PNG JPEG или WEBP до {cfg.max_image_mb} МБ\n\n"
            f"Сейчас: {count}/{max_c}"
        )
    else:
        text = tr(
            "send_image",
            label=tpl.image_label.lower(),
            max_mb=cfg.max_image_mb,
            count=count,
            max_count=max_c,
        )
    await q.message.answer(text, reply_markup=image_kb(count, ptype))


@router.callback_query(F.data == "draft:save")
async def save_draft(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
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
    for path in page_images(p.data):
        await db.attach_media(path, p.id, q.from_user.id)
    await state.clear()
    await q.message.answer(tr("saved", title=p.title), reply_markup=page_actions_kb(p.id, p.type, p.theme))


@router.callback_query(F.data == "draft:text")
async def text_draft(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    p = make_draft(d, q.from_user.id)
    await send_page_text(q.message, p, draft_kb(p.type, p.theme))


@router.callback_query(F.data == "draft:export")
async def export_draft(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return

    raw = Path(d.get("preview_path") or "")
    path = raw.resolve() if raw.is_absolute() else (cfg.work_dir / raw).resolve()
    if path.parent != cfg.work_dir.resolve() or not path.name.startswith("preview_") or not path.is_file():
        p = await show_preview(q.message, state, db, cfg, bot, q.from_user)
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


@router.callback_query(F.data == "quick:text")
async def quick_text(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    await send_page_text(q.message, make_draft(d, q.from_user.id), quick_kb())


@router.callback_query(F.data == "quick:preview")
async def quick_preview(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    await q.answer()
    await show_preview(q.message, state, db, cfg, bot, q.from_user)


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
    await q.message.answer(tr("choose_theme"), reply_markup=themes_kb("dt", d.get("theme", "light"), d.get("type", "")), parse_mode="HTML")


@router.message(StateFilter(None), F.text)
async def quick_input(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    text = msg.text.strip()
    if text in {CREATE, MY_PAGES, THEMES_BTN, SETTINGS, HELP, NEWS, STATS}:
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
        theme=s.theme,
        preview_path=None,
        quick_text=quick_text,
        max_image_mb=cfg.max_image_mb,
        creation_log_sent=False,
        generation_counted=False,
    )
    await show_quick(msg, state)




@router.callback_query(F.data == "draft:olddoc")
async def draft_olddoc_menu(q: CallbackQuery, state: FSMContext) -> None:
    await q.answer()
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    data = d.get("page_data") or {}
    from olddoc import ensure_old_meta, paper_count
    ensure_old_meta(data)
    pending = {
        "_old_seed": data.get("_old_seed"),
        "_old_stain_count": int(data.get("_old_stain_count", 0)),
        "_old_paper": int(data.get("_old_paper", 0)),
        "_old_drunk": bool(data.get("_old_drunk", False)),
        "_old_drunk_flags": bool(data.get("_old_drunk_flags", False)),
        "_old_substances": bool(data.get("_old_substances", False)),
        "_old_window": bool(data.get("_old_window", True)),
        "_old_outline": bool(data.get("_old_outline", True)),
        "_old_bw": bool(data.get("_old_bw", False)),
    }
    await state.update_data(page_data=data, old_pending=pending)
    await q.message.answer(
        tr(
            "olddoc_pick",
            seed=pending.get("_old_seed", 0),
            paper=int(pending.get("_old_paper", 0)) + 1,
            cups=pending.get("_old_stain_count", 0),
            text="пьяный" if pending.get("_old_drunk") else "обычный",
            flags="пьяные" if pending.get("_old_drunk_flags") else "обычные",
            sub="вкл" if pending.get("_old_substances") else "выкл",
            window="вкл" if pending.get("_old_window", True) else "выкл",
            outline="вкл" if pending.get("_old_outline", True) else "выкл",
            bw="вкл" if pending.get("_old_bw") else "выкл",
        ),
        reply_markup=olddoc_options_kb(
            None,
            stain_count=int(pending.get("_old_stain_count", 0)),
            paper=int(pending.get("_old_paper", 0)),
            paper_total=paper_count(),
            drunk=bool(pending.get("_old_drunk", False)),
            drunk_flags=bool(pending.get("_old_drunk_flags", False)),
            substances=bool(pending.get("_old_substances", False)),
            window=bool(pending.get("_old_window", True)),
            outline=bool(pending.get("_old_outline", True)),
            bw=bool(pending.get("_old_bw", False)),
        ),
    )


def _pending_opts(d: dict) -> dict:
    from olddoc import ensure_old_meta
    data = dict(d.get("page_data") or {})
    ensure_old_meta(data)
    pending = d.get("old_pending")
    if not isinstance(pending, dict):
        pending = {
            "_old_seed": data.get("_old_seed"),
            "_old_stain_count": int(data.get("_old_stain_count", 0)),
            "_old_paper": int(data.get("_old_paper", 0)),
            "_old_drunk": bool(data.get("_old_drunk", False)),
            "_old_drunk_flags": bool(data.get("_old_drunk_flags", False)),
            "_old_substances": bool(data.get("_old_substances", False)),
            "_old_window": bool(data.get("_old_window", True)),
            "_old_outline": bool(data.get("_old_outline", True)),
            "_old_bw": bool(data.get("_old_bw", False)),
        }
    return pending


def _kb_from_pending(pending: dict):
    from olddoc import paper_count
    return olddoc_options_kb(
        None,
        stain_count=int(pending.get("_old_stain_count", 0)),
        paper=int(pending.get("_old_paper", 0)),
        paper_total=paper_count(),
        drunk=bool(pending.get("_old_drunk", False)),
        drunk_flags=bool(pending.get("_old_drunk_flags", False)),
        substances=bool(pending.get("_old_substances", False)),
        window=bool(pending.get("_old_window", True)),
        outline=bool(pending.get("_old_outline", True)),
        bw=bool(pending.get("_old_bw", False)),
    )


async def _draft_old_apply(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot, action: str) -> None:
    d = await state.get_data()
    if not d.get("type"):
        await q.message.answer(tr("draft_missing"))
        return
    data = d.get("page_data") or {}
    from olddoc import (
        ensure_old_meta,
        new_seed,
        cycle_stain_count_step,
        cycle_paper,
        toggle_drunk,
        toggle_drunk_flags,
        toggle_substances,
        toggle_window,
        toggle_outline,
        toggle_bw,
    )
    ensure_old_meta(data)
    pending = _pending_opts(d)

    if action == "apply":
        for k, v in pending.items():
            data[k] = v
        data["_old_stains"] = int(data.get("_old_stain_count", 0) or 0) > 0
        await state.update_data(page_data=data, old_pending=pending)
        await q.message.answer(tr("olddoc_applied"))
        await show_preview(q.message, state, db, cfg, bot, q.from_user)
        return

    # mutate a temp dict that mirrors pending keys for cycle helpers
    tmp = dict(pending)
    ensure_old_meta(tmp)
    if action == "reseed":
        new_seed(tmp)
        pending["_old_seed"] = tmp["_old_seed"]
    elif action in {"cups", "cups_next"}:
        pending["_old_stain_count"] = cycle_stain_count_step(tmp, 1)
    elif action == "cups_prev":
        pending["_old_stain_count"] = cycle_stain_count_step(tmp, -1)
    elif action in {"paper", "paper_next"}:
        pending["_old_paper"] = cycle_paper(tmp, 1)
    elif action == "paper_prev":
        pending["_old_paper"] = cycle_paper(tmp, -1)
    elif action == "text":
        pending["_old_drunk"] = toggle_drunk(tmp)
    elif action == "flags":
        pending["_old_drunk_flags"] = toggle_drunk_flags(tmp)
    elif action == "sub":
        pending["_old_substances"] = toggle_substances(tmp)
    elif action == "window":
        pending["_old_window"] = toggle_window(tmp)
    elif action == "outline":
        pending["_old_outline"] = toggle_outline(tmp)
    elif action == "bw":
        pending["_old_bw"] = toggle_bw(tmp)
    else:
        return

    await state.update_data(old_pending=pending)
    try:
        await q.message.edit_reply_markup(reply_markup=_kb_from_pending(pending))
    except Exception:
        pass
    await q.answer("ок")


@router.callback_query(
    F.data.in_({
        "old:reseed", "old:cups", "old:cups_next", "old:cups_prev",
        "old:paper", "old:paper_next", "old:paper_prev", "old:text", "old:flags",
        "old:sub", "old:window", "old:outline", "old:bw", "old:apply",
    })
)
async def draft_old_actions(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config, bot: Bot) -> None:
    action = q.data.split(":", 1)[1]
    if action != "apply":
        await q.answer()
    await _draft_old_apply(q, state, db, cfg, bot, action)
