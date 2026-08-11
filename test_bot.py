from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from config import Config
from create_handlers import (
    draft_theme,
    quick_input,
    save_draft,
    skip_image,
    start_new,
    take_field,
)
from db import Db
from models import Page
from page_handlers import take_page_value
from states import EditPage, NewPage
from templates import COUNTRY
from ui import draft_kb, fields_kb, page_actions_kb, settings_kb, types_kb


def fake_message(user_id: int = 10, text: str | None = None):
    sent = SimpleNamespace(delete=AsyncMock())
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, first_name="Тест", username="test"),
        text=text,
        photo=None,
        document=None,
        answer=AsyncMock(return_value=sent),
        answer_photo=AsyncMock(return_value=sent),
        answer_document=AsyncMock(return_value=sent),
    )


def fake_callback(data: str, msg, user_id: int = 10):
    return SimpleNamespace(
        data=data,
        message=msg,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = Config("fake-token", root, root / "test.db")
        self.db = Db(self.cfg.db_path)
        await self.db.init()
        self.storage = MemoryStorage()
        self.state = FSMContext(
            storage=self.storage,
            key=StorageKey(bot_id=1, chat_id=10, user_id=10),
        )

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_short_wizard_reaches_preview_and_saves(self):
        msg = fake_message()
        await start_new(fake_callback("new:country", msg), self.state, self.db, self.cfg)

        values = [
            "Республика Гринвальд",
            "Северная Республика Гринвальд",
            "Норд",
            "18 миллионов",
            "Парламентская республика",
            "Северное государство",
        ]
        for s in values:
            msg.text = s
            await take_field(msg, self.state)

        self.assertEqual(await self.state.get_state(), NewPage.image.state)
        await skip_image(fake_callback("img:skip", msg), self.state, self.db, self.cfg)
        self.assertEqual(await self.state.get_state(), NewPage.theme.state)

        path = self.cfg.work_dir / "preview_test.png"
        path.write_bytes(b"png")
        with (
            patch("create_handlers.render_page", AsyncMock(return_value=path)),
            patch("create_handlers.send_png", AsyncMock()),
        ):
            await draft_theme(fake_callback("dt:dark", msg), self.state, self.db, self.cfg)

        self.assertEqual(await self.state.get_state(), NewPage.review.state)
        await save_draft(fake_callback("draft:save", msg), self.state, self.db)
        pages = await self.db.get_user_pages(10)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].data["capital"], "Норд")
        self.assertEqual(pages[0].theme, "dark")

    async def test_quick_input_creates_reviewable_draft(self):
        msg = fake_message(
            text="Тип: страна\nНазвание — Турбания\nСтолица Светлозорь\nНаселение: 12 млн"
        )
        await quick_input(msg, self.state, self.db, self.cfg)
        d = await self.state.get_data()
        self.assertEqual(await self.state.get_state(), NewPage.quick.state)
        self.assertEqual(d["type"], "country")
        self.assertEqual(d["page_data"]["capital"], "Светлозорь")

    async def test_saved_page_field_edit(self):
        p = await self.db.save_page(
            Page(
                owner_id=10,
                type="country",
                title="Турбания",
                data={"title": "Турбания", "capital": "Старый город"},
            )
        )
        await self.state.set_state(EditPage.value)
        await self.state.update_data(page_id=p.id, edit_kind="s", edit_key="capital")
        msg = fake_message(text="Светлозорь")

        with patch("page_handlers.render_saved", AsyncMock()):
            await take_page_value(msg, self.state, self.db, self.cfg)

        saved = await self.db.get_page(p.id, 10)
        self.assertEqual(saved.data["capital"], "Светлозорь")


class KeyboardTests(unittest.TestCase):
    def test_callback_data_fits_telegram_limit(self):
        data = {
            "custom_fields": [{"name": f"Поле {i}", "value": i} for i in range(20)],
            "sections": [
                {
                    "title": f"Раздел {i}",
                    "fields": [{"name": f"Значение {j}", "value": j} for j in range(6)],
                }
                for i in range(6)
            ],
        }
        keyboards = [
            types_kb(),
            draft_kb(),
            page_actions_kb(123456789),
            settings_kb(),
            fields_kb(COUNTRY, data, 123456789),
        ]
        for kb in keyboards:
            buttons = [b for row in kb.inline_keyboard for b in row]
            self.assertLessEqual(len(buttons), 100)
            for b in buttons:
                if b.callback_data:
                    self.assertLessEqual(len(b.callback_data.encode()), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)

