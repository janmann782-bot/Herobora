from __future__ import annotations

import re
from dataclasses import dataclass, field

from templates import TEMPLATES, get_template

TYPE_ALIASES = {
    "страна": "country",
    "государство": "country",
    "country": "country",
    "регион": "region",
    "область": "region",
    "провинция": "region",
    "штат": "region",
    "земля": "region",
    "округ": "region",
    "region": "region",
    "битва": "battle",
    "сражение": "battle",
    "battle": "battle",
    "персонаж": "person",
    "политик": "person",
    "человек": "person",
    "person": "person",
    "миротворец": "mirotorets",
    "миротворець": "mirotorets",
    "mirotorets": "mirotorets",
    "myrotvorets": "mirotorets",
}


ALIASES = {
    "название": "title",
    "надпись типа в карточке": "card_type_label",
    "тип в карточке": "card_type_label",
    "название типа в карточке": "card_type_label",
    "шапка типа": "card_type_label",
    "имя": "title",
    "официальное название": "official_name",
    "альтернативное название": "alt_name",
    "столица": "capital",
    "крупнейший город": "largest_city",
    "тип региона": "region_type",
    "страна": "country",
    "входит в": "parent_region",
    "административный центр": "administrative_center",
    "адм центр": "administrative_center",
    "адм. центр": "administrative_center",
    "административное деление": "administrative_divisions",
    "глава региона": "head_of_region",
    "губернатор": "head_of_region",
    "законодательный орган": "legislature",
    "парламент региона": "legislature",
    "исполнительный орган": "executive_body",
    "код региона": "region_code",
    "код / аббревиатура": "region_code",
    "официальный сайт": "website",
    "сайт": "website",
    "население": "population",
    "площадь": "area",
    "плотность": "density",
    "плотность населения": "density",
    "форма правления": "government",
    "правительство": "government",
    "глава государства": "head_of_state",
    "президент": "head_of_state",
    "глава правительства": "head_of_government",
    "премьер-министр": "head_of_government",
    "премьер министр": "head_of_government",
    "язык": "official_language",
    "официальный язык": "official_language",
    "другие языки": "other_languages",
    "основана": "founded",
    "основано": "founded",
    "дата основания": "founded",
    "дата образования": "founded",
    "образован": "founded",
    "образована": "founded",
    "независимость": "independence",
    "валюта": "currency",
    "часовой пояс": "timezone",
    "телефонный код": "phone_code",
    "домен": "internet_domain",
    "интернет-домен": "internet_domain",
    "девиз": "motto",
    "гимн": "anthem",
    "парламент": "parliament",
    "правящая партия": "ruling_party",
    "идеология": "ideology",
    "описание": "description",
    "краткое описание": "description",
    "часть войны": "part_of",
    "часть конфликта": "part_of",
    "дата": "date",
    "место": "place",
    "результат": "result",
    "сторона 1": "side_1",
    "сторона 2": "side_2",
    "командующий 1": "commander_1",
    "командующие 1": "commander_1",
    "командующий 2": "commander_2",
    "командующие 2": "commander_2",
    "силы 1": "strength_1",
    "силы 2": "strength_2",
    "потери 1": "losses_1",
    "потери 2": "losses_2",
    "подпись": "image_caption",
    "подпись изображения": "image_caption",
    "полное имя": "full_name",
    "дата рождения": "birth_date",
    "место рождения": "birth_place",
    "дата смерти": "death_date",
    "место смерти": "death_place",
    "гражданство": "citizenship",
    "национальность": "ethnicity",
    "этническая принадлежность": "ethnicity",
    "должность": "position",
    "начало полномочий": "term_start",
    "конец полномочий": "term_end",
    "предшественник": "predecessor",
    "преемник": "successor",
    "партия": "party",
    "профессия": "profession",
    "образование": "education",
    "семья": "family",
    "биография": "description",
}


@dataclass(slots=True)
class ParsedPage:
    type: str
    data: dict
    unknown: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def recognized(self) -> int:
        return len([k for k in self.data if k != "custom_fields"]) + len(
            self.data.get("custom_fields", [])
        )


def clean_key(s: str) -> str:
    s = s.casefold().replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .:-—–")


def split_line(line: str) -> tuple[str, str] | None:
    m = re.match(r"^\s*([^:—–=]{2,60}?)\s*(?::|—|–|=)\s*(.+?)\s*$", line)
    if m:
        return m.group(1), m.group(2)

    low = clean_key(line)
    for alias in sorted(ALIASES, key=len, reverse=True):
        if low.startswith(alias + " "):
            n = len(alias)
            return line[:n], line[n:].strip(" :-—–")
    return None


def infer_type(keys: set[str]) -> str:
    region_unique = {
        "region_type", "country", "parent_region", "administrative_center",
        "administrative_divisions", "head_of_region", "legislature", "executive_body",
        "region_code", "website",
    }
    scores = {
        "country": 2 * len(keys & {"capital", "government", "currency", "head_of_state", "head_of_government"})
        + len(keys & {"population", "area"}),
        "region": 2 * len(keys & region_unique) + len(keys & {"population", "area", "density"}),
        "battle": 2 * len(keys & {"part_of", "result", "side_1", "side_2", "losses_1"}),
        "person": 2 * len(keys & {"birth_date", "position", "party", "profession", "full_name"}),
    }
    return max(scores, key=scores.get) if max(scores.values()) else "country"


def parse_text(text: str) -> ParsedPage:
    pairs: list[tuple[str, str, str]] = []
    unknown: list[str] = []
    page_type = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        pair = split_line(line)
        if not pair:
            if re.fullmatch(r"[\d\s.,]+\s*(?:млн|миллион(?:а|ов)?|жител(?:ей|я))", line, re.IGNORECASE):
                pairs.append(("population", "Население", line))
            else:
                unknown.append(line)
            continue

        k, v = pair
        key = clean_key(k)
        if key == "тип":
            page_type = TYPE_ALIASES.get(clean_key(v), "")
            if not page_type:
                unknown.append(line)
            continue

        field_key = ALIASES.get(key)
        if field_key:
            pairs.append((field_key, k.strip(), v.strip()))
        else:
            pairs.append(("custom", k.strip(), v.strip()))

    if not page_type:
        page_type = infer_type({k for k, _, _ in pairs})

    tpl = get_template(page_type)
    allowed = {f.key for f in tpl.fields}
    data: dict = {"custom_fields": []}
    warnings: list[str] = []

    for key, label, value in pairs:
        if not value:
            continue
        limit = 3800 if key == "description" else 1000
        if key == "title":
            limit = 250
        if len(value) > limit:
            value = value[:limit]
            warnings.append(f"Поле {label}: значение сокращено до {limit} символов")
        if key in allowed:
            if key in data:
                warnings.append(f"Поле {label} встретилось несколько раз, взято последнее значение")
            data[key] = value
        elif len(data["custom_fields"]) < 20:
            data["custom_fields"].append({"name": label[:100], "value": value})
        else:
            warnings.append("Лишние пользовательские поля после двадцатого не добавлены")

    if not data["custom_fields"]:
        data.pop("custom_fields")

    if "title" not in data:
        warnings.append("Название не найдено, его нужно будет ввести вручную")

    return ParsedPage(page_type, data, unknown, warnings)


def parse_section(text: str) -> dict | None:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 2:
        return None

    title = lines[0].strip("# :—–")
    fields = []
    for line in lines[1:]:
        pair = split_line(line)
        if pair:
            k, v = pair
            fields.append({"name": k.strip(), "value": v.strip()})

    if not title or not fields:
        return None
    return {"title": title[:120], "fields": fields[:30]}


def known_types() -> tuple[str, ...]:
    return tuple(TEMPLATES)
