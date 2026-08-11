from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import BotCommand

from bot import make_dispatcher
from config import load_config
from db import Db


async def main() -> None:
    cfg = load_config()
    cfg.work_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    db = Db(cfg.db_path)
    await db.init()
    bot = Bot(cfg.bot_token)
    dp = make_dispatcher(db, cfg)

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="create", description="Создать страницу"),
                BotCommand(command="my_pages", description="Мои страницы"),
                BotCommand(command="settings", description="Настройки"),
                BotCommand(command="help", description="Помощь"),
                BotCommand(command="cancel", description="Отменить текущее действие"),
            ]
        )
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

