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
| 04 | `04_activity_cutoff.py` | 購買次數 = 跨所有店家的不同購買日數；活躍 = 在 ≥ 2 個不同日期下單（重複使用平台），並以兩成分幾何混合模型作為統計參考；以 Cliff's delta 比較活躍與一次型顧客 |
| 05 | `05_active_segments.py` | 加入回購行為特徵對活躍顧客分群，並與同樣人數的隨機一次型顧客比較 |
| 06 | `06_active_vs_one_time.py` | 以購買場次比較評分與消費額：一次型 vs 活躍顧客的首次與後續購買（Wilson／bootstrap 信賴區間、Cliff's delta） |
| 07 | `07_activity_geography.py` | 活躍與一次型顧客的州與區域分布：占比、活躍率（Wilson 信賴區間）、卡方檢定與 Cramér's V |
| 08 | `08_freight_simulation.py` | 運費占比容忍分布、重量 × 距離分布、隨機森林運費模型、同品類跨州的運費與購買占比關聯，以及運費占比壓到 20% 的情境模擬 |

輸出：`random_forest/features/`、`random_forest/outputs/`、`random_forest/charts/`。

## 推論與建議 (Conclusions and Recommendations)

以下為專案作者根據 [EDA 發現](EDA_findings.zh-TW.md) 與隨機森林分析中觀察到的現象所做的推論。每一點都列出支持它的數據；數據不支持的部分會直接註明。

### 推論

1. **平台沒有長期使用習慣。**
   - 97.8% 的顧客只在一個日期購買；兩成分混合模型顯示 99.05% 的顧客再次購買的機率只有 1.9%。
   - 黑色星期五高峰週首購的顧客，180 天內回購率 1.70%，與其他週（2.02%）沒有差異（p = 0.13）。
   - 活躍顧客沒有形成明確的族群：其隨機森林分群的品質，低於同樣人數的隨機一次型顧客。
2. **平台黏著度極低。**
   - 只有 2.2% 的顧客會有第二個購買日期；每週顧客中回頭客只占 2.2%，高峰週也一樣。
   - 在「店家 × 品類」組合中（該品類有 ≥ 30 位顧客的店家），63% 的組合完全沒有回頭客。
3. **營收幾乎完全仰賴新客流入，一旦新客流入放緩，購買量與營收有很高的斷崖式下跌風險。**
   - 每週訂單從 2017 年平均 853 筆成長到 2018 年 1–8 月的 1,571 筆，但 2018 年內持平（趨勢 −4.4 筆/週，p = 0.37）；每週新客同樣持平（約 1,516 位，p = 0.38）。
   - 最大高峰（黑色星期五那週）是滾動基準的 2.3 倍、2018 年週均的 1.9 倍；高峰週的訂單金額沒有提高（平均 R$ 155 vs R$ 161），所以高峰只帶來量，沒有提高每筆訂單的價值。
   - 97.8% 是一次型顧客，幾乎沒有留存的客群可以緩衝新客流入的下滑。
   - 限制：資料是平台的公開樣本，只到 2018 年 8 月，也沒有市場規模、人口或獲客成本資料；2018 年的走勢是「持平」而非已測得的「下滑」，人口紅利是否退去無法從這份資料衡量。
4. **重物並不集中在近距離的顧客。**
   - ≥ 10 kg 的出貨在 100 km 內的占比是整體的 ×0.96（沒有偏多）；重物集中在 100–300 km（×1.30），反而是 < 0.5 kg 的輕件在 100 km 內偏多（×1.19）。

### 建議

1. **對需求穩定且會重複購買的品類，大幅加強推薦與推送。**
   - 寢具有數據支持：`bed_bath_table` 在 2018 年的每週量最穩定（變異係數 0.175，為大型品類中最低），回購率 2.9%，高於整體的 2.2%；`furniture_decor`（2.9%）與 `sports_leisure`（2.8%）的回購率相近。
   - 電子產品沒有數據支持：`electronics` 回購率 1.4%（屬最低的一群），每週變異係數 0.365；`computers_accessories` 1.7%、`telephony` 2.1%。
2. **依地區，以運費（重量、距離、商品價值）為考量做針對性推薦。**
   - 有數據支持的前提：商品價值越高，運費占比越低（以出貨計 Spearman ρ −0.78）；每個重量層的運費都隨距離上升，且有固定部分（< 0.5 kg 為 R$ 11.7 + 每 100 km R$ 0.60）；隨機森林運費模型可解釋 73% 的運費變異（誤差中位數 R$ 1.57）。
   - 需修正：運費占比低於 20% 並不是常態——只有 44.7% 的出貨在 20% 以下（中位數 22%；< 0.5 kg 的輕件只有 34.6%）。
   - 模擬未能證實：同一品類中，預估運費占比較高的州，購買占比並沒有明顯較低（斜率 −0.07，95% 信賴區間 −0.33 到 +0.15）；而且運費占比幾乎與區域重疊，區域本身的偏好無法和運費分開。若把每個品類 × 州的運費占比壓到 20%，模擬的出貨量整體 +1.7%（95% 信賴區間 −3.4% 到 +8.6%），北部與東北部 +5–6% 但區間很寬。要驗證這項建議，需要有曝光與點擊紀錄的 A/B 測試。

圖表：`random_forest/charts/sim_*.png`；統計表：`random_forest/outputs/sim_*.csv`。
