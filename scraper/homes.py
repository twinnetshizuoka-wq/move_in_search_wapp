"""LIFULL HOME'S（homes.co.jp）物件一覧の半自動取得（賃貸・購入）。"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pandas as pd
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from scraper.athome import CSV_COLUMNS, ScrapeError, clean_text, wait_for_page_ready


@dataclass(frozen=True)
class HomesScraperConfig:
    """賃貸・購入など取得種別ごとの設定。"""

    property_type: str
    top_url: str
    list_page_name: str
    search_label: str
    example_list_url: str


CHINTAI_CONFIG = HomesScraperConfig(
    property_type="chintai",
    top_url="https://www.homes.co.jp/chintai/",
    list_page_name="賃貸物件",
    search_label="賃貸検索",
    example_list_url="https://www.homes.co.jp/chintai/shizuoka/fuji-city/list/",
)

KOUNYU_CONFIG = HomesScraperConfig(
    property_type="kounyu",
    top_url="https://www.homes.co.jp/mansion/shinchiku/",
    list_page_name="購入物件",
    search_label="購入検索",
    example_list_url=(
        "https://www.homes.co.jp/mansion/shinchiku/shizuoka/fuji-city/list/"
    ),
)

HOMES_TOP_URL = CHINTAI_CONFIG.top_url
HOMES_BUY_TOP_URL = KOUNYU_CONFIG.top_url

HOMES_DETAIL_URL_RE = re.compile(
    r"homes\.co\.jp/(?:chintai/(?:b-\d+|room/[a-f0-9]+)|(?:mansion|kodate|tochi)/b-\d+)/?",
    re.IGNORECASE,
)
HOMES_SKIP_SEGMENTS = frozenset(
    {"list", "map", "room", "chuko", "shinchiku", "search"}
)
PREFECTURE_NAMES = (
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)

_active_config: HomesScraperConfig = CHINTAI_CONFIG


def set_scraper_config(config: HomesScraperConfig) -> None:
    """取得種別（賃貸・購入）の設定を切り替える。"""
    global _active_config
    _active_config = config


def get_scraper_config() -> HomesScraperConfig:
    """現在の取得設定を返す。"""
    return _active_config

SECURITY_CHECK_KEYWORDS = (
    "セキュリティチェック",
    "セキュリティ認証",
    "セキュリティのため",
    "不正なアクセス",
    "不正アクセス",
    "アクセスが集中",
    "アクセスを確認",
    "ロボットでは",
    "認証にご協力",
    "認証してください",
    "人であることを確認",
    "ブラウザの確認",
    "確認してください",
    "チェックを行",
    "Checking your browser",
    "Just a moment",
    "Attention Required",
    "Verify you are human",
    "needs to review the security",
    "Enable JavaScript and cookies",
)

END_COMMANDS = frozenset({"end", "q", "quit", "終了", "おわり", "終わり"})

SECURITY_CHECK_SELECTORS = (
    "#captcha-box",
    ".geetest_holder",
    "iframe[src*='captcha']",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    ".cf-browser-verification",
    "#challenge-form",
    "#challenge-running",
    "#sec-cpt-if",
    ".sec-if-ctp",
    "[class*='captcha']",
    "[id*='captcha']",
    "[class*='challenge']",
)

SECURITY_URL_HINTS = (
    "captcha",
    "challenge",
    "cdn-cgi",
    "security-check",
    "bot-check",
)

JST = timezone(timedelta(hours=9))


def now_jst_iso() -> str:
    """現在時刻を JST の ISO 8601 形式で返す。"""
    return datetime.now(JST).isoformat(timespec="seconds")


def normalize_source_url(url: str) -> str:
    """詳細 URL を正規化する。"""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        url = "https://www.homes.co.jp" + (url if url.startswith("/") else f"/{url}")
        parsed = urlparse(url)
    path = parsed.path.rstrip("/") + "/"
    return urlunparse(("https", "www.homes.co.jp", path, "", "", ""))


def is_homes_detail_url(url: str) -> bool:
    """HOME'S の物件詳細 URL かどうかを判定する。"""
    return bool(url and HOMES_DETAIL_URL_RE.search(url))


def infer_homes_property_type(url: str) -> str:
    """URL から賃貸 / 購入を推定する。"""
    path = urlparse(url).path.lower()
    if "/chintai/" in path:
        return "chintai"
    if any(f"/{kind}/" in path for kind in ("mansion", "kodate", "tochi")):
        return "kounyu"
    return _active_config.property_type


def parse_homes_list_url(url: str) -> tuple[str, str]:
    """HOME'S 一覧 URL から都道府県・市区町村スラッグを取得する。"""
    path = urlparse(url).path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    if not segments or segments[-1].lower() != "list":
        raise ScrapeError(
            "一覧ページのURLから都道府県・市区町村を判別できません。\n"
            f"例（賃貸）: {CHINTAI_CONFIG.example_list_url}\n"
            f"例（購入）: {KOUNYU_CONFIG.example_list_url}\n"
            f"現在のURL: {url}"
        )

    body = [seg.lower() for seg in segments[:-1]]
    if not body:
        raise ScrapeError(f"一覧ページのURLが不正です。\n現在のURL: {url}")

    kind = body[0]
    rest = body[1:]
    if rest and rest[0] in {"chuko", "shinchiku"}:
        rest = rest[1:]

    if kind == "chintai":
        if len(rest) < 2 or rest[1] in HOMES_SKIP_SEGMENTS:
            raise ScrapeError(
                "市区町村まで絞り込んだ一覧ページで取得してください。\n"
                f"例: {CHINTAI_CONFIG.example_list_url}\n"
                f"現在のURL: {url}"
            )
        return rest[0], rest[1]

    if kind in {"mansion", "kodate", "tochi"}:
        if len(rest) >= 2 and rest[1] not in HOMES_SKIP_SEGMENTS:
            return rest[0], rest[1]
        if len(rest) == 1 and rest[0] not in HOMES_SKIP_SEGMENTS:
            # 都道府県一覧（市区町村未指定）
            return rest[0], "all"
        raise ScrapeError(
            "都道府県または市区町村まで絞り込んだ一覧ページで取得してください。\n"
            f"例: {KOUNYU_CONFIG.example_list_url}\n"
            f"現在のURL: {url}"
        )

    raise ScrapeError(
        "HOME'S の物件一覧URLではありません。\n"
        f"例（賃貸）: {CHINTAI_CONFIG.example_list_url}\n"
        f"例（購入）: {KOUNYU_CONFIG.example_list_url}\n"
        f"現在のURL: {url}"
    )


def parse_homes_page_number(url: str) -> int:
    """HOME'S 一覧 URL からページ番号を取得する。"""
    query = parse_qs(urlparse(url).query)
    values = query.get("page") or query.get("cond[page]")
    if not values:
        return 1
    try:
        return max(1, int(values[0]))
    except ValueError:
        return 1


def build_homes_page_url(url: str, page_number: int) -> str:
    """HOME'S 一覧 URL を指定ページ用に組み立てる。"""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("cond[page]", None)
    if page_number <= 1:
        query.pop("page", None)
    else:
        query["page"] = [str(page_number)]

    flat: list[tuple[str, str]] = []
    for key, values in query.items():
        for value in values:
            flat.append((key, value))
    new_query = urlencode(flat, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def is_homes_list_url(url: str, property_type: str | None = None) -> bool:
    """HOME'S の物件一覧 URL かどうかを判定する。"""
    if "homes.co.jp" not in url:
        return False
    try:
        parse_homes_list_url(url)
    except ScrapeError:
        return False

    expected = property_type or _active_config.property_type
    inferred = infer_homes_property_type(url)
    return inferred == expected


def has_homes_listings(page: Page) -> bool:
    """物件一覧カードが表示されているかどうか。"""
    try:
        if _active_config.property_type == "kounyu":
            return (
                page.locator(
                    "[class*='mod-mergeBuilding--sale'], .prg-kksBukken, tr.raSpecRow"
                ).count()
                > 0
                or page.locator(
                    "a[href*='/mansion/b-'], a[href*='/kodate/b-'], a[href*='/tochi/b-']"
                ).count()
                > 0
            )
        return (
            page.locator("div.moduleInner.prg-building, .prg-kksBukken").count() > 0
            or page.locator("tr.prg-roomInfo").count() > 0
        )
    except PlaywrightError:
        return False


def is_homes_list_page(page: Page) -> bool:
    """HOME'S の物件一覧ページかどうかを判定する。"""
    if not is_homes_list_url(page.url):
        return False
    if is_security_check_page(page):
        return False
    return (
        has_homes_listings(page)
        or page.locator("text=所在地").count() > 0
        or page.locator("text=交通").count() > 0
    )


def is_security_check_page(page: Page) -> bool:
    """セキュリティチェック / CAPTCHA 画面かどうかを判定する。"""
    if has_homes_listings(page):
        return False

    url = (page.url or "").lower()
    if any(hint in url for hint in SECURITY_URL_HINTS):
        return True

    for selector in SECURITY_CHECK_SELECTORS:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            if locator.first.is_visible():
                return True
        except PlaywrightError:
            continue

    try:
        title = page.title() or ""
    except PlaywrightError:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=2000)[:2500]
    except PlaywrightError:
        body = ""

    text = f"{title}\n{body}"
    if any(keyword in text for keyword in SECURITY_CHECK_KEYWORDS):
        return True

    # 一覧URLなのに物件も空ページUIも無い → チェック画面の可能性が高い
    if "homes.co.jp" in url and is_homes_list_url(url) and not is_empty_results_page_ui(page):
        try:
            # 本文が極端に短い / チェック系だけの画面
            if len(clean_text(body)) < 80:
                return True
        except Exception:
            return True
    return False


def is_empty_results_page_ui(page: Page) -> bool:
    """物件ゼロの一覧UI（検索フォーム等）かどうか。セキュリティ判定より先に使う。"""
    try:
        return (
            page.locator("text=キーワード検索").count() > 0
            or page.locator("#cond_sortby").count() > 0
            or page.locator("text=該当する物件がありません").count() > 0
        )
    except PlaywrightError:
        return False


def is_empty_results_page(page: Page) -> bool:
    """物件が無い一覧ページ（最終ページ超過など）かどうか。"""
    if not is_homes_list_url(page.url):
        return False
    if has_homes_listings(page):
        return False
    if is_security_check_page(page):
        return False
    return is_empty_results_page_ui(page)


def needs_user_security_wait(page: Page) -> bool:
    """セキュリティ待ちが必要かどうか。"""
    if has_homes_listings(page):
        return False
    if is_security_check_page(page):
        return True
    if "homes.co.jp" not in (page.url or ""):
        return False
    # 明確な空の一覧UIなら待たない。それ以外の不明画面は Enter 待ちへ。
    if is_homes_list_url(page.url) and is_empty_results_page_ui(page):
        return False
    return True


def wait_for_listings_ready(page: Page, timeout_ms: int = 20000) -> bool:
    """物件一覧の読み込み完了を待つ。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if is_security_check_page(page):
            return False
        if has_homes_listings(page):
            return True
        if is_empty_results_page(page):
            return False
        page.wait_for_timeout(500)
    return False


def _print_finish_help() -> None:
    """取得終了方法を表示する。"""
    print("【物件情報が終わっている場合】", flush=True)
    print("  ・この画面に end と入力して Enter（推奨）", flush=True)
    print("  ・または Ctrl+C", flush=True)
    print("  ・またはこの黒い画面（ターミナル）の × ボタンで閉じる", flush=True)
    print("  ※ 途中まで取得した CSV は data フォルダに保存済みです", flush=True)


def wait_for_security_cleared(page: Page, *, page_number: int | None = None) -> str:
    """セキュリティチェック画面のとき、ユーザー操作完了まで待機する。

    Returns:
        "ready": 一覧が表示され再開可能
        "end": ユーザーが取得終了を指示した、または物件なしと判断
    """
    if has_homes_listings(page) and not is_security_check_page(page):
        if page_number is None or parse_homes_page_number(page.url) >= page_number:
            return "ready"

    # セキュリティの可能性があるときは、空ページ判定で自動終了しない
    if (
        not needs_user_security_wait(page)
        and not is_security_check_page(page)
        and is_empty_results_page(page)
    ):
        print("\n物件一覧が無いページです。最終ページまで取得済みと判断します。", flush=True)
        return "end"

    print(flush=True)
    print("=" * 60, flush=True)
    if page_number is not None:
        print(
            f"【取得を一時停止】ページ {page_number} 付近で"
            " セキュリティチェックが表示されています",
            flush=True,
        )
    else:
        print("【取得を一時停止】セキュリティチェック認証が必要です", flush=True)
    print("ブラウザ上で認証（チェック）を完了してください。", flush=True)
    print("物件一覧が表示されたら、この画面で Enter を押してください。", flush=True)
    print("（止まっているように見えても、Enter 待ちの状態です。自動では進みません）", flush=True)
    print()
    _print_finish_help()
    print("=" * 60, flush=True)

    while True:
        try:
            prompt = "認証完了後に Enter / 終了する場合は end と入力..."
            if page_number is not None:
                prompt = (
                    f"ページ {page_number} を再開: Enter / 終了: end ..."
                )
            raw = input(prompt)
        except EOFError:
            raise ScrapeError("入力が中断されました。") from None

        command = clean_text(raw).lower()
        if command in END_COMMANDS:
            print("取得終了が指示されました。ここまでの結果を保存して終了します。", flush=True)
            return "end"

        try:
            wait_for_page_ready(page, extra_ms=2000)
        except PlaywrightTimeoutError:
            pass

        if is_security_check_page(page):
            print(
                "まだセキュリティチェック画面のようです。\n"
                "ブラウザで認証を完了してから Enter、"
                "物件が終わっている場合は end と入力してください。",
                flush=True,
            )
            continue

        if is_empty_results_page(page) or not has_homes_listings(page):
            print(
                "物件一覧が見つかりません。最終ページまで取得済みの可能性があります。\n"
                "終了する場合は end と入力、一覧があるページなら表示して Enter を押してください。",
                flush=True,
            )
            continue

        if page_number is not None and parse_homes_page_number(page.url) < page_number:
            print(
                f"まだページ {page_number} ではないようです"
                f"（現在: ページ {parse_homes_page_number(page.url)}）。\n"
                "ブラウザで目的のページを表示して Enter、"
                "終わっている場合は end と入力してください。",
                flush=True,
            )
            continue

        print("一覧を確認しました。取得を再開します...", flush=True)
        return "ready"

def expand_collapsed_rooms(page: Page) -> None:
    """建物カード内の折りたたまれた部屋一覧を展開する。"""
    for label in ("全", "表示する", "もっと見る"):
        buttons = page.locator(
            f'button:has-text("{label}"), a:has-text("{label}"), '
            f'span:has-text("{label}"), [role="button"]:has-text("{label}")'
        )
        try:
            count = min(buttons.count(), 40)
        except PlaywrightError:
            continue
        for index in range(count):
            candidate = buttons.nth(index)
            try:
                text = clean_text(candidate.inner_text())
                if "表示" not in text and "もっと見る" not in text:
                    continue
                if not candidate.is_visible():
                    continue
                candidate.click(timeout=2000)
                page.wait_for_timeout(300)
            except PlaywrightError:
                continue


def extract_labeled_field(card: Locator, label: str) -> str:
    """物件カード内のラベル付き項目（所在地・交通など）を取得する。"""
    rows = card.locator("tr")
    for index in range(min(rows.count(), 30)):
        row = rows.nth(index)
        headers = row.locator("th")
        values = row.locator("td")
        if headers.count() == 0 or values.count() == 0:
            continue
        header_text = clean_text(headers.first.inner_text())
        # 「交通 所在地」のような結合ヘッダーは個別ラベルでは拾わない
        if label == "交通" and "所在地" in header_text:
            continue
        if label == "所在地" and "交通" in header_text:
            continue
        if header_text != label and not header_text.startswith(label):
            continue
        return clean_text(values.first.inner_text())
    return ""


def _contains_prefecture(text: str) -> bool:
    return any(pref in text for pref in PREFECTURE_NAMES)


def _looks_like_access_line(text: str) -> bool:
    """駅徒歩・距離などアクセス行らしいかどうか。"""
    return bool(re.search(r"徒歩|\d+(?:\.\d+)?\s*[kKｋＫ][mMｍＭ]", text))


def _is_address_line(text: str) -> bool:
    """都道府県があり、徒歩/km が無い行を住所とみなす。"""
    value = clean_text(text)
    if not value or not _contains_prefecture(value):
        return False
    return not _looks_like_access_line(value)


def split_access_and_address(text: str) -> tuple[str, str]:
    """交通と所在地が一体のテキストを (address, access) に分割する。"""
    if not text or not clean_text(text):
        return "", ""

    # 改行区切り: 都道府県あり＆徒歩/kmなし → 住所、それ以外 → 交通
    lines = [
        clean_text(line)
        for line in re.split(r"[\r\n]+", text)
        if clean_text(line)
    ]
    if len(lines) >= 2:
        address_parts: list[str] = []
        access_parts: list[str] = []
        for line in lines:
            if _is_address_line(line):
                address_parts.append(line)
            else:
                access_parts.append(line)
        if address_parts:
            return " ".join(address_parts), " ".join(access_parts)

    # 1行結合: 都道府県名の直前で分割
    value = clean_text(text)
    earliest = -1
    for pref in PREFECTURE_NAMES:
        idx = value.find(pref)
        if idx < 0:
            continue
        if earliest < 0 or idx < earliest:
            earliest = idx
    if earliest > 0:
        access = clean_text(value[:earliest])
        address = clean_text(value[earliest:])
        if _is_address_line(address) or (
            _contains_prefecture(address) and not _looks_like_access_line(address)
        ):
            return address, access
        if _contains_prefecture(address):
            return address, access

    if _is_address_line(value):
        return value, ""
    return "", value


def extract_address_and_access(card: Locator) -> tuple[str, str]:
    """物件カードから所在地・交通を取得する。"""
    rows = card.locator("tr")
    for index in range(min(rows.count(), 30)):
        row = rows.nth(index)
        headers = row.locator("th")
        values = row.locator("td")
        if headers.count() == 0 or values.count() == 0:
            continue
        header_text = clean_text(headers.first.inner_text())
        if "所在地" in header_text and "交通" in header_text:
            return split_access_and_address(values.first.inner_text())

    address = extract_labeled_field(card, "所在地")
    access = extract_labeled_field(card, "交通")

    # 片方にまとまって入っている場合は分割する
    if address and access:
        return address, access
    if not address and access:
        return split_access_and_address(access)
    if address and not access and _looks_like_access_line(address):
        return split_access_and_address(address)
    return address, access


def extract_property_name_from_building(card: Locator) -> str:
    """建物カードから物件名を取得する。"""
    name = card.locator(".bukkenName").first
    if name.count() > 0:
        return clean_text(name.inner_text())
    heading = card.locator("h2.heading, h3.heading, h2, h3").first
    if heading.count() == 0:
        return ""
    return clean_text(heading.inner_text())


def extract_features_from_building(card: Locator) -> str:
    """建物カードから物件種別を取得する。"""
    for selector in (".bType", ".bukkenType", ".icon-bukkenType"):
        element = card.locator(selector).first
        if element.count() == 0:
            continue
        value = clean_text(element.inner_text())
        if value:
            return value

    name = extract_property_name_from_building(card)
    for token in (
        "新築マンション",
        "中古マンション",
        "新築一戸建て",
        "中古一戸建て",
        "土地",
        "賃貸アパート",
        "賃貸マンション",
        "賃貸一戸建て",
    ):
        if token in name:
            return token
    return ""


def extract_room_number_from_row(row: Locator) -> str:
    """部屋行から部屋番号を取得する。"""
    number = row.locator(".roomNumber").first
    floor = row.locator(".roomKaisuu").first
    parts: list[str] = []
    if floor.count() > 0:
        floor_text = clean_text(floor.inner_text())
        if floor_text:
            parts.append(floor_text)
    if number.count() > 0:
        number_text = clean_text(number.inner_text())
        if number_text:
            parts.append(number_text)
    if parts:
        return " ".join(parts)

    floar = row.locator("td.floar").first
    if floar.count() > 0:
        return clean_text(floar.inner_text())

    status = row.locator(".statusIcons span").first
    if status.count() > 0:
        return clean_text(status.inner_text())
    return ""


def _detail_href_selectors() -> tuple[str, ...]:
    if _active_config.property_type == "kounyu":
        return (
            "a.prg-detailAnchor",
            "a.prg-detailLink",
            "a.prg-bukkenNameAnchor",
            "a[href*='/mansion/b-']",
            "a[href*='/kodate/b-']",
            "a[href*='/tochi/b-']",
            "a:has-text('詳細')",
        )
    return (
        "a.prg-detailAnchor",
        "a.prg-detailLink",
        "a[href*='/chintai/']",
    )


def find_detail_url_in_scope(scope: Locator) -> str:
    """カードまたは行から詳細 URL を取得する。"""
    for selector in _detail_href_selectors():
        links = scope.locator(selector)
        for index in range(min(links.count(), 10)):
            href = links.nth(index).get_attribute("href") or ""
            if is_homes_detail_url(href):
                return normalize_source_url(href)

    data_href = scope.get_attribute("data-href") or ""
    if is_homes_detail_url(data_href):
        return normalize_source_url(data_href)

    bid = scope.get_attribute("data-bid") or ""
    if not bid:
        checkbox = scope.locator('input.prg-bCheck[name="pkey[]"]').first
        if checkbox.count() > 0:
            value = checkbox.get_attribute("value") or ""
            if value.startswith("BRent_"):
                bid = value.removeprefix("BRent_")
                if bid.isdigit():
                    return normalize_source_url(
                        f"https://www.homes.co.jp/chintai/b-{bid}/"
                    )
            if value.startswith("BSale_"):
                bid = value.removeprefix("BSale_")
                if bid.isdigit():
                    return normalize_source_url(
                        f"https://www.homes.co.jp/mansion/b-{bid}/"
                    )
    elif bid.isdigit():
        prefix = (
            "mansion"
            if _active_config.property_type == "kounyu"
            else "chintai"
        )
        return normalize_source_url(f"https://www.homes.co.jp/{prefix}/b-{bid}/")
    return ""


def find_detail_url_in_row(row: Locator) -> str:
    """部屋行から詳細 URL を取得する。"""
    return find_detail_url_in_scope(row)


def extract_listings_from_building_card(
    card: Locator, fetched_at: str
) -> list[dict[str, str]]:
    """建物カード1件から物件情報を抽出する。"""
    if _active_config.property_type == "kounyu":
        return extract_kounyu_listings_from_card(card, fetched_at)

    property_name = extract_property_name_from_building(card)
    if not property_name:
        return []

    address, access = extract_address_and_access(card)
    features = extract_features_from_building(card)

    listings: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    rows = card.locator("tr.prg-roomInfo")
    for index in range(rows.count()):
        row = rows.nth(index)
        try:
            if not row.is_visible():
                continue
        except PlaywrightError:
            pass

        source_url = find_detail_url_in_row(row)
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)

        listings.append(
            {
                "property_name": property_name,
                "address": address,
                "access": access,
                "room_number": extract_room_number_from_row(row),
                "features": features,
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
        )
    return listings


def extract_kounyu_listings_from_card(
    card: Locator, fetched_at: str
) -> list[dict[str, str]]:
    """購入物件カード1件から物件情報を抽出する。"""
    property_name = extract_property_name_from_building(card)
    if not property_name:
        return []

    address, access = extract_address_and_access(card)
    features = extract_features_from_building(card)

    listings: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    rows = card.locator("tr.raSpecRow")
    for index in range(rows.count()):
        row = rows.nth(index)
        try:
            if not row.is_visible():
                continue
        except PlaywrightError:
            pass

        source_url = find_detail_url_in_row(row)
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        listings.append(
            {
                "property_name": property_name,
                "address": address,
                "access": access,
                "room_number": extract_room_number_from_row(row),
                "features": features,
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
        )

    if listings:
        return listings

    source_url = find_detail_url_in_scope(card)
    if not source_url:
        return []
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


def extract_listings_from_pr_card(card: Locator, fetched_at: str) -> list[dict[str, str]]:
    """PR カード1件から物件情報を抽出する。"""
    name = card.locator(".bukkenName").first
    property_name = clean_text(name.inner_text()) if name.count() > 0 else ""
    if not property_name:
        return []

    room = card.locator(".bukkenRoom").first
    room_number = clean_text(room.inner_text()) if room.count() > 0 else ""
    features_el = card.locator(".bukkenType").first
    features = clean_text(features_el.inner_text()) if features_el.count() > 0 else ""
    address, access = extract_address_and_access(card)
    source_url = find_detail_url_in_scope(card)

    return [
        {
            "property_name": property_name,
            "address": address,
            "access": access,
            "room_number": room_number,
            "features": features,
            "source_url": source_url,
            "fetched_at": fetched_at,
        }
    ]


def find_property_cards(page: Page) -> list[tuple[str, Locator]]:
    """ページ内の物件カードを取得する（種別, locator）。"""
    cards: list[tuple[str, Locator]] = []
    seen: set[str] = set()

    if _active_config.property_type == "kounyu":
        selectors = (
            ("pr", ".prg-kksBukken"),
            ("building", "[class*='mod-mergeBuilding--sale']"),
        )
    else:
        selectors = (
            ("pr", ".prg-kksBukken"),
            ("building", "div.moduleInner.prg-building"),
        )

    for kind, selector in selectors:
        locators = page.locator(selector)
        for index in range(locators.count()):
            card = locators.nth(index)
            try:
                key = clean_text(card.inner_text())[:120]
            except PlaywrightError:
                continue
            if not key or key in seen:
                continue
            seen.add(key)
            cards.append((kind, card))

    # 購入一覧でカードクラスが取れない場合のフォールバック
    if _active_config.property_type == "kounyu" and not cards:
        links = page.locator(
            "a[href*='/mansion/b-'], a[href*='/kodate/b-'], a[href*='/tochi/b-']"
        )
        for index in range(links.count()):
            link = links.nth(index)
            card = link.locator(
                "xpath=ancestor::*[self::div or self::article or self::li][1]"
            )
            if card.count() == 0:
                continue
            candidate = card.first
            try:
                key = clean_text(candidate.inner_text())[:120]
            except PlaywrightError:
                continue
            if not key or key in seen:
                continue
            seen.add(key)
            cards.append(("building", candidate))

    return cards

def extract_page_listings(page: Page) -> list[dict[str, str]]:
    """現在ページから物件情報を抽出する。"""
    expand_collapsed_rooms(page)
    fetched_at = now_jst_iso()
    listings: list[dict[str, str]] = []

    print("  物件カードを検索中...")
    cards = find_property_cards(page)
    print(f"  物件カード {len(cards)} 件を検出")

    for index, (kind, card) in enumerate(cards, start=1):
        if index == 1 or index % 10 == 0 or index == len(cards):
            print(f"  抽出中... {index}/{len(cards)}")
        try:
            if kind == "pr":
                card_listings = extract_listings_from_pr_card(card, fetched_at)
            else:
                card_listings = extract_listings_from_building_card(card, fetched_at)
            listings.extend(card_listings)
        except PlaywrightError:
            continue

    return listings


def listing_dedup_key(item: dict[str, str]) -> tuple[str, str, str, str]:
    """重複判定用キー。"""
    return (
        item["property_name"],
        item["address"],
        item["room_number"],
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
    if any(token in class_name for token in ("disabled", "inactive", "is-disabled", "selected")):
        return False
    if candidate.get_attribute("aria-disabled") == "true":
        return False
    return True


def find_next_page_button(page: Page) -> Locator | None:
    """ページャーの次ページリンクを探す。"""
    try:
        page.keyboard.press("End")
        page.wait_for_timeout(500)
    except PlaywrightError:
        pass

    next_page = parse_homes_page_number(page.url) + 1
    for locator in (
        page.locator(f'a[data-page="{next_page}"]'),
        page.get_by_role("link", name=re.compile(r"次[へヘ]")),
        page.locator('a:has-text("次へ"), a:has-text("次ヘ")'),
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


def _ensure_list_page_ready(page: Page, page_number: int) -> str:
    """遷移後の一覧表示を確認する。

    Returns:
        "ready": 一覧あり
        "empty": 物件なし（最終ページ超過など）
        "end": ユーザーが終了を指示
    """
    page.wait_for_timeout(1500)

    if needs_user_security_wait(page):
        print(
            f"  ページ {page_number} でセキュリティチェックの可能性があります。"
            " ユーザー操作を待ちます。",
            flush=True,
        )
        status = wait_for_security_cleared(page, page_number=page_number)
        if status == "end":
            return "end"
        if has_homes_listings(page):
            return "ready"
        if is_empty_results_page(page):
            return "empty"
        return "empty"

    if wait_for_listings_ready(page, timeout_ms=8000):
        if has_homes_listings(page):
            return "ready"

    # 待機後にセキュリティが出た場合は終了せず Enter 待ち
    if needs_user_security_wait(page):
        print(
            f"  ページ {page_number} でセキュリティチェックの可能性があります。"
            " ユーザー操作を待ちます。",
            flush=True,
        )
        status = wait_for_security_cleared(page, page_number=page_number)
        if status == "end":
            return "end"
        if has_homes_listings(page):
            return "ready"
        return "empty"

    if is_empty_results_page(page) or not has_homes_listings(page):
        print(
            f"  ページ {page_number} に物件一覧がありません。"
            " 最終ページまで取得済みと判断します。",
            flush=True,
        )
        return "empty"

    return "ready"


def navigate_homes_list_page(page: Page, page_number: int) -> str:
    """HOME'S 一覧を ?page=N 形式の URL で直接開く。

    Returns:
        "ready" | "empty" | "end" | "failed"
    """
    if not is_homes_list_url(page.url):
        return "failed"

    next_url = build_homes_page_url(page.url, page_number)
    if next_url.rstrip("/") == page.url.rstrip("/"):
        return "failed"

    print(f"  URLでページ {page_number} を開きます...", flush=True)
    try:
        page.goto(next_url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        print("  ページ遷移がタイムアウトしました", flush=True)
        status = _ensure_list_page_ready(page, page_number)
        if status == "ready":
            actual = parse_homes_page_number(page.url)
            print(f"  ページ {actual} の一覧を確認しました", flush=True)
        return status
    except PlaywrightError as exc:
        print(f"  ページ遷移に失敗しました: {exc}", flush=True)
        return "failed"

    status = _ensure_list_page_ready(page, page_number)
    if status == "ready":
        actual = parse_homes_page_number(page.url)
        print(f"  ページ {actual} の一覧を確認しました", flush=True)
        return "ready"
    if status in {"empty", "end"}:
        return status

    print(f"  ページ {page_number} の一覧を確認できませんでした", flush=True)
    return "failed"


def advance_to_next_list_page(page: Page, current_page: int) -> str:
    """次ページへ進む（URL 優先 → 次へボタン）。

    Returns:
        "ready" | "empty" | "end" | "failed"
    """
    next_page = current_page + 1
    print(f"  ページ {current_page} → {next_page} へ進みます...", flush=True)

    status = navigate_homes_list_page(page, next_page)
    if status in {"ready", "empty", "end"}:
        return status

    next_button = find_next_page_button(page)
    if next_button is not None:
        try:
            print("  「次へ」ボタンをクリックします...", flush=True)
            next_button.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            status = _ensure_list_page_ready(page, next_page)
            if status in {"ready", "empty", "end"}:
                return status
        except PlaywrightError:
            pass

    # セキュリティを先に判定（物件なし扱いより優先）
    if needs_user_security_wait(page):
        print(
            "  セキュリティチェックの可能性があります。"
            " ブラウザで認証後に Enter、終わっている場合は end と入力してください。",
            flush=True,
        )
        status = wait_for_security_cleared(page, page_number=next_page)
        if status == "end":
            return "end"
        if has_homes_listings(page):
            return "ready"
        if is_empty_results_page(page):
            return "empty"
        return "empty"

    if is_empty_results_page(page) or not has_homes_listings(page):
        print("  次ページに物件が無いため、最終ページまで取得済みと判断します。", flush=True)
        return "empty"

    return "failed"

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


def scrape_current_session(
    page: Page,
    output_csv: Path,
    config: HomesScraperConfig | None = None,
) -> list[dict[str, str]]:
    """現在表示中の HOME'S 一覧から最終ページまで物件を取得する。"""
    if config is not None:
        set_scraper_config(config)

    print("ページの読み込み完了を待っています...")
    wait_for_page_ready(page, extra_ms=2000)

    if not is_homes_list_page(page):
        raise ScrapeError(
            f"HOME'S の{_active_config.list_page_name}一覧ページではないようです。\n"
            "都道府県または市区町村まで絞り込んだ一覧を表示してください。\n"
            f"例: {_active_config.example_list_url}"
        )

    all_listings: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    page_number = parse_homes_page_number(page.url)

    try:
        while True:
            print(f"\n--- ページ {page_number} を取得中 ---")
            print(f"URL: {page.url}")

            wait_for_page_ready(page, extra_ms=1500)

            if needs_user_security_wait(page):
                save_if_any(all_listings, output_csv)
                status = wait_for_security_cleared(page, page_number=page_number)
                if status == "end":
                    print("\n取得を終了します。")
                    break
                if not has_homes_listings(page):
                    if is_empty_results_page(page):
                        print("\n物件一覧が無いため、最終ページまで取得しました。")
                        break
                    print("\n一覧を確認できないため取得を終了します。")
                    break
                continue

            if not wait_for_listings_ready(page, timeout_ms=8000):
                if needs_user_security_wait(page):
                    save_if_any(all_listings, output_csv)
                    status = wait_for_security_cleared(page, page_number=page_number)
                    if status == "end":
                        print("\n取得を終了します。")
                        break
                    if has_homes_listings(page):
                        continue
                if is_empty_results_page(page) or not has_homes_listings(page):
                    print("\n物件一覧が無いため、最終ページまで取得しました。")
                    break
                continue

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

            advance_status = advance_to_next_list_page(page, page_number)
            if advance_status == "end":
                print("\n取得終了が指示されました。最終ページまで取得しました。")
                break
            if advance_status == "failed":
                if needs_user_security_wait(page):
                    save_if_any(all_listings, output_csv)
                    status = wait_for_security_cleared(
                        page, page_number=page_number + 1
                    )
                    if status == "end" or not has_homes_listings(page):
                        print("\n取得を終了します。")
                        break
                else:
                    print("\n次ページへ進めませんでした。最終ページまで取得しました。")
                    break
            if advance_status == "empty":
                print("\n次ページに物件が無いため、最終ページまで取得しました。")
                break

            if needs_user_security_wait(page):
                save_if_any(all_listings, output_csv)
                status = wait_for_security_cleared(page, page_number=page_number + 1)
                if status == "end" or not has_homes_listings(page):
                    print("\n取得を終了します。")
                    break

            if not has_homes_listings(page):
                print("\n次ページに物件が無いため、最終ページまで取得しました。")
                break

            next_page_number = parse_homes_page_number(page.url)
            if next_page_number <= page_number:
                print("\nページ番号が進まなかったため、最終ページと判断して終了します。")
                break
            page_number = next_page_number

    except KeyboardInterrupt:
        save_if_any(all_listings, output_csv)
        print(f"\n中断されました。{len(all_listings)} 件を {output_csv.resolve()} に保存しました。")
        print("ターミナルの × で閉じても問題ありません。", flush=True)
        raise

    return all_listings


def wait_for_user_start(page: Page) -> tuple[str, str]:
    """一覧ページの表示を確認してから取得を開始する。"""
    config = _active_config
    print()
    print("=" * 60)
    print("【操作手順】")
    print(f"1. 表示されたブラウザで HOME'S の{config.search_label}を行ってください")
    print("2. 都道府県または市区町村まで絞り込み、物件一覧ページを表示してください")
    print(f"   （例: {config.example_list_url} ）")
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
        if not is_homes_list_page(page):
            print()
            print(f"HOME'S の{config.list_page_name}一覧ページが表示されていません。")
            print(f"現在のURL: {current_url}")
            print(
                "ブラウザで一覧を表示してから、再度 Enter を押してください。"
            )
            print()
            continue

        prefecture, city = parse_homes_list_url(current_url)
        print()
        print(f"一覧ページを確認しました（{prefecture} / {city}）。取得を開始します...")
        return prefecture, city
