"""
賃貸・購入物件 入居発見 — GUI

物件情報の取得と、取得CSV同士の比較を行います。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import tkinter as tk

from billing_config import (
    APP_USE_DAYS,
    FREE_SCRAPE_LIMIT,
    PAYMENT_LINK_URL,
    PLAN_PRICE_INCLUDES_TAX,
    PLAN_PRICE_YEN,
    TRIAL_DAYS,
    UPDATE_URL,
    is_test_payment_link,
)
from compare import CompareError, compare_cross_company_data, compare_rental_data
from subscription_verify import SubscriptionCheck, check_subscription
from usage_state import (
    can_scrape,
    clear_subscription,
    ensure_first_launch,
    is_subscribed,
    is_use_period_expired,
    load_usage,
    mark_subscribed,
    record_scrape,
    remaining_scrapes,
    remaining_use_days,
)

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OFFICIAL_SITE_URL = "https://www.twin-net.net/index.html"
HOW_TO_URL = "https://move-in-search-wapp-19y7.vercel.app/#how-it-works"


class RentalDiscoveryApp:
    """メインウィンドウ。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("賃貸・購入物件 入居発見")
        self.root.geometry("760x700")
        self.root.minsize(680, 600)

        self.old_file_path: Path | None = None
        self.new_file_path: Path | None = None
        self.athome_cross_path: Path | None = None
        self.homes_cross_path: Path | None = None

        ensure_first_launch(DATA_DIR)
        self._build_ui()
        self.root.after(200, self._warn_if_use_period_expired)
        self._refresh_subscription_in_background()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            container,
            text="賃貸・購入物件 入居発見",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor=tk.W, pady=(0, 12))

        links_frame = ttk.Frame(container)
        links_frame.pack(anchor=tk.W, pady=(0, 12))

        ttk.Button(
            links_frame,
            text="公式ページを開く",
            command=self._open_official_site,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            links_frame,
            text="使い方を見る",
            command=self._open_how_to,
        ).pack(side=tk.LEFT)

        billing_frame = ttk.LabelFrame(container, text="ご利用プラン", padding=12)
        billing_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(
            billing_frame,
            text=(
                f"月額 {PLAN_PRICE_YEN} 円"
                f"{'（税込）' if PLAN_PRICE_INCLUDES_TAX else ''}。"
                f"最初の {TRIAL_DAYS} 日間は無料です。"
                "申し込み後にカードを登録すると、無料期間が始まります。"
            ),
            wraplength=680,
        ).pack(anchor=tk.W, pady=(0, 8))

        billing_buttons = ttk.Frame(billing_frame)
        billing_buttons.pack(anchor=tk.W)

        ttk.Button(
            billing_buttons,
            text="申し込む",
            command=self._open_billing,
        ).pack(side=tk.LEFT)

        email_row = ttk.Frame(billing_frame)
        email_row.pack(anchor=tk.W, fill=tk.X, pady=(10, 0))
        ttk.Label(email_row, text="登録メール").pack(side=tk.LEFT, padx=(0, 8))
        saved_email = str(load_usage(DATA_DIR).get("email") or "")
        self.email_var = tk.StringVar(value=saved_email)
        self.email_entry = ttk.Entry(email_row, textvariable=self.email_var, width=36)
        self.email_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.verify_button = ttk.Button(
            email_row,
            text="登録を確認",
            command=self._verify_subscription,
        )
        self.verify_button.pack(side=tk.LEFT)

        self.usage_var = tk.StringVar(value="")
        ttk.Label(
            billing_frame,
            textvariable=self.usage_var,
            wraplength=680,
        ).pack(anchor=tk.W, pady=(8, 0))
        self._refresh_usage_label()

        if is_test_payment_link():
            ttk.Label(
                billing_frame,
                text="いまはテスト決済です。実際の引き落としはありません。",
                foreground="#555555",
            ).pack(anchor=tk.W, pady=(8, 0))

        scrape_frame = ttk.LabelFrame(container, text="物件情報の取得", padding=12)
        scrape_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(
            scrape_frame,
            text="ブラウザで検索・一覧表示後、ターミナルで Enter を押して取得を開始します。",
            wraplength=680,
        ).pack(anchor=tk.W, pady=(0, 10))

        athome_frame = ttk.Frame(scrape_frame)
        athome_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        ttk.Label(athome_frame, text="アットホーム", width=14).pack(side=tk.LEFT)
        ttk.Button(
            athome_frame,
            text="賃貸情報を取得",
            command=self._start_scrape_rental,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            athome_frame,
            text="購入情報を取得",
            command=self._start_scrape_buy,
        ).pack(side=tk.LEFT)

        homes_frame = ttk.Frame(scrape_frame)
        homes_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        ttk.Label(homes_frame, text="HOME'S", width=14).pack(side=tk.LEFT)
        ttk.Button(
            homes_frame,
            text="賃貸情報を取得",
            command=self._start_scrape_homes_rental,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            homes_frame,
            text="購入情報を取得",
            command=self._start_scrape_homes_buy,
        ).pack(side=tk.LEFT)

        shizunabi_frame = ttk.Frame(scrape_frame)
        shizunabi_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        ttk.Label(shizunabi_frame, text="しずナビ", width=14).pack(side=tk.LEFT)
        ttk.Button(
            shizunabi_frame,
            text="購入情報を取得",
            command=self._start_scrape_shizunabi_buy,
        ).pack(side=tk.LEFT)

        ttk.Label(
            scrape_frame,
            text="アットホーム: ah_...csv / HOME'S: hs_...csv / しずナビ: sz_...csv",
            foreground="#555555",
        ).pack(anchor=tk.W)

        compare_toggle_frame = ttk.Frame(container)
        compare_toggle_frame.pack(fill=tk.X, pady=(0, 8))

        self.compare_button = ttk.Button(
            compare_toggle_frame,
            text="比較",
            command=self._toggle_compare_panel,
        )
        self.compare_button.pack(side=tk.LEFT, padx=(0, 8))

        self.cross_compare_button = ttk.Button(
            compare_toggle_frame,
            text="他社比較",
            command=self._toggle_cross_compare_panel,
        )
        self.cross_compare_button.pack(side=tk.LEFT)

        self.compare_panel = ttk.LabelFrame(container, text="取得CSVの比較", padding=12)
        self.compare_visible = False

        ttk.Label(
            self.compare_panel,
            text="古い取得CSVと新しい取得CSVを選び、入居済み物件を抽出します。",
            wraplength=640,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 12))

        ttk.Label(self.compare_panel, text="古いファイル").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4
        )
        ttk.Button(
            self.compare_panel,
            text="古いファイルを参照...",
            command=self._select_old_file,
        ).grid(row=1, column=1, sticky=tk.W, pady=4)
        self.old_file_label = ttk.Label(
            self.compare_panel,
            text="未選択",
            foreground="#666666",
            wraplength=360,
        )
        self.old_file_label.grid(row=1, column=2, sticky=tk.W, padx=(12, 0), pady=4)

        ttk.Label(self.compare_panel, text="新しいファイル").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4
        )
        ttk.Button(
            self.compare_panel,
            text="新しいファイルを参照...",
            command=self._select_new_file,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)
        self.new_file_label = ttk.Label(
            self.compare_panel,
            text="未選択",
            foreground="#666666",
            wraplength=360,
        )
        self.new_file_label.grid(row=2, column=2, sticky=tk.W, padx=(12, 0), pady=4)

        ttk.Label(
            self.compare_panel,
            text="出力ファイル名例: nyuukyo_ah_chintai_shizuoka_fuji-city_202606241631.csv",
            foreground="#555555",
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 8))

        ttk.Button(
            self.compare_panel,
            text="比較を実行",
            command=self._run_compare,
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W)

        self.cross_compare_panel = ttk.LabelFrame(
            container, text="他社比較（アットホーム × HOME'S）", padding=12
        )
        self.cross_compare_visible = False

        ttk.Label(
            self.cross_compare_panel,
            text="アットホームと HOME'S のCSVを選び、同じ物件名の物件情報を抽出します（住所は比較しません）。",
            wraplength=640,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 12))

        ttk.Label(self.cross_compare_panel, text="アットホーム").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4
        )
        ttk.Button(
            self.cross_compare_panel,
            text="アットホームCSVを参照...",
            command=self._select_athome_cross_file,
        ).grid(row=1, column=1, sticky=tk.W, pady=4)
        self.athome_cross_label = ttk.Label(
            self.cross_compare_panel,
            text="未選択",
            foreground="#666666",
            wraplength=360,
        )
        self.athome_cross_label.grid(row=1, column=2, sticky=tk.W, padx=(12, 0), pady=4)

        ttk.Label(self.cross_compare_panel, text="HOME'S").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4
        )
        ttk.Button(
            self.cross_compare_panel,
            text="HOME'S CSVを参照...",
            command=self._select_homes_cross_file,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)
        self.homes_cross_label = ttk.Label(
            self.cross_compare_panel,
            text="未選択",
            foreground="#666666",
            wraplength=360,
        )
        self.homes_cross_label.grid(row=2, column=2, sticky=tk.W, padx=(12, 0), pady=4)

        ttk.Label(
            self.cross_compare_panel,
            text="出力ファイル名例: tasha_chintai_shizuoka_fuji-city_202607211900.csv",
            foreground="#555555",
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 8))

        ttk.Button(
            self.cross_compare_panel,
            text="他社比較を実行",
            command=self._run_cross_compare,
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W)

        self.status_var = tk.StringVar(value="準備完了")
        status = ttk.Label(container, textvariable=self.status_var, foreground="#333333")
        status.pack(anchor=tk.W, pady=(12, 0))

    def _open_url(self, url: str) -> None:
        """既定のブラウザで URL を開く。"""
        try:
            webbrowser.open(url)
        except OSError as exc:
            messagebox.showerror("エラー", f"ページを開けませんでした。\n{exc}")

    def _open_official_site(self) -> None:
        self._open_url(OFFICIAL_SITE_URL)

    def _open_how_to(self) -> None:
        self._open_url(HOW_TO_URL)

    def _open_billing(self) -> None:
        self._open_url(PAYMENT_LINK_URL)
        self.status_var.set("決済ページをブラウザで開きました。")

    def _refresh_usage_label(self) -> None:
        leftover_days = remaining_use_days(DATA_DIR)
        period_text = (
            f"この版は初回起動から {APP_USE_DAYS} 日間利用できます。"
            f" 残り {leftover_days} 日です。"
        )
        if leftover_days <= 0:
            self.usage_var.set(
                f"この版の利用期間が終了しました。新しいバージョンに更新してください。"
            )
            return
        leftover = remaining_scrapes(DATA_DIR)
        if leftover is None:
            email = str(load_usage(DATA_DIR).get("email") or "")
            self.usage_var.set(
                f"登録を確認しました（{email}）。取得回数の制限はありません。\n"
                f"{period_text}"
            )
            return
        self.usage_var.set(
            f"未登録でも取得は {FREE_SCRAPE_LIMIT} 回まで体験できます。"
            f" 残り {leftover} 回です。申し込み後は登録メールで確認してください。\n"
            f"{period_text}"
        )

    def _show_update_required(self) -> None:
        go_update = messagebox.askyesno(
            "利用期間が終了しました",
            f"この版は初回起動から {APP_USE_DAYS} 日間利用できます。\n"
            "利用期間が終了したため、取得・比較は使えません。\n\n"
            "新しいバージョンのダウンロードページを開きますか？",
        )
        if go_update:
            self._open_url(UPDATE_URL)
        self.status_var.set("利用期間が終了しています。新しいバージョンに更新してください。")

    def _warn_if_use_period_expired(self) -> None:
        if is_use_period_expired(DATA_DIR):
            self._refresh_usage_label()
            self._show_update_required()

    def _ensure_use_period(self) -> bool:
        if not is_use_period_expired(DATA_DIR):
            return True
        self._show_update_required()
        return False

    def _verify_error_message(self, error: str) -> str:
        messages = {
            "invalid_email": "メールアドレスの形式を確認してください。",
            "not_deployed": (
                "確認用のページがまだ公開されていません。\n"
                "サイト（Vercel）に最新のプログラムを公開してください。"
            ),
            "not_configured": (
                "確認用の Stripe キーが未設定です。\n"
                "Vercel の環境変数に STRIPE_SECRET_KEY を追加してください。"
            ),
            "lookup_failed": (
                "Stripe への確認中にエラーになりました。\n"
                "キーの権限（Customers / Subscriptions の読み取り）を確認してください。"
            ),
            "network": "ネットに接続できないため、登録を確認できませんでした。",
            "http": "登録の確認に失敗しました。時間をおいてやり直してください。",
            "invalid_response": "確認結果を読み取れませんでした。",
        }
        return messages.get(error, "登録の確認に失敗しました。")

    def _apply_subscription_check(
        self,
        email: str,
        result: SubscriptionCheck,
        *,
        silent: bool,
    ) -> None:
        if result.error:
            if not silent:
                messagebox.showerror("登録確認", self._verify_error_message(result.error))
                self.status_var.set("登録を確認できませんでした。")
            return
        if result.subscribed:
            mark_subscribed(DATA_DIR, email)
            self._refresh_usage_label()
            self.status_var.set("登録を確認しました。")
            if not silent:
                messagebox.showinfo(
                    "登録確認",
                    "申し込みを確認しました。取得回数の制限を解除します。",
                )
            return
        clear_subscription(DATA_DIR)
        self._refresh_usage_label()
        self.status_var.set("このメールでは申し込みを確認できませんでした。")
        if not silent:
            messagebox.showwarning(
                "登録確認",
                "このメールでは有効な申し込みが見つかりませんでした。\n"
                "決済時に入力したメールと同じか確認してください。",
            )

    def _verify_subscription(self) -> None:
        email = self.email_var.get().strip()
        if "@" not in email:
            messagebox.showwarning("登録確認", "決済時に使ったメールアドレスを入力してください。")
            return
        self.verify_button.configure(state=tk.DISABLED)
        self.status_var.set("登録を確認しています...")

        def worker() -> None:
            result = check_subscription(email)
            self.root.after(
                0,
                lambda: self._on_verify_finished(email, result, silent=False),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_verify_finished(
        self,
        email: str,
        result: SubscriptionCheck,
        *,
        silent: bool,
    ) -> None:
        self.verify_button.configure(state=tk.NORMAL)
        self._apply_subscription_check(email, result, silent=silent)

    def _refresh_subscription_in_background(self) -> None:
        usage = load_usage(DATA_DIR)
        email = str(usage.get("email") or "").strip()
        if not email:
            if usage.get("subscribed"):
                clear_subscription(DATA_DIR)
                self._refresh_usage_label()
            return

        def worker() -> None:
            result = check_subscription(email)
            self.root.after(
                0,
                lambda: self._on_verify_finished(email, result, silent=True),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_compare_panel(self) -> None:
        if self.compare_visible:
            self.compare_panel.pack_forget()
            self.compare_visible = False
            self.compare_button.configure(text="比較")
        else:
            if self.cross_compare_visible:
                self._toggle_cross_compare_panel()
            self.compare_panel.pack(fill=tk.X, pady=(0, 8))
            self.compare_visible = True
            self.compare_button.configure(text="比較を閉じる")

    def _toggle_cross_compare_panel(self) -> None:
        if self.cross_compare_visible:
            self.cross_compare_panel.pack_forget()
            self.cross_compare_visible = False
            self.cross_compare_button.configure(text="他社比較")
        else:
            if self.compare_visible:
                self._toggle_compare_panel()
            self.cross_compare_panel.pack(fill=tk.X, pady=(0, 8))
            self.cross_compare_visible = True
            self.cross_compare_button.configure(text="他社比較を閉じる")

    def _launch_scrape_script(self, script_name: str, title: str, instructions: str) -> None:
        script = ROOT_DIR / script_name
        if not script.exists():
            messagebox.showerror("エラー", f"スクリプトが見つかりません: {script}")
            return

        if not self._ensure_use_period():
            return

        if not can_scrape(DATA_DIR):
            go_billing = messagebox.askyesno(
                "体験回数の上限です",
                f"未登録の取得は {FREE_SCRAPE_LIMIT} 回までです。\n\n"
                "申し込むと、最初の "
                f"{TRIAL_DAYS} 日間は無料で使い続けられます。\n"
                "決済ページを開きますか？\n\n"
                "すでに申し込み済みの場合は、決済時のメールを入力して"
                "「登録を確認」を押してください。",
            )
            if go_billing:
                self._open_billing()
            self.status_var.set("取得回数の上限に達しています。申し込み後に続けられます。")
            return

        self.status_var.set(f"{title}を起動しています...")
        try:
            popen_kwargs: dict = {"cwd": str(ROOT_DIR)}
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            subprocess.Popen(
                [sys.executable, str(script)],
                **popen_kwargs,
            )
        except OSError as exc:
            messagebox.showerror("エラー", f"{title}の起動に失敗しました。\n{exc}")
            self.status_var.set(f"{title}の起動に失敗しました")
            return

        if not is_subscribed(DATA_DIR):
            record_scrape(DATA_DIR)
            self._refresh_usage_label()

        self.status_var.set(f"{title}を起動しました。ブラウザとターミナルで操作を続けてください。")
        messagebox.showinfo(title, instructions)

    def _start_scrape_rental(self) -> None:
        self._launch_scrape_script(
            "scrape_athome.py",
            "賃貸情報の取得（アットホーム）",
            "別ウィンドウのターミナルとブラウザが起動します。\n"
            "1. ブラウザで賃貸を検索し、市区町村まで絞り込んで一覧を表示\n"
            "2. ターミナルで Enter を押して取得開始\n\n"
            "※ トップページ（/chintai/）のまま Enter を押すと開始できません。",
        )

    def _start_scrape_buy(self) -> None:
        self._launch_scrape_script(
            "scrape_athome_buy.py",
            "購入情報の取得（アットホーム）",
            "別ウィンドウのターミナルとブラウザが起動します。\n"
            "1. ブラウザでアットホームの購入検索を行い、市区町村まで絞り込んで一覧を表示\n"
            "   （buyall 一覧: .../buyall/shizuoka/list/?cities=fuji など）\n"
            "2. ターミナルで Enter を押して取得開始\n\n"
            "※ トップページ（/buyall/）のまま Enter を押すと開始できません。",
        )

    def _start_scrape_homes_rental(self) -> None:
        self._launch_scrape_script(
            "scrape_homes.py",
            "賃貸情報の取得（HOME'S）",
            "別ウィンドウのターミナルとブラウザが起動します。\n"
            "1. ブラウザで HOME'S の賃貸検索を行い、市区町村まで絞り込んで一覧を表示\n"
            "   （例: https://www.homes.co.jp/chintai/shizuoka/fuji-city/list/ ）\n"
            "2. ターミナルで Enter を押して取得開始\n\n"
            "※ トップページ（/chintai/）のまま Enter を押すと開始できません。",
        )

    def _start_scrape_homes_buy(self) -> None:
        self._launch_scrape_script(
            "scrape_homes_buy.py",
            "購入情報の取得（HOME'S）",
            "別ウィンドウのターミナルとブラウザが起動します。\n"
            "1. ブラウザで HOME'S の購入検索を行い、都道府県または市区町村まで絞り込んで一覧を表示\n"
            "   （例: https://www.homes.co.jp/mansion/shinchiku/shizuoka/fuji-city/list/ ）\n"
            "   （例: https://www.homes.co.jp/mansion/chuko/shizuoka/fuji-city/list/ ）\n"
            "2. ターミナルで Enter を押して取得開始\n\n"
            "※ トップページ（/mansion/shinchiku/）のまま Enter を押すと開始できません。",
        )

    def _start_scrape_shizunabi_buy(self) -> None:
        self._launch_scrape_script(
            "scrape_shizunabi_buy.py",
            "購入情報の取得（しずナビ）",
            "別ウィンドウのターミナルとブラウザが起動します。\n"
            "1. ブラウザでしずナビ（静岡県）の購入検索を行い、市区町村まで絞り込んで一覧を表示\n"
            "   （例: https://buy.s-est.co.jp/area/fujishi/house/ ）\n"
            "   （例: https://buy.s-est.co.jp/house/?area[]=fujishi&... ）\n"
            "2. ターミナルで Enter を押して取得開始\n\n"
            "※ トップページのまま Enter を押すと開始できません。",
        )

    def _select_old_file(self) -> None:
        path = filedialog.askopenfilename(
            title="古い取得CSVを選択",
            initialdir=str(DATA_DIR),
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        self.old_file_path = Path(path)
        self.old_file_label.configure(text=self.old_file_path.name, foreground="#000000")

    def _select_new_file(self) -> None:
        path = filedialog.askopenfilename(
            title="新しい取得CSVを選択",
            initialdir=str(DATA_DIR),
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        self.new_file_path = Path(path)
        self.new_file_label.configure(text=self.new_file_path.name, foreground="#000000")

    def _select_athome_cross_file(self) -> None:
        path = filedialog.askopenfilename(
            title="アットホームCSVを選択",
            initialdir=str(DATA_DIR),
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        self.athome_cross_path = Path(path)
        self.athome_cross_label.configure(
            text=self.athome_cross_path.name, foreground="#000000"
        )

    def _select_homes_cross_file(self) -> None:
        path = filedialog.askopenfilename(
            title="HOME'S CSVを選択",
            initialdir=str(DATA_DIR),
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        self.homes_cross_path = Path(path)
        self.homes_cross_label.configure(
            text=self.homes_cross_path.name, foreground="#000000"
        )

    def _run_compare(self) -> None:
        if not self._ensure_use_period():
            return
        if self.old_file_path is None or self.new_file_path is None:
            messagebox.showwarning(
                "ファイル未選択",
                "古いファイルと新しいファイルの両方を選択してください。",
            )
            return

        if self.old_file_path == self.new_file_path:
            messagebox.showwarning(
                "同じファイル",
                "古いファイルと新しいファイルは別のファイルを選んでください。",
            )
            return

        self.status_var.set("比較を実行しています...")
        self.root.configure(cursor="watch")
        thread = threading.Thread(target=self._compare_worker, daemon=True)
        thread.start()

    def _compare_worker(self) -> None:
        assert self.old_file_path is not None
        assert self.new_file_path is not None

        try:
            count, output_path = compare_rental_data(
                old_csv=self.old_file_path,
                new_csv=self.new_file_path,
                data_dir=DATA_DIR,
            )
            self.root.after(
                0,
                lambda: self._on_compare_success(count, output_path),
            )
        except CompareError as exc:
            self.root.after(0, lambda: self._on_compare_error(str(exc)))
        except Exception as exc:
            self.root.after(0, lambda: self._on_compare_error(f"予期しないエラー: {exc}"))

    def _on_compare_success(self, count: int, output_path: Path) -> None:
        self.root.configure(cursor="")
        self.status_var.set(f"比較完了: 入居済み {count} 件")
        if count == 0:
            messagebox.showinfo(
                "比較完了",
                "入居済み物件は見つかりませんでした。",
            )
        else:
            messagebox.showinfo(
                "比較完了",
                f"入居済み物件: {count} 件\n\n出力先:\n{output_path}",
            )

    def _on_compare_error(self, message: str) -> None:
        self.root.configure(cursor="")
        self.status_var.set("比較に失敗しました")
        messagebox.showerror("比較エラー", message)

    def _run_cross_compare(self) -> None:
        if not self._ensure_use_period():
            return
        if self.athome_cross_path is None or self.homes_cross_path is None:
            messagebox.showwarning(
                "ファイル未選択",
                "アットホームと HOME'S の両方のCSVを選択してください。",
            )
            return

        if self.athome_cross_path == self.homes_cross_path:
            messagebox.showwarning(
                "同じファイル",
                "アットホームと HOME'S は別のファイルを選んでください。",
            )
            return

        self.status_var.set("他社比較を実行しています...")
        self.root.configure(cursor="watch")
        thread = threading.Thread(target=self._cross_compare_worker, daemon=True)
        thread.start()

    def _cross_compare_worker(self) -> None:
        assert self.athome_cross_path is not None
        assert self.homes_cross_path is not None

        try:
            count, output_path = compare_cross_company_data(
                athome_csv=self.athome_cross_path,
                homes_csv=self.homes_cross_path,
                data_dir=DATA_DIR,
            )
            self.root.after(
                0,
                lambda: self._on_cross_compare_success(count, output_path),
            )
        except CompareError as exc:
            self.root.after(0, lambda: self._on_cross_compare_error(str(exc)))
        except Exception as exc:
            self.root.after(
                0, lambda: self._on_cross_compare_error(f"予期しないエラー: {exc}")
            )

    def _on_cross_compare_success(self, count: int, output_path: Path) -> None:
        self.root.configure(cursor="")
        self.status_var.set(f"他社比較完了: {count} 行")
        if count == 0:
            messagebox.showinfo(
                "他社比較完了",
                "同じ物件名の物件は見つかりませんでした。",
            )
        else:
            messagebox.showinfo(
                "他社比較完了",
                f"一致した物件情報: {count} 行\n\n出力先:\n{output_path}",
            )

    def _on_cross_compare_error(self, message: str) -> None:
        self.root.configure(cursor="")
        self.status_var.set("他社比較に失敗しました")
        messagebox.showerror("他社比較エラー", message)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    open_compare = "--compare" in args

    root = tk.Tk()
    app = RentalDiscoveryApp(root)
    if open_compare and not app.compare_visible:
        app._toggle_compare_panel()
    root.mainloop()


if __name__ == "__main__":
    main()
