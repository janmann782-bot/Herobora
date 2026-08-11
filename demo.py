from __future__ import annotations

import asyncio
from pathlib import Path

from models import Page
from renderer import render_page


async def main() -> None:
    root = Path(__file__).resolve().parent
    p = Page(
        owner_id=1,
        type="country",
        title="Республика Гринвальд",
        theme="aurelia",
        data={
            "title": "Республика Гринвальд",
            "official_name": "Северная Республика Гринвальд",
            "capital": "Норд",
            "largest_city": "Вейрхольм",
            "population": "18 500 000 человек",
            "area": "420 000 км²",
            "government": "Парламентская республика",
            "head_of_state": "Президент Алекс Вейр",
            "official_language": "Гринвальдский",
            "founded": "14 марта 1948 года",
            "custom_fields": [
                {"name": "Количество лун", "value": "3"},
                {"name": "Уровень технологий", "value": "7"},
            ],
            "sections": [
                {
                    "title": "Военные данные",
                    "fields": [
                        {"name": "Армия", "value": "250 000"},
                        {"name": "Резерв", "value": "600 000"},
                        {"name": "Самолеты", "value": "380"},
                    ],
                }
            ],
            "description": (
                "Северное государство на побережье Холодного моря. "
                "Карточка собрана из стандартных и пользовательских полей."
            ),
        },
    )
    path = await render_page(p, root, output=root / "demo_aurelia.png")
    print(path)


if __name__ == "__main__":
    asyncio.run(main())

