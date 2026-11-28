"""Собирает app/data/cities.json.gz: города мира от 5000 жителей (GeoNames, CC BY 4.0) с русскими названиями.

Россия и СНГ — русское название из GeoNames (выбирается то, что совпадает по звучанию с международным).
Вьетнам и популярные города мира — проверенный словарь. Остальные — международное название.
Запуск: python build_cities.py <cities5000.json> <выходной файл>
"""
import gzip
import json
import re
import sys
import unicodedata

SRC, OUT = sys.argv[1], sys.argv[2]

CIS = {"RU", "BY", "KZ", "KG", "UA", "UZ", "TJ", "AM", "AZ", "GE", "MD", "TM", "AB"}
TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
               "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
NOT_RU = set("јњљћђџіїєґўәөүңғқһҙҫҡ")
RU = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя- ")

# (международное название, страна) → по-русски
WORLD = {
    # Вьетнам
    ("Hanoi", "VN"): "Ханой", ("Ho Chi Minh City", "VN"): "Хошимин", ("Da Nang", "VN"): "Дананг", ("Da Lat", "VN"): "Далат",
    ("Nha Trang", "VN"): "Нячанг", ("Haiphong", "VN"): "Хайфон", ("Can Tho", "VN"): "Кантхо", ("Hue", "VN"): "Хюэ",
    ("Vung Tau", "VN"): "Вунгтау", ("Hoi An", "VN"): "Хойан", ("Phan Thiet", "VN"): "Фантхьет", ("Quy Nhon", "VN"): "Куинён",
    ("Duong Dong", "VN"): "Фукуок", ("Phú Quốc", "VN"): "Фукуок", ("Ha Long", "VN"): "Халонг", ("Cam Ranh", "VN"): "Камрань",
    ("Bien Hoa", "VN"): "Бьенхоа", ("Vinh", "VN"): "Винь", ("Buon Ma Thuot", "VN"): "Буонматхуот", ("Sa Pa", "VN"): "Сапа",
    ("Phan Rang-Thap Cham", "VN"): "Фанранг", ("Thanh Hoa", "VN"): "Тханьхоа", ("Nam Dinh", "VN"): "Намдинь",
    # Россия и СНГ — где международное название сильно отличается
    ("Moscow", "RU"): "Москва", ("Saint Petersburg", "RU"): "Санкт-Петербург", ("Kyiv", "UA"): "Киев", ("Lviv", "UA"): "Львов",
    ("Odesa", "UA"): "Одесса", ("Dnipro", "UA"): "Днепр", ("Kharkiv", "UA"): "Харьков", ("Zaporizhzhya", "UA"): "Запорожье",
    ("Kryvyy Rih", "UA"): "Кривой Рог", ("Mykolayiv", "UA"): "Николаев", ("Chisinau", "MD"): "Кишинёв",
    ("Almaty", "KZ"): "Алматы", ("Astana", "KZ"): "Астана", ("Bishkek", "KG"): "Бишкек", ("Tashkent", "UZ"): "Ташкент",
    ("Yerevan", "AM"): "Ереван", ("Tbilisi", "GE"): "Тбилиси", ("Baku", "AZ"): "Баку", ("Minsk", "BY"): "Минск",
    ("Ashgabat", "TM"): "Ашхабад", ("Dushanbe", "TJ"): "Душанбе",
    # Азия
    ("Bangkok", "TH"): "Бангкок", ("Phuket", "TH"): "Пхукет", ("Pattaya", "TH"): "Паттайя", ("Chiang Mai", "TH"): "Чиангмай",
    ("Krabi", "TH"): "Краби", ("Hua Hin", "TH"): "Хуахин", ("Ko Samui", "TH"): "Самуи", ("Phnom Penh", "KH"): "Пномпень",
    ("Siem Reap", "KH"): "Сиемреап", ("Sihanoukville", "KH"): "Сиануквиль", ("Vientiane", "LA"): "Вьентьян",
    ("Luang Prabang", "LA"): "Луангпхабанг", ("Kuala Lumpur", "MY"): "Куала-Лумпур", ("George Town", "MY"): "Джорджтаун",
    ("Singapore", "SG"): "Сингапур", ("Jakarta", "ID"): "Джакарта", ("Denpasar", "ID"): "Денпасар", ("Ubud", "ID"): "Убуд",
    ("Manila", "PH"): "Манила", ("Cebu City", "PH"): "Себу", ("Beijing", "CN"): "Пекин", ("Shanghai", "CN"): "Шанхай",
    ("Guangzhou", "CN"): "Гуанчжоу", ("Shenzhen", "CN"): "Шэньчжэнь", ("Hong Kong", "HK"): "Гонконг", ("Macau", "MO"): "Макао",
    ("Sanya", "CN"): "Санья", ("Harbin", "CN"): "Харбин", ("Taipei", "TW"): "Тайбэй", ("Seoul", "KR"): "Сеул",
    ("Busan", "KR"): "Пусан", ("Tokyo", "JP"): "Токио", ("Osaka", "JP"): "Осака", ("Kyoto", "JP"): "Киото",
    ("Ulaanbaatar", "MN"): "Улан-Батор", ("New Delhi", "IN"): "Нью-Дели", ("Delhi", "IN"): "Дели", ("Mumbai", "IN"): "Мумбаи",
    ("Goa", "IN"): "Гоа", ("Panaji", "IN"): "Панаджи", ("Kathmandu", "NP"): "Катманду", ("Colombo", "LK"): "Коломбо",
    ("Male", "MV"): "Мале", ("Dubai", "AE"): "Дубай", ("Abu Dhabi", "AE"): "Абу-Даби", ("Sharjah", "AE"): "Шарджа",
    ("Doha", "QA"): "Доха", ("Istanbul", "TR"): "Стамбул", ("Antalya", "TR"): "Анталья", ("Ankara", "TR"): "Анкара",
    ("Alanya", "TR"): "Аланья", ("Tel Aviv", "IL"): "Тель-Авив", ("Jerusalem", "IL"): "Иерусалим", ("Tehran", "IR"): "Тегеран",
    # Европа
    ("London", "GB"): "Лондон", ("Paris", "FR"): "Париж", ("Berlin", "DE"): "Берлин", ("Munich", "DE"): "Мюнхен",
    ("Rome", "IT"): "Рим", ("Milan", "IT"): "Милан", ("Madrid", "ES"): "Мадрид", ("Barcelona", "ES"): "Барселона",
    ("Lisbon", "PT"): "Лиссабон", ("Prague", "CZ"): "Прага", ("Vienna", "AT"): "Вена", ("Warsaw", "PL"): "Варшава",
    ("Budapest", "HU"): "Будапешт", ("Belgrade", "RS"): "Белград", ("Athens", "GR"): "Афины", ("Riga", "LV"): "Рига",
    ("Vilnius", "LT"): "Вильнюс", ("Tallinn", "EE"): "Таллин", ("Helsinki", "FI"): "Хельсинки", ("Stockholm", "SE"): "Стокгольм",
    ("Oslo", "NO"): "Осло", ("Copenhagen", "DK"): "Копенгаген", ("Amsterdam", "NL"): "Амстердам", ("Brussels", "BE"): "Брюссель",
    ("Zurich", "CH"): "Цюрих", ("Geneva", "CH"): "Женева", ("Limassol", "CY"): "Лимасол", ("Larnaca", "CY"): "Ларнака",
    ("Nicosia", "CY"): "Никосия", ("Budva", "ME"): "Будва", ("Podgorica", "ME"): "Подгорица", ("Sofia", "BG"): "София",
    ("Bucharest", "RO"): "Бухарест", ("Dublin", "IE"): "Дублин",
    # Остальной мир
    ("New York City", "US"): "Нью-Йорк", ("Los Angeles", "US"): "Лос-Анджелес", ("Miami", "US"): "Майами",
    ("Toronto", "CA"): "Торонто", ("Mexico City", "MX"): "Мехико", ("Cancún", "MX"): "Канкун", ("Buenos Aires", "AR"): "Буэнос-Айрес",
    ("Rio de Janeiro", "BR"): "Рио-де-Жанейро", ("São Paulo", "BR"): "Сан-Паулу", ("Sydney", "AU"): "Сидней",
    ("Melbourne", "AU"): "Мельбурн", ("Cairo", "EG"): "Каир", ("Hurghada", "EG"): "Хургада", ("Sharm el-Sheikh", "EG"): "Шарм-эш-Шейх",
}


def translit(s):
    return "".join(TR.get(ch, ch) for ch in s.lower())


def plain(s):
    s = s.lower().replace("đ", "d").replace("ð", "d")
    return re.sub(r"[^a-z ]", "", "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).replace("-", " "))


def dist(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cis_name(c):
    target = plain(c["name"])
    words = len(target.split())
    cands = [a for a in c.get("alternatenames", []) if a and all(ch.lower() in RU for ch in a) and not (set(a.lower()) & NOT_RU)
             and any("а" <= ch.lower() <= "я" for ch in a) and len(a.replace("-", " ").split()) == words
             and not re.search(r"ъ$|ъ |ськ|цьк|ьск|ьк$|ьскъ", a.lower())]
    if not cands:
        return None
    best = min(cands, key=lambda a: (dist(translit(a).replace("-", " "), target), "тс" in a.lower(), -len(a)))
    return best if dist(translit(best).replace("-", " "), target) <= max(2, len(target) // 3) else None


WORLD.update({("Rostov-on-Don", "RU"): "Ростов-на-Дону", ("Qui Nhon", "VN"): "Куинён", ("Ulan Bator", "MN"): "Улан-Батор",
              ("Zuerich", "CH"): "Цюрих", ("Zürich", "CH"): "Цюрих"})
WORLD_PLAIN = {(plain(n), cc): ru for (n, cc), ru in WORLD.items()}

data = json.load(open(SRC))
items = list(data.values()) if isinstance(data, dict) else data
out = []
for c in items:
    cc = c["countrycode"]
    ru = WORLD_PLAIN.get((plain(c["name"]), cc)) or (cis_name(c) if cc in CIS else None)
    out.append([ru or c["name"], cc, round(c["latitude"], 4), round(c["longitude"], 4), int(c.get("population") or 0)])
out.sort(key=lambda x: -x[4])
with gzip.open(OUT, "wt", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(len(out), "городов")
missing = sorted({v for k, v in WORLD.items() if not any(x[0] == v and x[1] == k[1] for x in out)})
print("не найдены в базе:", missing)
print("СНГ:", [x[0] for x in out if x[1] in CIS][:60])
print("VN:", [x[0] for x in out if x[1] == "VN"][:30])
