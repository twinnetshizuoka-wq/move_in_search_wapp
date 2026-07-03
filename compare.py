"""
賃貸物件データの差分比較ツール

古い取得CSVにあって新しい取得CSVにない物件を「入居済み」として抽出します。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from rental_files import (
    JST,
    RentalFileError,
    build_nyukyo_output_path,
    parse_rental_filename,
    validate_compare_pair,
)
from rental_match import property_match_key

# 必須カラム（物件の同一性判定に使用）
REQUIRED_COLUMNS = ["property_name", "room_number", "address"]
MATCH_KEY_COLUMNS = ["_match_name", "_match_address", "_match_room"]

DEFAULT_DATA_DIR = Path("data")


class CompareError(Exception):
    """比較処理に関するエラー"""


def load_csv(file_path: Path) -> pd.DataFrame:
    """CSVファイルを読み込む。"""
    if not file_path.exists():
        raise CompareError(f"ファイルが見つかりません: {file_path}")

    if not file_path.is_file():
        raise CompareError(f"ファイルではありません: {file_path}")

    encodings = ["utf-8-sig", "utf-8", "cp932"]
    last_error: Exception | None = None
    df: pd.DataFrame | None = None

    for encoding in encodings:
        try:
            df = pd.read_csv(file_path, encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
        except pd.errors.EmptyDataError:
            raise CompareError(f"CSVが空です: {file_path}") from None
        except pd.errors.ParserError as exc:
            raise CompareError(f"CSVの形式が不正です: {file_path}\n詳細: {exc}") from exc
    else:
        raise CompareError(
            f"CSVの文字コードを判別できませんでした: {file_path}\n"
            f"詳細: {last_error}"
        ) from last_error

    assert df is not None

    if df.empty:
        raise CompareError(f"CSVにデータ行がありません: {file_path}")

    df.columns = df.columns.str.strip()

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        raise CompareError(
            f"必須カラムが不足しています: {file_path}\n"
            f"不足カラム: {', '.join(missing_columns)}\n"
            f"必要なカラム: {', '.join(REQUIRED_COLUMNS)}"
        )

    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    invalid_mask = (
        df[REQUIRED_COLUMNS].eq("").any(axis=1)
        | df[REQUIRED_COLUMNS].eq("nan").any(axis=1)
    )
    invalid_count = invalid_mask.sum()
    if invalid_count > 0:
        print(
            f"警告: {file_path} にキーが空の行が {invalid_count} 件あります。これらは比較から除外します。",
            file=sys.stderr,
        )
        df = df[~invalid_mask].copy()

    if df.empty:
        raise CompareError(f"有効なデータ行がありません: {file_path}")

    return df


def add_match_keys(df: pd.DataFrame) -> pd.DataFrame:
    """比較用の正規化キー列を追加する。"""
    keyed = df.copy()
    keys = keyed.apply(
        lambda row: property_match_key(
            row["property_name"],
            row["address"],
            row["room_number"],
        ),
        axis=1,
        result_type="expand",
    )
    keyed["_match_name"] = keys[0]
    keyed["_match_address"] = keys[1]
    keyed["_match_room"] = keys[2]
    return keyed


def extract_moved_in_rows(old_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """旧データにあって新データにない物件を抽出する。"""
    old_keyed = add_match_keys(old_df)
    new_keyed = add_match_keys(new_df)

    merged = old_keyed.merge(
        new_keyed[MATCH_KEY_COLUMNS].drop_duplicates(),
        on=MATCH_KEY_COLUMNS,
        how="left",
        indicator=True,
    )
    moved_in = merged[merged["_merge"] == "left_only"].drop(
        columns=["_merge", *MATCH_KEY_COLUMNS]
    )
    return moved_in.drop_duplicates(subset=REQUIRED_COLUMNS, keep="first")


def save_csv(df: pd.DataFrame, file_path: Path) -> None:
    """結果をCSVに保存する。"""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise CompareError(f"CSVの書き込みに失敗しました: {file_path}\n詳細: {exc}") from exc


def compare_rental_data(
    old_csv: Path,
    new_csv: Path,
    output_csv: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> tuple[int, Path]:
    """
    入居済み物件を抽出してCSVに出力する。

    Returns:
        (抽出件数, 出力ファイルパス)
    """
    try:
        old_meta = parse_rental_filename(old_csv)
        new_meta = parse_rental_filename(new_csv)
        validate_compare_pair(old_meta, new_meta)
    except RentalFileError as exc:
        raise CompareError(str(exc)) from exc

    if output_csv is None:
        output_csv = build_nyukyo_output_path(
            datetime.now(JST),
            new_meta,
            data_dir,
        )

    print(f"古いファイル: {old_csv.name}")
    print(f"  作成日時: {old_meta.captured_at.strftime('%Y/%m/%d %H:%M')}")
    print(f"  対象: chintai / {old_meta.prefecture} / {old_meta.city}")

    print(f"新しいファイル: {new_csv.name}")
    print(f"  作成日時: {new_meta.captured_at.strftime('%Y/%m/%d %H:%M')}")
    print(f"  対象: chintai / {new_meta.prefecture} / {new_meta.city}")

    print(f"\n旧データを読み込み中: {old_csv}")
    old_df = load_csv(old_csv)
    print(f"  → {len(old_df)} 件")

    print(f"新データを読み込み中: {new_csv}")
    new_df = load_csv(new_csv)
    print(f"  → {len(new_df)} 件")

    moved_in = extract_moved_in_rows(old_df, new_df)
    save_csv(moved_in, output_csv)

    print(f"\n入居済み: {len(moved_in)} 件")
    print(f"出力先: {output_csv.resolve()}")

    return len(moved_in), output_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="古い取得CSVと新しい取得CSVを比較し、入居済み物件を抽出します。",
    )
    parser.add_argument(
        "--old",
        type=Path,
        help="古い取得CSV（chintai_都道府県_市区町村_YYYYMMDDHHMM.csv）",
    )
    parser.add_argument(
        "--new",
        type=Path,
        help="新しい取得CSV（chintai_都道府県_市区町村_YYYYMMDDHHMM.csv）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="入居済みCSVの出力先（省略時は自動生成）",
    )
    if argv is None:
        return parser.parse_args()
    return parser.parse_args(argv)


def main() -> None:
    """コマンドラインから実行する際のエントリーポイント。"""
    args = parse_args()

    if args.old is None or args.new is None:
        print(
            "GUI から比較する場合は python app.py を実行してください。\n"
            "CLI では --old と --new を指定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        count, _ = compare_rental_data(
            old_csv=args.old,
            new_csv=args.new,
            output_csv=args.output,
        )
        if count == 0:
            print("\n入居済み物件は見つかりませんでした。")
        else:
            print("\n処理が完了しました。")
    except CompareError as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n予期しないエラーが発生しました: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
