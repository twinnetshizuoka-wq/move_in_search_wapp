"""Stripe 課金設定。

決済は Stripe の決済用リンクをブラウザで開く。
秘密鍵はアプリに置かない。PAYMENT_LINK_URL は本環境の決済用リンク。
"""

from __future__ import annotations

PAYMENT_LINK_URL = "https://buy.stripe.com/14AfZjcjL72S1V74nibwk00"
PLAN_NAME = "新規入居発見アプリ"
PLAN_PRICE_YEN = 550
PLAN_PRICE_INCLUDES_TAX = True
TRIAL_DAYS = 90
FREE_SCRAPE_LIMIT = 4
SUBSCRIPTION_STATUS_URL = (
    "https://move-in-search-wapp-19y7.vercel.app/api/subscription-status"
)


def is_test_payment_link(url: str = PAYMENT_LINK_URL) -> bool:
    return "/test_" in url
