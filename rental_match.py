"""賃貸物件の同一性判定用キー正規化。"""

from __future__ import annotations

import re
import unicodedata

ROOM_NUMBER_DASHES = frozenset({"-", "－", "―", "ー", "—", "‐", "‑"})


def normalize_text(value: str) -> str:
    """全角・半角などの表記ゆれを吸収する。"""
    return unicodedata.normalize("NFKC", (value or "").strip())


FLOOR_BUILDING_SUFFIX_PATTERN = re.compile(
    r"[\s　]*(?:\d+|[０-９]+)階建\s*$|[\s　]*平屋建\s*$"
)


def normalize_property_name(name: str) -> str:
    """物件名を比較用に正規化する。"""
    value = normalize_text(name)
    # アットホーム由来の「〇階建」表記ゆれを吸収
    value = FLOOR_BUILDING_SUFFIX_PATTERN.sub("", value).strip()
    return value


def normalize_address(address: str) -> str:
    """住所を比較用に正規化する。"""
    value = normalize_text(address)
    if not value:
        return ""

    # 市・郡の後の町名末尾「町」を除去（例: 富士市瓜島町 → 富士市瓜島）
    value = re.sub(r"市([^市区町村]+?)町$", r"市\1", value)
    value = re.sub(r"郡([^市区町村]+?)町$", r"郡\1", value)
    return value


def normalize_room_number(room: str) -> str:
    """部屋番号を比較用に正規化する。"""
    value = normalize_text(room)
    if not value:
        return ""
    if value in ROOM_NUMBER_DASHES:
        return ""

    if re.fullmatch(r"\d+階", value):
        return value

    if re.fullmatch(r"\d+号室?", value):
        return f"{int(re.match(r'\d+', value).group(0))}号"

    if re.fullmatch(r"\d+", value):
        return str(int(value))

    digit_match = re.fullmatch(r"0*(\d+)(.+)", value)
    if digit_match and digit_match.group(2) in {"号", "号室"}:
        return f"{int(digit_match.group(1))}号"

    return value


def property_match_key(
    property_name: str,
    address: str,
    room_number: str,
) -> tuple[str, str, str]:
    """物件の同一性判定キーを返す。"""
    return (
        normalize_property_name(property_name),
        normalize_address(address),
        normalize_room_number(room_number),
    )
