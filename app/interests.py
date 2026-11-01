"""Опрос при регистрации и подбор пары по интересам."""
from __future__ import annotations

GENDERS = {"male": "Мужчина", "female": "Женщина"}
LOOKING_FOR = {"male": "Мужчин", "female": "Женщин", "any": "Всех"}

# Вопросы опроса. key="goals" хранится отдельно, остальные ответы — общий список интересов.
SURVEY: list[dict] = [
    {
        "key": "goals",
        "title": "Что вы ищете",
        "hint": "Можно несколько вариантов",
        "options": ["Серьёзные отношения", "Свидания", "Дружба", "Компания для хобби", "Просто общение"],
    },
    {
        "key": "hobby",
        "title": "Чем любите заниматься",
        "hint": "Выберите то, на что правда тратите время",
        "options": [
            "Спортзал", "Бег", "Йога", "Велосипед", "Танцы", "Плавание", "Сноуборд и лыжи",
            "Фотография", "Рисование", "Играю на инструменте", "Готовка", "Настольные игры",
            "Видеоигры", "Чтение", "Программирование", "Рукоделие", "Растения",
        ],
    },
    {
        "key": "music",
        "title": "Какая музыка звучит у вас в наушниках",
        "hint": "",
        "options": [
            "Поп", "Рок", "Хип-хоп", "Электроника", "Техно", "Инди", "Джаз",
            "Классика", "Метал", "R&B", "K-pop", "Русский рок",
        ],
    },
    {
        "key": "screen",
        "title": "Кино и сериалы",
        "hint": "",
        "options": [
            "Комедии", "Драмы", "Триллеры", "Ужасы", "Фантастика", "Аниме",
            "Документальное", "Артхаус", "Мультфильмы", "Сериалы запоем",
        ],
    },
    {
        "key": "weekend",
        "title": "Идеальные выходные",
        "hint": "",
        "options": [
            "Кофейни", "Рестораны", "Вечеринки", "Концерты", "Театр", "Выставки и музеи",
            "Природа и походы", "Путешествия", "Дома с фильмом", "Загородом", "Пляж", "Стендап",
        ],
    },
    {
        "key": "values",
        "title": "Что для вас важно",
        "hint": "",
        "options": [
            "Семья", "Карьера", "Саморазвитие", "Здоровье", "Животные", "Экология",
            "Юмор", "Творчество", "Свобода", "Вера",
        ],
    },
]

GOALS = set(SURVEY[0]["options"])
INTERESTS = {opt for q in SURVEY[1:] for opt in q["options"]}
MIN_INTERESTS = 3


def clean(values: list[str], allowed: set[str]) -> list[str]:
    """Оставляет только варианты из каталога, без повторов, в исходном порядке."""
    seen: list[str] = []
    for v in values:
        if v in allowed and v not in seen:
            seen.append(v)
    return seen


def match_score(my_interests: list[str], my_goals: list[str], interests: list[str], goals: list[str]) -> tuple[int, list[str]]:
    """Процент совпадения 0..100 и список общих интересов.

    Интересы дают 80% оценки: доля общих от меньшего из двух списков
    (иначе человек с 40 галочками проигрывал бы тому, у кого их 5).
    Цели знакомства дают 20%.
    """
    common = [i for i in interests if i in set(my_interests)]
    base = min(len(my_interests), len(interests)) or 1
    interest_part = len(common) / base
    goal_common = set(my_goals) & set(goals)
    goal_part = len(goal_common) / (min(len(my_goals), len(goals)) or 1) if my_goals and goals else 0
    return round(100 * (0.8 * interest_part + 0.2 * goal_part)), common


def compatible(my_gender: str | None, my_looking: str | None, gender: str | None, looking: str | None) -> bool:
    """Оба должны подходить под то, кого ищет другой."""
    def ok(looking_for, g):
        return looking_for in (None, "any") or looking_for == g

    return ok(my_looking, gender) and ok(looking, my_gender)
