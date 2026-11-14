"""Быстрая загрузка статики (важно для дальних стран: из Вьетнама до сервера в Москве ~0,3 с на каждый запрос).

* У статики есть версия — хэш всех файлов в static/. Страницы ссылаются на /static/v/<версия>/...,
  такие файлы браузер хранит год и не перепроверяет. Новая версия кода = новые адреса, старое не залипает.
* В <head> перечислены все модули, нужные для старта (modulepreload): браузер качает их разом,
  а не по цепочке «скачал app.js → увидел import ui.js → скачал ui.js → …».
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from .config import BASE_DIR

STATIC_DIR = BASE_DIR / "static"
_IMPORT = re.compile(r"""^\s*(?:import|export)\s[^;]*?from\s+["'](\.{1,2}/[^"']+\.js)["']|^\s*import\s+["'](\.{1,2}/[^"']+\.js)["']""", re.M)


@lru_cache(maxsize=1)
def version() -> str:
    h = hashlib.sha256()
    for p in sorted(STATIC_DIR.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(STATIC_DIR)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


def module_graph(entry: str) -> list[str]:
    """Все модули, которые entry (например, js/app.js) подтягивает статическими import. Пути относительно static/."""
    seen: list[str] = []
    todo = [entry]
    while todo:
        rel = todo.pop()
        if rel in seen or not (STATIC_DIR / rel).is_file():
            continue
        seen.append(rel)
        base = Path(rel).parent
        for a, b in _IMPORT.findall((STATIC_DIR / rel).read_text(encoding="utf-8")):
            target = (STATIC_DIR / base / (a or b)).resolve()
            if STATIC_DIR.resolve() in target.parents:
                todo.append(target.relative_to(STATIC_DIR.resolve()).as_posix())
    return seen


@lru_cache(maxsize=4)
def page(name: str, entry: str) -> str:
    """HTML страницы с адресами статики под текущей версией и списком модулей для предзагрузки."""
    prefix = f"/static/v/{version()}/"
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    # только скрипты и стили: иконки и manifest остаются на постоянных адресах (их запоминает телефон)
    html = re.sub(r'((?:src|href)=")/static/([^"]+\.(?:js|css)")', lambda m: m.group(1) + prefix + m.group(2), html)
    preload = "".join(f'\n  <link rel="modulepreload" href="{prefix}{m}">' for m in module_graph(entry)[1:])
    return html.replace("</head>", f"{preload}\n</head>", 1)
