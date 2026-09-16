"""Stripe 課金設定。

決済は Stripe の決済用リンクをブラウザで開く。
秘密鍵はアプリに置かない。本番公開前に PAYMENT_LINK_URL を本環境のリンクへ差し替える。
"""

from __future__ import annotations

PAYMENT_LINK_URL = "https://buy.stripe.com/test_7sY9AU6L0boK6Xkci8gUM00"
PLAN_NAME = "新規入居発見アプリ"
PLAN_PRICE_YEN = 550
PLAN_PRICE_INCLUDES_TAX = True
TRIAL_DAYS = 90
APP_USE_DAYS = 90
FREE_SCRAPE_LIMIT = 2
SUBSCRIPTION_STATUS_URL = (
    "https://move-in-search-wapp-19y7.vercel.app/api/subscription-status"
)
UPDATE_URL = (
    "https://github.com/twinnetshizuoka-wq/move_in_search_wapp/releases/latest"
)


def is_test_payment_link(url: str = PAYMENT_LINK_URL) -> bool:
    return "/test_" in url
