from __future__ import annotations

from typing import Iterable

from media import image_caption, page_images, set_image_caption, set_page_images

MAX_SIDE_MEMBERS = 10


def normalize_sides(data: dict) -> list[dict]:
    raw = data.get("battle_sides")
    if isinstance(raw, list) and len(raw) >= 2:
        out = []
        for i in range(2):
            src = raw[i] if isinstance(raw[i], dict) else {}
            members = []
            for m in src.get("members") or []:
                if not isinstance(m, dict):
                    continue
                name = str(m.get("name") or "").strip()
                flag = str(m.get("flag") or "").strip() or None
                if name:
                    members.append({"name": name[:160], "flag": flag})
            out.append({"name": str(src.get("name") or f"Сторона {i + 1}")[:160], "members": members[:MAX_SIDE_MEMBERS]})
        return out

    out = []
    for i in range(2):
        key = f"side_{i + 1}"
        text = str(data.get(key) or "").strip()
        names = [x.strip() for x in text.splitlines() if x.strip()]
        out.append({
            "name": names[0] if names else f"Сторона {i + 1}",
            "members": [{"name": x, "flag": None} for x in names[1:MAX_SIDE_MEMBERS + 1]],
        })
    return out


def save_sides(data: dict, sides: list[dict]) -> None:
    clean = []
    for i in range(2):
        side = sides[i] if i < len(sides) else {"name": f"Сторона {i + 1}", "members": []}
        members = []
        for m in side.get("members") or []:
            name = str(m.get("name") or "").strip()
            if not name:
                continue
            members.append({"name": name[:160], "flag": str(m.get("flag") or "").strip() or None})
        clean.append({
            "name": str(side.get("name") or f"Сторона {i + 1}").strip()[:160] or f"Сторона {i + 1}",
            "members": members[:MAX_SIDE_MEMBERS],
        })

    data["battle_sides"] = clean
    for i, side in enumerate(clean, 1):
        names = [side["name"]] + [m["name"] for m in side["members"]]
        data[f"side_{i}"] = "\n".join(names)

    sync_flag_images(data)


def sync_flag_images(data: dict) -> None:
    sides = normalize_sides(data)
    old_images = page_images(data)
    keep = []
    for path in old_images:
        cap = image_caption(data, path, old_images.index(path))
        low = cap.casefold().strip()
        if low.startswith("s1:") or low.startswith("s2:"):
            continue
        keep.append(path)

    captions: dict[str, str] = {}
    for i, path in enumerate(old_images):
        cap = image_caption(data, path, i)
        if cap and not cap.casefold().strip().startswith(("s1:", "s2:")):
            captions[path] = cap

    for si, side in enumerate(sides, 1):
        for m in side["members"]:
            flag = m.get("flag")
            if not flag:
                continue
            keep.append(flag)
            captions[flag] = f"s{si}:{m['name']}"

    set_page_images(data, keep)
    if captions:
        data["image_captions"] = captions
    else:
        data.pop("image_captions", None)


def side_label(sides: list[dict], i: int) -> str:
    return str(sides[i].get("name") or f"Сторона {i + 1}")


def members_text(side: dict) -> str:
    return "\n".join(m["name"] for m in side.get("members") or [])


def member_count(side: dict) -> int:
    return len(side.get("members") or [])


def member(sides: list[dict], side_i: int, member_i: int) -> dict | None:
    if not 0 <= side_i < 2:
        return None
    members = sides[side_i].get("members") or []
    if not 0 <= member_i < len(members):
        return None
    return members[member_i]
