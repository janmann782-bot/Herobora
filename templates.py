from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    section: str
    column: int = 0
    multiline: bool = False


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    label: str
    emoji: str
    fields: tuple[Field, ...]
    wizard: tuple[str, ...]
    image_label: str
    subtitle_key: str | None = None

    def get_field(self, key: str) -> Field | None:
        return next((f for f in self.fields if f.key == key), None)


def f(key: str, label: str, section: str, column: int = 0, multiline: bool = False) -> Field:
    return Field(key, label, section, column, multiline)


COUNTRY = Template(
    key="country",
    label="Страна",
    emoji="🌍",
    image_label="Флаг, герб или главное изображение",
    subtitle_key="official_name",
    wizard=("title", "official_name", "capital", "population", "government", "description"),
    fields=(
        f("card_type_label", "Надпись типа в карточке", "Основные сведения"),
        f("title", "Название", "Основные сведения"),
        f("alt_name", "Альтернативное название", "Основные сведения"),
        f("official_name", "Официальное название", "Основные сведения"),
        f("motto", "Девиз", "Основные сведения"),
        f("anthem", "Гимн", "Основные сведения"),
        f("anthem_duration", "Длительность гимна", "Основные сведения"),
        f("capital", "Столица", "География"),
        f("largest_city", "Крупнейший город", "География"),
        f("area", "Площадь", "География"),
        f("water_percent", "Воды", "География"),
        f("timezone", "Часовой пояс", "География"),
        f("highest_point", "Высшая точка", "География"),
        f("lowest_point", "Низшая точка", "География"),
        f("climate", "Климат", "География"),
        f("borders", "Граничит с", "География"),
        f("official_language", "Официальный язык", "Население"),
        f("other_languages", "Другие языки", "Население"),
        f("population", "Население", "Население"),
        f("density", "Плотность населения", "Население"),
        f("population_year", "Год переписи", "Население"),
        f("ethnic_groups", "Этнический состав", "Население", multiline=True),
        f("religion", "Религия", "Население"),
        f("literacy", "Грамотность", "Население"),
        f("life_expectancy", "Ожидаемая продолжительность жизни", "Население"),
        f("government", "Форма правления", "Государственное устройство"),
        f("head_of_state", "Глава государства", "Государственное устройство"),
        f("head_of_government", "Глава правительства", "Государственное устройство"),
        f("parliament", "Парламент", "Государственное устройство"),
        f("ruling_party", "Правящая партия", "Государственное устройство"),
        f("ideology", "Идеология", "Государственное устройство"),
        f("legislature_seats", "Мест в парламенте", "Государственное устройство"),
        f("constitution", "Конституция", "Государственное устройство"),
        f("founded", "Дата основания", "История"),
        f("independence", "Дата независимости", "История"),
        f("gdp_nominal", "ВВП (номинал)", "Экономика"),
        f("gdp_ppp", "ВВП (ППС)", "Экономика"),
        f("gdp_per_capita", "ВВП на душу населения", "Экономика"),
        f("gdp_growth", "Рост ВВП", "Экономика"),
        f("inflation", "Инфляция", "Экономика"),
        f("unemployment", "Безработица", "Экономика"),
        f("currency", "Валюта", "Экономика"),
        f("hdi", "ИЧР", "Экономика"),
        f("gini", "Коэффициент Джини", "Экономика"),
        f("exports", "Экспорт", "Экономика"),
        f("imports", "Импорт", "Экономика"),
        f("phone_code", "Телефонный код", "Коды и обозначения"),
        f("internet_domain", "Интернет-домен", "Коды и обозначения"),
        f("iso_code", "Код ISO", "Коды и обозначения"),
        f("ioc_code", "Код МОК", "Коды и обозначения"),
        f("driving_side", "Сторона движения", "Прочее"),
        f("power_voltage", "Электричество", "Прочее"),
        f("military", "Вооружённые силы", "Прочее"),
        f("description", "Краткое описание", "Описание", multiline=True),
    ),
)



REGION = Template(
    key="region",
    label="Регион",
    emoji="🗺️",
    image_label="Флаг, герб или главное изображение региона",
    subtitle_key="official_name",
    wizard=("title", "region_type", "country", "administrative_center", "population", "description"),
    fields=(
        f("card_type_label", "Надпись типа в карточке", "Основные сведения"),
        f("title", "Название", "Основные сведения"),
        f("official_name", "Официальное название", "Основные сведения"),
        f("region_type", "Тип региона", "Основные сведения"),
        f("anthem", "Гимн", "Основные сведения"),
        f("anthem_duration", "Длительность гимна", "Основные сведения"),
        f("country", "Страна", "Принадлежность"),
        f("parent_region", "Входит в", "Принадлежность"),
        f("administrative_center", "Административный центр", "Административное устройство"),
        f("largest_city", "Крупнейший город", "Административное устройство"),
        f("administrative_divisions", "Административное деление", "Административное устройство", multiline=True),
        f("head_of_region", "Глава региона", "Органы власти"),
        f("legislature", "Законодательный орган", "Органы власти"),
        f("executive_body", "Исполнительный орган", "Органы власти"),
        f("area", "Площадь", "География"),
        f("timezone", "Часовой пояс", "География"),
        f("population", "Население", "Население"),
        f("density", "Плотность населения", "Население"),
        f("official_language", "Официальный язык", "Население"),
        f("other_languages", "Другие языки", "Население"),
        f("ethnic_groups", "Этнический состав", "Население", multiline=True),
        f("religion", "Религия", "Население"),
        f("gdp_nominal", "ВВП", "Экономика"),
        f("gdp_per_capita", "ВВП на душу населения", "Экономика"),
        f("founded", "Дата образования", "История"),
        f("region_code", "Код / аббревиатура", "Прочее"),
        f("website", "Официальный сайт", "Прочее"),
        f("description", "Краткое описание", "Описание", multiline=True),
    ),
)



BATTLE = Template(
    key="battle",
    label="Битва",
    emoji="💥",
    image_label="главное изображение битвы и мини-флаги сторон; для флагов используй подписи s1: или s2:",
    subtitle_key="part_of",
    wizard=("title", "part_of", "date", "place", "result", "description"),
    fields=(
        f("card_type_label", "Надпись типа в карточке", "Основные сведения"),
        f("title", "Название", "Основные сведения"),
        f("part_of", "Часть войны", "Основные сведения"),
        f("image_caption", "Подпись изображения", "Основные сведения"),
        f("date", "Дата", "Основные сведения"),
        f("place", "Место", "Основные сведения"),
        f("result", "Результат", "Основные сведения"),
        f("side_1", "Сторона 1", "Стороны конфликта", 1),
        f("side_2", "Сторона 2", "Стороны конфликта", 2),
        f("commander_1", "Командующие", "Командующие и лидеры", 1, True),
        f("commander_2", "Командующие", "Командующие и лидеры", 2, True),
        f("strength_1", "Силы", "Силы", 1, True),
        f("strength_2", "Силы", "Силы", 2, True),
        f("losses_1", "Потери", "Потери", 1, True),
        f("losses_2", "Потери", "Потери", 2, True),
        f("casualties_civilian", "Жертвы среди гражданских", "Потери", multiline=True),
        f("territorial_changes", "Территориальные изменения", "Итоги"),
        f("description", "Краткое описание", "Описание", multiline=True),
    ),
)


PERSON = Template(
    key="person",
    label="Персонаж",
    emoji="👤",
    image_label="Портрет",
    subtitle_key="full_name",
    wizard=("title", "full_name", "birth_date", "position", "party", "description"),
    fields=(
        f("card_type_label", "Надпись типа в карточке", "Основные сведения"),
        f("title", "Имя", "Основные сведения"),
        f("full_name", "Полное имя", "Основные сведения"),
        f("birth_date", "Дата рождения", "Биография"),
        f("birth_place", "Место рождения", "Биография"),
        f("death_date", "Дата смерти", "Биография"),
        f("death_place", "Место смерти", "Биография"),
        f("citizenship", "Гражданство", "Биография"),
        f("ethnicity", "Национальность / этническая принадлежность", "Биография"),
        f("position", "Должность", "Политическая деятельность"),
        f("term_start", "Начало полномочий", "Политическая деятельность"),
        f("term_end", "Конец полномочий", "Политическая деятельность"),
        f("predecessor", "Предшественник", "Политическая деятельность"),
        f("successor", "Преемник", "Политическая деятельность"),
        f("party", "Партия", "Политическая деятельность"),
        f("ideology", "Идеология", "Политическая деятельность"),
        f("profession", "Профессия", "Личная информация"),
        f("education", "Образование", "Личная информация"),
        f("family", "Семья", "Личная информация", multiline=True),
        f("religion", "Религия", "Личная информация"),
        f("awards", "Награды", "Личная информация", multiline=True),
        f("military_rank", "Воинское звание", "Личная информация"),
        f("website", "Сайт", "Личная информация"),
        f("description", "Краткая биография", "Описание", multiline=True),
    ),
)


NEWS = Template(
    key="news",
    label="Новости (БЕТА)",
    emoji="📰",
    image_label="одна картинка к новости",
    subtitle_key=None,
    wizard=("title", "body", "button_text"),
    fields=(
        f("title", "Заголовок", "Новость"),
        f("body", "Текст новости", "Новость", multiline=True),
        f("button_text", "Текст на кнопке", "Новость"),
    ),
)


SUPEREVENT = Template(
    key="superevent",
    label="Суперевент (БЕТА)",
    emoji="‼️",
    image_label="одна картинка к суперевенту",
    subtitle_key=None,
    wizard=("title", "body", "button_text"),
    fields=(
        f("title", "Заголовок", "Суперевент"),
        f("body", "Текст суперевента", "Суперевент", multiline=True),
        f("button_text", "Текст на кнопке", "Суперевент"),
    ),
)


MIROTORETS = Template(
    key="mirotorets",
    label="Миротворец",
    emoji="📋",
    image_label="одно фото (или N/D если без фото)",
    subtitle_key=None,
    wizard=("title", "birth_date", "country", "rank", "unit", "description"),
    fields=(
        f("title", "Имя / ФИО", "Основные сведения"),
        f("birth_date", "Дата рождения", "Основные сведения"),
        f("country", "Страна", "Основные сведения"),
        f("rank", "Звание", "Военные данные"),
        f("unit", "Подразделение", "Военные данные"),
        f("position", "Должность", "Военные данные"),
        f("personal_number", "Личный номер", "Военные данные"),
        f("passport", "Паспорт", "Военные данные"),
        f("birth_place", "Место рождения", "Военные данные"),
        f("description", "Описание / обвинение", "Текст карточки", multiline=True),
        f("source", "Источник", "Текст карточки"),
        f("hashtags", "Хэштеги", "Текст карточки"),
        f("footer", "Текст внизу (красный)", "Текст карточки", multiline=True),
    ),
)


TEMPLATES = {x.key: x for x in (COUNTRY, REGION, BATTLE, PERSON, NEWS, SUPEREVENT, MIROTORETS)}


def get_template(key: str) -> Template:
    try:
        return TEMPLATES[key]
    except KeyError as e:
        raise ValueError(f"Неизвестный шаблон: {key}") from e
