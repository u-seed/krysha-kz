#!/usr/bin/env python3
"""krysha-kz: ежедневный сбор объявлений о продаже квартир в Актау с krisha.kz.

Что делает:
  1. обходит выдачу крыши по каждому числу комнат из config.json;
  2. разбирает карточки по ТЕКСТУ (устойчиво к смене CSS-классов);
  3. классифицирует отделку (draft / likely / renovated / unknown);
  4. сравнивает с прошлым data.json (новые, цена упала, пропавшие);
  5. пишет data.json и status.json в корень репозитория.

Запуск:  python scraper/krysha_scraper.py
Тест:    python scraper/test_parse.py
"""
import argparse
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=5))  # Актау, UTC+5

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")

DEFAULT_CFG = {
    "city_name": "Актау",
    "list_url": "https://krisha.kz/prodazha/kvartiry/aktau/",
    "rooms": [2, 3, 4],
    "max_pages": 400,
    "delay_min": 1.0,
    "delay_max": 2.2,
    "keep_missing_runs": 3,
    "min_ratio_to_prev": 0.5,
    "detail_fetch": False,
    "detail_mkr": ["17", "18", "19"],
    "detail_max_per_run": 120,
}


class Blocked(Exception):
    """Крыша не отдала нормальную выдачу (блокировка, капча, смена вёрстки)."""


# --------------------------------------------------------------------------
#  Разбор текста карточки
# --------------------------------------------------------------------------

LAT2CYR = {"a": "А", "A": "А", "b": "Б", "B": "Б"}
LETTER = "аАбБвВгГaAbB"

# «18-й мкр», «29а мкр», «19А мкр», «17 мкр»
MKR_A = re.compile(r"(\d{1,2})\s*([%s])?\s*-?\s*(?:й\s*)?(?:мкр|микрорайон|мкрн)\b" % LETTER, re.I)
# «Микрорайон 29а 170», «мкр 18»
MKR_B = re.compile(r"(?:мкр|микрорайон)\.?\s*(\d{1,2})\s*([%s])?(?![\dа-яa-z])" % LETTER, re.I)
# мкр "Самал", мкр «Шыгыс 1»
MKR_NAMED = re.compile(r"мкр\.?\s*[\"«“]([^\"»”]+)[\"»”]", re.I)

HOUSE = re.compile(r"(?<![\d/-])(\d{1,3}(?:[/-]\d{1,3})?)(?![\dа-яa-z/-])", re.I)

SEP = r"\s*(?:\|\s*)?·\s*(?:\|\s*)?"
TITLE = re.compile(
    r"(\d)\s*-?\s*комнатн\w*\s+квартира" + SEP + r"([\d.,]+)\s*(?:\|\s*)?м[²2]"
    r"(?:" + SEP + r"(\d{1,2})(?:/(\d{1,2}))?\s*(?:\|\s*)?этаж)?",
    re.I)
PRICE = re.compile(r"(от\s+)?(\d[\d\s]{3,}?)\s*(?:\|\s*)?₸")
DATE_LINE = re.compile(
    r"^(\d{1,2}\s+(?:янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)\.?|сегодня|вчера)$", re.I)
STATE = re.compile(r"состояние:\s*([^,|\n]+)", re.I)
ZHK = re.compile(r"жил\.?\s*комплекс\s+([^,|\n]+?)\s*(?:,|$)", re.I)
BUILDING = re.compile(r"(кирпичный|панельный|монолитный|иной)\s+дом", re.I)
YEAR = re.compile(r"(\d{4})\s*г\.\s*п\.", re.I)

SELLER_LABELS = {
    "хозяин недвижимости": "o",
    "специалист": "a",
    "компания": "c",
}
TAG_STATES = ["черновая отделка", "предчистовая отделка", "с ремонтом", "без отделки", "требует ремонта"]
NOISE = ("квартиры, которые можно", "приобрести в ипотеку", "от банков и по гос", "в избранное",
         "сохранить в подборку", "оставить заметку", "редактировать заметку", "подробнее о подтверждении",
         "перейти в личный кабинет", "объявление поднято", "каждый посетитель", "просмотров на", "дней активного",
         "поднятие в топ", "подключить в личном", "объявление с такой меткой", "вызывает в 1,5", "интереса у покупателей",
         "личность подтверждена", "подтвердил личность", "в горячих", "топ объявление", "преимущества")

# --- классификация отделки ---
DRAFT_STRONG = re.compile(
    r"чернов|без\s+ремонта|без\s+отделки|предчистов|под\s+чистов|под\s+отделк|без\s+ремонт|ремонтсыз|жөндеусіз|"
    r"требует\s+отделк|только\s+стены", re.I)
DRAFT_WEAK = re.compile(r"бетон|стяжк|штукатурк|голые\s+стены|коробк", re.I)
RENOV = re.compile(
    r"свежий\s+ремонт|евроремонт|с\s+ремонтом|капитальн\w*\s+ремонт|дизайнерск|новый\s+ремонт|хороший\s+ремонт|"
    r"жана\s+ремонт|жаңа\s+ремонт|ремонт\s+бар|аккуратный\s+ремонт|косметическ|отличное|хорошее|"
    r"меблирована\s+(?:полностью|частично)|с\s+мебелью|мебель\s+остается|мебель\s+остаётся|мебель\s+қалады", re.I)

CASH = re.compile(r"налич(?:к|н|ны|ные|ными)", re.I)
URGENT = re.compile(r"срочн", re.I)
TORG = re.compile(r"торг", re.I)


def norm_ws(s):
    return re.sub(r"[\s  ]+", " ", (s or "").replace("\u200b", "")).strip()


def norm_mkr(num, letter):
    letter = (letter or "").strip()
    letter = LAT2CYR.get(letter, letter).upper()
    return "%s%s" % (int(num), letter)


def parse_address(addr):
    """-> (mkr, house). mkr — «18», «18А», «Самал» или None."""
    if not addr:
        return None, None
    main = addr.split("—")[0]
    ms = [m for m in MKR_A.finditer(main)]
    mkr = None
    last_end = 0
    if ms:
        m0 = ms[0]
        mkr = norm_mkr(m0.group(1), m0.group(2))
        last_end = ms[-1].end()
    else:
        mb = MKR_B.search(main)
        if mb:
            mkr = norm_mkr(mb.group(1), mb.group(2))
            last_end = mb.end()
        else:
            mn = MKR_NAMED.search(main)
            if mn:
                mkr = mn.group(1).strip()
                last_end = mn.end()
    house = None
    rest = main[last_end:]
    hs = HOUSE.findall(rest)
    if hs:
        house = hs[-1]
    return mkr, house


# --------------------------------------------------------------------------
#  Какой это микрорайон на самом деле
#
#  Поле адреса на крыше состоит из двух частей: «18-й мкр , Мкр. 29А Латифа».
#  Первая — микрорайон, выбранный на карте (его часто ставят «как попало»),
#  вторая — адрес, который ввёл продавец. Ещё мкр бывает в описании.
#  Приоритет: описание > адрес продавца > мкр с карты.
# --------------------------------------------------------------------------

MKR_MAX = 41  # в Актау микрорайоны 1–41; бóльшие числа — это номер дома
MKR_WORD = r"(?:мкр\.?|мкрн\.?|мкр-н|микр-н|микрорайон\w{0,3})"
# «29А микрорайон», «19 мкр», «29а мкр», «18-й мкр»
MKR_TXT_A = re.compile(
    r"(?<![\d/.,-])(\d{1,2})\s*-?\s*(?:й|м|ый|ой|ом|ий)?\s*([%s])?\s*-?\s*(?:й|м)?\s*%s(?![а-яёa-z])" % (LETTER, MKR_WORD), re.I)
# «Мкр. 29А 167», «микрорайон 18а»; «Новый микрорайон 5)» — это пункт списка, не мкр
MKR_TXT_B = re.compile(r"%s\s*(\d{1,2})\s*([%s])?(?![\d)\-а-яёa-z])" % (MKR_WORD, LETTER), re.I)
# мкр с именем («Шыгыс 3», «Самал 2»): цифра после имени — часть названия, а не номер мкр
NAMED_MKR = re.compile(r"(?:шыг[ыі]с|шығыс|самал|толкын|оймаш|акжелкен)\s*-?\s*\d+", re.I)
EXCHANGE = re.compile(r"обмен|айырбас", re.I)
# адрес продавца без слова «мкр»: «29 а 167», «29А167», «18 7» = мкр 29А дом 167, мкр 18 дом 7
BARE_ADDR = re.compile(r"^\W*(\d{1,2})\s*([%s])?\s*[ ]?\s*(\d{1,3}(?:[/-]\d{1,3})?)\W*$" % LETTER, re.I)
GLUED_ADDR = re.compile(r"^\W*(\d{1,2})([%s])(\d{1,3}(?:[/-]\d{1,3})?)\W*$" % LETTER, re.I)


def _bare_addr(text):
    """«29 а 167» / «29А167» / «18 7» -> (мкр, дом) или None. Только если это вся строка адреса."""
    m = GLUED_ADDR.match(text or "") or BARE_ADDR.match(text or "")
    if not m or not (1 <= int(m.group(1)) <= MKR_MAX):
        return None
    return norm_mkr(m.group(1), m.group(2)), m.group(3)
# ориентиры, а не адрес: «рядом с 17 мкр», «обмен на 27 мкр», «напротив 16 мкрн»
LANDMARK_BEFORE = re.compile(
    r"(?:^|[\s,.;:(—-])(?:рядом|возле|около|напротив|недалеко|близко|близ|вблизи|обмен\w*|между|соседн\w*|через|"
    r"от|до|из|в\s+сторону)\s*(?:с|со|на|от|к|же)?\s*$", re.I)


def _mkr_mentions(text, skip_landmarks=False):
    """Все упоминания микрорайона в тексте: [(норм. мкр, начало, конец)] по порядку.
    skip_landmarks=True — режим для описания: пропускаем ориентиры («рядом с 17 мкр»), всё, что сказано
    после слова «обмен» (там перечисляют, куда хотят обменять), и «мкр 18» без буквы и знака после числа."""
    text = NAMED_MKR.sub(lambda m: "\u00a7" * len(m.group(0)), text or "")  # § — чтобы число после «Самал-2» не стало номером мкр
    limit = len(text)
    if skip_landmarks:
        ex = EXCHANGE.search(text)
        if ex:
            limit = ex.start()
    found = []
    a_spans = []
    for m in MKR_TXT_A.finditer(text):
        a_spans.append((m.start(), m.end()))
        found.append((m.start(), m.end(), m.group(1), m.group(2)))
    for m in MKR_TXT_B.finditer(text):
        if any(s <= m.start() < e for s, e in a_spans):
            continue  # «мкр» уже входит в «18 мкр», а число после него — номер дома
        if skip_landmarks and not m.group(2) and not re.match(r"\s*(?:[,.;]|$)", text[m.end():]):
            continue  # «микрорайон 18 дом 7» — 18 здесь может быть и домом
        found.append((m.start(), m.end(), m.group(1), m.group(2)))
    found.sort()
    out = []
    for s, e, num, let in found:
        if not (1 <= int(num) <= MKR_MAX) or s >= limit:
            continue
        if skip_landmarks and LANDMARK_BEFORE.search(text[max(0, s - 34):s]):
            continue
        out.append((norm_mkr(num, let), s, e))
    return out


def resolve_mkr(addr, desc):
    """-> (mkr, house, src, orig).
    src: None — как на карте; 'a' — мкр из адреса продавца; 'd' — мкр из описания.
    orig — мкр с карты до исправления (None, если не менялся)."""
    geo, house = parse_address(addr)
    mkr, src = geo, None
    main = (addr or "").split("—")[0]
    _, _, typed = main.partition(",")
    tm = _mkr_mentions(typed)
    cand = None
    if tm:
        hs = HOUSE.findall(typed[tm[0][2]:])
        cand = (tm[0][0], hs[-1] if hs else None)
    else:
        cand = _bare_addr(typed)
    if cand and cand[0] != mkr:
        mkr, house, src = cand[0], cand[1], "a"
    if mkr is None:  # мкр на карте не выбран, а адрес — просто «29 а 167»
        bare = _bare_addr(main)
        if bare:
            mkr, house, src = bare[0], bare[1], "a"
    dm = [x[0] for x in _mkr_mentions(desc, skip_landmarks=True)]
    if dm and mkr not in dm:
        best, cnt = dm[0], 0
        for x in dm:
            if dm.count(x) > cnt:
                best, cnt = x, dm.count(x)
        mkr, src, house = best, "d", None
    if mkr == geo:  # после всех поправок вернулись к мкр с карты — значит, исправлять нечего
        return geo, parse_address(addr)[1], None, None
    return mkr, house, src, geo


def fix_record(rec):
    """Пересчитать мкр у готовой записи (по сохранённым ad и ds). Нужна для старых снимков и для --reprocess."""
    mkr, house, src, orig = resolve_mkr(rec.get("ad"), rec.get("ds"))
    if src is None:
        # мкр не менялся — оставляем как есть (дом тоже), старые пометки убираем
        rec.pop("mo", None)
        rec.pop("mw", None)
        geo, h0 = parse_address(rec.get("ad"))
        rec["m"], rec["h"] = geo, h0
    else:
        rec["m"], rec["h"], rec["mo"], rec["mw"] = mkr, house, orig, src
    return rec


class ExcludeRules(list):
    """Правила исключения: сам список — регулярки ЖК (exclude_zhk); .houses — {мкр: {номера домов}} (exclude_houses)."""
    houses = {}


def _norm_house(h):
    return re.sub(r"\s+", "", str(h or "")).lower().replace("-", "/").replace("\\", "/")


def is_excluded(rec, rules):
    """Объявления, которые пользователь не рассматривает (config.json): ЖК по названию и дома по адресу."""
    zk = rec.get("zk") or ""
    text = "%s %s" % (rec.get("ad") or "", rec.get("ds") or "")
    for p in rules:
        if p.search(zk):
            return True
        if re.search(r"(?:жк|комплекс\w*)\W{0,3}(?:%s)" % p.pattern, text, re.I):
            return True
    hs = getattr(rules, "houses", None) or {}
    if rec.get("m") in hs and rec.get("h") and _norm_house(rec["h"]) in hs[rec["m"]]:
        return True
    return False


def exclude_patterns(cfg):
    rules = ExcludeRules(re.compile(x, re.I) for x in cfg.get("exclude_zhk", []) if x)
    rules.houses = {str(m): set(_norm_house(h) for h in hs) for m, hs in (cfg.get("exclude_houses") or {}).items()}
    return rules


def classify(state, text):
    """-> класс отделки: draft | likely | renovated | unknown."""
    st = (state or "").lower()
    if "чернов" in st or "предчистов" in st or "без отделки" in st:
        return "draft"
    if st and ("ремонт" in st or "хорош" in st or "отличн" in st or "новое" in st or "евро" in st):
        return "renovated"
    low = text or ""
    strong = DRAFT_STRONG.search(low)
    weak = DRAFT_WEAK.search(low)
    renov = RENOV.search(low)
    if strong and not (renov and re.search(r"с\s+ремонтом|свежий\s+ремонт|евроремонт", low, re.I)
                       and not re.search(r"чернов|предчистов", low, re.I)):
        return "likely"
    if weak and not renov:
        return "likely"
    if renov:
        return "renovated"
    return "unknown"


def lines_of(card_text):
    out = []
    for ln in card_text.split("\n"):
        ln = norm_ws(ln)
        if not ln:
            continue
        if out and ln in ("₸", "тг", "тг.", "м²", "м2", "этаж"):
            out[-1] = out[-1] + " " + ln
            continue
        out.append(ln)
    return out


def parse_card_lines(lines, city_name="Актау"):
    """Разбор карточки по списку строк текста. Возвращает dict или None."""
    blob = " | ".join(lines)
    flat = " ".join(lines)  # для заголовка и цены: не зависит от того, как вёрстка раздробила текст по узлам
    mt = TITLE.search(flat)
    if not mt:
        return None
    rooms = int(mt.group(1))
    area = float(mt.group(2).replace(",", "."))
    floor = int(mt.group(3)) if mt.group(3) else None
    floors = int(mt.group(4)) if mt.group(4) else None

    # цена: первая «N ₸» после заголовка
    after_title = flat[mt.end():]
    mp = PRICE.search(after_title)
    if not mp:
        return None
    price = int(re.sub(r"\D", "", mp.group(2)))
    from_price = bool(mp.group(1))

    # строка с ценой -> следующая строка = адрес
    addr = None
    desc_start = None
    for i, ln in enumerate(lines):
        if PRICE.search(ln) and not TITLE.search(ln):
            if i + 1 < len(lines):
                addr = lines[i + 1]
                desc_start = i + 2
            break
    if addr is None:
        # запасной вариант: кусок текста сразу после цены
        addr = norm_ws(after_title[mp.end():][:60])
        desc_start = len(lines)

    # описание: строки после адреса до служебных меток
    desc_parts = []
    seller = None
    date_txt = None
    city_ok = False
    for ln in lines[desc_start:]:
        low = ln.lower()
        if low in SELLER_LABELS:
            seller = SELLER_LABELS[low]
            continue
        if DATE_LINE.match(ln):
            date_txt = ln
            continue
        if ln == city_name:
            city_ok = True
            continue
        if any(n in low for n in NOISE):
            continue
        if low.startswith("жк «") or low.startswith("от застройщика") or low == "новостройка" or low == "ипотека":
            continue
        desc_parts.append(ln)
    desc = norm_ws(" ".join(desc_parts))
    if city_name in blob:
        city_ok = True

    developer = bool(re.search(r"от застройщика|новостройка", blob, re.I)) or from_price
    if developer and seller is None:
        seller = "d"
    if seller is None:
        # запасной вариант: метка склеена с соседним текстом («Хозяин недвижимости Актау 17 окт.»)
        if re.search(r"(?<![\wа-яё])хозяин недвижимости(?![\wа-яё])", blob, re.I):
            seller = "o"
        elif re.search(r"(?<![\wа-яё])специалист(?![\wа-яё])(?!\s+подтвердил)", blob, re.I):
            seller = "a"

    mkr, house, mkr_src, mkr_orig = resolve_mkr(addr, desc)

    state = None
    ms = STATE.search(desc)
    if ms:
        state = norm_ws(ms.group(1)).lower()
    if state is None:
        for ln in lines:
            if ln.lower() in TAG_STATES:
                state = ln.lower()
                break
        if state is None:
            # теги склеены без разделителей: «...Черновая отделка»
            for t in TAG_STATES:
                if re.search(re.escape(t), desc, re.I) and t != "с ремонтом":
                    state = t
                    break
            if state is None and re.search(r"(?:доступно в ипотеку|наличный расчёт)\s*с ремонтом", desc, re.I):
                state = "с ремонтом"

    zhk = None
    mz = ZHK.search(desc)
    if mz:
        zhk = norm_ws(mz.group(1))
    else:
        for ln in lines:
            m2 = re.match(r"ЖК «([^»]+)»", ln)
            if m2:
                zhk = m2.group(1).strip()
                break
    mb = BUILDING.search(desc)
    building = mb.group(1).lower() if mb else None
    my = YEAR.search(desc)
    year = int(my.group(1)) if my else None

    cls = classify(state, desc)

    flags = []
    if CASH.search(blob):
        flags.append("cash")
    if URGENT.search(blob):
        flags.append("urgent")
    if TORG.search(blob):
        flags.append("torg")

    href_id = None
    item = {
        "r": rooms, "a": area, "f": floor, "ft": floors, "p": price, "dev": developer,
        "m": mkr, "h": house, "ad": addr, "zk": zhk, "b": building, "y": year,
        "st": state, "cl": cls, "s": seller or "?", "fl": flags,
        "d": date_txt, "ds": desc, "_city_ok": city_ok, "_id": href_id,
    }
    if mkr_src:
        item["mo"], item["mw"] = mkr_orig, mkr_src
    return item


SHOW_ID = re.compile(r"/a/show/(\d+)")


def _ids_in(node):
    out = set()
    for a in node.select('a[href*="/a/show/"]'):
        m = SHOW_ID.search(a.get("href", ""))
        if m:
            out.add(m.group(1))
    return out


def _after_cut(soup):
    """Узлы после заголовка «Горячие предложения в …» (боковой блок с другими городами) — их пропускаем."""
    cut = soup.find(string=re.compile(r"Горячие предложения в"))
    if cut is None:
        return set()
    try:
        return set(id(x) for x in cut.find_all_next())
    except Exception:  # noqa: BLE001
        return set()


def _max_container(a):
    """Самый большой контейнер вокруг якоря, внутри которого только одно объявление."""
    m = SHOW_ID.search(a.get("href", ""))
    if not m:
        return None
    cid = m.group(1)
    node = a
    for _ in range(14):
        par = node.parent
        if par is None or par.name in ("body", "html", "[document]"):
            break
        if _ids_in(par) - {cid}:
            break
        node = par
    return node


def parse_page(html, city_name="Актау", diag=None):
    """HTML страницы выдачи -> (карточки, soup). Сначала контейнеры карточек (data-product-id / a-card),
    затем запасной разбор по якорям. Проблемные карточки (до 3) кладёт в diag['bad'] целиком с извлечённым текстом."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml") if _has_lxml() else BeautifulSoup(html, "html.parser")
    after = _after_cut(soup)
    bad = []

    page_ids = set()
    for a in soup.select('a[href*="/a/show/"]'):
        if id(a) in after:
            continue
        m = SHOW_ID.search(a.get("href", ""))
        if m:
            page_ids.add(int(m.group(1)))

    cards = {}

    def take(node, cid):
        if cid in cards or id(node) in after:
            return
        lns = lines_of(node.get_text("\n", strip=True))
        item = parse_card_lines(lns, city_name)
        if not item:
            if len(bad) < 3:
                bad.append({"id": cid, "why": "no_title_or_price", "lines": lns[:40], "html": str(node)[:6000]})
            return
        ok = item.pop("_city_ok", False)
        item.pop("_id", None)
        if not ok and item.get("m") is None:
            if len(bad) < 3:
                bad.append({"id": cid, "why": "no_city_no_mkr", "lines": lns[:40], "html": str(node)[:6000]})
            return  # ни города, ни микрорайона — скорее всего чужая карточка
        item["id"] = cid
        cards[cid] = item

    def card_id(node):
        v = node.get("data-product-id") or node.get("data-id") or ""
        if str(v).isdigit():
            return int(v)
        a = node.select_one('a[href*="/a/show/"]')
        m = SHOW_ID.search(a.get("href", "")) if a else None
        return int(m.group(1)) if m else None

    for node in soup.select("[data-product-id], div.a-card[data-id], article.a-card, [class*=a-card][data-id]"):
        if not node.select_one('a[href*="/a/show/"]'):
            continue
        cid = card_id(node)
        if cid is not None:
            take(node, cid)

    if page_ids and len(cards) < 0.6 * len(page_ids):
        for a in soup.select('a[href*="/a/show/"]'):
            m = SHOW_ID.search(a.get("href", ""))
            if not m or id(a) in after:
                continue
            cid = int(m.group(1))
            if cid in cards:
                continue
            node = _max_container(a)
            if node is not None:
                take(node, cid)

    if diag is not None:
        diag.update({"anchors": len(page_ids), "parsed": len(cards), "html_len": len(html),
                     "a_card_nodes": len(soup.select("[class*=a-card]")), "cut": bool(after),
                     "product_nodes": len(soup.select("[data-product-id]")), "bad": bad})
    return list(cards.values()), soup


def _has_lxml():
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


def found_total(soup):
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"Найдено\s+([\d\s ]+?)\s+объявлен", txt)
    if m:
        return int(re.sub(r"\D", "", m.group(1)) or 0)
    return None


# --------------------------------------------------------------------------
#  Сеть
# --------------------------------------------------------------------------

def make_session():
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
    })
    return s


def fetch(sess, url, params=None, retries=3):
    last = None
    for attempt in range(retries):
        try:
            r = sess.get(url, params=params, timeout=40)
            if r.status_code in (403, 429):
                last = "HTTP %s" % r.status_code
                time.sleep(8 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last = "HTTP %s" % r.status_code
                time.sleep(4 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last = str(e)[:200]
            time.sleep(3 * (attempt + 1))
    raise Blocked("не удалось получить %s: %s" % (url, last))


# --------------------------------------------------------------------------
#  Сбор и слияние с прошлым снимком
# --------------------------------------------------------------------------

DIAG = {"samples": [], "pages": []}


def scrape(cfg, log=print):
    EXCL = exclude_patterns(cfg)
    sess = make_session()
    found = {}
    pages_total = 0
    for rooms in cfg["rooms"]:
        page = 1
        expected_pages = None
        dup_pages = 0
        while page <= cfg["max_pages"]:
            params = {"das[live.rooms]": rooms}
            if page > 1:
                params["page"] = page
            html = fetch(sess, cfg["list_url"], params)
            d = {}
            cards, soup = parse_page(html, cfg["city_name"], d)
            pages_total += 1
            title = (soup.title.string if soup.title and soup.title.string else "")[:70]
            if len(DIAG["pages"]) < 60:
                DIAG["pages"].append([rooms, page, d.get("anchors"), d.get("parsed"), d.get("a_card_nodes"), d.get("html_len"), d.get("product_nodes"), title])
            if page == 1:
                total = found_total(soup)
                if total:
                    expected_pages = int(math.ceil(total / 20.0)) + 1
                log("rooms=%s: найдено на сайте %s, страниц ~%s, разобрано карточек %s из %s" % (
                    rooms, total, expected_pages, d.get("parsed"), d.get("anchors")))
                for b in d.get("bad", []):
                    DIAG["samples"].append(("bad_card_%s_%s" % (rooms, b["id"]),
                                            "<!-- причина: %s -->\n<!-- извлечённые строки:\n%s\n-->\n%s" % (
                                                b["why"], "\n".join(b["lines"]).replace("-->", "--"), b["html"])))
                if cards:
                    DIAG["samples"].append(("first_parsed_%s" % rooms, json.dumps(cards[0], ensure_ascii=False, indent=1)))
                else:
                    body = html[html.find("<body"):] if "<body" in html else html
                    DIAG["samples"].append(("page_without_cards", body[:7000]))
                    raise Blocked("первая страница без карточек (title=%r, якорей %s, a-card %s, длина %s) — блокировка или смена вёрстки" % (
                        title, d.get("anchors"), d.get("a_card_nodes"), d.get("html_len")))
            if not cards:
                break
            new = [c for c in cards if c["id"] not in found]
            for c in new:
                if is_excluded(c, EXCL):
                    DIAG["excluded"] = DIAG.get("excluded", 0) + 1
                    continue
                found[c["id"]] = c
            if page > 1 and not new:
                dup_pages += 1
                if dup_pages >= 2:
                    break
            else:
                dup_pages = 0
            if expected_pages and page >= expected_pages:
                break
            page += 1
            time.sleep(random.uniform(cfg["delay_min"], cfg["delay_max"]))
        log("rooms=%s: всего собрано %d объявлений" % (rooms, len(found)))
    return found, pages_total


def today_str(now=None):
    return (now or datetime.now(TZ)).strftime("%Y-%m-%d")


def merge(prev_data, found, cfg, now=None):
    """Слияние текущего сбора с прошлым снимком: first_seen, история цен, счётчик пропусков."""
    now = now or datetime.now(TZ)
    today = today_str(now)
    prev = {}
    if prev_data and not prev_data.get("sample"):
        prev = {l["id"]: l for l in prev_data.get("listings", [])}

    out = []
    n_new = 0
    for cid, c in found.items():
        p = prev.get(cid)
        rec = dict(c)
        rec["id"] = cid
        rec["fs"] = p["fs"] if p else today
        rec["ms"] = 0
        ph = list(p.get("ph", [])) if p else []
        if not ph:
            ph = [[rec["fs"], rec["p"]]]
        elif ph[-1][1] != rec["p"]:
            ph.append([today, rec["p"]])
        rec["ph"] = ph[-8:]
        if p is None:
            n_new += 1
        if p and p.get("dd"):
            rec["dd"] = p["dd"]
        out.append(rec)

    keep = cfg["keep_missing_runs"]
    for cid, p in prev.items():
        if cid in found:
            continue
        ms = p.get("ms", 0) + 1
        if ms < keep:
            q = fix_record(dict(p))
            if is_excluded(q, exclude_patterns(cfg)):
                continue
            q["ms"] = ms
            out.append(q)

    # компактность: у «обычных» объявлений описание короткое
    for rec in out:
        limit = 110 if rec.get("cl") == "renovated" else 300
        if rec.get("ds") and len(rec["ds"]) > limit:
            rec["ds"] = rec["ds"][:limit].rstrip() + "…"

    out.sort(key=lambda r: (r.get("fs", ""), r["id"]), reverse=True)
    # base — день самого первого снимка: у его объявлений «первая находка» одна, и «свежие» там считаются по дате на крыше
    base = prev_data.get("base") if prev and prev_data else None
    if not base:
        base = min([l["fs"] for l in prev.values() if l.get("fs")] or [today])
    data = {
        "base": base,
        "updated": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "today": today,
        "city": cfg["city_name"],
        "rooms": cfg["rooms"],
        "count": len(out),
        "new_today": sum(1 for r in out if r.get("fs") == today and r.get("ms", 0) == 0),
        "listings": out,
    }
    return data, n_new


def write_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def fetch_details(cfg, data, log=print):
    """Необязательно: докачать полное описание для «unknown» в выбранных мкр."""
    from bs4 import BeautifulSoup
    sess = make_session()
    done = 0
    for rec in data["listings"]:
        if done >= cfg["detail_max_per_run"]:
            break
        if rec.get("cl") != "unknown" or rec.get("dd") or rec.get("ms", 0):
            continue
        if cfg["detail_mkr"] and rec.get("m") not in cfg["detail_mkr"]:
            continue
        try:
            html = fetch(sess, "https://krisha.kz/a/show/%s" % rec["id"], retries=1)
        except Blocked:
            log("detail: остановка (блок), обработано %d" % done)
            break
        soup = BeautifulSoup(html, "html.parser")
        node = (soup.select_one(".offer__description") or soup.select_one("[itemprop=description]")
                or soup.select_one(".a-text"))
        text = node.get_text(" ", strip=True) if node else ""
        if not text:
            meta = soup.find("meta", attrs={"name": "description"})
            text = meta.get("content", "") if meta else ""
        rec["dd"] = 1
        done += 1
        if text:
            full = norm_ws(text)
            cls = classify(rec.get("st"), full)
            if cls in ("draft", "likely"):
                rec["cl"] = "likely"
                rec["ds"] = full[:300]
            elif cls == "renovated":
                rec["cl"] = "renovated"
        time.sleep(random.uniform(cfg["delay_min"], cfg["delay_max"]))
    log("detail: обработано %d" % done)


def write_debug(dbg):
    dbg.mkdir(parents=True, exist_ok=True)
    for old in dbg.glob("*"):
        if old.is_file():
            old.unlink()
    for i, (kind, body) in enumerate(DIAG["samples"]):
        ext = "json" if kind.startswith("first_parsed") else "html"
        (dbg / ("%d_%s.%s" % (i, kind, ext))).write_text(body, encoding="utf-8")
    (dbg / "pages.json").write_text(json.dumps(DIAG["pages"], ensure_ascii=False), encoding="utf-8")


def reprocess(out, cfg, log=print):
    """Без сети: пересчитать мкр и убрать исключённые ЖК в уже собранном data.json."""
    data = load_json(out / "data.json")
    if not data or not data.get("listings"):
        raise SystemExit("нет data.json для переобработки")
    pats = exclude_patterns(cfg)
    kept, n_ex, n_fix = [], 0, 0
    for rec in data["listings"]:
        before = rec.get("m")
        fix_record(rec)
        if is_excluded(rec, pats):
            n_ex += 1
            continue
        if rec.get("m") != before:
            n_fix += 1
        kept.append(rec)
    data["listings"] = kept
    if not data.get("base"):
        data["base"] = min([l["fs"] for l in kept if l.get("fs")] or [data.get("today")])
    data["count"] = len(kept)
    data["new_today"] = sum(1 for r in kept if r.get("fs") == data.get("today") and not r.get("ms"))
    write_json(out / "data.json", data)
    st = load_json(out / "status.json") or {}
    st["excluded"] = st.get("excluded", 0) + n_ex  # накопительно: прошлые убранные + эти
    write_json(out / "status.json", st)
    log("Переобработка: убрано ЖК из списка исключений %d, исправлен мкр у %d, осталось %d" % (n_ex, n_fix, len(kept)))
    return n_ex, n_fix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT), help="куда писать data.json/status.json")
    ap.add_argument("--debug-dir", default=str(ROOT / "debug"))
    ap.add_argument("--reprocess", action="store_true",
                    help="без сети: заново применить правила (мкр, исключённые ЖК) к текущему data.json")
    args = ap.parse_args()

    cfg = dict(DEFAULT_CFG)
    cfg.update(load_json(ROOT / "config.json") or {})
    out = Path(args.out)
    if args.reprocess:
        reprocess(out, cfg)
        return
    dbg = Path(args.debug_dir)
    now = datetime.now(TZ)
    status = {"ok": False, "time": now.strftime("%Y-%m-%dT%H:%M:%S%z")}

    prev = load_json(out / "data.json")
    try:
        found, pages = scrape(cfg)
    except Blocked as e:
        status["error"] = str(e)
        write_json(out / "status.json", status)
        write_debug(dbg)
        print("ОШИБКА: %s" % e, file=sys.stderr)
        sys.exit(2)
    write_debug(dbg)

    prev_real = prev if prev and not prev.get("sample") else None
    if prev_real:
        prev_active = sum(1 for l in prev_real["listings"] if not l.get("ms"))
        if prev_active and len(found) < prev_active * cfg["min_ratio_to_prev"]:
            status["error"] = "собрано %d при прошлых %d — подозрительно мало, снимок не обновлён" % (
                len(found), prev_active)
            write_json(out / "status.json", status)
            print("ОШИБКА: " + status["error"], file=sys.stderr)
            sys.exit(3)

    data, n_new = merge(prev, found, cfg, now)
    if cfg.get("detail_fetch"):
        fetch_details(cfg, data)

    write_json(out / "data.json", data)
    status.update({"ok": True, "pages": pages, "listings": len(found), "new": n_new,
                   "excluded": DIAG.get("excluded", 0)})
    write_json(out / "status.json", status)
    draft = sum(1 for l in data["listings"] if l["cl"] in ("draft", "likely") and not l.get("ms"))
    print("Готово: %d объявлений, новых %d, черновых/вероятных %d" % (len(found), n_new, draft))


if __name__ == "__main__":
    main()
