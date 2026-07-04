"""
賃貸・購入物件 入居発見 — GUI

物件情報の取得と、取得CSV同士の比較を行います。
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import tkinter as tk

from compare import CompareError, compare_rental_data

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"


class RentalDiscoveryApp:
    """メインウィンドウ。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("賃貸・購入物件 入居発見")
        self.root.geometry("760x460")
        self.root.minsize(680, 400)

        self.old_file_path: Path | None = None
        self.new_file_path: Path | None = None

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
            text="アットホーム賃貸: chintai_shizuoka_fuji-city_202606241631.csv / "
            "購入: kounyu_shizuoka_fuji-city_202606241631.csv",
            foreground="#555555",
        ).pack(anchor=tk.W)

        compare_toggle_frame = ttk.Frame(container)
        compare_toggle_frame.pack(fill=tk.X, pady=(0, 8))

        self.compare_button = ttk.Button(
            compare_toggle_frame,
            text="比較",
            command=self._toggle_compare_panel,
        )
        self.compare_button.pack(anchor=tk.W)

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
            text="出力ファイル名例: nyuukyo_chintai_shizuoka_fuji-city_202606241631.csv",
            foreground="#555555",
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 8))

        ttk.Button(
            self.compare_panel,
            text="比較を実行",
            command=self._run_compare,
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W)

        self.status_var = tk.StringVar(value="準備完了")
        status = ttk.Label(container, textvariable=self.status_var, foreground="#333333")
        status.pack(anchor=tk.W, pady=(12, 0))

    def _toggle_compare_panel(self) -> None:
        if self.compare_visible:
            self.compare_panel.pack_forget()
            self.compare_visible = False
            self.compare_button.configure(text="比較")
        else:
            self.compare_panel.pack(fill=tk.X, pady=(0, 8))
            self.compare_visible = True
            self.compare_button.configure(text="比較を閉じる")

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
