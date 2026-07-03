"""しずナビ（buy.s-est.co.jp）購入物件一覧の半自動取得。"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from scraper.athome import CSV_COLUMNS, ScrapeError, clean_text, wait_for_page_ready

SHIZUNABI_TOP_URL = "https://buy.s-est.co.jp/"

SHIZUNABI_PROPERTY_TYPES = (
    "house",
    "mansion",
    "newhouse",
    "land",
    "income",
    "business",
)

SHIZUNABI_AREA_LIST_RE = re.compile(
    r"/area/([^/]+)/([^/]+)(?:/page/(\d+))?/?$"
)

SHIZUNABI_LEGACY_LIST_RE = re.compile(
    r"/(" + "|".join(SHIZUNABI_PROPERTY_TYPES) + r")/?$"
)

SHIZUNABI_QUERY_LIST_RE = re.compile(
    r"/(" + "|".join(SHIZUNABI_PROPERTY_TYPES) + r")(?:/page/(\d+))?/?$"
)

SHIZUNABI_AREA_SLUGS: dict[str, str] = {
    "fujishi": "fuji",
    "gotembashi": "gotemba",
    "gotenbashi": "gotemba",
    "shizuokashi": "shizuoka",
    "hamamatsushi": "hamamatsu",
    "numadushi": "numazu",
    "numazushi": "numazu",
    "fujinomiyashi": "fujinomiya",
}

SHIZUNABI_SKIP_HEADING_KEYWORDS = (
    "購入情報",
    "新着情報",
    "不動産購入",
    "メリット",
    "操作手順",
)

JST = timezone(timedelta(hours=9))


def now_jst_iso() -> str:
    """現在時刻を JST の ISO 8601 形式で返す。"""
    return datetime.now(JST).isoformat(timespec="seconds")


def _city_slug_from_area(area_slug: str) -> str:
    slug = area_slug.lower()
    if slug in SHIZUNABI_AREA_SLUGS:
        return SHIZUNABI_AREA_SLUGS[slug]
    for suffix in ("shichosonku", "shi", "ku", "cho", "machi", "gun"):
        if slug.endswith(suffix) and len(slug) > len(suffix):
            return slug[: -len(suffix)]
    return slug


def _extract_area_slugs_from_url(url: str) -> list[str]:
    from urllib.parse import parse_qs

    query = parse_qs(urlparse(url).query)
    areas: list[str] = []
    for key, values in query.items():
        if key == "area" or key.startswith("area["):
            areas.extend(values)
    return areas


def parse_shizunabi_list_url(url: str) -> tuple[str, str]:
    """しずナビ一覧 URL から都道府県・市区町村スラッグを取得する。"""
    path = urlparse(url).path.rstrip("/")
    match = SHIZUNABI_AREA_LIST_RE.search(path + "/")
    if match:
        return "shizuoka", _city_slug_from_area(match.group(1))

    areas = _extract_area_slugs_from_url(url)
    if areas:
        cities = [_city_slug_from_area(area) for area in areas]
        if len(cities) == 1:
            return "shizuoka", cities[0]
        return "shizuoka", "-".join(cities)
    return "shizuoka", "shizuoka"


def parse_shizunabi_page_number(url: str) -> int:
    """しずナビ一覧 URL からページ番号を取得する。"""
    path = urlparse(url).path.rstrip("/")
    match = SHIZUNABI_AREA_LIST_RE.search(path + "/")
    if match and match.group(3):
        return max(1, int(match.group(3)))

    match = SHIZUNABI_QUERY_LIST_RE.search(path)
    if match and match.group(2):
        return max(1, int(match.group(2)))
    return 1


def build_shizunabi_page_url(url: str, page_number: int) -> str:
    """しずナビ一覧 URL を指定ページ用に組み立てる。"""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    match = SHIZUNABI_AREA_LIST_RE.search(path + "/")
    if match:
        area_slug = match.group(1)
        property_type = match.group(2)
        if page_number <= 1:
            new_path = f"/area/{area_slug}/{property_type}/"
        else:
            new_path = f"/area/{area_slug}/{property_type}/page/{page_number}/"
        return urlunparse(parsed._replace(path=new_path))

    match = SHIZUNABI_QUERY_LIST_RE.search(path)
    if match:
        property_type = match.group(1)
        if page_number <= 1:
            new_path = f"/{property_type}/"
        else:
            new_path = f"/{property_type}/page/{page_number}/"
        return urlunparse(parsed._replace(path=new_path))

    return url


def is_shizunabi_list_url(url: str) -> bool:
    """しずナビの物件一覧 URL かどうかを判定する。"""
    if "buy.s-est.co.jp" not in url:
        return False

    path = urlparse(url).path.rstrip("/")
    if SHIZUNABI_AREA_LIST_RE.search(path + "/"):
        return True
    if SHIZUNABI_QUERY_LIST_RE.search(path):
        return True
    if SHIZUNABI_LEGACY_LIST_RE.search(path) and _extract_area_slugs_from_url(url):
        return True
    return False


def is_shizunabi_list_page(page: Page) -> bool:
    """しずナビの物件一覧ページかどうかを判定する。"""
    url = page.url
    if not is_shizunabi_list_url(url):
        return False

    return page.locator("text=所在地").count() > 0 or page.locator("text=万円").count() > 0


def wait_for_listings_ready(page: Page, timeout_ms: int = 20000) -> bool:
    """物件一覧の読み込み完了を待つ。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if page.locator("h2").count() > 0 and (
            page.locator("text=所在地").count() > 0 or page.locator("text=万円").count() > 0
        ):
            return True
        page.wait_for_timeout(500)
    return False


def _is_property_heading(text: str) -> bool:
    value = clean_text(text)
    if not value or len(value) < 3:
        return False
    return not any(keyword in value for keyword in SHIZUNABI_SKIP_HEADING_KEYWORDS)


def card_position_key(card: Locator) -> tuple[int, int] | None:
    """物件カードの画面上位置をキーとして返す。"""
    box = card.bounding_box()
    if box is None:
        return None
    return (round(box["y"]), round(box["x"]))


def find_property_cards(page: Page) -> list[Locator]:
    """ページ内の物件カードを取得する。"""
    cards: list[Locator] = []
    seen_positions: set[tuple[int, int]] = set()

    headings = page.locator("h2")
    for index in range(headings.count()):
        heading = headings.nth(index)
        heading_text = clean_text(heading.inner_text())
        if not _is_property_heading(heading_text):
            continue

        card = heading.locator(
            "xpath=ancestor::*[contains(., '所在地') and contains(., '交通')][1]"
        )
        if card.count() == 0:
            continue

        candidate = card.first
        try:
            if len(candidate.inner_text()) > 5000:
                continue
        except PlaywrightError:
            continue

        position = card_position_key(candidate)
        if position is None or position in seen_positions:
            continue
        seen_positions.add(position)
        cards.append(candidate)

    return cards


def extract_labeled_field(card: Locator, label: str) -> str:
    """物件カード内のラベル付き項目（所在地・交通など）を取得する。"""
    rows = card.locator("tr")
    for index in range(min(rows.count(), 20)):
        row = rows.nth(index)
        headers = row.locator("th, dt")
        values = row.locator("td, dd")
        if headers.count() == 0 or values.count() == 0:
            continue
        header_text = clean_text(headers.first.inner_text())
        if header_text != label and not header_text.startswith(label):
            continue
        return clean_text(values.first.inner_text())

    for selector in ("dt", "th", "span", "div", "p"):
        elements = card.locator(selector)
        for index in range(min(elements.count(), 40)):
            element = elements.nth(index)
            text = clean_text(element.inner_text())
            if text != label:
                continue
            sibling = element.locator("xpath=following-sibling::*[1]")
            if sibling.count() > 0:
                return clean_text(sibling.first.inner_text())

    try:
        text = card.inner_text()
    except PlaywrightError:
        return ""

    pattern = rf"{label}\s+(.+?)(?=(?:価格|所在地|交通|建物面積|土地面積|間取り|築年月|物件番号)|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return clean_text(match.group(1).splitlines()[0])
    return ""


def extract_property_name(card: Locator) -> str:
    """物件カードから物件名を取得する。"""
    heading = card.locator("h2").first
    if heading.count() == 0:
        return ""
    name = clean_text(heading.inner_text())
    if _is_property_heading(name):
        return name
    return ""


def find_detail_link_in_card(card: Locator) -> str:
    """物件カードから詳細ページ URL を取得する。"""
    for selector in (
        'a:has-text("詳細を見る")',
        'a:has-text("詳細をみる")',
        "h2 a",
        'a[href*="/house/"]',
        'a[href*="/mansion/"]',
        'a[href*="/newhouse/"]',
        'a[href*="/land/"]',
    ):
        links = card.locator(selector)
        for index in range(links.count()):
            href = links.nth(index).get_attribute("href") or ""
            if not href or "/page/" in href:
                continue
            if re.search(r"/page/\d+", href):
                continue
            if href.startswith("/") or "buy.s-est.co.jp" in href:
                return href.split("#")[0].split("?")[0]
    return ""


def extract_listings_from_card(card: Locator, fetched_at: str) -> list[dict[str, str]]:
    """物件カード1件から物件情報を抽出する。"""
    property_name = extract_property_name(card)
    if not property_name:
        return []

    address = extract_labeled_field(card, "所在地")
    access = extract_labeled_field(card, "交通")

    return [
        {
            "property_name": property_name,
            "address": address,
            "access": access,
            "room_number": "",
            "features": "",
            "source_url": find_detail_link_in_card(card),
            "fetched_at": fetched_at,
        }
    ]


def extract_page_listings(page: Page) -> list[dict[str, str]]:
    """現在ページから物件情報を抽出する。"""
    fetched_at = now_jst_iso()
    listings: list[dict[str, str]] = []

    print("  物件カードを検索中...")
    cards = find_property_cards(page)
    print(f"  物件カード {len(cards)} 件を検出")

    for index, card in enumerate(cards, start=1):
        if index == 1 or index % 10 == 0 or index == len(cards):
            print(f"  抽出中... {index}/{len(cards)}")
        try:
            card_listings = extract_listings_from_card(card, fetched_at)
            listings.extend(card_listings)
        except PlaywrightError:
            continue

    return listings


def listing_dedup_key(item: dict[str, str]) -> tuple[str, str, str, str]:
    """重複判定用キー。"""
    return (
        item["property_name"],
        item["address"],
        item["access"],
        item["source_url"],
    )


def _is_next_control_enabled(candidate: Locator) -> bool:
    """次ページボタンが有効かどうか。"""
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
    return True


def find_next_page_button(page: Page) -> Locator | None:
    """ページャーの「次へ」ボタンを探す。"""
    try:
        page.keyboard.press("End")
        page.wait_for_timeout(500)
    except PlaywrightError:
        pass

    for locator in (
        page.get_by_role("link", name="次へ"),
        page.locator('a:has-text("次へ")'),
        page.locator('button:has-text("次へ")'),
    ):
        try:
            if locator.count() == 0:
                continue
            candidate = locator.first
            if not _is_next_control_enabled(candidate):
                continue
            candidate.scroll_into_view_if_needed(timeout=5000)
            return candidate
        except PlaywrightError:
            continue
    return None


def navigate_shizunabi_list_page(page: Page, page_number: int) -> bool:
    """しずナビ一覧を /page/N/ 形式の URL で直接開く。"""
    if not is_shizunabi_list_page(page) and "buy.s-est.co.jp" not in page.url:
        return False

    next_url = build_shizunabi_page_url(page.url, page_number)
    if next_url.rstrip("/") == page.url.rstrip("/"):
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

    if not wait_for_listings_ready(page):
        print(f"  ページ {page_number} の一覧を確認できませんでした", flush=True)
        return False

    actual = parse_shizunabi_page_number(page.url)
    if actual >= page_number:
        print(f"  ページ {actual} の一覧を確認しました", flush=True)
        return True
    return False


def advance_to_next_list_page(page: Page, current_page: int) -> bool:
    """次ページへ進む（URL 優先 → 次へボタン）。"""
    next_page = current_page + 1
    print(f"  ページ {current_page} → {next_page} へ進みます...", flush=True)

    if navigate_shizunabi_list_page(page, next_page):
        return True

    next_button = find_next_page_button(page)
    if next_button is not None:
        try:
            print("  「次へ」ボタンをクリックします...", flush=True)
            next_button.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            if wait_for_listings_ready(page) and parse_shizunabi_page_number(page.url) > current_page:
                return True
        except PlaywrightError:
            pass

    return False


def wait_between_pages() -> None:
    """ページ遷移前にランダム待機を入れる。"""
    delay = random.uniform(2, 5)
    print(f"  次ページへ進む前に {delay:.1f} 秒待機します...")
    time.sleep(delay)


def save_listings_csv(listings: list[dict[str, str]], output_path: Path) -> None:
    """取得結果を CSV に保存する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(listings, columns=CSV_COLUMNS)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")


def save_if_any(listings: list[dict[str, str]], output_csv: Path) -> None:
    """取得済みデータがあれば CSV に保存する。"""
    if listings:
        save_listings_csv(listings, output_csv)


def scrape_current_session(page: Page, output_csv: Path) -> list[dict[str, str]]:
    """現在表示中のしずナビ一覧から最終ページまで物件を取得する。"""
    print("ページの読み込み完了を待っています...")
    wait_for_page_ready(page, extra_ms=2000)

    if not is_shizunabi_list_page(page):
        raise ScrapeError(
            "しずナビの購入物件一覧ページではないようです。\n"
            "市区町村まで絞り込んだ一覧を表示してください。"
        )

    all_listings: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    page_number = parse_shizunabi_page_number(page.url)

    try:
        while True:
            print(f"\n--- ページ {page_number} を取得中 ---")
            print(f"URL: {page.url}")

            wait_for_page_ready(page, extra_ms=1500)
            if not wait_for_listings_ready(page):
                print("\n物件一覧の読み込みを確認できませんでした。")
                break

            page_listings = extract_page_listings(page)

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

            if not advance_to_next_list_page(page, page_number):
                print("\n次ページへ進めませんでした。最終ページまで取得しました。")
                break

            next_page_number = parse_shizunabi_page_number(page.url)
            if next_page_number <= page_number:
                print("\nページ番号が進まなかったため、最終ページと判断して終了します。")
                break
            page_number = next_page_number

    except KeyboardInterrupt:
        save_if_any(all_listings, output_csv)
        print(f"\n中断されました。{len(all_listings)} 件を {output_csv.resolve()} に保存しました。")
        raise

    return all_listings


def wait_for_user_start(page: Page) -> tuple[str, str]:
    """一覧ページの表示を確認してから取得を開始する。"""
    print()
    print("=" * 60)
    print("【操作手順】")
    print("1. 表示されたブラウザでしずナビの購入検索を行ってください")
    print("2. 市区町村まで絞り込み、物件一覧ページを表示してください")
    print("   （例: https://buy.s-est.co.jp/area/fujishi/house/ ）")
    print("   （例: https://buy.s-est.co.jp/house/?area[]=fujishi&... ）")
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

        current_url = page.url
        if not is_shizunabi_list_page(page):
            print()
            print("しずナビの購入物件一覧ページが表示されていません。")
            print(f"現在のURL: {current_url}")
            print(
                "ブラウザで市区町村まで絞り込んだ一覧を表示してから、"
                "再度 Enter を押してください。"
            )
            print()
            continue

        prefecture, city = parse_shizunabi_list_url(current_url)
        print()
        print(f"一覧ページを確認しました（{prefecture} / {city}）。取得を開始します...")
        return prefecture, city
