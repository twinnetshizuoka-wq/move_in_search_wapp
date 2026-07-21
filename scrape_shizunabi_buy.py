"""
しずナビ半自動購入物件情報取得ツール

Playwright でブラウザを表示し、ユーザーが手動で検索条件を設定した後、
購入物件一覧ページから物件情報を CSV に保存します。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from rental_files import JST, RentalFileError, build_shizunabi_output_path
from scraper.athome import ScrapeError
from scraper.shizunabi import (
    SHIZUNABI_TOP_URL,
    scrape_current_session,
    wait_for_user_start,
)

DEFAULT_DATA_DIR = Path("data")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="しずナビの購入物件一覧から物件情報を半自動取得します。",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "出力 CSV のパス（省略時は data/sz_kounyu_都道府県_市区町村_YYYYMMDDHHMM.csv を自動生成）"
        ),
    )
    if argv is None:
        return parser.parse_args()
    return parser.parse_args(argv)


def run_scraper(output_csv: Path | None) -> tuple[int, Path]:
    """ブラウザを起動し、購入物件情報の取得を実行する。"""
    print("Playwright でブラウザを起動します（表示あり）...")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        resolved_output = output_csv

        try:
            print(f"しずナビ購入トップを開きます: {SHIZUNABI_TOP_URL}")
            page.goto(SHIZUNABI_TOP_URL, wait_until="domcontentloaded", timeout=60000)

            wait_for_user_start(page)

            if resolved_output is None:
                try:
                    resolved_output = build_shizunabi_output_path(
                        datetime.now(JST),
                        page.url,
                        DEFAULT_DATA_DIR,
                    )
                except RentalFileError as exc:
                    raise ScrapeError(str(exc)) from exc

            print(f"出力先: {resolved_output.resolve()}")
            listings = scrape_current_session(page, output_csv=resolved_output)

            print()
            print(f"取得完了: {len(listings)} 件")
            print(f"保存先: {resolved_output.resolve()}")
            return len(listings), resolved_output

        except KeyboardInterrupt:
            print("\n取得を中断しました。", file=sys.stderr)
            if resolved_output and resolved_output.exists():
                print(f"保存済みファイル: {resolved_output.resolve()}", file=sys.stderr)
            raise
        except ScrapeError as exc:
            print(f"\nエラー: {exc}", file=sys.stderr)
            if resolved_output and resolved_output.exists():
                print(f"取得済みデータ: {resolved_output.resolve()}", file=sys.stderr)
            print(
                "\nブラウザは開いたままです。確認後 Enter を押すと閉じます。",
                file=sys.stderr,
            )
            try:
                input()
            except EOFError:
                pass
            raise exc
        except Exception as exc:
            raise ScrapeError(f"予期しないエラーが発生しました: {exc}") from exc
        finally:
            browser.close()


def main() -> None:
    args = parse_args()

    try:
        count, output_path = run_scraper(output_csv=args.output)
        if count == 0:
            print("\n物件は取得できませんでした。一覧ページの表示を確認してください。")
        else:
            print("\n処理が完了しました。")
            print(f"保存ファイル: {output_path.name}")
    except KeyboardInterrupt:
        sys.exit(130)
    except ScrapeError:
        sys.exit(1)


if __name__ == "__main__":
    main()
