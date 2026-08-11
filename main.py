from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.types import BotCommand

from bot import make_dispatcher
from config import load_config
from db import Db

log = logging.getLogger("infobox")


async def setup_telegram(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="create", description="Создать страницу"),
        BotCommand(command="my_pages", description="Мои страницы"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
    ]

    try:
        await bot.set_my_commands(commands)
    except TelegramUnauthorizedError as e:
        raise RuntimeError(
            "Telegram отклонил BOT_TOKEN. Проверь токен в переменных окружения BotHost "
            "и при необходимости выпусти новый через @BotFather."
        ) from e
    except TelegramAPIError as e:
        log.warning("Не удалось установить меню команд, продолжаю запуск: %s", e)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except TelegramUnauthorizedError as e:
        raise RuntimeError(
            "Telegram отклонил BOT_TOKEN. Проверь токен в переменных окружения BotHost "
            "и при необходимости выпусти новый через @BotFather."
        ) from e
    except TelegramAPIError as e:
        # polling сам повторяет запросы после временных сетевых ошибок
        log.warning("Не удалось проверить webhook, перехожу к polling: %s", e)


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
        await setup_telegram(bot)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
