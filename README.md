# 賃貸物件 入居発見 MVP

1カ月前と現在の賃貸物件データを比較し、掲載が消えた物件を「入居済み」として抽出するツールです。

## 必要環境

- Python 3.10 以上
- Google Chrome（Playwright が使用）

## セットアップ

```powershell
cd c:\Users\user\projects\rental-discovery-mvp
pip install -r requirements.txt
playwright install chromium
```

## 使い方（GUI）

```powershell
python app.py
```

### 物件情報の取得

**賃貸**

1. **賃貸情報を取得** をクリック
2. ブラウザで賃貸検索を行い、**市区町村まで絞り込んだ一覧**を表示
3. ターミナルで **Enter** を押して取得開始

**購入**

1. **購入情報を取得** をクリック
2. ブラウザで購入検索（マンション・一戸建て・土地など）を行い、**市区町村まで絞り込んだ一覧**を表示
3. ターミナルで **Enter** を押して取得開始

保存ファイル名は自動で次の形式になります。

```
data/202606241631_chintai_shizuoka_fuji-city.csv   # 賃貸
data/202606241631_kounyu_shizuoka_fuji-city.csv    # 購入
```

### 比較（入居済みの抽出）

1. **比較** をクリック
2. **古いファイルを参照** で過去の取得CSVを選択
3. **新しいファイルを参照** で新しい取得CSVを選択
4. **比較を実行** をクリック

比較時に次を確認します。

- 古いファイルの作成日時が新しいファイルより前であること
- 賃貸（chintai）・都道府県・市区町村が同じであること

入居済み物件は次の形式で `data` フォルダに保存されます。

```
data/nyuukyo202606241631_chintai_shizuoka_fuji-city.csv
```

## CLI（コマンドライン）

### 物件取得

```powershell
python scrape_athome.py       # 賃貸
python scrape_athome_buy.py     # 購入
```

### 比較

```powershell
python compare.py --old data/202606011200_chintai_shizuoka_fuji-city.csv --new data/202606241631_chintai_shizuoka_fuji-city.csv
```

## ファイル構成

```
rental-discovery-mvp/
├── app.py                  # GUI（賃貸・購入の取得、比較）
├── compare.py              # CSV 差分比較
├── rental_files.py         # ファイル名の生成・検証
├── scrape_athome.py        # 賃貸 半自動取得
├── scrape_athome_buy.py    # 購入 半自動取得
├── requirements.txt
├── scraper/
│   └── athome.py           # 取得ロジック
└── data/                   # 取得CSV・入居済みCSV
```

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| ファイル名が自動生成されない | 市区町村まで絞り込んだ一覧URLか確認（例: `.../shizuoka/fuji-city/list/`） |
| 比較で日時エラー | 古いファイルの `YYYYMMDDHHMM` が新しいファイルより前か確認 |
| 比較で都道府県エラー | 同じエリアの取得CSV同士を選んでいるか確認 |
| CAPTCHA が表示される | ブラウザ上で認証を完了し、ターミナルで Enter を押す |
