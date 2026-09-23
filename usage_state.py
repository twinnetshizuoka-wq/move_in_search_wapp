"""未登録ユーザーの取得回数と、メール確認済み状態をローカルに保存する。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from billing_config import FREE_SCRAPE_LIMIT

USAGE_FILE_NAME = ".usage.json"


def _usage_path(data_dir: Path) -> Path:
    return data_dir / USAGE_FILE_NAME


def load_usage(data_dir: Path) -> dict[str, Any]:
    path = _usage_path(data_dir)
    empty = {
        "scrape_count": 0,
        "subscribed": False,
        "email": "",
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
    return {
        "scrape_count": max(0, scrape_count),
        "subscribed": bool(raw.get("subscribed")),
        "email": email.strip(),
    }


def save_usage(
    data_dir: Path,
    scrape_count: int,
    subscribed: bool,
    email: str = "",
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "scrape_count": max(0, scrape_count),
        "subscribed": subscribed,
        "email": email.strip(),
    }
    _usage_path(data_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
