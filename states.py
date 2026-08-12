from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.fsm.state import State, StatesGroup

from media import page_images, safe_unlink

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

    from config import Config
    from db import Db


class NewPage(StatesGroup):
    field = State()
    image = State()
    image_caption = State()
    battle_text = State()
    battle_flag = State()
    theme = State()
    review = State()
    edit_value = State()
    custom_name = State()
    custom_value = State()
    section = State()
    quick = State()
    battle_text = State()
    battle_flag = State()


class EditPage(StatesGroup):
    value = State()
    custom_name = State()
    custom_value = State()
    section = State()
    image = State()
    image_caption = State()
    battle_text = State()
    battle_flag = State()


async def clear_flow(state: FSMContext, user_id: int, db: Db, cfg: Config) -> None:
    d = await state.get_data()
    safe_unlink(d.get("preview_path"), cfg.work_dir, "preview_")
    for path in page_images(d.get("page_data") or {}):
        if await db.drop_unattached_media(path, user_id):
            safe_unlink(path, cfg.work_dir, "media_")
    await state.clear()
