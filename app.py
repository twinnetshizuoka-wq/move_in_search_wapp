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

from compare import CompareError, compare_cross_company_data, compare_rental_data

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OFFICIAL_SITE_URL = "https://www.twin-net.net/index.html"
HOW_TO_URL = "https://move-in-search-wapp-19y7.vercel.app/#how-it-works"


class RentalDiscoveryApp:
    """メインウィンドウ。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("賃貸・購入物件 入居発見")
        self.root.geometry("760x560")
        self.root.minsize(680, 500)

        self.old_file_path: Path | None = None
        self.new_file_path: Path | None = None
        self.athome_cross_path: Path | None = None
        self.homes_cross_path: Path | None = None

        self._build_ui()

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
