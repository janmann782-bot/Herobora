from __future__ import annotations

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
        header = (
            "<b>▼ СОЗДАЁТСЯ INFOBOX-КАРТОЧКА</b>\n\n"
            f"<b>Автор:</b> {_author_line(user)}\n"
            f"<b>Telegram ID:</b> <code>{user.id}</code>\n"
            f"<b>Тип:</b> {html.escape(tpl.label, quote=False)}\n"
            f"<b>Название:</b> {html.escape(page.title, quote=False)}\n"
            f"<b>Тема:</b> {html.escape(get_theme(page.theme).name, quote=False)}\n"
            f"<b>ID страницы:</b> {page_id}"
        )

        # Карточка идёт отдельным сообщением, чтобы её было удобно открыть в логах.
        await bot.send_photo(
            chat_id=cfg.log_chat_id,
            photo=FSInputFile(path),
            caption=header,
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
