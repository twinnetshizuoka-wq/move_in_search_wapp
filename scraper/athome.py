"""アットホーム一覧ページから物件情報を取得する。"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

import pandas as pd
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError
from rental_files import RentalFileError, parse_athome_list_url
from scraper.config import CHINTAI_CONFIG, AtHomeScraperConfig

CSV_COLUMNS = [
    "property_name",
    "address",
    "access",
    "room_number",
    "features",
    "source_url",
    "fetched_at",
]

DEFAULT_DATA_DIR = Path("data")
ATHOME_TOP_URL = CHINTAI_CONFIG.top_url
JST = timezone(timedelta(hours=9))

_active_config: AtHomeScraperConfig = CHINTAI_CONFIG


def set_scraper_config(config: AtHomeScraperConfig) -> None:
    """取得種別（賃貸・購入）の設定を切り替える。"""
    global _active_config
    _active_config = config


def get_scraper_config() -> AtHomeScraperConfig:
    """現在の取得設定を返す。"""
    return _active_config


def _detail_links_locator(scope: Locator | Page) -> Locator:
    """設定に応じた詳細リンクの locator を返す。"""
    selector = ", ".join(
        f'a[href*="{fragment}"]'
        for fragment in _active_config.detail_link_href_substrings
    )
    return scope.locator(selector)
ROOM_NUMBER_MAX_LENGTH = 40
ROOM_NUMBER_DASHES = frozenset({"－", "-", "―", "—"})
ROOM_NUMBER_REJECT_KEYWORDS = (
    "万円",
    "詳細",
    "お気に入り",
    "画像を見る",
    "人気の設備",
    "駐車場",
    "ペット相談",
    "即入居可",
)
ROOM_COLUMN_HEADER_KEYWORDS = ("部屋番号", "階数", "号室", "階数番号", "階数/号室")
# 部屋番号に使われる漢字（方角・号室・漢数字・階棟など）
ROOM_KANJI_ALLOWED = frozenset(
    "東西南北号室"
    "一二三四五六七八九"
    "壱弐参叁肆伍陸柒捌玖"
    "階棟建物全部"
    "部分"  # メゾネット1階～2階部分 など
)
# 部屋番号らしさ（数字・英字・方角・漢数字・号室 など）
ROOM_CONTENT_PATTERN = re.compile(
    r"(?:"
    r"[0-9０-９]{1,6}"
    r"|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴ]"
    r"|[A-Za-zＡ-Ｚａ-ｚ]"
    r"|[東西南北号室一二三四五六七八九壱弐参叁肆伍陸柒捌玖部分]"
    r"|階|棟|建物|全部|メゾネット|メゾネ"
    r"|[－\-―—~～・（）()]"
    r")"
)
NOT_ROOM_PATTERN = re.compile(
    r"万円|円|敷金|礼金|管理費|バス・トイレ|トイレ別"
)
INVALID_ROOM_LABEL_PATTERN = re.compile(
    r"^[0-9０-９]+人$"  # 1人, ２人（入居人数のみ）
    r"|人以下$"
    r"|名$"
)
OCCUPANCY_PREFIX_PATTERN = re.compile(r"^[0-9０-９]+人")
LAYOUT_PATTERN = re.compile(
    r"^(\d+\.?\d*万?円)$"
    r"|^\d*[KＫDKSLdk]+$"
    r"|^ワンルーム$"
    r"|^\d+LDK$"
    r"|^\d+SDK$"
    r"|^\d+SLDK$"
    r"|^\d+\.?\d*m²?$"
    r"|^\d+\.?\d*㎡$"
)
LAYOUT_AREA_INFIX_PATTERN = re.compile(
    r"\d+LDK|\d+SDK|\d+SLDK|\d+DK"
    r"|ワンルーム"
    r"|m²|㎡|m2"
)
ADDRESS_HINT_PATTERN = re.compile(r"[都道府県市区郡町村丁目]")
CHOME_PATTERN = re.compile(r"^(.+?[0-9０-９]+丁目)")
WARD_PATTERN = re.compile(
    r"^([\u4e00-\u9fff\d０-９\-－]+[都道府県][\u4e00-\u9fff\d０-９\-－]*[市区郡町村][\u4e00-\u9fff\d０-９\-－]*)"
)
CITY_PATTERN = re.compile(
    r"^([\u4e00-\u9fff\d０-９]+[市区町村郡][\u4e00-\u9fff\d０-９\-－]*)"
)
TRANSIT_SPLIT_PATTERN = re.compile(
    r"\s+(?:[Ｊ都]|徒歩|[0-9０-９]+\.?[0-9０-９]*万円|賃貸|築|【)"
)

CARD_CONTAINER_SELECTOR = (
    "xpath=ancestor::*[(self::div or self::section or self::article or self::li)"
    " and (.//h2 or .//h3)][1]"
)
KOUNYU_CARD_SELECTORS = (
    "xpath=ancestor::*[(self::div or self::li or self::section or self::article)"
    " and contains(., '所在地')][1]",
    "xpath=ancestor::*[(self::div or self::li or self::section or self::article)"
    " and contains(., '交通')][1]",
    "xpath=ancestor::li[contains(@class,'cassette') or contains(@class,'item')][1]",
    "xpath=ancestor::div[contains(@class,'cassette')][1]",
    "xpath=ancestor::li[1]",
)
KOUNYU_CARD_MAX_TEXT_LENGTH = 8000
MAX_LABEL_SCAN_ELEMENTS = 40
KOUNYU_PAGE_HEADING_PATTERN = re.compile(r"の不動産|件表示|該当物件|不動産購入情報")
CAPTCHA_HEADING_KEYWORDS = ("認証にご協力", "CAPTCHA", "ロボット")


class ScrapeError(Exception):
    """スクレイピング処理に関するエラー"""


def now_jst_iso() -> str:
    """現在時刻を JST の ISO 8601 形式で返す。"""
    return datetime.now(JST).isoformat(timespec="seconds")


def clean_text(text: str) -> str:
    """テキストの前後空白と連続空白を正規化する。"""
    return re.sub(r"\s+", " ", (text or "")).strip()


def is_detail_url(href: str) -> bool:
    """物件詳細ページの URL かどうかを判定する。"""
    if not href or "/list/" in href:
        return False
    return bool(_active_config.detail_url_pattern.search(href))


def normalize_source_url(href: str) -> str:
    """重複判定用に URL を正規化する。"""
    return href.split("#")[0].split("?")[0]


def extract_address(text: str) -> str:
    """住所文字列から主要部分を抽出する。"""
    value = clean_text(text)
    if not value:
        return ""

    without_transit = TRANSIT_SPLIT_PATTERN.split(value)[0]
    chome_match = CHOME_PATTERN.match(without_transit)
    if chome_match:
        return clean_text(chome_match.group(1))

    ward_match = WARD_PATTERN.match(without_transit)
    if ward_match:
        return clean_text(ward_match.group(1))

    city_match = CITY_PATTERN.match(without_transit)
    if city_match:
        return clean_text(city_match.group(1))

    return clean_text(without_transit)


def strip_property_name_prefix(text: str, property_name: str) -> str:
    """住所行に物件名が含まれている場合は除去する。"""
    value = clean_text(text)
    if property_name and value.startswith(property_name):
        return clean_text(value[len(property_name) :])
    return value


def extract_address_from_line(text: str, property_name: str = "") -> str:
    """物件カード内の住所行から住所部分だけを抽出する。"""
    value = strip_property_name_prefix(text, property_name)
    return extract_address(value)


def normalize_features(text: str) -> str:
    """特徴文字列を正規化する（例: 賃貸マンション 2階建 → 賃貸マンション2階建）。"""
    return re.sub(r"\s+", "", clean_text(text))


FLOOR_BUILDING_SUFFIX_PATTERN = re.compile(
    r"[\s　]*(?:\d+|[０-９]+)階建\s*$|[\s　]*平屋建\s*$"
)


def strip_floor_building_suffix(name: str) -> str:
    """物件名末尾の「〇階建」「平屋建」を除去する。"""
    value = clean_text(name)
    if not value:
        return ""
    return clean_text(FLOOR_BUILDING_SUFFIX_PATTERN.sub("", value))


def extract_features_from_text(text: str) -> str:
    """テキストから物件の特徴（建物種別など）を抽出する。"""
    match = _active_config.feature_pattern.search(text)
    if not match:
        return ""
    return normalize_features(match.group(1))


def _is_layout_or_fee(value: str) -> bool:
    """間取り・家賃・面積など部屋番号ではない文字列か。"""
    if LAYOUT_PATTERN.match(value):
        return True
    if LAYOUT_AREA_INFIX_PATTERN.search(value):
        return True
    if re.match(r"^\d+ヶ月$", value):
        return True
    if value in {"なし"}:
        return True
    return False


def _has_disallowed_kanji(value: str) -> bool:
    """部屋番号として想定外の漢字が含まれるか。"""
    for char in value:
        if "\u4e00" <= char <= "\u9fff" and char not in ROOM_KANJI_ALLOWED:
            return True
    return False


def _is_valid_room_number(value: str) -> bool:
    """部屋番号として有効な文字列かどうか。"""
    if not value:
        return False
    if value in ROOM_NUMBER_DASHES:
        return True
    if len(value) > ROOM_NUMBER_MAX_LENGTH:
        return False
    if INVALID_ROOM_LABEL_PATTERN.match(value):
        return False
    if any(keyword in value for keyword in ROOM_NUMBER_REJECT_KEYWORDS):
        return False
    if NOT_ROOM_PATTERN.search(value):
        return False
    if _is_layout_or_fee(value):
        return False
    if _has_disallowed_kanji(value):
        return False
    if not ROOM_CONTENT_PATTERN.search(value):
        return False
    return True


def _room_number_score(value: str) -> int:
    """部屋番号候補の信頼度スコア（高いほど部屋番号らしい）。"""
    if value in ROOM_NUMBER_DASHES:
        return 50
    score = 0
    if re.search(r"[東西南北]", value):
        score += 14
    if "号室" in value:
        score += 12
    if re.search(r"[棟]", value):
        score += 20
    if re.search(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]", value):
        score += 15
    if re.match(r"^[0-9０-９]{3,6}$", value):
        score += 12
    if re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", value) and re.search(r"[0-9０-９]", value):
        score += 10
    if re.search(r"[一二三四五六七八九壱弐参叁肆伍陸柒捌玖]", value) and re.search(
        r"[0-9０-９階号室棟]", value
    ):
        score += 10
    if re.search(r"階", value):
        score += 8
    if "メゾネ" in value or "部分" in value:
        score += 16
    if re.match(r"^[A-Za-zＡ-Ｚａ-ｚ]$", value):
        score += 6
    if re.match(r"^[0-9０-９]{1,2}$", value):
        score += 3
    return score + min(len(value), 10)


def _room_number_variants(raw: str) -> list[str]:
    """部屋番号候補の表記ゆれ（入居人数の前置きなど）を展開する。"""
    value = clean_text(raw)
    if not value:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def add_variant(candidate: str) -> None:
        candidate = clean_text(candidate)
        if candidate and candidate not in seen:
            seen.add(candidate)
            variants.append(candidate)

    add_variant(value)
    for raw_line in re.split(r"[\n\r\t]+", value):
        add_variant(raw_line)
        for token in re.split(r"\s+", raw_line.strip()):
            add_variant(token)

    occupancy_match = OCCUPANCY_PREFIX_PATTERN.match(value)
    if occupancy_match:
        remainder = clean_text(value[occupancy_match.end() :])
        add_variant(remainder)

    return variants


def _collect_room_number_candidates(text: str) -> list[str]:
    """テキストから部屋番号候補をすべて集める。"""
    candidates: list[str] = []
    seen: set[str] = set()

    for variant in _room_number_variants(text or ""):
        if variant in seen:
            continue
        if _is_valid_room_number(variant):
            seen.add(variant)
            candidates.append(variant)

    return candidates


def _pick_best_room_number(candidates: list[str]) -> str:
    """候補の中から最も部屋番号らしい値を選ぶ。"""
    if not candidates:
        return ""
    unique = list(dict.fromkeys(candidates))
    best = max(unique, key=_room_number_score)
    return "－" if best in ROOM_NUMBER_DASHES else best


def parse_room_number(text: str) -> str:
    """部屋番号・階数らしい文字列を返す。家賃や間取り・入居人数は除外する。"""
    return _pick_best_room_number(_collect_room_number_candidates(text))


def wait_for_page_ready(page: Page, extra_ms: int = 2000) -> None:
    """ページ読み込み完了後、追加で待機する。"""
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(extra_ms)


def wait_for_listings_ready(page: Page, timeout_ms: int = 20000) -> bool:
    """物件一覧の読み込み完了を待つ。"""
    selectors = (
        'a[href*="/mansion/"]',
        'a[href*="/kodate/"]',
        'a[href*="/tochi/"]',
        "text=所在地",
    )
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if is_captcha_page(page):
            return False
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0 and locator.first.is_visible():
                    return True
            except PlaywrightError:
                continue
        page.wait_for_timeout(500)
    return False


def is_captcha_page(page: Page) -> bool:
    """CAPTCHA 画面かどうかを判定する（表示中のもののみ）。"""
    for selector in ("#captcha-box", ".geetest_holder"):
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            if locator.first.is_visible():
                return True
        except PlaywrightError:
            continue
    return False


def is_athome_list_page(page: Page) -> bool:
    """アットホームの物件一覧ページかどうかを判定する。"""
    url = page.url
    if "athome.co.jp" not in url:
        return False
    if not any(prefix in url for prefix in _active_config.list_path_prefixes):
        return False

    if is_captcha_page(page):
        return False

    if "/list/" in url:
        return True

    detail_links = _detail_links_locator(page)
    for index in range(min(detail_links.count(), 30)):
        href = detail_links.nth(index).get_attribute("href") or ""
        if is_detail_url(href):
            return True
    return False


def _is_kounyu_page_heading(text: str) -> bool:
    """一覧ページ全体の見出しかどうか（物件カードではない）。"""
    value = clean_text(text)
    if not value:
        return True
    return bool(KOUNYU_PAGE_HEADING_PATTERN.search(value))


def _is_valid_kounyu_card(card: Locator) -> bool:
    """購入物件の1件分のカード範囲かどうか。"""
    try:
        text = card.inner_text()
    except PlaywrightError:
        return False
    if len(text) > KOUNYU_CARD_MAX_TEXT_LENGTH:
        return False
    return "所在地" in text or "交通" in text


def _get_kounyu_property_card(link: Locator) -> Locator:
    """購入一覧の詳細リンクから、1物件分に絞ったカード範囲を取得する。"""
    for selector in KOUNYU_CARD_SELECTORS:
        card = link.locator(selector)
        if card.count() == 0:
            continue
        candidate = card.first
        if _is_valid_kounyu_card(candidate):
            return candidate

    fallback = link.locator(CARD_CONTAINER_SELECTOR)
    if fallback.count() > 0:
        candidate = fallback.first
        if _is_valid_kounyu_card(candidate):
            return candidate

    for selector in ("xpath=ancestor::li[1]", "xpath=ancestor::div[1]"):
        card = link.locator(selector)
        if card.count() > 0:
            return card.first

    return link


def get_property_card(link: Locator) -> Locator:
    """詳細リンクを含む物件カードの DOM 範囲を取得する。"""
    if _active_config.property_type == "kounyu":
        return _get_kounyu_property_card(link)

    card = link.locator(CARD_CONTAINER_SELECTOR)
    if card.count() > 0:
        return card
    return link.locator("xpath=ancestor::tr[1]")


def card_position_key(card: Locator) -> tuple[int, int] | None:
    """物件カードの画面上位置をキーとして返す。"""
    box = card.bounding_box()
    if box is None:
        return None
    return (round(box["y"]), round(box["x"]))


def find_property_cards(page: Page) -> list[Locator]:
    """ページ内の物件カードを重複なく取得する。"""
    print("  物件カードを検索中...")
    cards = _find_property_cards_from_detail_links(page)
    if cards or _active_config.property_type != "kounyu":
        print(f"  物件カード {len(cards)} 件を検出")
        return cards
    cards = _find_property_cards_from_headings(page)
    print(f"  物件カード {len(cards)} 件を検出")
    return cards


def _find_property_cards_from_detail_links(page: Page) -> list[Locator]:
    """詳細リンクから物件カードを取得する。"""
    cards: list[Locator] = []
    seen_positions: set[tuple[int, int]] = set()
    seen_urls: set[str] = set()

    detail_links = _detail_links_locator(page)
    for index in range(detail_links.count()):
        link = detail_links.nth(index)
        href = link.get_attribute("href") or ""
        if not is_detail_url(href):
            continue

        if _active_config.property_type == "kounyu":
            source_url = normalize_source_url(href)
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)

        try:
            card = get_property_card(link)
            if _active_config.property_type == "kounyu" and not _is_valid_kounyu_card(card):
                continue
            position = card_position_key(card)
            if position is None or position in seen_positions:
                continue
            seen_positions.add(position)
            cards.append(card)
        except PlaywrightError:
            continue

    return cards


def _is_property_heading_text(text: str) -> bool:
    """物件名見出しとして妥当なテキストか。"""
    value = clean_text(text)
    if not value or len(value) < 3:
        return False
    return not any(keyword in value for keyword in CAPTCHA_HEADING_KEYWORDS)


def _find_property_cards_from_headings(page: Page) -> list[Locator]:
    """見出し（h2/h3）から物件カードを取得する（buyall 一覧向け）。"""
    cards: list[Locator] = []
    seen_positions: set[tuple[int, int]] = set()

    headings = page.locator("h2, h3")
    for index in range(headings.count()):
        heading = headings.nth(index)
        heading_text = clean_text(heading.inner_text())
        if not _is_property_heading_text(heading_text):
            continue
        if _active_config.property_type == "kounyu" and _is_kounyu_page_heading(heading_text):
            continue

        card = heading.locator(CARD_CONTAINER_SELECTOR)
        if card.count() == 0:
            continue
        if _active_config.property_type == "kounyu" and not _is_valid_kounyu_card(card.first):
            continue

        position = card_position_key(card)
        if position is None or position in seen_positions:
            continue
        seen_positions.add(position)
        cards.append(card)

    return cards


def extract_labeled_field(card: Locator, label: str) -> str:
    """物件カード内のラベル付き項目（所在地・交通など）を取得する。"""
    rows = card.locator("tr")
    for index in range(min(rows.count(), 30)):
        row = rows.nth(index)
        headers = row.locator("th, dt")
        values = row.locator("td, dd")
        if headers.count() == 0 or values.count() == 0:
            continue
        header_text = clean_text(headers.first.inner_text())
        if header_text != label and not header_text.startswith(label):
            continue
        return clean_text(values.first.inner_text())

    for selector in ("dt", "th"):
        elements = card.locator(selector)
        for index in range(min(elements.count(), MAX_LABEL_SCAN_ELEMENTS)):
            element = elements.nth(index)
            text = clean_text(element.inner_text())
            if text != label:
                continue
            sibling = element.locator("xpath=following-sibling::*[1]")
            if sibling.count() > 0:
                return clean_text(sibling.first.inner_text())

    return ""


def find_first_detail_link_in_card(card: Locator) -> Locator | None:
    """物件カード内の最初の詳細リンクを取得する。"""
    links = _detail_links_locator(card)
    for index in range(links.count()):
        link = links.nth(index)
        try:
            href = link.get_attribute("href") or ""
            if is_detail_url(href):
                return link
        except PlaywrightError:
            continue

    for selector in ("h2 a", "h3 a"):
        heading_link = card.locator(selector).first
        if heading_link.count() == 0:
            continue
        href = heading_link.get_attribute("href") or ""
        if is_detail_url(href):
            return heading_link

    return None


def extract_kounyu_listings_from_card(card: Locator, fetched_at: str) -> list[dict[str, str]]:
    """購入物件カード1件から物件情報を抽出する。"""
    property_name = extract_property_name(card)
    if not property_name:
        return []

    address = extract_labeled_field(card, "所在地")
    if not address:
        address = extract_address_from_card(card, property_name)

    access = extract_labeled_field(card, "交通")
    features = extract_features_from_text(property_name)
    if not features:
        try:
            features = extract_features_from_text(card.inner_text()[:800])
        except PlaywrightError:
            features = ""
    detail_link = find_first_detail_link_in_card(card)
    source_url = ""
    if detail_link is not None:
        href = detail_link.get_attribute("href") or ""
        if is_detail_url(href):
            source_url = normalize_source_url(href)

    return [
        {
            "property_name": property_name,
            "address": address,
            "access": access,
            "room_number": "",
            "features": features,
            "source_url": source_url,
            "fetched_at": fetched_at,
        }
    ]


def _extract_kounyu_property_name(card: Locator) -> str:
    """購入一覧カードから物件名を取得する（見出しタグがない場合のフォールバック）。"""
    for selector in (
        '[class*="title"] a',
        '[class*="title"]',
        "h2 a",
        "h3 a",
        "h2",
        "h3",
    ):
        element = card.locator(selector).first
        if element.count() == 0:
            continue
        text = clean_text(element.inner_text())
        if text and len(text) >= 3 and not _is_kounyu_page_heading(text):
            return text

    try:
        for line in card.inner_text().splitlines():
            value = clean_text(line)
            if not value or len(value) < 3:
                continue
            if _is_kounyu_page_heading(value):
                continue
            if re.match(r"^\d+万円", value):
                continue
            if value in {"詳細をみる", "お気に入り", "物件を閉じる", "物件を開く"}:
                continue
            return value
    except PlaywrightError:
        pass
    return ""


def extract_property_name(card: Locator) -> str:
    """物件カードから物件名を取得する。"""
    heading = card.locator("h2, h3").first
    if heading.count() > 0:
        name = clean_text(heading.inner_text())
        if name and not (
            _active_config.property_type == "kounyu" and _is_kounyu_page_heading(name)
        ):
            return strip_floor_building_suffix(name)

    if _active_config.property_type == "kounyu":
        return strip_floor_building_suffix(_extract_kounyu_property_name(card))
    return ""


def _is_likely_address(text: str, property_name: str) -> bool:
    """住所らしい短いテキストかどうか。"""
    if not text or text == property_name:
        return False
    if "万円" in text or "賃貸" in text or len(text) > 40:
        return False
    return bool(ADDRESS_HINT_PATTERN.search(text))


def extract_address_from_card(card: Locator, property_name: str) -> str:
    """物件カードから住所を取得する。"""
    address_candidates = card.locator(
        '[class*="address"], [class*="location"], p, span, li, dd, div'
    )
    for index in range(min(address_candidates.count(), 60)):
        text = clean_text(address_candidates.nth(index).inner_text())
        if not _is_likely_address(text, property_name):
            continue
        address = extract_address_from_line(text, property_name)
        if address and address != property_name:
            return address
    return ""


def extract_features_from_card(card: Locator) -> str:
    """物件カードから特徴（建物種別など）を取得する。"""
    candidates = card.locator("p, span, li, dd, div")
    for index in range(candidates.count()):
        text = clean_text(candidates.nth(index).inner_text())
        features = extract_features_from_text(text)
        if features:
            return features
    return ""


def locator_position_key(locator: Locator) -> tuple[int, int, int]:
    """要素の画面上位置を重複判定用キーとして返す。"""
    box = locator.bounding_box()
    if box is None:
        return (0, 0, 0)
    return (round(box["y"]), round(box["x"]), round(box.get("height", 0)))


def find_room_column_index(table: Locator) -> int | None:
    """部屋番号・階の列インデックスを取得する。"""
    rows = table.locator("tr")
    for row_index in range(min(rows.count(), 4)):
        row = rows.nth(row_index)
        cells = row.locator("th, td")
        for col_index in range(cells.count()):
            header_text = clean_text(cells.nth(col_index).inner_text())
            if any(keyword in header_text for keyword in ROOM_COLUMN_HEADER_KEYWORDS):
                return col_index
            if header_text in {"階", "階数"}:
                return col_index
    return None


def _is_header_row(row: Locator) -> bool:
    """テーブルのヘッダー行かどうか。"""
    return row.locator("th").count() > 0 and row.locator("td").count() == 0


def find_detail_link_in_row(row: Locator) -> Locator | None:
    """部屋行から物件詳細リンクを取得する。"""
    links = _detail_links_locator(row)
    for index in range(links.count()):
        link = links.nth(index)
        href = link.get_attribute("href") or ""
        if is_detail_url(href):
            return link
    return None


def find_room_rows_in_card(card: Locator) -> list[Locator]:
    """物件カード内の部屋行（1部屋＝1行）を取得する。"""
    rows: list[Locator] = []
    seen_positions: set[tuple[int, int, int]] = set()

    table_rows = card.locator("tr")
    for index in range(table_rows.count()):
        row = table_rows.nth(index)
        if _is_header_row(row):
            continue
        if find_detail_link_in_row(row) is None:
            continue
        position = locator_position_key(row)
        if position in seen_positions:
            continue
        seen_positions.add(position)
        rows.append(row)

    if rows:
        return rows

    row_container_xpaths = (
        "xpath=ancestor::tr[1]",
        "xpath=ancestor::li[1]",
        "xpath=ancestor::*[contains(@class,'room')][1]",
        "xpath=ancestor::*[contains(@class,'unit')][1]",
        "xpath=ancestor::*[contains(@class,'item')][1]",
        "xpath=parent::*",
    )
    detail_links = _detail_links_locator(card)
    for index in range(detail_links.count()):
        link = detail_links.nth(index)
        href = link.get_attribute("href") or ""
        if not is_detail_url(href):
            continue

        for xpath in row_container_xpaths:
            container = link.locator(xpath)
            if container.count() == 0:
                continue
            if container.locator("h2, h3").count() > 0:
                continue
            position = locator_position_key(container)
            if position in seen_positions:
                break
            seen_positions.add(position)
            rows.append(container)
            break

    return rows


ROOM_COLUMN_SELECTORS = (
    '[class*="room"]',
    '[class*="floor"]',
    '[class*="number"]',
    '[class*="heya"]',
    '[class*="kaidate"]',
)


def _extract_room_candidates_from_row_text(row: Locator) -> list[str]:
    """テーブル以外の部屋行から、先頭列相当のテキストを推定する。"""
    candidates: list[str] = []
    try:
        row_text = row.inner_text()
    except PlaywrightError:
        return candidates

    for segment in re.split(r"[\n\r\t]+", row_text):
        segment = clean_text(segment)
        if not segment or "万円" in segment or "詳細" in segment:
            continue
        candidates.extend(_collect_room_number_candidates(segment))
        if candidates:
            return candidates

    return candidates


def _extract_room_candidates_from_row_elements(row: Locator) -> list[str]:
    """部屋行内の短いテキスト要素から部屋番号候補を集める。"""
    candidates: list[str] = []

    for selector in ROOM_COLUMN_SELECTORS:
        scoped = row.locator(selector)
        for index in range(scoped.count()):
            text = clean_text(scoped.nth(index).inner_text())
            if not text or "万円" in text or "詳細" in text:
                continue
            candidates.extend(_collect_room_number_candidates(text))

    if candidates:
        return candidates

    for selector in ("td", "th", "span", "div", "p", "li"):
        for index in range(row.locator(selector).count()):
            element = row.locator(selector).nth(index)
            text = clean_text(element.inner_text())
            if not text or "万円" in text or "詳細" in text or len(text) > 30:
                continue
            found = _collect_room_number_candidates(text)
            if found:
                candidates.extend(found)
                return candidates

    return candidates


def _sanitize_room_column_text(text: str) -> str:
    """部屋番号列のテキストから入居人数などの前置きを除去する。"""
    value = clean_text(text)
    if not value:
        return ""
    value = OCCUPANCY_PREFIX_PATTERN.sub("", value).strip()
    return value


def _collect_room_number_from_cell_text(text: str) -> list[str]:
    """部屋番号列セルのテキストから候補を集める。"""
    candidates = _collect_room_number_candidates(text)
    if candidates:
        return candidates

    sanitized = _sanitize_room_column_text(text)
    if sanitized and _is_valid_room_number(sanitized):
        return [sanitized]
    return []


def _room_column_indices(table: Locator, cells: Locator) -> list[int]:
    """部屋番号列として試す列インデックス（優先順）。"""
    indices: list[int] = []
    room_col_index = find_room_column_index(table)
    if room_col_index is not None:
        indices.append(room_col_index)
    for index in range(min(cells.count(), 4)):
        if index not in indices:
            indices.append(index)
    return indices


def extract_room_number_from_row_container(row: Locator) -> str:
    """部屋行から部屋番号を取得する。

    アットホームでは部屋番号自体が詳細ページへのリンクになっていることが多い。
    入居人数表示（1人など）は除外し、部屋番号列・詳細リンクから取得する。
    """
    candidates: list[str] = []
    used_table_room_column = False

    detail_links = _detail_links_locator(row)
    for index in range(detail_links.count()):
        link = detail_links.nth(index)
        href = link.get_attribute("href") or ""
        if not is_detail_url(href):
            continue
        link_text = clean_text(link.inner_text())
        if "詳細" in link_text:
            continue
        candidates.extend(_collect_room_number_candidates(link_text))

    table = row.locator("xpath=ancestor::table[1]")
    cells = row.locator("td, th")
    if table.count() > 0 and cells.count() > 0:
        used_table_room_column = True
        for col_index in _room_column_indices(table, cells):
            cell_candidates = _collect_room_number_from_cell_text(
                cells.nth(col_index).inner_text()
            )
            if cell_candidates:
                candidates.extend(cell_candidates)
                break

    if candidates or used_table_room_column:
        return _pick_best_room_number(candidates)

    candidates.extend(_extract_room_candidates_from_row_text(row))
    if not candidates:
        candidates.extend(_extract_room_candidates_from_row_elements(row))

    return _pick_best_room_number(candidates)


def extract_listings_from_card(card: Locator, fetched_at: str) -> list[dict[str, str]]:
    """物件カード1件から、部屋行ごとに物件情報を抽出する。"""
    if _active_config.property_type == "kounyu":
        return extract_kounyu_listings_from_card(card, fetched_at)

    property_name = extract_property_name(card)
    if not property_name:
        return []

    address = extract_address_from_card(card, property_name)
    features = extract_features_from_card(card)
    listings: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for row in find_room_rows_in_card(card):
        detail_link = find_detail_link_in_row(row)
        if detail_link is None:
            continue

        href = detail_link.get_attribute("href") or ""
        if not is_detail_url(href):
            continue

        source_url = normalize_source_url(href)
        if source_url in seen_urls:
            continue
        seen_urls.add(source_url)

        listings.append(
            {
                "property_name": property_name,
                "address": address,
                "access": "",
                "room_number": extract_room_number_from_row_container(row),
                "features": features,
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
        )

    return listings


def extract_page_listings(page: Page) -> list[dict[str, str]]:
    """現在ページから物件カード単位で部屋行を抽出する。"""
    fetched_at = now_jst_iso()
    listings: list[dict[str, str]] = []

    cards = find_property_cards(page)
    for index, card in enumerate(cards, start=1):
        if index == 1 or index % 10 == 0 or index == len(cards):
            print(f"  抽出中... {index}/{len(cards)}")
        try:
            card_listings = extract_listings_from_card(card, fetched_at)
            if card_listings:
                listings.extend(card_listings)
        except PlaywrightError:
            continue

    return listings


def listing_dedup_key(item: dict[str, str]) -> tuple[str, str, str, str]:
    """重複判定用キー（物件名・住所・部屋番号・URL）。"""
    return (
        item["property_name"],
        item["address"],
        item["room_number"],
        item["source_url"],
    )


NEXT_PAGE_LABELS = frozenset({">", "＞", "次へ", "次へ>", "次へ＞", "次へ >", "次へ ＞"})
NEXT_PAGE_TEXT_PATTERN = re.compile(r"^次へ\s*[>＞]?$")
BUYALL_LIST_PATH_RE = re.compile(r"/buyall/([^/]+)/list(?:/page(\d+))?/?")

PAGER_SELECTORS = (
    'nav[class*="pager"]',
    'nav[class*="pagination"]',
    'nav[class*="paging"]',
    '[class*="pager"]',
    '[class*="pagination"]',
    '[class*="paging"]',
    '[class*="mod-pager"]',
    '[class*="mod_pager"]',
    "nav",
)


def _get_control_label(candidate: Locator) -> str:
    """リンク/ボタンの表示ラベルを取得する（アイコンのみの場合は aria-label 等）。"""
    text = clean_text(candidate.inner_text())
    if text:
        return text
    for attr in ("aria-label", "title"):
        attr_text = clean_text(candidate.get_attribute(attr) or "")
        if attr_text:
            return attr_text
    return ""


def _matches_next_label(text: str) -> bool:
    """次ページボタンのラベル（> / ＞ / 次へ > など）かどうか。"""
    value = clean_text(text)
    if not value:
        return False
    if value in NEXT_PAGE_LABELS:
        return True
    if re.sub(r"\s+", "", value) in {"次へ>", "次へ＞"}:
        return True
    return bool(NEXT_PAGE_TEXT_PATTERN.match(value))


def _next_label_priority(label: str) -> int:
    """次ページ候補の優先度（小さいほど優先）。"""
    if "次へ" in label:
        return 0
    return 1


def _is_next_control_enabled(candidate: Locator, *, in_pager: bool = False) -> bool:
    """次ページボタンが表示・有効かどうかを確認する。"""
    try:
        if not candidate.is_visible():
            return False
    except PlaywrightError:
        return False

    class_name = (candidate.get_attribute("class") or "").lower()
    if any(token in class_name for token in ("disabled", "inactive", "is-disabled")):
        return False

    if candidate.get_attribute("aria-disabled") == "true":
        return False
    if candidate.get_attribute("disabled") is not None:
        return False

    try:
        if candidate.is_disabled():
            return False
    except PlaywrightError:
        pass

    label = _get_control_label(candidate)
    allow_javascript_href = in_pager or candidate.get_attribute("rel") == "next" or "次へ" in label

    href = candidate.get_attribute("href")
    if href is not None:
        href = href.strip()
        if href.startswith("#"):
            return False
        if not href:
            if not in_pager:
                return False
        elif href.lower().startswith("javascript:") and not allow_javascript_href:
            return False

    return True


def _find_pager_area(page: Page) -> Locator | None:
    """ページ番号と次へボタンを含むページャー領域を探す。"""
    for page_path in (2, 3):
        page_links = page.locator(f'a[href*="/page{page_path}/"]')
        if page_links.count() == 0:
            continue
        link = page_links.first
        for xpath in (
            "xpath=ancestor::nav[1]",
            "xpath=ancestor::ul[1]",
            "xpath=ancestor::*[contains(@class,'pager')][1]",
            "xpath=ancestor::*[contains(@class,'paging')][1]",
            "xpath=ancestor::*[contains(@class,'pagination')][1]",
            "xpath=ancestor::div[.//a[contains(@href,'/page')]][1]",
        ):
            container = link.locator(xpath)
            if container.count() > 0:
                return container.first

    for selector in (
        '[class*="paging"]',
        '[class*="pager"]',
        '[class*="Pager"]',
        '[class*="pagination"]',
        "nav",
    ):
        blocks = page.locator(selector)
        for index in range(blocks.count()):
            block = blocks.nth(index)
            try:
                text = block.inner_text()
            except PlaywrightError:
                continue
            if not re.search(r"\b1\b", text):
                continue
            if "次へ" in text or ">" in text or "＞" in text:
                return block
    return None


def _href_points_to_buyall_list_page(href: str, target_page: int) -> bool:
    """一覧ページのページ番号リンクかどうかを href で判定する。"""
    if not href:
        return False

    value = href.strip()
    if target_page <= 1:
        if re.search(r"/page\d+/", value):
            return False
        return "/list/" in value or "buyall/" in value

    if f"/page{target_page}/" in value or value.rstrip("/").endswith(f"/page{target_page}"):
        return True

    return bool(re.search(rf"(?:^|[?&])q={target_page}(?:&|$)", value))


def _find_next_in_controls(controls: Locator, *, in_pager: bool = False) -> Locator | None:
    """リンク/ボタン群から有効な次ページボタンを探す。"""
    candidates: list[tuple[int, Locator]] = []
    for index in range(controls.count()):
        candidate = controls.nth(index)
        try:
            label = _get_control_label(candidate)
            if not _matches_next_label(label):
                continue
            if not _is_next_control_enabled(candidate, in_pager=in_pager):
                continue
            candidates.append((_next_label_priority(label), candidate))
        except PlaywrightError:
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    best = candidates[0][1]
    best.scroll_into_view_if_needed(timeout=5000)
    return best


def _control_tags_for_pager() -> tuple[str, ...]:
    return ("a", "button", "span", "li", "div")


def find_page_number_link(page: Page, target_page: int) -> Locator | None:
    """ページャー内のページ番号リンク（例: 2, 3）を探す。"""
    pager = _find_pager_area(page)
    if pager is None:
        return None

    target = str(target_page)
    for tag in ("a", "button"):
        controls = pager.locator(tag)
        for index in range(controls.count()):
            candidate = controls.nth(index)
            try:
                if clean_text(candidate.inner_text()) != target:
                    continue
                if not _is_next_control_enabled(candidate, in_pager=True):
                    continue
                href = candidate.get_attribute("href") or ""
                if not _href_points_to_buyall_list_page(href, target_page):
                    continue
                candidate.scroll_into_view_if_needed(timeout=5000)
                return candidate
            except PlaywrightError:
                continue
    return None


def parse_buyall_page_number(url: str) -> int:
    """buyall 一覧 URL からページ番号を取得する（/list/page2/ または q=）。"""
    match = BUYALL_LIST_PATH_RE.search(urlparse(url).path)
    if match and match.group(2):
        return max(1, int(match.group(2)))

    query = parse_qs(urlparse(url).query)
    raw = query.get("q", ["1"])[0]
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def build_buyall_page_url(url: str, page_number: int) -> str:
    """buyall 一覧 URL を指定ページ用に組み立てる（/list/page2/ 形式）。"""
    parsed = urlparse(url)
    match = BUYALL_LIST_PATH_RE.search(parsed.path)
    if not match:
        return url

    prefecture_slug = match.group(1)
    if page_number <= 1:
        new_path = f"/buyall/{prefecture_slug}/list/"
    else:
        new_path = f"/buyall/{prefecture_slug}/list/page{page_number}/"

    query = parsed.query
    if re.search(r"(?:^|[&?])q=\d+", query):
        new_query = re.sub(r"q=\d+", f"q={page_number}", query)
    elif query:
        new_query = f"{query}&q={page_number}"
    else:
        new_query = f"q={page_number}"

    return urlunparse(parsed._replace(path=new_path, query=new_query))


def _buyall_target_page_reached(url: str, target_page: int) -> bool:
    """buyall 一覧 URL が指定ページ以上かどうか。"""
    return parse_buyall_page_number(url) >= target_page


def navigate_buyall_list_page(page: Page, page_number: int) -> bool:
    """buyall 一覧を /list/pageN/ 形式の URL で直接開く。"""
    if "/buyall/" not in page.url or "/list/" not in page.url:
        print("  buyall 一覧 URL ではないため URL 遷移をスキップします", flush=True)
        return False

    if _buyall_target_page_reached(page.url, page_number) and wait_for_listings_ready(page):
        return True

    next_url = build_buyall_page_url(page.url, page_number)
    if (
        parse_buyall_page_number(next_url) <= parse_buyall_page_number(page.url)
        and next_url.split("?", 1)[0] == page.url.split("?", 1)[0]
    ):
        print("  遷移先 URL を生成できませんでした", flush=True)
        return False

    print(f"  URLでページ {page_number} を開きます...", flush=True)
    try:
        page.goto(next_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
    except PlaywrightTimeoutError:
        print("  ページ遷移がタイムアウトしました", flush=True)
        return False
    except PlaywrightError as exc:
        print(f"  ページ遷移に失敗しました: {exc}", flush=True)
        return False

    if is_captcha_page(page):
        wait_for_captcha_cleared(page, page_number=page_number)

    for _ in range(3):
        if is_captcha_page(page):
            wait_for_captcha_cleared(page, page_number=page_number)

        if wait_for_listings_ready(page, timeout_ms=15000):
            if _buyall_target_page_reached(page.url, page_number):
                actual = parse_buyall_page_number(page.url)
                print(f"  ページ {actual} の一覧を確認しました", flush=True)
                return True

        if _buyall_target_page_reached(page.url, page_number) and "/list/" in page.url:
            page.wait_for_timeout(3000)
            if wait_for_listings_ready(page, timeout_ms=10000):
                return True

        page.wait_for_timeout(1500)

    actual = parse_buyall_page_number(page.url)
    print(
        f"  ページ {page_number} の一覧を確認できませんでした（URL上のページ: {actual}）",
        flush=True,
    )
    return False


def _buyall_page_advanced(page: Page, previous_page: int) -> bool:
    """buyall 一覧でページ番号が進んだかどうか。"""
    return parse_buyall_page_number(page.url) > previous_page


def advance_to_next_list_page(page: Page, current_page: int) -> bool:
    """次ページへ進む（buyall は URL 優先 → 次へボタン → ページ番号）。"""
    next_page = current_page + 1
    is_buyall = "/buyall/" in page.url and "/list/" in page.url

    print(f"  ページ {current_page} → {next_page} へ進みます...", flush=True)

    if is_buyall:
        for attempt in range(2):
            if navigate_buyall_list_page(page, next_page):
                return True
            if attempt == 0:
                print("  URL遷移を再試行します...", flush=True)
                page.wait_for_timeout(2000)

    url_before = page.url
    next_button = find_next_page_button(page)
    if next_button is not None and _is_next_control_enabled(next_button, in_pager=True):
        try:
            print("  次ページボタンをクリックします...")
            next_button.scroll_into_view_if_needed(timeout=5000)
            next_button.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            if is_athome_list_page(page) and not is_captcha_page(page):
                if is_buyall:
                    return _buyall_page_advanced(page, current_page)
                return page.url != url_before
        except PlaywrightError:
            pass

    page_link = find_page_number_link(page, next_page)
    if page_link is not None:
        try:
            print(f"  ページャーの {next_page} をクリックします...")
            page_link.scroll_into_view_if_needed(timeout=5000)
            page_link.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            if is_athome_list_page(page) and not is_captcha_page(page):
                if is_buyall:
                    return _buyall_page_advanced(page, current_page)
                return True
        except PlaywrightError:
            pass

    return False


def find_next_page_button(page: Page) -> Locator | None:
    """ページ下部のページャーから次ページボタンを探す。"""
    try:
        page.keyboard.press("End")
        page.wait_for_timeout(500)
    except PlaywrightError:
        pass

    rel_next = page.locator('a[rel="next"]')
    if rel_next.count() > 0:
        candidate = rel_next.first
        if _is_next_control_enabled(candidate, in_pager=True):
            try:
                candidate.scroll_into_view_if_needed(timeout=5000)
            except PlaywrightError:
                pass
            return candidate

    try:
        next_link = page.get_by_role("link", name=re.compile(r"^次へ\s*[>＞]?$"))
        if next_link.count() > 0:
            candidate = next_link.first
            if _is_next_control_enabled(candidate, in_pager=True):
                try:
                    candidate.scroll_into_view_if_needed(timeout=5000)
                except PlaywrightError:
                    pass
                return candidate
    except PlaywrightError:
        pass

    pager = _find_pager_area(page)
    if pager is not None:
        for tag in _control_tags_for_pager():
            found = _find_next_in_controls(pager.locator(tag), in_pager=True)
            if found is not None:
                return found

    for pager_selector in PAGER_SELECTORS:
        pagers = page.locator(pager_selector)
        for pager_index in range(pagers.count()):
            pager = pagers.nth(pager_index)
            for tag in ("a", "button"):
                found = _find_next_in_controls(pager.locator(tag), in_pager=True)
                if found is not None:
                    return found

    for tag in _control_tags_for_pager():
        found = _find_next_in_controls(page.locator(tag))
        if found is not None:
            return found

    return None


def wait_between_pages() -> None:
    """ページ遷移前に 2〜5 秒のランダム待機を入れる。"""
    delay = random.uniform(2, 5)
    print(f"  次ページへ進む前に {delay:.1f} 秒待機します...")
    time.sleep(delay)


def save_listings_csv(listings: list[dict[str, str]], output_path: Path) -> None:
    """取得結果を CSV に保存する。"""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(listings, columns=CSV_COLUMNS)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise ScrapeError(f"CSVの書き込みに失敗しました: {output_path}\n詳細: {exc}") from exc


def save_if_any(listings: list[dict[str, str]], output_csv: Path) -> None:
    """取得済みデータがあれば CSV に保存する。"""
    if listings:
        save_listings_csv(listings, output_csv)


def scrape_current_session(
    page: Page,
    output_csv: Path,
    config: AtHomeScraperConfig | None = None,
) -> list[dict[str, str]]:
    """
    現在表示中の一覧ページから最終ページまで物件を取得する。

    呼び出し前に、ユーザーが一覧ページを表示している必要がある。
    """
    if config is not None:
        set_scraper_config(config)

    print("ページの読み込み完了を待っています...")
    try:
        wait_for_page_ready(page, extra_ms=2000)
    except PlaywrightTimeoutError as exc:
        raise ScrapeError("ページの読み込みがタイムアウトしました。") from exc

    wait_for_captcha_cleared(page)

    if not is_athome_list_page(page):
        raise ScrapeError(
            f"{_active_config.list_page_name}の一覧ページではないようです。\n"
            "アットホームで検索し、物件一覧が表示されていることを確認してください。"
        )

    all_listings: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    page_number = (
        parse_buyall_page_number(page.url)
        if "/buyall/" in page.url and "/list/" in page.url
        else 1
    )

    try:
        while True:
            print(f"\n--- ページ {page_number} を取得中 ---")
            print(f"URL: {page.url}")

            try:
                wait_for_page_ready(page, extra_ms=2000)
            except PlaywrightTimeoutError as exc:
                save_if_any(all_listings, output_csv)
                raise ScrapeError("ページの読み込みがタイムアウトしました。") from exc

            if is_captcha_page(page):
                save_if_any(all_listings, output_csv)
                wait_for_captcha_cleared(page, page_number=page_number)
                if not is_athome_list_page(page):
                    raise ScrapeError(
                        f"認証後も{_active_config.list_page_name}の一覧ページではないようです。\n"
                        "物件一覧ページを表示してから再度お試しください。"
                    )
                continue

            try:
                page_listings = extract_page_listings(page)
            except PlaywrightError as exc:
                save_if_any(all_listings, output_csv)
                raise ScrapeError(
                    "物件情報の取得中にページが遷移しました。\n"
                    "一覧ページが安定して表示されている状態で再度お試しください。"
                ) from exc

            new_count = 0
            for item in page_listings:
                key = listing_dedup_key(item)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_listings.append(item)
                new_count += 1

            print(f"  このページ: {len(page_listings)} 件（新規 {new_count} 件）")
            print(f"  累計: {len(all_listings)} 件")
            save_listings_csv(all_listings, output_csv)
            print(f"  途中保存: {output_csv.resolve()}")

            if new_count == 0 and len(page_listings) > 0 and page_number > 1:
                print("\n新規物件がないため、最終ページまで取得しました。")
                break

            if len(page_listings) == 0:
                print("\n物件が見つからないため、最終ページまで取得しました。")
                break

            wait_between_pages()

            try:
                if not advance_to_next_list_page(page, page_number):
                    print("\n次ページへ進めませんでした。最終ページまで取得しました。")
                    break
                if is_captcha_page(page):
                    save_if_any(all_listings, output_csv)
                    wait_for_captcha_cleared(page, page_number=page_number + 1)
            except PlaywrightTimeoutError as exc:
                save_if_any(all_listings, output_csv)
                raise ScrapeError("次ページへの遷移がタイムアウトしました。") from exc
            except PlaywrightError as exc:
                save_if_any(all_listings, output_csv)
                raise ScrapeError(f"次ページへの遷移に失敗しました: {exc}") from exc

            if "/buyall/" in page.url and "/list/" in page.url:
                next_page_number = parse_buyall_page_number(page.url)
                if next_page_number <= page_number:
                    print(
                        "\nページ番号が進まなかったため、最終ページと判断して終了します。",
                        flush=True,
                    )
                    break
                page_number = next_page_number
            else:
                page_number += 1

    except KeyboardInterrupt:
        save_if_any(all_listings, output_csv)
        print(f"\n中断されました。{len(all_listings)} 件を {output_csv.resolve()} に保存しました。")
        raise
    except ScrapeError:
        raise
    except (PlaywrightError, PlaywrightTimeoutError) as exc:
        save_if_any(all_listings, output_csv)
        raise ScrapeError(f"ブラウザ操作中にエラーが発生しました: {exc}") from exc
    except Exception as exc:
        save_if_any(all_listings, output_csv)
        raise ScrapeError(f"予期しないエラーが発生しました: {exc}") from exc

    return all_listings


def wait_for_captcha_cleared(page: Page, *, page_number: int | None = None) -> None:
    """CAPTCHA 画面のとき、ブラウザを開いたままユーザーの認証完了を待つ。"""
    if not is_captcha_page(page):
        return

    print(flush=True)
    print("=" * 60, flush=True)
    if page_number is not None:
        print(f"【取得を一時停止】ページ {page_number} 付近で CAPTCHA が表示されました", flush=True)
    else:
        print("【取得を一時停止】CAPTCHA 認証が必要です", flush=True)
    print("ブラウザ上で認証（パズル）を完了してください。", flush=True)
    print("認証後に物件一覧が表示されたら、この画面で Enter を押してください。", flush=True)
    print("（止まっているように見えても、Enter 待ちの状態です）", flush=True)
    print("=" * 60, flush=True)

    while is_captcha_page(page):
        try:
            prompt = "認証完了後に Enter を押してください..."
            if page_number is not None:
                prompt = f"ページ {page_number} の取得を再開するには Enter を押してください..."
            input(prompt)
        except EOFError:
            raise ScrapeError("入力が中断されました。") from None

        try:
            wait_for_page_ready(page, extra_ms=2000)
        except PlaywrightTimeoutError:
            pass

        if is_captcha_page(page):
            print(
                "まだ認証画面のようです。\n"
                "ブラウザで認証を完了してから、再度 Enter を押してください。",
                flush=True,
            )

    print("CAPTCHA を確認しました。取得を再開します...", flush=True)


def wait_for_user_start(page: Page) -> None:
    """一覧ページの表示を確認してから取得を開始する。"""
    config = _active_config
    print()
    print("=" * 60)
    print("【操作手順】")
    print(f"1. 表示されたブラウザでアットホームの{config.search_label}を行ってください")
    print("2. 市区町村まで絞り込み、物件一覧ページを表示してください")
    print("3. 一覧が表示されたら、この画面に戻り Enter キーを押してください")
    print("=" * 60)

    while True:
        try:
            input("取得を開始するには Enter キーを押してください...")
        except EOFError:
            raise ScrapeError("入力が中断されました。") from None

        try:
            wait_for_page_ready(page, extra_ms=1000)
        except PlaywrightTimeoutError:
            pass

        if is_captcha_page(page):
            wait_for_captcha_cleared(page)
            continue

        current_url = page.url
        if not is_athome_list_page(page):
            print()
            print(f"{config.list_page_name}の一覧ページが表示されていません。")
            print(f"現在のURL: {current_url}")
            print(
                "ブラウザで市区町村まで絞り込んだ一覧を表示してから、"
                "再度 Enter を押してください。"
            )
            print()
            continue

        try:
            prefecture, city = parse_athome_list_url(
                current_url, property_type=config.filename_type
            )
        except RentalFileError as exc:
            print()
            print(str(exc))
            print("再度 Enter を押してください。")
            print()
            continue

        print()
        print(
            f"一覧ページを確認しました（{prefecture} / {city}）。"
            "取得を開始します..."
        )
        print()
        return
