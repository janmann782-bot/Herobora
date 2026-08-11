from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.fsm.state import State, StatesGroup

from media import safe_unlink

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

    from config import Config
    from db import Db


class NewPage(StatesGroup):
    field = State()
    image = State()
    theme = State()
    review = State()
    edit_value = State()
    custom_name = State()
    custom_value = State()
    section = State()
    quick = State()


class EditPage(StatesGroup):
    value = State()
    custom_name = State()
    custom_value = State()
    section = State()
    image = State()


async def clear_flow(state: FSMContext, user_id: int, db: Db, cfg: Config) -> None:
    d = await state.get_data()
    safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
    image = (d.get("page_data") or {}).get("image")
    if image and await db.drop_unattached_media(image, user_id):
        safe_unlink(image, cfg.work_dir, "media_")
    await state.clear()
