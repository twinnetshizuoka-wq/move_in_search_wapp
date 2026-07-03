"""物件CSVのファイル名生成・解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

PROPERTY_TYPES = frozenset({"chintai", "kounyu"})

SCRAPE_FILENAME_PATTERN = re.compile(
    r"^(chintai|kounyu)_([^_]+)_(.+)_(\d{12})\.csv$",
    re.IGNORECASE,
)
SCRAPE_FILENAME_LEGACY_PATTERN = re.compile(
    r"^(\d{12})_(chintai|kounyu)_([^_]+)_(.+)\.csv$",
    re.IGNORECASE,
)
NYUKYO_FILENAME_PATTERN = re.compile(
    r"^nyuukyo_(chintai|kounyu)_([^_]+)_(.+)_(\d{12})\.csv$",
    re.IGNORECASE,
)
NYUKYO_FILENAME_LEGACY_PATTERN = re.compile(
    r"^nyuukyo(\d{12})_(chintai|kounyu)_([^_]+)_(.+)\.csv$",
    re.IGNORECASE,
)
CHINTAI_LIST_URL_PATTERN = re.compile(
    r"athome\.co\.jp/chintai/([^/?#]+)/([^/?#]+)",
    re.IGNORECASE,
)
KOUNYU_LIST_URL_PATTERN = re.compile(
    r"athome\.co\.jp/(?:mansion|kodate|tochi)/([^/?#]+)/([^/?#]+)",
    re.IGNORECASE,
)
BUYALL_LIST_URL_PATTERN = re.compile(
    r"athome\.co\.jp/buyall/([^/?#]+)/list",
    re.IGNORECASE,
)
CITIES_QUERY_PATTERN = re.compile(r"[?&]cities=([^&]+)", re.IGNORECASE)
ATHOME_SKIP_SEGMENTS = frozenset({"list", "map", "ranking", "rosen"})


class RentalFileError(Exception):
    """ファイル名・URL の解析エラー"""


@dataclass(frozen=True)
class RentalFileMeta:
    """物件CSVファイル名から得られるメタ情報。"""

    captured_at: datetime
    rental_type: str
    prefecture: str
    city: str
    is_nyukyo: bool = False


def _parse_capture_datetime(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=JST)
    except ValueError as exc:
        raise RentalFileError(
            f"ファイル名の日時が不正です（YYYYMMDDHHMM 形式）: {value}"
        ) from exc


def build_scrape_filename(
    captured_at: datetime,
    property_type: str,
    prefecture: str,
    city: str,
) -> str:
    """取得CSVのファイル名を生成する。"""
    stamp = captured_at.strftime("%Y%m%d%H%M")
    return f"{property_type}_{prefecture}_{city}_{stamp}.csv"


def build_nyukyo_filename(
    captured_at: datetime,
    property_type: str,
    prefecture: str,
    city: str,
) -> str:
    """入居済みCSVのファイル名を生成する。"""
    stamp = captured_at.strftime("%Y%m%d%H%M")
    return f"nyuukyo_{property_type}_{prefecture}_{city}_{stamp}.csv"


def parse_rental_filename(path: Path) -> RentalFileMeta:
    """物件CSVのファイル名を解析する。"""
    name = path.name

    nyukyo_match = NYUKYO_FILENAME_PATTERN.match(name)
    if nyukyo_match:
        return RentalFileMeta(
            captured_at=_parse_capture_datetime(nyukyo_match.group(4)),
            rental_type=nyukyo_match.group(1).lower(),
            prefecture=nyukyo_match.group(2).lower(),
            city=nyukyo_match.group(3).lower(),
            is_nyukyo=True,
        )

    scrape_match = SCRAPE_FILENAME_PATTERN.match(name)
    if scrape_match:
        return RentalFileMeta(
            captured_at=_parse_capture_datetime(scrape_match.group(4)),
            rental_type=scrape_match.group(1).lower(),
            prefecture=scrape_match.group(2).lower(),
            city=scrape_match.group(3).lower(),
            is_nyukyo=False,
        )

    nyukyo_legacy = NYUKYO_FILENAME_LEGACY_PATTERN.match(name)
    if nyukyo_legacy:
        return RentalFileMeta(
            captured_at=_parse_capture_datetime(nyukyo_legacy.group(1)),
            rental_type=nyukyo_legacy.group(2).lower(),
            prefecture=nyukyo_legacy.group(3).lower(),
            city=nyukyo_legacy.group(4).lower(),
            is_nyukyo=True,
        )

    scrape_legacy = SCRAPE_FILENAME_LEGACY_PATTERN.match(name)
    if scrape_legacy:
        return RentalFileMeta(
            captured_at=_parse_capture_datetime(scrape_legacy.group(1)),
            rental_type=scrape_legacy.group(2).lower(),
            prefecture=scrape_legacy.group(3).lower(),
            city=scrape_legacy.group(4).lower(),
            is_nyukyo=False,
        )

    raise RentalFileError(
        "ファイル名の形式が不正です。\n"
        "取得データ: chintai_都道府県_市区町村_YYYYMMDDHHMM.csv\n"
        "取得データ(購入): kounyu_都道府県_市区町村_YYYYMMDDHHMM.csv\n"
        "入居済み: nyuukyo_chintai_都道府県_市区町村_YYYYMMDDHHMM.csv\n"
        f"指定ファイル: {name}"
    )


def validate_compare_pair(old_meta: RentalFileMeta, new_meta: RentalFileMeta) -> None:
    """比較に使う2ファイルの整合性を確認する。"""
    if old_meta.is_nyukyo or new_meta.is_nyukyo:
        raise RentalFileError(
            "比較の入力には取得データファイル"
            "（chintai_都道府県_市区町村_YYYYMMDDHHMM.csv）を指定してください。"
        )

    if old_meta.captured_at >= new_meta.captured_at:
        raise RentalFileError(
            "古いファイルの作成日時は、新しいファイルより前である必要があります。\n"
            f"古い: {old_meta.captured_at.strftime('%Y/%m/%d %H:%M')}\n"
            f"新しい: {new_meta.captured_at.strftime('%Y/%m/%d %H:%M')}"
        )

    mismatches: list[str] = []
    type_label = {"chintai": "賃貸", "kounyu": "購入"}.get(
        old_meta.rental_type, old_meta.rental_type
    )
    if old_meta.rental_type != new_meta.rental_type:
        mismatches.append(
            f"種別（{old_meta.rental_type} / {new_meta.rental_type}）"
        )
    if old_meta.prefecture != new_meta.prefecture:
        mismatches.append(
            f"都道府県（{old_meta.prefecture} / {new_meta.prefecture}）"
        )
    if old_meta.city != new_meta.city:
        mismatches.append(f"市区町村（{old_meta.city} / {new_meta.city}）")

    if mismatches:
        raise RentalFileError(
            f"古いファイルと新しいファイルの{type_label}対象が一致しません。\n"
            + "\n".join(f"- {item}" for item in mismatches)
        )


def parse_athome_list_url(url: str, property_type: str = "chintai") -> tuple[str, str]:
    """アットホーム一覧URLから都道府県・市区町村スラッグを取得する。"""
    if property_type == "kounyu":
        buyall_match = BUYALL_LIST_URL_PATTERN.search(url)
        if buyall_match:
            prefecture = buyall_match.group(1).lower()
            cities_match = CITIES_QUERY_PATTERN.search(url)
            if not cities_match:
                raise RentalFileError(
                    "buyall 一覧のURLに市区町村（cities=）が含まれていません。\n"
                    "例: https://www.athome.co.jp/buyall/shizuoka/list/?cities=fuji\n"
                    f"現在のURL: {url}"
                )
            city = cities_match.group(1).split(",")[0].lower()
            return prefecture, city

        pattern = KOUNYU_LIST_URL_PATTERN
        example = "https://www.athome.co.jp/mansion/shizuoka/fuji-city/list/"
    else:
        pattern = CHINTAI_LIST_URL_PATTERN
        example = "https://www.athome.co.jp/chintai/shizuoka/fuji-city/list/"

    match = pattern.search(url)
    if not match:
        raise RentalFileError(
            "一覧ページのURLから都道府県・市区町村を判別できません。\n"
            f"例: {example}\n"
            "購入の buyall 例: https://www.athome.co.jp/buyall/shizuoka/list/?cities=fuji\n"
            f"現在のURL: {url}"
        )

    prefecture = match.group(1).lower()
    city = match.group(2).lower()
    if city in ATHOME_SKIP_SEGMENTS:
        raise RentalFileError(
            "市区町村まで絞り込んだ一覧ページで取得してください。\n"
            f"現在のURL: {url}"
        )

    return prefecture, city


def parse_shizunabi_list_url_for_filename(url: str) -> tuple[str, str]:
    """しずナビ一覧URLから都道府県・市区町村スラッグを取得する。"""
    from scraper.shizunabi import is_shizunabi_list_url, parse_shizunabi_list_url

    if not is_shizunabi_list_url(url):
        raise RentalFileError(
            "しずナビ一覧のURLから市区町村を判別できません。\n"
            "例: https://buy.s-est.co.jp/area/fujishi/house/\n"
            "例: https://buy.s-est.co.jp/house/?area[]=fujishi&...\n"
            f"現在のURL: {url}"
        )

    return parse_shizunabi_list_url(url)


def build_scrape_output_path(
    captured_at: datetime,
    page_url: str,
    data_dir: Path,
    property_type: str = "chintai",
) -> Path:
    """取得結果の保存パスを生成する。"""
    if "buy.s-est.co.jp" in page_url:
        prefecture, city = parse_shizunabi_list_url_for_filename(page_url)
        filename = build_scrape_filename(captured_at, "kounyu", prefecture, city)
        return data_dir / filename

    prefecture, city = parse_athome_list_url(page_url, property_type=property_type)
    filename = build_scrape_filename(captured_at, property_type, prefecture, city)
    return data_dir / filename


def build_shizunabi_output_path(
    captured_at: datetime,
    page_url: str,
    data_dir: Path,
) -> Path:
    """しずナビ取得結果の保存パスを生成する。"""
    return build_scrape_output_path(captured_at, page_url, data_dir, property_type="kounyu")


def build_nyukyo_output_path(captured_at: datetime, meta: RentalFileMeta, data_dir: Path) -> Path:
    """入居済みCSVの保存パスを生成する。"""
    filename = build_nyukyo_filename(
        captured_at, meta.rental_type, meta.prefecture, meta.city
    )
    return data_dir / filename
