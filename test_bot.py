from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from PIL import Image

from config import Config
from battle_handlers import battle_text_input
from battle_sides import normalize_sides
from create_handlers import (
    draft_image_caption_action,
    draft_theme,
    quick_input,
    remove_draft_image,
    save_draft,
    skip_image,
    start_new,
    take_image,
    take_draft_image_caption,
    take_field,
)
from db import Db
from models import Page
from page_handlers import take_page_image_caption, take_page_value
from states import EditPage, NewPage
from templates import COUNTRY, REGION
from ui import (
    draft_kb,
    fields_kb,
    image_kb,
    image_caption_kb,
    page_actions_kb,
    battle_sides_kb,
    battle_side_edit_kb,
    page_image_kb,
    progress_text,
    settings_kb,
    types_kb,
)


def fake_message(user_id: int = 10, text: str | None = None):
    sent = SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
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

    async def test_draft_accepts_multiple_images(self):
        await self.state.set_state(NewPage.image)
        await self.state.update_data(
            type="country",
            page_data={"title": "Турбания"},
            image_mode="initial",
        )
        buf = BytesIO()
        Image.new("RGB", (320, 180), "#a9f38f").save(buf, "PNG")
        raw = buf.getvalue()
        f = SimpleNamespace(file_size=len(raw))
        msg = fake_message()
        msg.photo = [f]

        async def download(_, destination):
            destination.write(raw)

        bot = SimpleNamespace(download=AsyncMock(side_effect=download))
        await take_image(msg, self.state, bot, self.db, self.cfg)
        self.assertEqual(await self.state.get_state(), NewPage.image_caption.state)
        msg.text = "Первая картинка"
        await take_draft_image_caption(msg, self.state)

        msg.text = None
        await take_image(msg, self.state, bot, self.db, self.cfg)
        await draft_image_caption_action(fake_callback("imgcap:skip", msg), self.state)

        d = await self.state.get_data()
        self.assertEqual(len(d["page_data"]["images"]), 2)
        self.assertEqual(
            d["page_data"]["image_captions"][d["page_data"]["images"][0]],
            "Первая картинка",
        )
        self.assertEqual(await self.state.get_state(), NewPage.image.state)

        await remove_draft_image(
            fake_callback("img:rm:0", msg),
            self.state,
            self.db,
            self.cfg,
        )
        d = await self.state.get_data()
        self.assertEqual(len(d["page_data"]["images"]), 1)
        self.assertNotIn("image_caption", d["page_data"])

    async def test_saved_page_image_caption_is_updated(self):
        path = "media_10_test.webp"
        p = await self.db.save_page(
            Page(
                owner_id=10,
                type="country",
                title="Турбания",
                data={"title": "Турбания", "images": [path], "image": path},
            )
        )
        await self.state.set_state(EditPage.image_caption)
        await self.state.update_data(page_id=p.id, caption_path=path, caption_i=0)
        msg = fake_message(text="Новая подпись")

        await take_page_image_caption(msg, self.state, self.db, self.cfg)

        saved = await self.db.get_page(p.id, 10)
        self.assertEqual(saved.data["image_caption"], "Новая подпись")
        self.assertEqual(await self.state.get_state(), EditPage.image.state)


    async def test_battle_editor_data_roundtrip(self):
        await self.state.update_data(type="battle", page_data={"title": "Битва"})
        msg = fake_message(text="Кефирстан")
        await self.state.set_state(NewPage.battle_text)
        await self.state.update_data(battle_side_i=0, battle_member_i=None, battle_action="side_name", battle_page_id=None)
        with patch("battle_handlers._show_side", AsyncMock()):
            await battle_text_input(msg, self.state, self.db, self.cfg, False)
        d = await self.state.get_data()
        self.assertEqual(d["page_data"]["side_1"], "Кефирстан")


class KeyboardTests(unittest.TestCase):
    def test_progress_text(self):
        s = progress_text(31)
        self.assertIn("31%", s)
        self.assertIn("▓▓▓", s)
        self.assertIn("░", s)

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
            image_kb(10),
            image_caption_kb(),
            image_caption_kb(123456789),
            page_actions_kb(123456789),
            page_image_kb(123456789, 10),
            settings_kb(),
            fields_kb(COUNTRY, data, 123456789),
            fields_kb(REGION, data, 123456789),
            battle_sides_kb("p", 123456789),
            battle_side_edit_kb("p", 0, [{"name": "Кефирстан", "flag": "media_flag.webp"}], 123456789),
        ]
        for kb in keyboards:
            buttons = [b for row in kb.inline_keyboard for b in row]
            self.assertLessEqual(len(buttons), 100)
            for b in buttons:
                if b.callback_data:
                    self.assertLessEqual(len(b.callback_data.encode()), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
