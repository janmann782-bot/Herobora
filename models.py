from __future__ import annotations

import json
from dataclasses import dataclass, field
from sqlite3 import Row


@dataclass(slots=True)
class Page:
    owner_id: int
    type: str
    title: str
    theme: str = "light"
    data: dict = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    preview_path: str | None = None

    @classmethod
    def from_row(cls, row: Row) -> Page:
        d = json.loads(row["data"])
        return cls(
            id=row["id"],
            owner_id=row["owner_id"],
            type=row["type"],
            title=row["title"],
            theme=row["theme"],
            data=d,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            preview_path=row["preview_path"],
        )


@dataclass(slots=True)
class UserSettings:
    user_id: int
    theme: str = "light"
    language: str = "ru"
    quality: str = "high"
    export_format: str = "png"
    watermark: bool = True
