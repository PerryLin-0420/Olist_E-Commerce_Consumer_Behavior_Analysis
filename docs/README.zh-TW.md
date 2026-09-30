# Olist_E-Commerce_Consumer_Behavior_Analysis

[English](../README.md) | **繁體中文**

本專案分析 Olist 電商平台的消費者行為，重點在於建立消費者行為模型以預測消費趨勢。

## 文件 (Documents)

- [EDA 發現](EDA_findings.zh-TW.md)：探索式分析觀察到的現象（只描述現象，不推論因果）

## ETL：Raw_data → DuckDB

將 `Raw_data/` 的 9 個 Olist CSV 載入 `DB/olist.duckdb`。

> `DB/` 不進版控（含 PK/FK 索引約 140 MB，超過 GitHub 單檔 100 MB 限制）。clone 後請執行下方指令於本機重建。

### 執行方式

```bash
pip install -r requirements.txt
ETL_scripts\Auto_ETL.bat
```

`Auto_ETL.bat` 會依序執行下列步驟，任一步失敗即中止，且**不會覆蓋**既有的正式 DB：

| 步驟 | 腳本 | 說明 |
|---|---|---|
| 01 | `01_validate_raw.py` | 檢查 raw CSV 是否存在、表頭是否與 schema 一致 |
| 02 | `02_load_raw.py` | 建立 `DB/olist_staging.duckdb`，依 `sql/schema.sql` 建表（含 PK/FK），以明確型別載入 |
| 03 | `03_build_derived.py` | 依 `sql/derived.sql` 建立衍生表 `geolocation_zip` |
| 04 | `04_quality_check.py` | 筆數與 CSV 對帳、金額精度檢查（hard）；已知資料問題統計（info） |
| 05 | `05_publish.py` | 以驗證通過的 staging DB 替換 `DB/olist.duckdb` |

執行紀錄寫在 `ETL_scripts/logs/etl.log`（不進版控）。

### 資料表

| 資料表 | 主鍵 (PK) | 外鍵 (FK) |
|---|---|---|
| `customers` | `customer_id` | |
| `sellers` | `seller_id` | |
| `product_category_name_translation` | `product_category_name` | |
| `products` | `product_id` | |
| `orders` | `order_id` | `customer_id` → `customers` |
| `order_items` | (`order_id`, `order_item_id`) | `order_id` → `orders`、`product_id` → `products`、`seller_id` → `sellers` |
| `order_payments` | (`order_id`, `payment_sequential`) | `order_id` → `orders` |
| `order_reviews` | (`review_id`, `order_id`) | `order_id` → `orders` |
| `geolocation` | 無（原始資料含重複列） | |
| `geolocation_zip` | 無宣告約束（衍生表，每個 `geolocation_zip_code_prefix` 一列） | |

### 設計說明

- **PK/FK 由 DuckDB 強制**：任何重複主鍵或孤兒外鍵都會使載入失敗；正式 DB 保留完整約束，可用 `SELECT * FROM duckdb_constraints()` 查詢。
- **先建 staging 再替換**：所有步驟都在 `DB/olist_staging.duckdb` 進行，驗證全通過才替換正式 DB，失敗時不會留下半套資料。
- **欄位名稱與原始 CSV 相同**（包含原檔拼字錯誤 `product_name_lenght`、`product_description_lenght`），方便對照來源。
- 金額欄位使用 `DECIMAL(12, 2)`，避免浮點誤差。

### 已知資料問題

- `products` 有 2 個類別（`pc_gamer`、`portateis_cozinha_e_preparadores_de_alimentos`，共 13 筆商品）不在翻譯表中，因此未設 FK；另有 610 筆商品類別為 NULL。
- `geolocation` 含 261,831 筆完全重複列、42 筆座標落在巴西境外；`geolocation_zip` 已去重、排除境外座標後以 zip prefix 彙總。
- 158 個顧客 zip prefix、7 個賣家 zip prefix 在 `geolocation_zip` 中找不到。
- `customer_unique_id` 非唯一：同一個人每筆訂單會有不同的 `customer_id`，有 2,997 個 `customer_unique_id` 對應多個 `customer_id`。

## 隨機森林分群 (Random Forest Segmentation)

以非監督式隨機森林（50 棵樹）分別對店家與顧客分群，再窮舉所有「店家群 × 顧客群」配對，確認店家類型是否有固定配對的顧客類型。

```bash
random_forest\Auto_RF.bat
```

| 步驟 | 腳本 | 說明 |
|---|---|---|
| 01 | `01_build_features.py` | 每家店家一列特徵（位置、品類組成、商品大小、多樣性、銷售、服務），每位顧客一列特徵（位置、品類組成、訂單金額、頻率、付款、購物體驗） |
| 02 | `02_cluster.py` | 非監督式 RF（真實資料 vs 各欄獨立打亂的合成資料）→ 葉節點相似度 → Ward 階層式分群，群數依輪廓係數挑選；再以監督式 RF 解釋各群差異 |
| 03 | `03_overlap.py` | 以出貨紀錄窮舉每一組店家群 × 顧客群：占比、lift、標準化殘差、Cramér's V |

輸出：`random_forest/features/`、`random_forest/outputs/`、`random_forest/charts/`。
