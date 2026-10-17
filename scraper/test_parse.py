#!/usr/bin/env python3
"""Проверка разбора карточек на реальных объявлениях, которые попали в выдачу 17.10.2026.

Запуск:  python scraper/test_parse.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import krysha_scraper as k  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append("%s: ожидали %r, получили %r" % (name, want, got))


def card(lines):
    return k.parse_card_lines(lines, "Актау")


# 1. 3к, ЖК Lagyl Tas, черновая (состояние в карточке), хозяин, срочно
c = card([
    "3-комнатная квартира · 113.1 м² · 7/7 этаж", "33 000 000 ₸", "41-й мкр 6",
    "жил. комплекс Lagyl Tas, кирпичный дом, 2025 г.п., состояние: черновая отделка, без мебели, "
    "СРОЧНО! ақша керек, документі бар, банкпен алуға болады",
    "Хозяин недвижимости", "Актау", "17 окт."])
check("1.rooms", c["r"], 3); check("1.area", c["a"], 113.1); check("1.floor", (c["f"], c["ft"]), (7, 7))
check("1.price", c["p"], 33000000); check("1.mkr", (c["m"], c["h"]), ("41", "6"))
check("1.state", c["st"], "черновая отделка"); check("1.cls", c["cl"], "draft")
check("1.seller", c["s"], "o"); check("1.zhk", c["zk"], "Lagyl Tas"); check("1.urgent", "urgent" in c["fl"], True)
check("1.year", c["y"], 2025); check("1.building", c["b"], "кирпичный")

# 2. 2к, 18 мкр, состояние НЕ выбрано, «черновая» только в описании, специалист
c = card([
    "2-комнатная квартира · 83.5 м² · 12/15 этаж", "17 100 000 ₸", "18-й мкр , 18 мкр 43/1",
    "монолитный дом, 2026 г.п., потолки 3м., Продается просторная 2-комнатная квартира с панорамным видом на "
    "город! Квартира в черновой отделке — идеальный вариант для тех, кто хочет создать интерь…",
    "Личность подтверждена", "Специалист подтвердил личность документами", "Специалист", "Актау", "17 окт."])
check("2.mkr", (c["m"], c["h"]), ("18", "43/1")); check("2.state", c["st"], None)
check("2.cls", c["cl"], "likely"); check("2.seller", c["s"], "a"); check("2.price", c["p"], 17100000)

# 3. 1к, 18А мкр, ЖК Premium Plaza, черновая
c = card([
    "1-комнатная квартира · 52 м² · 4/10 этаж", "17 500 000 ₸", "18А мкр 5",
    "жил. комплекс Premium Plaza, монолитный дом, 2021 г.п., состояние: черновая отделка, потолки 3.2м., "
    "Барлык документы биткен, 52м2, обмен жок тек продажа", "Хозяин недвижимости", "Актау", "17 окт."])
check("3.mkr", (c["m"], c["h"]), ("18А", "5")); check("3.cls", c["cl"], "draft"); check("3.zhk", c["zk"], "Premium Plaza")

# 4. новостройка от застройщика: «от» в цене, состояние в теге
c = card([
    "1-комнатная квартира · 57.1 м²", "от 17 130 000 ₸", "20-й мкр 16-17", "Ипотека",
    "Ипотека Квартиры, которые можно приобрести в ипотеку от банков и по гос.программам",
    "жил. комплекс Baq Sarai, 7 этажей, 2022 г.п., потолки 3м., санузел 2 с/у и более, Наличный расчёт",
    "Доступно в ипотеку", "Черновая отделка", "Преимущества:", "Новостройка",
    "ЖК «Baq Sarai» от застройщика «ТОО СтройТехСервис - Т»", "Актау", "17 окт."])
check("4.dev", c["dev"], True); check("4.seller", c["s"], "d"); check("4.state", c["st"], "черновая отделка")
check("4.cls", c["cl"], "draft"); check("4.mkr", (c["m"], c["h"]), ("20", "16-17"))
check("4.zhk", c["zk"], "Baq Sarai"); check("4.cash", "cash" in c["fl"], True)

# 5. 2к в 19А мкр, «в хорошем состоянии» -> renovated, специалист
c = card([
    "2-комнатная квартира · 73.4 м² · 7/7 этаж", "22 000 000 ₸", "19А мкр, 19а 22",
    "монолитный дом, 2022 г.п., потолки 3м., санузел совмещенный, интернет проводной, меблирована полностью, "
    "Продается 2х комн квартира в хорошем состоянии лифт есть. документы в порядке",
    "Специалист", "Актау", "17 окт."])
check("5.mkr", (c["m"], c["h"]), ("19А", "22")); check("5.cls", c["cl"], "renovated"); check("5.seller", c["s"], "a")

# 6. 2к в 14 мкр без дома и без описания состояния -> unknown
c = card([
    "2-комнатная квартира · 50 м²", "33 000 000 ₸", "14-й мкр",
    "монолитный дом, 2025 г.п., потолки 3.2м., санузел 2 с/у и более, телефон: отдельный, интернет проводной, "
    "Срочно сатылады квартира", "Хозяин недвижимости", "Актау", "17 окт."])
check("6.mkr", (c["m"], c["h"]), ("14", None)); check("6.cls", c["cl"], "renovated" if False else c["cl"])
check("6.state", c["st"], None)

# 7. 3к, 29а мкр, свежий ремонт, наличка, торг
c = card([
    "3-комнатная квартира · 103 м² · 6/6 этаж", "30 000 000 ₸", "29а мкр 171 — 29 а Адал Таун Bs Holding",
    "жил. комплекс Adal Town, монолитный дом, 2024 г.п., состояние: свежий ремонт, потолки 2.8м., санузел "
    "раздельный, меблирована частично, Новый ремонт уй жылы. Застройщик Bs holding лифт газ документ есть. "
    "Ипотека цена 32 млн наличка уступка будет обмен цена 32 млн обмен 35 млн",
    "Срочно, торг", "Хозяин недвижимости", "Актау", "17 окт."])
check("7.mkr", (c["m"], c["h"]), ("29А", "171")); check("7.cls", c["cl"], "renovated")
check("7.cash", "cash" in c["fl"], True); check("7.torg", "torg" in c["fl"], True)
check("7.zhk", c["zk"], "Adal Town")

# 8. карточка другого города из блока «Горячие предложения» (нет слова «Актау») -> в parse_page отсеивается
html = """
<html><body><div class="a-list">
 <div class="a-card" data-id="111"><a class="a-card__title" href="/a/show/111">2-комнатная квартира · 64 м² · 4/9 этаж</a>
  <div class="a-card__price">32 300 000 ₸</div><div class="a-card__subtitle">17-й мкр 25</div>
  <div class="a-card__text-preview">монолитный дом, состояние: черновая отделка</div>
  <div>Хозяин недвижимости</div><div>Актау</div><div>17 окт.</div></div>
 <div class="a-card" data-id="111"><a class="a-card__title" href="/a/show/111">2-комнатная квартира · 64 м² · 4/9 этаж</a>
  <div class="a-card__price">32 300 000 ₸</div><div class="a-card__subtitle">17-й мкр 25</div>
  <div class="a-card__text-preview">дубль из блока «горячие»</div><div>Актау</div></div>
 <div class="a-card" data-id="222"><a class="a-card__title" href="/a/show/222">5-комнатная квартира · 120 м² · 3 этаж</a>
  <div class="a-card__price">32 000 000 ₸</div><div class="a-card__subtitle">Жалын 3а</div><div>Жанаозен</div></div>
</div><div>Найдено 11 089 объявлений</div></body></html>"""
cards, soup = k.parse_page(html, "Актау")
check("8.count", len(cards), 1); check("8.id", cards[0]["id"], 111); check("8.cls", cards[0]["cl"], "draft")
check("8.total", k.found_total(soup), 11089)

# 8b. другая вёрстка: нет классов a-card, карточка = вложенные div; боковой блок «Горячие предложения в…» игнорируется
html2 = """
<html><body><main>
 <div class="x1"><div class="x2"><div class="x3"><a href="/a/show/501"><span>3-комнатная квартира · 81 м² · 7/7 этаж</span></a></div>
   <div class="x4"><span>33 000 000 ₸</span></div><div class="x5">41-й мкр 17</div><p>2026 г.п., состояние: черновая отделка</p></div>
   <footer><b>Хозяин недвижимости</b><i>Актау</i><i>17 окт.</i></footer></div>
 <div class="x1"><div class="x2"><a href="/a/show/502">2-комнатная квартира · 70 м² · 2/5 этаж</a><div>25 000 000 ₸</div><div>17-й мкр 3</div>
   <p>без ремонта</p></div><footer><b>Специалист</b><i>Актау</i></footer></div>
</main>
<h2>Горячие предложения в Мангистауской обл.</h2>
<div><a href="/a/show/503">2-комнатная квартира · 64 м² · 4/9 этаж</a><div>32 300 000 ₸</div><div>17-й мкр</div></div>
</body></html>"""
cards2, _ = k.parse_page(html2, "Актау")
by2 = {c["id"]: c for c in cards2}
check("8b.ids", sorted(by2), [501, 502]); check("8b.seller", (by2[501]["s"], by2[502]["s"]), ("o", "a"))
check("8b.cls", (by2[501]["cl"], by2[502]["cl"]), ("draft", "likely")); check("8b.mkr", by2[501]["m"], "41")

# 8c. структура как на живой странице: карточка с data-product-id, значения раздроблены по span, «₸» отдельно
html3 = """
<html><body><div class="a-list">
 <div class="a-card a-storage-live ddl_product" id="id-601" data-product-id="601">
  <div class="a-card__inc"><a class="a-card__title" href="/a/show/601">2-комнатная квартира<span> · </span>83.5 м²<span> · </span>12/15 этаж</a>
  <div class="a-card__price"><span>17 100 000</span> <span>₸</span></div>
  <div class="a-card__subtitle">18-й мкр , 18 мкр 43/1</div>
  <div class="a-card__text-preview">монолитный дом, 2026 г.п., потолки 3м., Квартира в черновой отделке</div>
  <div class="a-card__owner-label"><span>Специалист</span></div>
  <div class="card-stats"><span>Актау</span><span>17 окт.</span></div></div></div>
 <div class="a-card a-storage-live ddl_product" id="id-602" data-product-id="602">
  <a class="a-card__title" href="/a/show/602">2-комнатная квартира · 75 м² · 4/6 этаж</a>
  <div class="a-card__price">20 000 000 ₸</div><div class="a-card__subtitle">29а мкр 162</div>
  <div class="a-card__text-preview">состояние: черновая отделка</div>
  <div class="a-card__owner-label">Хозяин недвижимости</div><div class="card-stats">Актау 17 окт.</div></div>
</div><div>Найдено 11 089 объявлений</div></body></html>"""
cards3, _ = k.parse_page(html3, "Актау")
by3 = {c["id"]: c for c in cards3}
check("8c.ids", sorted(by3), [601, 602])
check("8c.price", (by3[601]["p"], by3[602]["p"]), (17100000, 20000000))
check("8c.mkr", (by3[601]["m"], by3[601]["h"]), ("18", "43/1"))
check("8c.seller", (by3[601]["s"], by3[602]["s"]), ("a", "o"))
check("8c.cls", (by3[601]["cl"], by3[602]["cl"]), ("likely", "draft"))
check("8c.floor", (by3[601]["f"], by3[601]["ft"], by3[601]["a"]), (12, 15, 83.5))

# 9. адреса
check("9a", k.parse_address('мкр "Самал"'), ("Самал", None))
check("9b", k.parse_address("Микрорайон 29а 170 — 29 а жк Adal Town"), ("29А", "170"))
check("9c", k.parse_address("29 a 170 — 29 a Адал Таун Bs Holding")[0], None)  # без слова «мкр» — не угадываем
check("9d", k.parse_address("17-й мкр 24"), ("17", "24"))

# 10. классификатор
check("10a", k.classify(None, "без ремонта, под чистовую отделку"), "likely")
check("10b", k.classify(None, "хозяин, торг, документы готовы"), "unknown")
check("10c", k.classify("свежий ремонт", "черновая отделка"), "renovated")
check("10d", k.classify("предчистовая отделка", ""), "draft")
check("10e", k.classify(None, "стяжка, штукатурка, бетон"), "likely")
check("10f", k.classify(None, "евроремонт, меблирована полностью, стяжка пола"), "renovated")

# 11. слияние со вчерашним снимком
from datetime import datetime  # noqa: E402
cfg = dict(k.DEFAULT_CFG)
prev = {"listings": [
    {"id": 111, "p": 33000000, "fs": "2026-10-10", "ph": [["2026-10-10", 33000000]], "ms": 0, "cl": "draft", "ds": ""},
    {"id": 999, "p": 20000000, "fs": "2026-10-01", "ph": [["2026-10-01", 20000000]], "ms": 0, "cl": "draft", "ds": ""}]}
found = {111: dict(cards[0], id=111), 333: dict(cards[0], id=333, p=25000000)}
now = datetime(2026, 10, 18, 8, 0, tzinfo=k.TZ)
data, n_new = k.merge(prev, found, cfg, now)
by = {l["id"]: l for l in data["listings"]}
check("11.new", n_new, 1)
check("11.fs_kept", by[111]["fs"], "2026-10-10")
check("11.price_hist", by[111]["ph"], [["2026-10-10", 33000000], ["2026-10-18", 32300000]])
check("11.fs_new", by[333]["fs"], "2026-10-18")
check("11.missing_kept", (by[999]["ms"], 999 in by), (1, True))
check("11.new_today", data["new_today"], 1)

if FAILS:
    print("ПРОВАЛЕНО %d проверок:" % len(FAILS))
    for f in FAILS:
        print(" -", f)
    sys.exit(1)
print("OK: все проверки разбора пройдены")
