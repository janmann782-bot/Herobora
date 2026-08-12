from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from db import Db

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def format_count(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def milestone_text(value: int) -> str:
    return (
        "<b>ЙОУ!!! МЫ ДОСТИГЛИ ОТМЕТКИ ГЕНЕРАЦИЙ "
        f"В КОЛИЧЕСТВЕ {format_count(value)}🥳</b>"
    )


async def broadcast_milestone(bot: Bot, db: Db, milestone: int) -> None:
    text = milestone_text(milestone)
    users = await db.get_all_user_ids()
    sent = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.2)
            try:
                await bot.send_message(user_id, text, parse_mode="HTML")
                sent += 1
            except Exception:
                log.debug("milestone retry failed for user %s", user_id, exc_info=True)
        except (TelegramForbiddenError, TelegramBadRequest):
            # Пользователь мог заблокировать бота или удалить чат.
            pass
        except Exception:
            log.warning("milestone broadcast failed for user %s", user_id, exc_info=True)
        await asyncio.sleep(0.04)
    log.info("milestone %s broadcast: %s/%s users", milestone, sent, len(users))


def spawn_milestone_broadcast(bot: Bot, db: Db, milestone: int) -> None:
    task = asyncio.create_task(broadcast_milestone(bot, db, milestone))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
