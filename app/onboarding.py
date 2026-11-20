"""На каком шаге регистрации человек — тот же порядок, что в приложении (static/js/app.js → onboardingStep)."""
from __future__ import annotations

from .legal import TERMS_VERSION
from .models import User

# (код, название для админки) — по порядку прохождения
STEPS = [
    ("email", "Подтверждение почты"),
    ("about", "Имя, дата рождения, согласия"),
    ("identity", "Пол и кого ищет"),
    ("extras", "Рост, вес, знак"),
    ("survey", "Интересы"),
    ("photo", "Фото"),
    ("scan", "Проверка лица"),
    ("location", "Геопозиция"),
    ("done", "Регистрация завершена"),
]
LABELS = dict(STEPS)
ORDER = {code: i for i, (code, _) in enumerate(STEPS)}


def step_of(u: User) -> str:
    if u.auth_provider == "email" and not u.email_verified and not u.telegram_id:
        return "email"
    if not u.name or not u.birth_date or not (u.terms_accepted_at and u.terms_version == TERMS_VERSION):
        return "about"
    if not u.gender or not u.looking_for:
        return "identity"
    if not u.survey_done and not u.extras_done:
        return "extras"
    if not u.survey_done:
        return "survey"
    if not u.photo_path:
        return "photo"
    if not u.photo_verified:
        return "scan"
    if u.lat is None:
        return "location"
    return "done"
