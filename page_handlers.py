from __future__ import annotations

import logging
from contextlib import suppress
from io import BytesIO
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Config
from db import Db
from locales import tr
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
from parser import parse_section
from renderer import render_error_text, render_page
from states import EditPage, clear_flow
from templates import get_template
from text_export import send_page_text
from themes import THEMES, get_theme
from ui import (
    MY_PAGES,
    delete_kb,
    edit_value_kb,
    fields_kb,
    image_caption_kb,
    main_menu,
    page_actions_kb,
    olddoc_options_kb,
    page_image_kb,
    pages_kb,
    progress_text,
    render_progress,
    send_png,
    themes_kb,
)

router = Router(name="pages")
log = logging.getLogger(__name__)
IMAGE_CAPTION_LIMIT = 500


def valid_preview(path: str | None, cfg: Config) -> Path | None:
    if not path:
        return None
    root = cfg.work_dir.resolve()
    raw = Path(path)
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("preview_"):
        return None
    return p if p.is_file() else None


async def render_saved(
    msg: Message,
    p: Page,
    db: Db,
    cfg: Config,
    document: bool = False,
) -> Path | None:
    path = valid_preview(p.preview_path, cfg)
    wait = None
    if not path:
        wait = await msg.answer(progress_text(8))
        try:
            s = await db.get_settings(p.owner_id)
            path = await render_progress(
                wait,
                render_page(
                    p,
                    cfg.work_dir,
                    s.quality,
                    watermark=s.watermark,
                ),
            )
            p.preview_path = path.name
            await db.update_page(p)
        except Exception as e:
            log.exception("saved page render failed: page=%s user=%s", p.id, p.owner_id)
            await msg.answer(tr("render_error", error=render_error_text(e)))
            return None
        finally:
            if wait:
                with suppress(TelegramBadRequest):
                    await wait.delete()

    caption = tr("page_caption", title=p.title, theme=get_theme(p.theme).name)
    await send_png(msg, path, caption, None if document else page_actions_kb(p.id, p.type, p.theme), document)
    return path


async def get_owned(q: CallbackQuery, db: Db, page_id: int) -> Page | None:
    p = await db.get_page(page_id, q.from_user.id)
    if not p:
        await q.message.answer(tr("page_not_found"))
    return p


async def show_pages(msg: Message, db: Db, user_id: int) -> None:
    pages = await db.get_user_pages(user_id)
    if not pages:
        await msg.answer(tr("pages_empty"), reply_markup=main_menu())
        return
    await msg.answer(tr("pages_title"), reply_markup=pages_kb(pages))


@router.message(Command("my_pages"))
@router.message(F.text == MY_PAGES)
async def my_pages(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    await clear_flow(state, msg.from_user.id, db, cfg)
    await show_pages(msg, db, msg.from_user.id)


@router.callback_query(F.data == "pages:list")
async def page_list_callback(
    q: CallbackQuery, state: FSMContext, db: Db, cfg: Config
) -> None:
    await q.answer()
    await clear_flow(state, q.from_user.id, db, cfg)
    await show_pages(q.message, db, q.from_user.id)


@router.callback_query(F.data.startswith("p:o:"))
async def open_page(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await clear_flow(state, q.from_user.id, db, cfg)
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if p:
        await render_saved(q.message, p, db, cfg)


@router.callback_query(F.data.startswith("p:e:"))
async def edit_page(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    await clear_flow(state, q.from_user.id, db, cfg)
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if not p:
        return
    await q.message.answer(
        tr("fields_title"),
        reply_markup=fields_kb(get_template(p.type), p.data, p.id),
    )


@router.callback_query(F.data.startswith("pe:"))
async def choose_page_field(q: CallbackQuery, state: FSMContext, db: Db) -> None:
    await q.answer()
    parts = q.data.split(":")
    if len(parts) < 4:
        return
    page_id = int(parts[1])
    kind = parts[2]
    p = await get_owned(q, db, page_id)
    if not p:
        return

    label = "Поле"
    edit: dict = {"page_id": page_id, "edit_kind": kind}
    if kind == "s":
        i = int(parts[3])
        tpl = get_template(p.type)
        if not 0 <= i < len(tpl.fields):
            return
        f = tpl.fields[i]
        edit.update(edit_key=f.key)
        label = f.label
    elif kind == "c":
        i = int(parts[3])
        items = p.data.get("custom_fields") or []
        if not 0 <= i < len(items):
            return
        edit.update(edit_i=i)
        label = items[i].get("name", "Свое поле")
    elif kind == "h":
        i = int(parts[3])
        sections = p.data.get("sections") or []
        if not 0 <= i < len(sections):
            return
        edit.update(edit_i=i)
        label = "Название раздела"
    elif kind == "x" and len(parts) == 5:
        i, j = int(parts[3]), int(parts[4])
        sections = p.data.get("sections") or []
        if not 0 <= i < len(sections) or not 0 <= j < len(sections[i].get("fields") or []):
            return
        edit.update(edit_i=i, edit_j=j)
        label = sections[i]["fields"][j].get("name", "Поле")
    else:
        return

    await state.update_data(**edit)
    await state.set_state(EditPage.value)
    await q.message.answer(
        tr("edit_value", label=label),
        reply_markup=edit_value_kb(f"p:e:{page_id}", f"p:o:{page_id}"),
    )


async def save_and_render(msg: Message, p: Page, db: Db, cfg: Config) -> None:
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.preview_path = None
    await db.update_page(p)
    await msg.answer(tr("field_saved"))
    await render_saved(msg, p, db, cfg)


@router.message(EditPage.value)
async def take_page_value(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    if not msg.text:
        await msg.answer(tr("text_only"))
        return
    s = msg.text.strip()
    if len(s) > 3800:
        await msg.answer(tr("too_long", limit=3800))
        return

    d = await state.get_data()
    p = await db.get_page(int(d["page_id"]), msg.from_user.id)
    if not p:
        await state.clear()
        await msg.answer(tr("page_not_found"))
        return

    kind = d["edit_kind"]
    value = "" if s == "-" else s
    if kind == "s":
        key = d["edit_key"]
        if key == "title" and not value:
            await msg.answer(tr("title_required"))
            return
        if key == "image_caption" and page_images(p.data):
            set_image_caption(p.data, page_images(p.data)[0], value)
        elif value:
            p.data[key] = value
        else:
            p.data.pop(key, None)
        if key == "title":
            p.title = value
    elif kind == "c":
        i = int(d["edit_i"])
        if value:
            p.data["custom_fields"][i]["value"] = value
        else:
            p.data["custom_fields"].pop(i)
    elif kind == "h":
        if not value:
            await msg.answer(tr("section_title_empty"))
            return
        p.data["sections"][int(d["edit_i"])]["title"] = value[:120]
    elif kind == "x":
        i, j = int(d["edit_i"]), int(d["edit_j"])
        if value:
            p.data["sections"][i]["fields"][j]["value"] = value
        else:
            p.data["sections"][i]["fields"].pop(j)

    await state.clear()
    await save_and_render(msg, p, db, cfg)


@router.callback_query(F.data.startswith("pa:"))
async def page_add(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    _, raw_id, action = q.data.split(":")
    page_id = int(raw_id)
    p = await get_owned(q, db, page_id)
    if not p:
        return
    await state.update_data(page_id=page_id)

    if action == "custom":
        if len(p.data.get("custom_fields") or []) >= 20:
            await q.message.answer(tr("limit_reached"))
            return
        await state.set_state(EditPage.custom_name)
        await q.message.answer(
            tr("custom_name"),
            reply_markup=edit_value_kb(f"p:e:{page_id}", f"p:o:{page_id}"),
        )
    elif action == "section":
        if len(p.data.get("sections") or []) >= 6:
            await q.message.answer(tr("limit_reached"))
            return
        await state.set_state(EditPage.section)
        await q.message.answer(
            tr("section_prompt"),
            reply_markup=edit_value_kb(f"p:e:{page_id}", f"p:o:{page_id}"),
        )
    elif action == "image":
        await state.set_state(EditPage.image)
        tpl = get_template(p.type)
        count = len(page_images(p.data))
        await q.message.answer(
            tr(
                "send_image",
                label=tpl.image_label.lower(),
                max_mb=cfg.max_image_mb,
                count=count,
                max_count=MAX_PAGE_IMAGES,
            ),
            reply_markup=page_image_kb(page_id, count),
        )


@router.message(EditPage.custom_name)
async def page_custom_name(msg: Message, state: FSMContext) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("custom_name"))
        return
    name = msg.text.strip()[:100]
    d = await state.get_data()
    await state.update_data(custom_name=name)
    await state.set_state(EditPage.custom_value)
    await msg.answer(
        tr("custom_value", name=name),
        reply_markup=edit_value_kb(f"p:e:{d['page_id']}", f"p:o:{d['page_id']}"),
    )


@router.message(EditPage.custom_value)
async def page_custom_value(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    if not msg.text or not msg.text.strip():
        await msg.answer(tr("empty_value"))
        return
    d = await state.get_data()
    p = await db.get_page(int(d["page_id"]), msg.from_user.id)
    if not p:
        await state.clear()
        await msg.answer(tr("page_not_found"))
        return
    p.data.setdefault("custom_fields", []).append(
        {"name": d["custom_name"], "value": msg.text.strip()[:3800]}
    )
    await state.clear()
    await save_and_render(msg, p, db, cfg)


@router.message(EditPage.section)
async def page_section(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    sec = parse_section(msg.text or "")
    if not sec:
        await msg.answer(tr("section_bad"))
        return
    d = await state.get_data()
    p = await db.get_page(int(d["page_id"]), msg.from_user.id)
    if not p:
        await state.clear()
        await msg.answer(tr("page_not_found"))
        return
    total = sum(len(x.get("fields") or []) for x in p.data.get("sections") or [])
    if total + len(sec["fields"]) > 40:
        await msg.answer(tr("limit_reached"))
        return
    p.data.setdefault("sections", []).append(sec)
    await state.clear()
    await save_and_render(msg, p, db, cfg)


@router.message(EditPage.image)
async def page_image(msg: Message, state: FSMContext, bot: Bot, db: Db, cfg: Config) -> None:
    d = await state.get_data()
    p = await db.get_page(int(d["page_id"]), msg.from_user.id)
    if not p:
        await state.clear()
        await msg.answer(tr("page_not_found"))
        return
    images = page_images(p.data)
    if len(images) >= MAX_PAGE_IMAGES:
        await msg.answer(
            tr("image_limit", max_count=MAX_PAGE_IMAGES),
            reply_markup=page_image_kb(p.id, len(images)),
        )
        return

    f = msg.photo[-1] if msg.photo else msg.document
    if not f:
        await msg.answer(tr("image_only"), reply_markup=page_image_kb(p.id, len(images)))
        return
    size = getattr(f, "file_size", 0) or 0
    if size > cfg.max_image_mb * 1024 * 1024:
        await msg.answer(
            tr("image_bad", error=f"файл больше {cfg.max_image_mb} МБ"),
            reply_markup=page_image_kb(p.id, len(images)),
        )
        return

    buf = BytesIO()
    try:
        await bot.download(f, destination=buf)
        info = await save_image(buf.getvalue(), msg.from_user.id, cfg.work_dir, cfg.max_image_mb)
    except BadImage as e:
        await msg.answer(
            tr("image_bad", error=str(e)),
            reply_markup=page_image_kb(p.id, len(images)),
        )
        return
    except Exception:
        log.exception("page image download failed for user %s", msg.from_user.id)
        await msg.answer(
            tr("image_bad", error="не удалось скачать файл"),
            reply_markup=page_image_kb(p.id, len(images)),
        )
        return

    images.append(info.path.name)
    set_page_images(p.data, images)
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.preview_path = None
    await db.add_media(msg.from_user.id, info.path.name, info.width, info.height, p.id)
    await db.update_page(p)
    await state.update_data(
        page_id=p.id,
        caption_path=info.path.name,
        caption_i=len(images) - 1,
    )
    await state.set_state(EditPage.image_caption)
    await msg.answer(
        tr("image_saved", count=len(images), max_count=MAX_PAGE_IMAGES)
        + "\n\n"
        + tr("image_caption_prompt", number=len(images), limit=IMAGE_CAPTION_LIMIT),
        reply_markup=image_caption_kb(p.id),
    )


@router.callback_query(F.data.startswith("pi:"))
async def page_image_action(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    page_id = int(parts[1])
    p = await get_owned(q, db, page_id)
    if not p:
        await state.clear()
        return
    images = page_images(p.data)
    action = parts[2]

    if action == "done":
        await state.clear()
        await render_saved(q.message, p, db, cfg)
        return
    if action == "cap" and len(parts) == 4:
        i = int(parts[3])
        if not 0 <= i < len(images):
            return
        path = images[i]
        await state.update_data(page_id=page_id, caption_path=path, caption_i=i)
        await state.set_state(EditPage.image_caption)
        s = tr("image_caption_prompt", number=i + 1, limit=IMAGE_CAPTION_LIMIT)
        current = image_caption(p.data, path, i)
        if current:
            s += "\n\n" + tr("current_value", value=current[:500])
        await q.message.answer(s, reply_markup=image_caption_kb(page_id))
        return
    if action != "rm" or len(parts) != 4:
        return

    i = int(parts[3])
    if not 0 <= i < len(images):
        return
    old = images.pop(i)
    set_page_images(p.data, images)
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.preview_path = None
    await db.update_page(p)
    if await db.drop_media_if_unused(old, q.from_user.id):
        safe_unlink(old, cfg.work_dir, "media_")
    await q.message.answer(
        tr("image_removed", number=i + 1, count=len(images)),
        reply_markup=page_image_kb(page_id, len(images)),
    )


@router.message(EditPage.image_caption)
async def take_page_image_caption(msg: Message, state: FSMContext, db: Db, cfg: Config) -> None:
    d = await state.get_data()
    page_id = int(d["page_id"])
    if not msg.text:
        await msg.answer(tr("text_only"), reply_markup=image_caption_kb(page_id))
        return
    s = msg.text.strip()
    if not s:
        await msg.answer(tr("empty_value"), reply_markup=image_caption_kb(page_id))
        return
    if len(s) > IMAGE_CAPTION_LIMIT:
        await msg.answer(
            tr("too_long", limit=IMAGE_CAPTION_LIMIT),
            reply_markup=image_caption_kb(page_id),
        )
        return

    p = await db.get_page(page_id, msg.from_user.id)
    if not p:
        await state.clear()
        await msg.answer(tr("page_not_found"))
        return
    images = page_images(p.data)
    path = str(d.get("caption_path") or "")
    if path not in images:
        await state.set_state(EditPage.image)
        await msg.answer(tr("images_continue"), reply_markup=page_image_kb(page_id, len(images)))
        return

    set_image_caption(p.data, path, s)
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.preview_path = None
    await db.update_page(p)
    await state.update_data(page_id=page_id, caption_path=None, caption_i=None)
    await state.set_state(EditPage.image)
    await msg.answer(tr("image_caption_saved"), reply_markup=page_image_kb(page_id, len(images)))


@router.callback_query(EditPage.image_caption, F.data.startswith("pc:"))
async def page_image_caption_action(
    q: CallbackQuery,
    state: FSMContext,
    db: Db,
    cfg: Config,
) -> None:
    await q.answer()
    _, raw_id, action = q.data.split(":")
    page_id = int(raw_id)
    p = await get_owned(q, db, page_id)
    if not p:
        await state.clear()
        return

    d = await state.get_data()
    images = page_images(p.data)
    path = str(d.get("caption_path") or "")
    text = tr("images_continue")
    if action == "skip" and path in images:
        set_image_caption(p.data, path, "")
        safe_unlink(p.preview_path, cfg.work_dir, "preview_")
        p.preview_path = None
        await db.update_page(p)
        text = tr("image_caption_skipped")

    await state.update_data(page_id=page_id, caption_path=None, caption_i=None)
    await state.set_state(EditPage.image)
    await q.message.answer(text, reply_markup=page_image_kb(page_id, len(images)))


@router.callback_query(F.data.startswith("p:t:"))
async def page_theme(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if p:
        await q.message.answer(tr("choose_theme"), reply_markup=themes_kb(f"pt:{page_id}", p.theme, p.type), parse_mode="HTML")


@router.callback_query(F.data.startswith("pt:"))
async def set_page_theme(q: CallbackQuery, db: Db, cfg: Config) -> None:
    await q.answer()
    _, raw_id, theme = q.data.split(":")
    page_id = int(raw_id)
    p = await get_owned(q, db, page_id)
    if not p:
        return
    if theme == "back":
        await render_saved(q.message, p, db, cfg)
        return
    if theme not in THEMES:
        return
    from themes import theme_allowed
    if not theme_allowed(theme, p.type):
        await q.message.answer("Тема «Старый документ» пока доступна только для стран")
        return
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.theme = theme
    p.preview_path = None
    await db.update_page(p)
    await render_saved(q.message, p, db, cfg)


@router.callback_query(F.data.startswith("p:txt:"))
async def text_page(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if p:
        await send_page_text(q.message, p, page_actions_kb(p.id, p.type, p.theme))


@router.callback_query(F.data.startswith("p:c:"))
async def copy_page(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await db.copy_page(page_id, q.from_user.id)
    if not p:
        await q.message.answer(tr("page_not_found"))
        return
    for path in page_images(p.data):
        await db.attach_media(path, p.id, q.from_user.id)
    await q.message.answer(tr("copied", title=p.title), reply_markup=page_actions_kb(p.id, p.type, p.theme))


@router.callback_query(F.data.startswith("p:x:"))
async def export_page(q: CallbackQuery, db: Db, cfg: Config) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if p:
        await render_saved(q.message, p, db, cfg, document=True)


@router.callback_query(F.data.startswith("p:d:"))
async def ask_delete(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if p:
        await q.message.answer(tr("delete_confirm", title=p.title), reply_markup=delete_kb(page_id))


@router.callback_query(F.data.startswith("pd:") & F.data.endswith(":yes"))
async def delete_page(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config) -> None:
    await q.answer()
    page_id = int(q.data.split(":")[1])
    p = await get_owned(q, db, page_id)
    if not p:
        return
    ok = await db.delete_page(page_id, q.from_user.id)
    if ok:
        safe_unlink(p.preview_path, cfg.work_dir, "preview_")
        for path in page_images(p.data):
            if await db.drop_media_if_unused(path, q.from_user.id):
                safe_unlink(path, cfg.work_dir, "media_")
        await state.clear()
        await q.message.answer(tr("deleted"), reply_markup=main_menu())



@router.callback_query(F.data.startswith("p:old:"))
async def page_olddoc_menu(q: CallbackQuery, db: Db) -> None:
    await q.answer()
    page_id = int(q.data.rsplit(":", 1)[1])
    p = await get_owned(q, db, page_id)
    if not p:
        return
    from olddoc import ensure_old_meta
    ensure_old_meta(p.data)
    await q.message.answer(
        tr(
            "olddoc_options",
            seed=p.data.get("_old_seed", 0),
            cups=p.data.get("_old_stain_count", 1),
            paper=int(p.data.get("_old_paper", 0)) + 1,
            text="пьяный" if p.data.get("_old_drunk") else "обычный",
        ),
        reply_markup=olddoc_options_kb(
            page_id,
            stain_count=int(p.data.get("_old_stain_count", 0)),
            paper=int(p.data.get("_old_paper", 0)),
            paper_total=__import__("olddoc", fromlist=["paper_count"]).paper_count(),
            drunk=bool(p.data.get("_old_drunk", False)),
        ),
    )


@router.callback_query(
    F.data.func(
        lambda d: isinstance(d, str)
        and d.startswith("old:")
        and d.count(":") == 2
        and d.split(":")[1].isdigit()
        and d.split(":")[2] in {
            "reseed", "cups", "cups_next", "cups_prev",
            "paper", "paper_next", "paper_prev", "text",
        }
    )
)
async def page_old_actions(q: CallbackQuery, db: Db, cfg: Config) -> None:
    parts = (q.data or "").split(":")
    await q.answer()
    page_id = int(parts[1])
    action = parts[2]
    p = await get_owned(q, db, page_id)
    if not p:
        return
    from olddoc import (
        ensure_old_meta,
        new_seed,
        cycle_stain_count_step,
        cycle_paper,
        toggle_drunk,
    )
    ensure_old_meta(p.data)
    if action == "reseed":
        new_seed(p.data)
        msg = tr("olddoc_reseeded")
    elif action in {"cups", "cups_next"}:
        n = cycle_stain_count_step(p.data, 1)
        msg = tr("olddoc_cups", count=n)
    elif action == "cups_prev":
        n = cycle_stain_count_step(p.data, -1)
        msg = tr("olddoc_cups", count=n)
    elif action in {"paper", "paper_next"}:
        n = cycle_paper(p.data, 1)
        msg = tr("olddoc_paper", n=n + 1)
    elif action == "paper_prev":
        n = cycle_paper(p.data, -1)
        msg = tr("olddoc_paper", n=n + 1)
    elif action == "text":
        drunk = toggle_drunk(p.data)
        msg = tr("olddoc_text_drunk" if drunk else "olddoc_text_normal")
    else:
        return
    safe_unlink(p.preview_path, cfg.work_dir, "preview_")
    p.preview_path = None
    await db.update_page(p)
    await q.message.answer(msg)
    await render_saved(q.message, p, db, cfg)

