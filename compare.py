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
    build_tasha_output_path,
    parse_rental_filename,
    validate_compare_pair,
    validate_cross_compare_pair,
)
from rental_match import normalize_property_name, property_match_key

# 必須カラム（物件の同一性判定に使用）
REQUIRED_COLUMNS = ["property_name", "room_number", "address"]
NAME_ONLY_REQUIRED_COLUMNS = ["property_name"]
MATCH_KEY_COLUMNS = ["_match_name", "_match_address", "_match_room"]

DEFAULT_DATA_DIR = Path("data")
CROSS_OUTPUT_COLUMNS = [
    "property_name",
    "source",
    "address",
    "access",
    "room_number",
    "features",
    "source_url",
    "fetched_at",
]


class CompareError(Exception):
    """比較処理に関するエラー"""


def load_csv(
    file_path: Path,
    *,
    required_columns: list[str] | None = None,
) -> pd.DataFrame:
    """CSVファイルを読み込む。"""
    if not file_path.exists():
        raise CompareError(f"ファイルが見つかりません: {file_path}")

    if not file_path.is_file():
        raise CompareError(f"ファイルではありません: {file_path}")

    required = required_columns or REQUIRED_COLUMNS
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

    missing_columns = [col for col in required if col not in df.columns]
    if missing_columns:
        raise CompareError(
            f"必須カラムが不足しています: {file_path}\n"
            f"不足カラム: {', '.join(missing_columns)}\n"
            f"必要なカラム: {', '.join(required)}"
        )

    for col in required:
        df[col] = df[col].astype(str).str.strip()

    # 任意カラムを文字列化（他社比較用）
    for col in ("address", "access", "room_number", "features", "source_url", "fetched_at"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
            df.loc[df[col].isin({"nan", "None"}), col] = ""

    invalid_mask = df[required].eq("").any(axis=1) | df[required].eq("nan").any(axis=1)
    invalid_count = int(invalid_mask.sum())
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

    source_label = {
        "ah": "アットホーム",
        "hs": "HOME'S",
        "sz": "しずナビ",
    }.get(old_meta.source, old_meta.source or "不明")

    print(f"古いファイル: {old_csv.name}")
    print(f"  作成日時: {old_meta.captured_at.strftime('%Y/%m/%d %H:%M')}")
    print(
        f"  対象: {source_label} / {old_meta.rental_type} / "
        f"{old_meta.prefecture} / {old_meta.city}"
    )

    print(f"新しいファイル: {new_csv.name}")
    print(f"  作成日時: {new_meta.captured_at.strftime('%Y/%m/%d %H:%M')}")
    print(
        f"  対象: {source_label} / {new_meta.rental_type} / "
        f"{new_meta.prefecture} / {new_meta.city}"
    )

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


def _tag_source_rows(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """他社比較用に source 列を付与し、出力列を揃える。"""
    tagged = df.copy()
    tagged["source"] = source
    if "access" not in tagged.columns:
        tagged["access"] = ""
    for col in CROSS_OUTPUT_COLUMNS:
        if col not in tagged.columns:
            tagged[col] = ""
    return tagged[CROSS_OUTPUT_COLUMNS]


def extract_cross_name_matches(
    ah_df: pd.DataFrame,
    hs_df: pd.DataFrame,
) -> pd.DataFrame:
    """物件名が一致する行を両社分抽出する。"""
    ah = ah_df.copy()
    hs = hs_df.copy()
    ah["_match_name"] = ah["property_name"].map(normalize_property_name)
    hs["_match_name"] = hs["property_name"].map(normalize_property_name)

    common_names = set(ah["_match_name"]) & set(hs["_match_name"])
    common_names.discard("")
    if not common_names:
        return pd.DataFrame(columns=CROSS_OUTPUT_COLUMNS)

    ah_matched = _tag_source_rows(ah[ah["_match_name"].isin(common_names)], "ah")
    hs_matched = _tag_source_rows(hs[hs["_match_name"].isin(common_names)], "hs")
    result = pd.concat([ah_matched, hs_matched], ignore_index=True)
    result["_sort_name"] = result["property_name"].map(normalize_property_name)
    result = result.sort_values(
        by=["_sort_name", "source", "room_number", "address"],
        kind="stable",
    ).drop(columns=["_sort_name"])
    return result.reset_index(drop=True)


def compare_cross_company_data(
    athome_csv: Path,
    homes_csv: Path,
    output_csv: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> tuple[int, Path]:
    """
    アットホームと HOME'S のCSVから、物件名が一致する物件を抽出する。

    Returns:
        (抽出件数, 出力ファイルパス)
    """
    try:
        ah_meta = parse_rental_filename(athome_csv)
        hs_meta = parse_rental_filename(homes_csv)
        validate_cross_compare_pair(ah_meta, hs_meta)
    except RentalFileError as exc:
        raise CompareError(str(exc)) from exc

    if output_csv is None:
        output_csv = build_tasha_output_path(datetime.now(JST), ah_meta, data_dir)

    print(f"アットホーム: {athome_csv.name}")
    print(
        f"  対象: {ah_meta.rental_type} / {ah_meta.prefecture} / {ah_meta.city}"
    )
    print(f"HOME'S: {homes_csv.name}")
    print(
        f"  対象: {hs_meta.rental_type} / {hs_meta.prefecture} / {hs_meta.city}"
    )

    print(f"\nアットホームデータを読み込み中: {athome_csv}")
    ah_df = load_csv(athome_csv, required_columns=NAME_ONLY_REQUIRED_COLUMNS)
    print(f"  → {len(ah_df)} 件")

    print(f"HOME'S データを読み込み中: {homes_csv}")
    hs_df = load_csv(homes_csv, required_columns=NAME_ONLY_REQUIRED_COLUMNS)
    print(f"  → {len(hs_df)} 件")

    matched = extract_cross_name_matches(ah_df, hs_df)
    save_csv(matched, output_csv)

    name_count = (
        matched["property_name"].map(normalize_property_name).nunique()
        if not matched.empty
        else 0
    )
    print(f"\n物件名一致: {name_count} 件（出力行 {len(matched)} 行）")
    print(f"出力先: {output_csv.resolve()}")

    return len(matched), output_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="古い取得CSVと新しい取得CSVを比較し、入居済み物件を抽出します。",
    )
    parser.add_argument(
        "--old",
        type=Path,
        help="古い取得CSV（ah_chintai_都道府県_市区町村_YYYYMMDDHHMM.csv など）",
    )
    parser.add_argument(
        "--new",
        type=Path,
        help="新しい取得CSV（ah_chintai_都道府県_市区町村_YYYYMMDDHHMM.csv など）",
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
