"""Stripe の契約状態をサイトの API 経由で確認する。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from billing_config import SUBSCRIPTION_STATUS_URL


@dataclass(frozen=True)
class SubscriptionCheck:
    subscribed: bool
    error: str | None = None


def check_subscription(
    email: str,
    url: str = SUBSCRIPTION_STATUS_URL,
) -> SubscriptionCheck:
    cleaned = email.strip()
    if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
        return SubscriptionCheck(False, "invalid_email")

    payload = json.dumps({"email": cleaned}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return SubscriptionCheck(False, "not_deployed")
        if exc.code == 503:
            return SubscriptionCheck(False, "not_configured")
        if exc.code == 502:
            return SubscriptionCheck(False, "lookup_failed")
        return SubscriptionCheck(False, "http")
    except (TimeoutError, urllib.error.URLError, OSError):
        return SubscriptionCheck(False, "network")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return SubscriptionCheck(False, "invalid_response")
    if not isinstance(data, dict) or "subscribed" not in data:
        return SubscriptionCheck(False, "invalid_response")
    return SubscriptionCheck(bool(data["subscribed"]), None)
