"""配布用 zip を1つ生成する。"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
JST = ZoneInfo("Asia/Tokyo")

INCLUDE_FILES = [
    "スタート.bat",
    "比較.bat",
    "はじめに.txt",
    "README.md",
    "requirements.txt",
    "app.py",
    "compare.py",
    "rental_files.py",
    "rental_match.py",
    "scrape_athome.py",
    "scrape_athome_buy.py",
    "scrape_shizunabi_buy.py",
    "scripts/ensure_env.bat",
]

INCLUDE_DIRS = [
    "scraper",
]

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "venv",
    ".git",
    "node_modules",
    ".next",
    "dist",
    "web",
    "data",
}

EXCLUDE_FILE_SUFFIXES = {".pyc", ".pyo", ".csv"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return False
    if path.suffix.lower() in EXCLUDE_FILE_SUFFIXES:
        return False
    if path.name.startswith(".") and path.name not in {".gitkeep"}:
        return False
    return True


def collect_files() -> list[Path]:
    files: list[Path] = []

    for name in INCLUDE_FILES:
        path = ROOT / name
        if not path.is_file():
            raise FileNotFoundError(f"配布に必要なファイルがありません: {name}")
        files.append(path)

    for dir_name in INCLUDE_DIRS:
        directory = ROOT / dir_name
        if not directory.is_dir():
            raise FileNotFoundError(f"配布に必要なフォルダがありません: {dir_name}")
        for path in directory.rglob("*"):
            if path.is_file() and should_include(path.relative_to(ROOT)):
                files.append(path)

    data_keep = ROOT / "data" / ".gitkeep"
    if data_keep.is_file():
        files.append(data_keep)

    return files


def build_zip() -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime("%Y%m%d")
    zip_name = f"nyuukyo-hakken-tool_{stamp}.zip"
    zip_path = DIST_DIR / zip_name
    folder_name = "入居発見ツール"

    files = collect_files()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, arcname=f"{folder_name}/{relative}")

        if "data/.gitkeep" not in {p.relative_to(ROOT).as_posix() for p in files}:
            archive.writestr(f"{folder_name}/data/.gitkeep", "")

    latest = DIST_DIR / "入居発見ツール.zip"
    latest.write_bytes(zip_path.read_bytes())
    return latest


def main() -> None:
    zip_path = build_zip()
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"配布用 zip を作成しました: {zip_path}")
    print(f"サイズ: {size_mb:.2f} MB")
    print("このファイル1つを配布してください。")


if __name__ == "__main__":
    main()
