"""Hidden admin tools — not listed in BotFather / set_my_commands menu."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import Config

log = logging.getLogger(__name__)
router = Router(name="admin")

# Primary admin (hardcoded) + optional ADMIN_IDS=1,2,3 from env
_DEFAULT_ADMINS = {7787565361}


def admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "").strip()
    ids = set(_DEFAULT_ADMINS)
    if raw:
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
    return ids


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) in admin_ids()


class AdminFilter(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if user is None and hasattr(event, "message"):
            user = getattr(event.message, "from_user", None)
        return is_admin(getattr(user, "id", None))


def _state_path(cfg: Config) -> Path:
    return Path(cfg.work_dir).resolve() / "bot_runtime_state.json"


def get_maintenance(cfg: Config) -> bool:
    import json

    p = _state_path(cfg)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text("utf-8"))
        return bool(data.get("maintenance", False))
    except Exception:
        return False


def set_maintenance(cfg: Config, on: bool) -> None:
    import json

    p = _state_path(cfg)
    data = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text("utf-8"))
        except Exception:
            data = {}
    data["maintenance"] = bool(on)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def maintenance_text() -> str:
    return "Бот на техработах пока не работает\nЗайди позже"


@router.message(Command("admin"), AdminFilter())
async def admin_help(msg: Message) -> None:
    await msg.answer(
        "Админ команды (скрыты из меню)\n\n"
        "/maint — статус техработ\n"
        "/maint_on — включить техработы\n"
        "/maint_off — выключить\n"
        "/admin — эта справка"
    )


@router.message(Command("maint"), AdminFilter())
async def maint_status(msg: Message, cfg: Config) -> None:
    on = get_maintenance(cfg)
    await msg.answer(f"Техработы: {'вкл' if on else 'выкл'}")


@router.message(Command("maint_on"), AdminFilter())
async def maint_on(msg: Message, cfg: Config) -> None:
    set_maintenance(cfg, True)
    log.warning("Maintenance ON by admin %s", msg.from_user.id if msg.from_user else "?")
    await msg.answer("Техработы включены\nОстальным бот молчит тебе можно")


@router.message(Command("maint_off"), AdminFilter())
async def maint_off(msg: Message, cfg: Config) -> None:
    set_maintenance(cfg, False)
    log.warning("Maintenance OFF by admin %s", msg.from_user.id if msg.from_user else "?")
    await msg.answer("Техработы выключены\nБот снова для всех")


async def maintenance_middleware(handler, event, data):
    cfg: Config | None = data.get("cfg")
    if cfg is None or not get_maintenance(cfg):
        return await handler(event, data)

    user = None
    if isinstance(event, Message):
        user = event.from_user
    elif isinstance(event, CallbackQuery):
        user = event.from_user
    else:
        user = getattr(event, "from_user", None)

    uid = getattr(user, "id", None)
    if is_admin(uid):
        return await handler(event, data)

    text = maintenance_text()
    try:
        if isinstance(event, CallbackQuery):
            await event.answer("техработы", show_alert=True)
            if event.message:
                await event.message.answer(text)
        elif isinstance(event, Message):
            await event.answer(text)
    except Exception:
        log.exception("maintenance reply failed")
    return None
