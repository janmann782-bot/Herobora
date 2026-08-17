from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, User

from config import Config
from db import Db
from models import Page
from renderer import render_page
from templates import get_template
from text_export import page_to_text, split_text
from themes import get_theme

log = logging.getLogger(__name__)


def _preview_path(page: Page, cfg: Config) -> Path | None:
    if not page.preview_path:
        return None
    root = cfg.work_dir.resolve()
    raw = Path(page.preview_path)
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if path.parent != root or not path.name.startswith("preview_"):
        return None
    return path if path.is_file() else None


def _author_line(user: User) -> str:
    name = html.escape(user.full_name or "Без имени", quote=False)
    if user.username:
        return f"{name} (@{html.escape(user.username, quote=False)})"
    return name


def _user_block(user: User) -> str:
    return (
        f"<b>Автор:</b> {_author_line(user)}\n"
        f"<b>Telegram ID:</b> <code>{user.id}</code>"
    )


async def send_log_text(bot: Bot, cfg: Config, text: str) -> bool:
    """Простое текстовое событие в лог-группу."""
    try:
        await bot.send_message(
            chat_id=cfg.log_chat_id,
            text=text[:4000],
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        log.exception("failed to send text log: chat=%s", cfg.log_chat_id)
        return False


def spawn_log_text(bot: Bot, cfg: Config, text: str) -> None:
    """Фоновая отправка - не тормозит пользователя."""
    try:
        asyncio.create_task(send_log_text(bot, cfg, text))
    except RuntimeError:
        log.debug("no running loop for log text")


async def send_created_page_log(
    bot: Bot,
    cfg: Config,
    db: Db,
    page: Page,
    user: User,
    preview_path: Path | None = None,
    stage: str = "render",
) -> bool:
    """Отправляет карточку в лог-чат в момент её первого рендера."""
    try:
        path = preview_path if preview_path and preview_path.is_file() else _preview_path(page, cfg)
        if path is None:
            settings = await db.get_settings(page.owner_id)
            path = await render_page(
                page,
                cfg.work_dir,
                settings.quality,
                watermark=settings.watermark,
            )
            page.preview_path = path.name
            if page.id is not None:
                await db.update_page(page)

        tpl = get_template(page.type)
        page_id = (
            f"<code>{page.id}</code>" if page.id is not None else "<i>ещё не сохранена</i>"
        )
        stage_label = {
            "render": "ПРЕВЬЮ",
            "save": "СОХРАНЕНА",
            "export": "ЭКСПОРТ",
        }.get(stage, stage.upper())
        header = (
            f"<b>▼ INFOBOX - {html.escape(stage_label, quote=False)}</b>\n\n"
            f"{_user_block(user)}\n"
            f"<b>Тип:</b> {html.escape(tpl.label, quote=False)}\n"
            f"<b>Название:</b> {html.escape(page.title or '-', quote=False)}\n"
            f"<b>Тема:</b> {html.escape(get_theme(page.theme).name, quote=False)}\n"
            f"<b>ID страницы:</b> {page_id}"
        )

        await bot.send_photo(
            chat_id=cfg.log_chat_id,
            photo=FSInputFile(path),
            caption=header[:1024],
            parse_mode="HTML",
        )

        text = page_to_text(page)
        chunks = split_text(text, limit=3800)
        for i, chunk in enumerate(chunks):
            title = "▼ ТЕКСТ КАРТОЧКИ\n\n" if i == 0 else "▼ ПРОДОЛЖЕНИЕ\n\n"
            await bot.send_message(
                chat_id=cfg.log_chat_id,
                text=title + chunk,
            )
        return True
    except Exception:
        log.exception(
            "failed to send card render log: chat=%s page=%s user=%s",
            cfg.log_chat_id,
            page.id,
            user.id,
        )
        return False


def spawn_created_page_log(
    bot: Bot,
    cfg: Config,
    db: Db,
    page: Page,
    user: User,
    preview_path: Path | None = None,
    stage: str = "render",
) -> None:
    try:
        asyncio.create_task(
            send_created_page_log(bot, cfg, db, page, user, preview_path, stage)
        )
    except RuntimeError:
        log.debug("no running loop for page log")


async def log_user_start(bot: Bot, cfg: Config, user: User) -> None:
    text = (
        "<b>▼ СТАРТ</b>\n\n"
        f"{_user_block(user)}\n"
        "Открыл бота /start"
    )
    await send_log_text(bot, cfg, text)


async def log_create_started(bot: Bot, cfg: Config, user: User, page_type: str) -> None:
    try:
        label = get_template(page_type).label
    except Exception:
        label = page_type
    text = (
        "<b>▼ НОВАЯ КАРТОЧКА</b>\n\n"
        f"{_user_block(user)}\n"
        f"<b>Тип:</b> {html.escape(str(label), quote=False)}"
    )
    await send_log_text(bot, cfg, text)


async def log_page_saved(bot: Bot, cfg: Config, user: User, page: Page) -> None:
    try:
        label = get_template(page.type).label
    except Exception:
        label = page.type
    text = (
        "<b>▼ СОХРАНЕНО</b>\n\n"
        f"{_user_block(user)}\n"
        f"<b>Тип:</b> {html.escape(str(label), quote=False)}\n"
        f"<b>Название:</b> {html.escape(page.title or '-', quote=False)}\n"
        f"<b>Тема:</b> {html.escape(get_theme(page.theme).name, quote=False)}\n"
        f"<b>ID:</b> <code>{page.id}</code>"
    )
    await send_log_text(bot, cfg, text)


async def log_page_deleted(bot: Bot, cfg: Config, user: User, page: Page) -> None:
    try:
        label = get_template(page.type).label
    except Exception:
        label = page.type
    text = (
        "<b>▼ УДАЛЕНО</b>\n\n"
        f"{_user_block(user)}\n"
        f"<b>Тип:</b> {html.escape(str(label), quote=False)}\n"
        f"<b>Название:</b> {html.escape(page.title or '-', quote=False)}\n"
        f"<b>ID:</b> <code>{page.id}</code>"
    )
    await send_log_text(bot, cfg, text)


async def log_export(bot: Bot, cfg: Config, user: User, page: Page) -> None:
    try:
        label = get_template(page.type).label
    except Exception:
        label = page.type
    text = (
        "<b>▼ ЭКСПОРТ PNG</b>\n\n"
        f"{_user_block(user)}\n"
        f"<b>Тип:</b> {html.escape(str(label), quote=False)}\n"
        f"<b>Название:</b> {html.escape(page.title or '-', quote=False)}\n"
        f"<b>ID:</b> <code>{page.id if page.id is not None else 'черновик'}</code>"
    )
    await send_log_text(bot, cfg, text)


async def log_render_error(bot: Bot, cfg: Config, user: User, page_type: str, error: str) -> None:
    text = (
        "<b>▼ ОШИБКА РЕНДЕРА</b>\n\n"
        f"{_user_block(user)}\n"
        f"<b>Тип:</b> {html.escape(str(page_type or '-'), quote=False)}\n"
        f"<b>Ошибка:</b>\n<code>{html.escape(str(error)[:800], quote=False)}</code>"
    )
    await send_log_text(bot, cfg, text)


async def log_cancel(bot: Bot, cfg: Config, user: User) -> None:
    text = (
        "<b>▼ ОТМЕНА</b>\n\n"
        f"{_user_block(user)}\n"
        "Сбросил создание / черновик"
    )
    await send_log_text(bot, cfg, text)


def spawn_user_start(bot: Bot, cfg: Config, user: User) -> None:
    try:
        asyncio.create_task(log_user_start(bot, cfg, user))
    except RuntimeError:
        pass


def spawn_create_started(bot: Bot, cfg: Config, user: User, page_type: str) -> None:
    try:
        asyncio.create_task(log_create_started(bot, cfg, user, page_type))
    except RuntimeError:
        pass


def spawn_page_saved(bot: Bot, cfg: Config, user: User, page: Page) -> None:
    try:
        asyncio.create_task(log_page_saved(bot, cfg, user, page))
    except RuntimeError:
        pass


def spawn_page_deleted(bot: Bot, cfg: Config, user: User, page: Page) -> None:
    try:
        asyncio.create_task(log_page_deleted(bot, cfg, user, page))
    except RuntimeError:
        pass


def spawn_export(bot: Bot, cfg: Config, user: User, page: Page) -> None:
    try:
        asyncio.create_task(log_export(bot, cfg, user, page))
    except RuntimeError:
        pass


def spawn_render_error(bot: Bot, cfg: Config, user: User, page_type: str, error: str) -> None:
    try:
        asyncio.create_task(log_render_error(bot, cfg, user, page_type, error))
    except RuntimeError:
        pass


def spawn_cancel(bot: Bot, cfg: Config, user: User) -> None:
    try:
        asyncio.create_task(log_cancel(bot, cfg, user))
    except RuntimeError:
        pass
