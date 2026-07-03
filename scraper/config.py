"""アットホーム取得用の設定。"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AtHomeScraperConfig:
    """賃貸・購入など取得種別ごとの設定。"""

    property_type: str
    top_url: str
    list_path_prefixes: tuple[str, ...]
    detail_url_pattern: re.Pattern[str]
    detail_link_href_substrings: tuple[str, ...]
    feature_pattern: re.Pattern[str]
    list_page_name: str
    search_label: str
    filename_type: str


CHINTAI_CONFIG = AtHomeScraperConfig(
    property_type="chintai",
    top_url="https://www.athome.co.jp/chintai/",
    list_path_prefixes=("/chintai/",),
    detail_url_pattern=re.compile(r"/chintai/\d+/?(?:\?|#|$)"),
    detail_link_href_substrings=("/chintai/",),
    feature_pattern=re.compile(
        r"(賃貸(?:マンション|アパート|一戸建て|テラスハウス|タウンハウス)(?:\s*\d+階建|\s*平屋建)?)"
    ),
    list_page_name="賃貸物件",
    search_label="賃貸検索",
    filename_type="chintai",
)

KOUNYU_CONFIG = AtHomeScraperConfig(
    property_type="kounyu",
    top_url="https://www.athome.co.jp/buyall/",
    list_path_prefixes=("/buyall/", "/mansion/", "/kodate/", "/tochi/"),
    detail_url_pattern=re.compile(
        r"/(?:mansion|kodate|tochi|ikkodate|buy)/\d+/?(?:\?|#|$)"
    ),
    detail_link_href_substrings=(
        "/mansion/",
        "/kodate/",
        "/tochi/",
        "/ikkodate/",
        "/buy/",
    ),
    feature_pattern=re.compile(
        r"((?:新築|中古)?(?:マンション|一戸建て|土地|テラスハウス|タウンハウス)"
        r"(?:\s*\d+階建|\s*平屋建)?)"
    ),
    list_page_name="購入物件",
    search_label="購入検索",
    filename_type="kounyu",
)
