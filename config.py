from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw in path.read_text("utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    work_dir: Path
    db_path: Path
    log_level: str = "INFO"
    max_image_mb: int = 12
    log_chat_id: int = -1004368904200


def load_config(require_token: bool = True) -> Config:
    here = Path(__file__).resolve().parent
    _load_dotenv(here / ".env")

    work_raw = Path(os.getenv("INFOBOX_WORK_DIR", ".")).expanduser()
    work_dir = (here / work_raw).resolve() if not work_raw.is_absolute() else work_raw.resolve()

    db_raw = Path(os.getenv("INFOBOX_DB_PATH", "infobox.db")).expanduser()
    db_path = (work_dir / db_raw).resolve() if not db_raw.is_absolute() else db_raw.resolve()
    token = os.getenv("BOT_TOKEN", "").strip()

    if require_token and not token:
        raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и вставь токен.")

    return Config(
        bot_token=token,
        work_dir=work_dir,
        db_path=db_path,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        max_image_mb=max(1, int(os.getenv("MAX_IMAGE_MB", "12"))),
        log_chat_id=int(os.getenv("INFOBOX_LOG_CHAT_ID", "-1004368904200")),
    )
