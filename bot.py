from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from admin import maintenance_middleware, router as admin_router
from config import Config
from create_handlers import router as create_router
from battle_handlers import router as battle_router
from db import Db
from handlers import on_error
from handlers import router as common_router
from page_handlers import router as page_router


def make_dispatcher(db: Db, cfg: Config) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["cfg"] = cfg
    # Blocks non-admins when maintenance is on (admin commands still work)
    dp.message.middleware(maintenance_middleware)
    dp.callback_query.middleware(maintenance_middleware)
    # Admin router first so /maint_* always reachable for admins
    dp.include_router(admin_router)
    dp.include_router(common_router)
    dp.include_router(page_router)
    dp.include_router(create_router)
    dp.include_router(battle_router)
    dp.errors()(on_error)
    return dp
