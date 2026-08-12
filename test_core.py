from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from battle_sides import normalize_sides, save_sides
from db import Db
from media import (
    BadImage,
    battle_image_groups,
    image_caption,
    page_images,
    save_image,
    set_image_caption,
    set_page_images,
)
from models import Page
from parser import parse_section, parse_text
from pillow_renderer import render_pillow
from renderer import make_html, render_page
from templates import get_template
from text_export import page_to_text, split_text
from themes import get_theme


class TemplateTests(unittest.TestCase):
    def test_required_templates_and_themes_exist(self):
        self.assertEqual(get_template("country").label, "Страна")
        self.assertEqual(get_template("region").label, "Регион")
        self.assertEqual(get_template("region").get_field("administrative_center").label, "Административный центр")
        self.assertEqual(get_template("battle").get_field("side_2").column, 2)
        self.assertTrue(get_template("person").get_field("description").multiline)
        aurelia = get_theme("aurelia")
        self.assertEqual(aurelia.accent, "#a9f38f")
        self.assertEqual(aurelia.background, "#000000")
        self.assertEqual(aurelia.text, aurelia.accent)
        self.assertEqual(aurelia.border_width, 3)
        self.assertFalse(aurelia.pixel_border)
        self.assertIn("Isaac Fill", aurelia.font)
        self.assertIsNone(aurelia.row_alt)
        self.assertIn("Wikipedia Sans", get_theme("light").font)
        self.assertIn("Wikipedia Serif", get_theme("light").heading_font)
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

    def test_region_parser(self):
        p = parse_text(
            """Тип: регион
Название: Верхняя Бавария
Страна: Германия
Входит в: Бавария
Административный центр: Мюнхен
Площадь: 17 529 км²
Население: 4 238 195"""
        )
        self.assertEqual(p.type, "region")
        self.assertEqual(p.data["country"], "Германия")
        self.assertEqual(p.data["administrative_center"], "Мюнхен")
        self.assertEqual(p.data["parent_region"], "Бавария")

    def test_region_can_be_inferred(self):
        p = parse_text(
            """Название: Северная область
Страна: Турбания
Административный центр: Лесоград
Глава региона: Марк Светов"""
        )
        self.assertEqual(p.type, "region")

    def test_text_export_contains_all_user_text(self):
        page = Page(
            owner_id=1,
            type="region",
            title="Лесополье",
            data={
                "title": "Лесополье",
                "country": "Турбания",
                "administrative_center": "Лесополь",
                "custom_fields": [{"name": "Код", "value": "LP"}],
                "sections": [{"title": "Экономика", "fields": [{"name": "Заводы", "value": "38"}]}],
                "images": ["media_fake.webp"],
                "image_captions": {"media_fake.webp": "Карта региона"},
            },
        )
        text = page_to_text(page)
        self.assertTrue(text.startswith("РЕГИОН\n"))
        self.assertIn("Название: Лесополье", text)
        self.assertIn("Страна: Турбания", text)
        self.assertIn("Код: LP", text)
        self.assertIn("Заводы: 38", text)
        self.assertIn("Изображение 1: Карта региона", text)
        self.assertNotIn("media_fake.webp", text)
        self.assertGreater(len(split_text("x" * 9000)), 1)

    def test_aurelia_html_has_alternating_row_background(self):
        p = Page(
            owner_id=1,
            type="region",
            title="Тест",
            theme="aurelia",
            data={"title": "Тест", "country": "Турбания", "area": "100 км²"},
        )
        html = make_html(p)
        self.assertIn('data-theme="aurelia"', html)
        self.assertIn("--row-alt:#000000", html)
        self.assertIn('row.row-alt', html)
        self.assertEqual(html.count('class="row row-alt"'), 1)

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
        self.assertNotIn("INFOBOX BOT", make_html(p, watermark=False))


class BattleSideTests(unittest.TestCase):
    def test_legacy_sides_are_upgraded(self):
        d = {"side_1": "Турбания\nКефирстан", "side_2": "Йогуртстан\nСеверная коалиция"}
        sides = normalize_sides(d)
        self.assertEqual(sides[0]["name"], "Турбания")
        self.assertEqual(sides[0]["members"][0]["name"], "Кефирстан")
        self.assertEqual(sides[1]["members"][0]["name"], "Северная коалиция")

    def test_side_flags_are_synced_to_battle_image_roles(self):
        d = {"title": "Тест", "images": ["media_main.webp"]}
        sides = normalize_sides(d)
        sides[0]["name"] = "Кефирстан"
        sides[0]["members"] = [{"name": "Северная армия", "flag": "media_flag1.webp"}]
        sides[1]["name"] = "Йогуртстан"
        sides[1]["members"] = [{"name": "Южная армия", "flag": "media_flag2.webp"}]
        save_sides(d, sides)
        self.assertEqual(d["side_1"], "Кефирстан\nСеверная армия")
        self.assertEqual(d["side_2"], "Йогуртстан\nЮжная армия")
        self.assertIn("media_flag1.webp", d["images"])
        self.assertIn("media_flag2.webp", d["images"])
        self.assertEqual(d["image_captions"]["media_flag1.webp"], "s1:Северная армия")
        self.assertEqual(d["image_captions"]["media_flag2.webp"], "s2:Южная армия")


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
        self.assertEqual(copy.title, "Иван - копия")
        self.assertTrue(await self.db.delete_page(p.id, 7))
        self.assertFalse(await self.db.delete_page(copy.id, 8))

    async def test_settings_roundtrip(self):
        s = await self.db.get_settings(77)
        s.theme = "aurelia"
        s.quality = "ultra"
        s.watermark = False
        await self.db.save_settings(s)
        saved = await self.db.get_settings(77)
        self.assertEqual((saved.theme, saved.quality), ("aurelia", "ultra"))
        self.assertFalse(saved.watermark)

    async def test_generation_stats_and_milestone(self):
        total, own, milestone = await self.db.count_generation(101)
        self.assertEqual((total, own, milestone), (1, 1, None))
        total, own, milestone = await self.db.count_generation(101)
        self.assertEqual((total, own, milestone), (2, 2, None))
        total, own = await self.db.get_generation_stats(101)
        self.assertEqual((total, own), (2, 2))

        with sqlite3.connect(self.db.path) as conn:
            conn.execute("UPDATE generation_totals SET total = 99 WHERE id = 1")
        total, own, milestone = await self.db.count_generation(202)
        self.assertEqual(total, 100)
        self.assertEqual(own, 1)
        self.assertEqual(milestone, 100)
        self.assertTrue(Db._is_generation_milestone(500))
        self.assertTrue(Db._is_generation_milestone(1000))
        self.assertFalse(Db._is_generation_milestone(2000))

    async def test_only_owner_can_drop_unattached_media(self):
        await self.db.add_media(12, "media_12_random.webp", 100, 100)
        self.assertFalse(await self.db.drop_unattached_media("media_12_random.webp", 13))
        self.assertTrue(await self.db.drop_unattached_media("media_12_random.webp", 12))

    async def test_watermark_change_can_clear_cached_previews(self):
        p = await self.db.save_page(
            Page(
                owner_id=88,
                type="country",
                title="Турбания",
                data={"title": "Турбания"},
                preview_path="preview_old.png",
            )
        )
        self.assertEqual(await self.db.clear_previews(88), ["preview_old.png"])
        saved = await self.db.get_page(p.id, 88)
        self.assertIsNone(saved.preview_path)

    async def test_shared_media_is_removed_only_after_last_page(self):
        path = "media_5_shared.webp"
        p1 = await self.db.save_page(
            Page(owner_id=5, type="country", title="Один", data={"title": "Один", "image": path})
        )
        p2 = await self.db.save_page(
            Page(owner_id=5, type="country", title="Два", data={"title": "Два", "image": path})
        )
        self.assertFalse(await self.db.drop_media_if_unused(path, 5))
        p1.data.pop("image")
        await self.db.update_page(p1)
        self.assertFalse(await self.db.drop_media_if_unused(path, 5))
        p2.data.pop("image")
        await self.db.update_page(p2)
        self.assertTrue(await self.db.drop_media_if_unused(path, 5))


class DbMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_settings_table_gets_watermark_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    CREATE TABLE user_settings (
                        user_id INTEGER PRIMARY KEY,
                        theme TEXT NOT NULL DEFAULT 'light',
                        language TEXT NOT NULL DEFAULT 'ru',
                        quality TEXT NOT NULL DEFAULT 'high',
                        export_format TEXT NOT NULL DEFAULT 'png'
                    )
                    """
                )
            db = Db(path)
            await db.init()
            s = await db.get_settings(1)
            self.assertTrue(s.watermark)


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_and_multiple_page_images(self):
        d = {"image": "media_old.webp", "images": ["media_two.webp"]}
        self.assertEqual(page_images(d), ["media_old.webp", "media_two.webp"])
        set_page_images(d, ["media_one.webp", "media_two.webp"])
        self.assertEqual(d["image"], "media_one.webp")
        self.assertEqual(d["images"], ["media_one.webp", "media_two.webp"])

    async def test_each_image_keeps_its_own_caption(self):
        d = {"images": ["media_one.webp", "media_two.webp"]}
        set_page_images(d, d["images"])
        set_image_caption(d, "media_one.webp", "Первое изображение")
        set_image_caption(d, "media_two.webp", "Второе изображение")
        self.assertEqual(image_caption(d, "media_one.webp", 0), "Первое изображение")
        self.assertEqual(image_caption(d, "media_two.webp", 1), "Второе изображение")

        set_page_images(d, ["media_two.webp"])
        self.assertEqual(image_caption(d, "media_two.webp", 0), "Второе изображение")
        self.assertNotIn("media_one.webp", d["image_captions"])


    def test_battle_image_groups_support_multiple_flags(self):
        d = {
            "images": ["m1.webp", "f1.webp", "f2.webp", "f3.webp", "x1.webp"],
            "image_captions": {
                "m1.webp": "main: Главное изображение",
                "f1.webp": "s1: Флаг 1",
                "f2.webp": "s1: Флаг 2",
                "f3.webp": "s2: Флаг 3",
                "x1.webp": "extra: Доп",
            },
        }
        main, side1, side2, extras = battle_image_groups(d)
        self.assertEqual(main, ("m1.webp", "Главное изображение"))
        self.assertEqual(side1, [("f1.webp", "Флаг 1"), ("f2.webp", "Флаг 2")])
        self.assertEqual(side2, [("f3.webp", "Флаг 3")])
        self.assertEqual(extras, [("x1.webp", "Доп")])

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

    async def test_html_renders_caption_for_each_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ["media_one.webp", "media_two.webp"]
            for name in names:
                Image.new("RGB", (32, 32), "blue").save(Path(tmp) / name, "WEBP")
            p = Page(
                owner_id=1,
                type="country",
                title="Тест",
                data={
                    "title": "Тест",
                    "images": names,
                    "image_captions": {
                        names[0]: "Подпись один",
                        names[1]: "Подпись два",
                    },
                },
            )
            s = make_html(p, work_dir=tmp)
            self.assertIn("Подпись один", s)
            self.assertIn("Подпись два", s)
            self.assertNotIn("sheet::before", s)



    def test_custom_card_type_label_and_hide(self):
        p = Page(owner_id=1, type="country", title="Тест", data={"title": "Тест", "card_type_label": "Кукуруза"})
        html = make_html(p)
        self.assertIn("КУКУРУЗА", html)

        p.data["card_type_label"] = "скрыть"
        html = make_html(p)
        self.assertNotIn('class="kind">', html)

class RendererSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_pillow_fallback_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "media_1_test.png"
            Image.new("RGB", (640, 360), "#315caa").save(media)
            media2 = Path(tmp) / "media_1_test_2.png"
            Image.new("RGB", (360, 640), "#a9f38f").save(media2)
            p = Page(
                owner_id=1,
                type="country",
                title="Турбания",
                theme="aurelia",
                data={
                    "title": "Турбания",
                    "capital": "Светлозорь",
                    "population": "18 500 000",
                    "images": [media.name, media2.name],
                    "image_captions": {
                        media.name: "Главное изображение",
                        media2.name: "Второе изображение",
                    },
                    "custom_fields": [{"name": "Военный резерв", "value": "420 000"}],
                },
            )
            path = Path(tmp) / "fallback.png"
            render_pillow(p, tmp, "standard", path)
            clean = Path(tmp) / "fallback_clean.png"
            render_pillow(p, tmp, "standard", clean, watermark=False)
            with Image.open(path) as img:
                self.assertGreaterEqual(img.width, 1000)
                self.assertGreater(img.height, 500)
                full_h = img.height
            with Image.open(clean) as img:
                self.assertLess(img.height, full_h)
            self.assertGreater(path.stat().st_size, 10_000)

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
