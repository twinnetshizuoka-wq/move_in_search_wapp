"""未登録ユーザーの取得回数と、メール確認済み状態をローカルに保存する。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from billing_config import APP_USE_DAYS, FREE_SCRAPE_LIMIT

USAGE_FILE_NAME = ".usage.json"
JST = ZoneInfo("Asia/Tokyo")


def _usage_path(data_dir: Path) -> Path:
    return data_dir / USAGE_FILE_NAME


def today_jst() -> date:
    return datetime.now(JST).date()


def _parse_iso_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def load_usage(data_dir: Path) -> dict[str, Any]:
    path = _usage_path(data_dir)
    empty = {
        "scrape_count": 0,
        "subscribed": False,
        "email": "",
        "first_launched_at": "",
    }
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    try:
        scrape_count = int(raw.get("scrape_count") or 0)
    except (TypeError, ValueError):
        scrape_count = 0
    email = raw.get("email") if isinstance(raw.get("email"), str) else ""
    first_launched_at = raw.get("first_launched_at")
    if not isinstance(first_launched_at, str):
        first_launched_at = ""
    return {
        "scrape_count": max(0, scrape_count),
        "subscribed": bool(raw.get("subscribed")),
        "email": email.strip(),
        "first_launched_at": first_launched_at.strip(),
    }


def save_usage(
    data_dir: Path,
    scrape_count: int,
    subscribed: bool,
    email: str = "",
    first_launched_at: str | None = None,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    existing = load_usage(data_dir)
    launched = (
        first_launched_at
        if first_launched_at is not None
        else str(existing.get("first_launched_at") or "")
    )
    payload = {
        "scrape_count": max(0, scrape_count),
        "subscribed": subscribed,
        "email": email.strip(),
        "first_launched_at": launched.strip(),
    }
    _usage_path(data_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_first_launch(data_dir: Path, today: date | None = None) -> date:
    usage = load_usage(data_dir)
    launched = _parse_iso_date(usage.get("first_launched_at"))
    if launched is None:
        launched = today or today_jst()
        save_usage(
            data_dir,
            int(usage["scrape_count"]),
            bool(usage["subscribed"]),
            str(usage["email"]),
            launched.isoformat(),
        )
    return launched


def remaining_use_days(data_dir: Path, today: date | None = None) -> int:
    current = today or today_jst()
    launched = ensure_first_launch(data_dir, current)
    elapsed = (current - launched).days
    return max(0, APP_USE_DAYS - elapsed)


def is_use_period_expired(data_dir: Path, today: date | None = None) -> bool:
    return remaining_use_days(data_dir, today) <= 0


def is_subscribed(data_dir: Path) -> bool:
    usage = load_usage(data_dir)
    return bool(usage["subscribed"] and usage["email"])


def remaining_scrapes(data_dir: Path) -> int | None:
    if is_subscribed(data_dir):
        return None
    usage = load_usage(data_dir)
    return max(0, FREE_SCRAPE_LIMIT - int(usage["scrape_count"]))


def can_scrape(data_dir: Path) -> bool:
    leftover = remaining_scrapes(data_dir)
    return leftover is None or leftover > 0


def record_scrape(data_dir: Path) -> None:
    usage = load_usage(data_dir)
    if is_subscribed(data_dir):
        return
    save_usage(
        data_dir,
        int(usage["scrape_count"]) + 1,
        False,
        str(usage["email"]),
    )


def mark_subscribed(data_dir: Path, email: str) -> None:
    usage = load_usage(data_dir)
    save_usage(data_dir, int(usage["scrape_count"]), True, email)


def clear_subscription(data_dir: Path) -> None:
    usage = load_usage(data_dir)
    save_usage(data_dir, int(usage["scrape_count"]), False, str(usage["email"]))
