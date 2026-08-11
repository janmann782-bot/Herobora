from __future__ import annotations

import importlib.util
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from db import Db
from media import BadImage, save_image
from models import Page
from parser import parse_section, parse_text
from renderer import make_html, render_page
from templates import get_template
from themes import get_theme


class TemplateTests(unittest.TestCase):
    def test_required_templates_and_themes_exist(self):
        self.assertEqual(get_template("country").label, "Страна")
        self.assertEqual(get_template("battle").get_field("side_2").column, 2)
        self.assertTrue(get_template("person").get_field("description").multiline)
        self.assertEqual(get_theme("aurelia").accent, "#00ff66")
        self.assertEqual(get_theme("nope").key, "light")

    def test_fast_parser_is_not_strict_about_separators(self):
        p = parse_text(
            """Тип: страна
Название — Республика Гринвальд
Столица Норд
население 18 миллионов
Магическая мощность: 820 ед."""
        )
        self.assertEqual(p.type, "country")
        self.assertEqual(p.data["capital"], "Норд")
        self.assertEqual(p.data["population"], "18 миллионов")
        self.assertEqual(p.data["custom_fields"][0]["name"], "Магическая мощность")

    def test_custom_section(self):
        sec = parse_section("МАГИЯ\nОсновная школа — Некромантия\nКоличество магов: 38 000")
        self.assertEqual(sec["title"], "МАГИЯ")
        self.assertEqual(len(sec["fields"]), 2)

    def test_html_escapes_user_text(self):
        p = Page(
            owner_id=1,
            type="country",
            title="<script>alert(1)</script>",
            data={"title": "<script>alert(1)</script>", "capital": "A&B"},
        )
        s = make_html(p)
        self.assertNotIn("<script>alert(1)</script>", s)
        self.assertIn("&lt;script&gt;", s)
        self.assertIn("A&amp;B", s)


class DbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(Path(self.tmp.name) / "test.db")
        await self.db.init()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_page_roundtrip_and_owner_check(self):
        data = {
            "title": "Турбания",
            "custom_fields": [{"name": "Военный резерв", "value": "420 000"}],
        }
        p = await self.db.save_page(Page(owner_id=101, type="country", title="Турбания", data=data))

        own = await self.db.get_page(p.id, 101)
        other = await self.db.get_page(p.id, 202)

        self.assertEqual(own.data, data)
        self.assertIsNone(other)

    async def test_update_copy_and_delete(self):
        p = await self.db.save_page(
            Page(owner_id=7, type="person", title="Иван", data={"title": "Иван"})
        )
        p.data["position"] = "Глава города"
        self.assertTrue(await self.db.update_page(p))

        copy = await self.db.copy_page(p.id, 7)
        self.assertEqual(copy.title, "Иван — копия")
        self.assertTrue(await self.db.delete_page(p.id, 7))
        self.assertFalse(await self.db.delete_page(copy.id, 8))

    async def test_settings_roundtrip(self):
        s = await self.db.get_settings(77)
        s.theme = "aurelia"
        s.quality = "ultra"
        await self.db.save_settings(s)
        saved = await self.db.get_settings(77)
        self.assertEqual((saved.theme, saved.quality), ("aurelia", "ultra"))

    async def test_only_owner_can_drop_unattached_media(self):
        await self.db.add_media(12, "media_12_random.webp", 100, 100)
        self.assertFalse(await self.db.drop_unattached_media("media_12_random.webp", 13))
        self.assertTrue(await self.db.drop_unattached_media("media_12_random.webp", 12))


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_is_checked_and_gets_random_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = BytesIO()
            Image.new("RGB", (320, 180), "red").save(buf, "PNG")
            info = await save_image(buf.getvalue(), 55, tmp)
            self.assertTrue(info.path.name.startswith("media_55_"))
            self.assertEqual(info.path.suffix, ".webp")
            self.assertEqual((info.width, info.height), (320, 180))

    async def test_garbage_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(BadImage):
            await save_image(b"definitely not an image", 1, tmp)

    async def test_renderer_accepts_only_internal_image_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "media_test.webp"
            Image.new("RGB", (32, 32), "blue").save(path, "WEBP")
            p = Page(
                owner_id=1,
                type="person",
                title="Тест",
                data={"title": "Тест", "image": path.name},
            )
            self.assertIn("data:image/webp;base64,", make_html(p, work_dir=tmp))
            p.data["image"] = "/etc/passwd"
            self.assertNotIn("data:image/webp;base64,", make_html(p, work_dir=tmp))


class RendererSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_png_render(self):
        if importlib.util.find_spec("playwright") is None:
            self.skipTest("playwright не установлен")

        with tempfile.TemporaryDirectory() as tmp:
            p = Page(
                owner_id=1,
                type="battle",
                title="Битва у Одессы",
                theme="dark",
                data={
                    "title": "Битва у Одессы",
                    "date": "24 февраля 1781",
                    "side_1": "Повстанцы",
                    "side_2": "Лоялисты",
                    "losses_1": "4 000 погибших",
                    "losses_2": "10 700 погибших",
                },
            )
            try:
                path = await render_page(p, tmp)
            except Exception as e:
                if "executable doesn't exist" in str(e).lower():
                    self.skipTest("Chromium еще не установлен")
                raise
            self.assertGreater(path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
