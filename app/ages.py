"""Возрастные группы. Подростки (12–17) и взрослые (18+) живут в разных лентах и не видят друг друга.

Проверка возраста:
  * при регистрации обязательна дата рождения, возраст считается от неё каждый день,
    поэтому в 18 лет человек сам переходит во взрослую группу;
  * дату нельзя поменять самому, только через поддержку (админ правит её в панели);
  * младше 12 лет зарегистрироваться нельзя;
  * взрослые не могут попасть в ленту подростков, подростки во взрослую, чаты между группами закрыты.
Для юридически значимой проверки нужен документ (например, через Госуслуги или сервис KYC);
здесь стоит понятный крючок: поле age_verified, которое админ отмечает вручную.
"""
from __future__ import annotations

from datetime import date

MIN_AGE = 12
ADULT_AGE = 18
TEEN_GOALS = ["Дружба", "Компания для хобби", "Просто общение", "Партнёр для спорта", "Единомышленники для проектов", "Языковой обмен"]


def years_between(birth: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def birth_for_age(age: int, today: date | None = None) -> date:
    """Дата рождения для человека, которому сейчас age лет (для демо и тестов)."""
    today = today or date.today()
    try:
        return today.replace(year=today.year - age, day=min(today.day, 28))
    except ValueError:
        return date(today.year - age, today.month, 1)


def group_for(years: int | None) -> str | None:
    if years is None or years < MIN_AGE:
        return None
    return "adult" if years >= ADULT_AGE else "teen"
