from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from models import Page, UserSettings


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Db:
    def __init__(self, path: str | Path):
        self.path = str(Path(path).resolve())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    async def init(self) -> None:
        await asyncio.to_thread(self._init)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    theme TEXT NOT NULL DEFAULT 'light',
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    preview_path TEXT,
                    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_pages_owner_updated
                ON pages(owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS uploaded_media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    page_id INTEGER,
                    path TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL DEFAULT 'main',
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    theme TEXT NOT NULL DEFAULT 'light',
                    language TEXT NOT NULL DEFAULT 'ru',
                    quality TEXT NOT NULL DEFAULT 'high',
                    export_format TEXT NOT NULL DEFAULT 'png',
                    watermark INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(user_settings)")}
            if "watermark" not in cols:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN watermark INTEGER NOT NULL DEFAULT 1"
                )

    async def touch_user(self, user_id: int, first_name: str = "", username: str = "") -> None:
        await asyncio.to_thread(self._touch_user, user_id, first_name, username)

    def _touch_user(self, user_id: int, first_name: str, username: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(id, first_name, username, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    first_name = excluded.first_name,
                    username = excluded.username
                """,
                (user_id, first_name, username, now()),
            )

    async def save_page(self, page: Page) -> Page:
        return await asyncio.to_thread(self._save_page, page)

    def _save_page(self, page: Page) -> Page:
        ts = now()
        d = json.dumps(page.data, ensure_ascii=False, separators=(",", ":"))

        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(id, first_name, username, created_at) VALUES (?, '', '', ?)",
                (page.owner_id, ts),
            )
            cur = conn.execute(
                """
                INSERT INTO pages(owner_id, type, title, theme, data, created_at, updated_at, preview_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (page.owner_id, page.type, page.title, page.theme, d, ts, ts, page.preview_path),
            )
            page.id = int(cur.lastrowid)
            page.created_at = ts
            page.updated_at = ts
        return page

    async def get_page(self, page_id: int, owner_id: int) -> Page | None:
        return await asyncio.to_thread(self._get_page, page_id, owner_id)

    def _get_page(self, page_id: int, owner_id: int) -> Page | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pages WHERE id = ? AND owner_id = ?",
                (page_id, owner_id),
            ).fetchone()
        return Page.from_row(row) if row else None

    async def get_user_pages(self, owner_id: int, limit: int = 30, offset: int = 0) -> list[Page]:
        return await asyncio.to_thread(self._get_user_pages, owner_id, limit, offset)

    def _get_user_pages(self, owner_id: int, limit: int, offset: int) -> list[Page]:
        n = min(max(limit, 1), 100)
        x = max(offset, 0)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pages WHERE owner_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (owner_id, n, x),
            ).fetchall()
        return [Page.from_row(row) for row in rows]

    async def clear_previews(self, owner_id: int) -> list[str]:
        return await asyncio.to_thread(self._clear_previews, owner_id)

    def _clear_previews(self, owner_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT preview_path FROM pages WHERE owner_id = ? AND preview_path IS NOT NULL",
                (owner_id,),
            ).fetchall()
            conn.execute(
                "UPDATE pages SET preview_path = NULL WHERE owner_id = ?",
                (owner_id,),
            )
        return [row["preview_path"] for row in rows]

    async def update_page(self, page: Page) -> bool:
        if page.id is None:
            return False
        return await asyncio.to_thread(self._update_page, page)

    def _update_page(self, page: Page) -> bool:
        ts = now()
        d = json.dumps(page.data, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE pages
                SET type = ?, title = ?, theme = ?, data = ?, updated_at = ?, preview_path = ?
                WHERE id = ? AND owner_id = ?
                """,
                (page.type, page.title, page.theme, d, ts, page.preview_path, page.id, page.owner_id),
            )
        if cur.rowcount:
            page.updated_at = ts
            return True
        return False

    async def delete_page(self, page_id: int, owner_id: int) -> bool:
        return await asyncio.to_thread(self._delete_page, page_id, owner_id)

    def _delete_page(self, page_id: int, owner_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM pages WHERE id = ? AND owner_id = ?",
                (page_id, owner_id),
            )
        return bool(cur.rowcount)

    async def copy_page(self, page_id: int, owner_id: int) -> Page | None:
        p = await self.get_page(page_id, owner_id)
        if not p:
            return None
        p.id = None
        p.title = f"{p.title} — копия"
        p.data = json.loads(json.dumps(p.data, ensure_ascii=False))
        p.data["title"] = p.title
        p.preview_path = None
        return await self.save_page(p)

    async def add_media(
        self,
        owner_id: int,
        path: str,
        width: int,
        height: int,
        page_id: int | None = None,
        kind: str = "main",
    ) -> int:
        return await asyncio.to_thread(
            self._add_media, owner_id, path, width, height, page_id, kind
        )

    def _add_media(
        self,
        owner_id: int,
        path: str,
        width: int,
        height: int,
        page_id: int | None,
        kind: str,
    ) -> int:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(id, first_name, username, created_at) VALUES (?, '', '', ?)",
                (owner_id, now()),
            )
            cur = conn.execute(
                """
                INSERT INTO uploaded_media(owner_id, page_id, path, kind, width, height, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_id, page_id, path, kind, width, height, now()),
            )
        return int(cur.lastrowid)

    async def attach_media(self, path: str, page_id: int, owner_id: int) -> bool:
        return await asyncio.to_thread(self._attach_media, path, page_id, owner_id)

    def _attach_media(self, path: str, page_id: int, owner_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE uploaded_media SET page_id = ?
                WHERE path = ? AND owner_id = ?
                """,
                (page_id, path, owner_id),
            )
        return bool(cur.rowcount)

    async def drop_unattached_media(self, path: str, owner_id: int) -> bool:
        return await asyncio.to_thread(self._drop_unattached_media, path, owner_id)

    def _drop_unattached_media(self, path: str, owner_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM uploaded_media
                WHERE path = ? AND owner_id = ? AND page_id IS NULL
                """,
                (path, owner_id),
            )
        return bool(cur.rowcount)

    async def get_settings(self, user_id: int) -> UserSettings:
        return await asyncio.to_thread(self._get_settings, user_id)

    def _get_settings(self, user_id: int) -> UserSettings:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            return UserSettings(user_id=user_id)
        return UserSettings(
            user_id=row["user_id"],
            theme=row["theme"],
            language=row["language"],
            quality=row["quality"],
            export_format=row["export_format"],
            watermark=bool(row["watermark"]),
        )

    async def save_settings(self, s: UserSettings) -> None:
        await asyncio.to_thread(self._save_settings, s)

    def _save_settings(self, s: UserSettings) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(id, first_name, username, created_at) VALUES (?, '', '', ?)",
                (s.user_id, now()),
            )
            conn.execute(
                """
                INSERT INTO user_settings(user_id, theme, language, quality, export_format, watermark)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    theme = excluded.theme,
                    language = excluded.language,
                    quality = excluded.quality,
                    export_format = excluded.export_format,
                    watermark = excluded.watermark
                """,
                (s.user_id, s.theme, s.language, s.quality, s.export_format, int(s.watermark)),
            )
