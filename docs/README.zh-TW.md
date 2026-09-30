<a id="top"></a>

<p align="center">
  <img src="Olist.jpg" alt="Olist store" width="760">
</p>

<h1 align="center">Olist 電商消費者行為分析</h1>

<p align="center">
  <a href="../README.md"><img src="https://img.shields.io/badge/Language-English-8c959f?style=for-the-badge" alt="English"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/%E8%AA%9E%E8%A8%80-%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87-1f6feb?style=for-the-badge" alt="繁體中文"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/DuckDB-FFF000?style=flat-square&logo=duckdb&logoColor=black" alt="DuckDB">
  <img src="https://img.shields.io/badge/scikit--learn-F7931E?style=flat-square&logo=scikitlearn&logoColor=white" alt="scikit-learn">
  <img src="https://img.shields.io/badge/pandas-150458?style=flat-square&logo=pandas&logoColor=white" alt="pandas">
</p>

<p align="center">
  <a href="#documents"><b>📄 文件</b></a> &nbsp;·&nbsp;
  <a href="#etl"><b>🗄️ ETL</b></a> &nbsp;·&nbsp;
  <a href="#random-forest"><b>🌲 隨機森林</b></a> &nbsp;·&nbsp;
  <a href="#time-matrix"><b>🕒 時間矩陣</b></a> &nbsp;·&nbsp;
  <a href="#conclusions"><b>💡 推論與建議</b></a>
</p>

本專案分析 Olist 電商平台的消費者行為，重點在於建立消費者行為模型以預測消費趨勢。

<details>
<summary><b>目錄</b></summary>

- [文件](#documents)
- [ETL：Raw_data → DuckDB](#etl)
  - [執行方式](#etl-usage) · [資料表](#etl-tables) · [設計說明](#etl-design) · [已知資料問題](#etl-issues)
- [隨機森林分群](#random-forest)
- [時間矩陣分析（星期 × 小時）](#time-matrix)
- [推論與建議](#conclusions)
  - [推論](#inferences) · [建議](#recommendations)

</details>

<a id="documents"></a>

## 📄 文件 (Documents)

| 文件 | 內容 |
|---|---|
| [EDA 發現](EDA_findings.zh-TW.md) | 探索式分析、隨機森林與時間矩陣步驟觀察到的現象（只描述現象，不推論因果） |
| [EDA 發現 §9 星期 × 小時](EDA_findings.zh-TW.md#9-星期--小時-weekday--hour) | 星期 × 小時矩陣、時段分群與黃金時段 |

<a id="etl"></a>

## 🗄️ ETL：Raw_data → DuckDB

將 `Raw_data/` 的 9 個 Olist CSV 載入 `DB/olist.duckdb`。

> [!NOTE]
> `DB/` 不進版控（含 PK/FK 索引約 140 MB，超過 GitHub 單檔 100 MB 限制）。clone 後請執行下方指令於本機重建。

<a id="etl-usage"></a>

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

<a id="etl-tables"></a>

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

<a id="etl-design"></a>

### 設計說明

- **PK/FK 由 DuckDB 強制**：任何重複主鍵或孤兒外鍵都會使載入失敗；正式 DB 保留完整約束，可用 `SELECT * FROM duckdb_constraints()` 查詢。
- **先建 staging 再替換**：所有步驟都在 `DB/olist_staging.duckdb` 進行，驗證全通過才替換正式 DB，失敗時不會留下半套資料。
- **欄位名稱與原始 CSV 相同**（包含原檔拼字錯誤 `product_name_lenght`、`product_description_lenght`），方便對照來源。
- 金額欄位使用 `DECIMAL(12, 2)`，避免浮點誤差。

<a id="etl-issues"></a>

### 已知資料問題

- `products` 有 2 個類別（`pc_gamer`、`portateis_cozinha_e_preparadores_de_alimentos`，共 13 筆商品）不在翻譯表中，因此未設 FK；另有 610 筆商品類別為 NULL。
- `geolocation` 含 261,831 筆完全重複列、42 筆座標落在巴西境外；`geolocation_zip` 已去重、排除境外座標後以 zip prefix 彙總。
- 158 個顧客 zip prefix、7 個賣家 zip prefix 在 `geolocation_zip` 中找不到。
- `customer_unique_id` 非唯一：同一個人每筆訂單會有不同的 `customer_id`，有 2,997 個 `customer_unique_id` 對應多個 `customer_id`。

<p align="right"><a href="#top">↑ 回到頂端</a></p>

<a id="random-forest"></a>

## 🌲 隨機森林分群 (Random Forest Segmentation)

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

<p align="right"><a href="#top">↑ 回到頂端</a></p>

<a id="time-matrix"></a>

## 🕒 時間矩陣分析 (Time Matrix, weekday × hour)

建立訂單量、平均訂單金額與分期（一次付清記為 0）的 7 × 24「星期 × 小時」矩陣，對 168 個時段分群，確認樣態在整條時間軸上都成立，並在最忙的時段群內找出黃金時段。重抽時以整週為單位，避免單一次活動週左右結果。

```bash
time_matrix\Auto_TM.bat
```

| 步驟 | 腳本 | 說明 |
|---|---|---|
| 01 | `01_time_matrix.py` | 星期 × 小時矩陣：訂單量、平均訂單金額、平均分期 |
| 02 | `02_k_selection.py` | 從 k = 10 往下遞減，以 100 次整週重抽計算輪廓係數、ARI 與兩者的平衡分數並畫平滑曲線，選出最佳 k（k = 3） |
| 03 | `03_time_clusters.py` | 以選定的 k 做 KMeans；時段群地圖與訂單層級輪廓；k = 10 各群如何併入選定的群 |
| 04 | `04_time_correlation_stability.py` | 時段層級相關、時段的效果量、每週指紋，以及矩陣與分群在各時期的穩定度 |
| 05 | `05_golden_hours.py` | T1 內的黃金時段：以 1,000 次整週重抽計算每個時段以每週營收進入前 25% 的機率，並以奇偶週與各時期檢驗 |

輸出：`time_matrix/outputs/`、`time_matrix/charts/`。

<p align="right"><a href="#top">↑ 回到頂端</a></p>

<a id="conclusions"></a>

## 💡 推論與建議 (Conclusions and Recommendations)

以下是我個人的觀點，依據 [EDA 發現](EDA_findings.zh-TW.md)、隨機森林與時間矩陣分析中觀察到的現象所做的推論。每一點我都附上支撐它的數據；數據撐不起來的部分，我會直接講明。

<a id="inferences"></a>

### 推論

1. **平台上沒有長期的使用習慣。**
   - 97.8% 的顧客只在單一日期買過；用兩成分混合模型來看，99.05% 的顧客再買一次的機率只有 1.9%。
   - 就算是黑色星期五高峰週進來的新客，180 天內回購率也只有 1.70%，和其他週（2.02%）沒有差別（p = 0.13），大促銷並沒有換來比較會回來的顧客。
   - 活躍顧客也沒有形成明確的族群：他們的隨機森林分群品質，甚至比同樣人數、隨機抽出的一次型顧客還差。
2. **平台黏著度極低。**
   - 只有 2.2% 的顧客會走到第二個購買日；每週顧客裡的回頭客也只占 2.2%，高峰週一樣。
   - 在「店家 × 品類」組合中（該品類有 ≥ 30 位顧客的店家），有 63% 連一位回頭客都沒有。
3. **營收幾乎完全靠新客撐著，新客一旦放緩，購買量與營收都有斷崖式下跌的風險。**
   - 每週訂單從 2017 年平均 853 筆成長到 2018 年 1–8 月的 1,571 筆，但 2018 年內已經走平（趨勢 −4.4 筆/週，p = 0.37），每週新客也同樣持平（約 1,516 位，p = 0.38）。
   - 最大的高峰（黑色星期五那週）是滾動基準的 2.3 倍、2018 年週均的 1.9 倍，但高峰週的訂單金額沒有變高（平均 R$ 155 vs R$ 161）：高峰帶來的是量，不是單價。
   - 97.8% 都是一次型顧客，等於沒有留存客群能在新客變少時接住營收。
   - 限制：這份資料是平台的公開樣本，只到 2018 年 8 月，也沒有市場規模、人口或獲客成本資料。2018 年的走勢目前是「持平」，還不是測得到的「下滑」；人口紅利是否已經退去，這份資料沒辦法衡量。
4. **重物並沒有集中在近距離的顧客。**
   - ≥ 10 kg 的出貨在 100 km 內的占比只有整體的 ×0.96（沒有偏多）；重物反而集中在 100–300 km（×1.30），真正偏向近距離的是 < 0.5 kg 的輕件（×1.19）。
5. **依地區、以運費（重量、距離、商品價值）為考量做針對性推薦。**
   - 前提有數據支持：商品價值越高，運費占比越低（以出貨計 Spearman ρ −0.78）；每個重量層的運費都隨距離上升，而且有一段固定成本（< 0.5 kg 為 R$ 11.7 + 每 100 km R$ 0.60）；隨機森林運費模型能解釋 73% 的運費變異（誤差中位數 R$ 1.57），代表運費可以事先估出來。
   - 需要修正的地方：運費占比低於 20% 並不是常態，只有 44.7% 的出貨在 20% 以下（中位數 22%；< 0.5 kg 的輕件只有 34.6%）。
   - 模擬結果：同一品類中，預估運費占比較高的州，購買占比並沒有明顯比較低（斜率 −0.07，95% 信賴區間 −0.33 到 +0.15）；把每個品類 × 州的運費占比壓到 20%，模擬出貨量整體 +1.7%（95% 信賴區間 −3.4% 到 +8.6%），北部與東北部 +5–6%，但區間很寬。
   - 圖表：`random_forest/charts/sim_*.png`；統計表：`random_forest/outputs/sim_*.csv`。
   - **這項推論目前無法驗證。** 運費占比幾乎和區域完全重疊，區域本身的偏好沒辦法跟運費拆開，資料裡也沒有曝光與點擊紀錄；運費導向的推薦到底有沒有效，只能靠 A/B 測試確認。
6. **購買有固定的每週節奏；時段決定的是「多少人買」，不是「買多少錢」。** *（這裡只談現象，我不推論顧客為什麼在這些時段購買。）*
   - 訂單偏向週初（週一 16.3% → 週六 11.0%）和下午，最忙的時段是週二 14:00。整週最適合切成 3 群：T1（約 08:00–00:00，占 95.8% 訂單）加上兩個夜間群。
   - 這個樣態非常穩：各時期之間 r = 0.94–0.98，奇偶週之間 0.98，拿掉高峰週也是 1.00。
   - 反過來看，訂單金額與分期幾乎不受時段影響（epsilon² 0.0023 與 0.0049），它們的星期 × 小時樣態在不同時期之間也不會重現（r ≤ 0.22 與 ≤ 0.36）。

<a id="recommendations"></a>

### 建議

1. **對需求穩定、會重複購買的品類，加重推薦與推送的力道。**
   - 穩定購買意願品項：`bed_bath_table` 在 2018 年的每週量最穩定（變異係數 0.175，大型品類中最低），回購率 2.9%，高於整體的 2.2%；`furniture_decor`（2.9%）與 `sports_leisure`（2.8%）的回購率也很接近。
2. **推送時間對準黃金時段。** *（依據的是「什麼時候買」，不推論「為什麼買」。）*

   | 優先度 | 時段 | 依據 |
   |---|---|---|
   | 🥇 主要 | **週一 14–16 點、週一 21 點、週二 14 點、週二 16 點、週三 14 點、週三 16 點、週五 16 點** | 1,000 次重抽中 ≥ 97% 進入 T1 每週營收前 25%；每時段每週 R$ 1.87K–1.99K；9 個中有 8 個在四個時期都進入前 25% |
   | 🥈 次要 | 主要時段周邊的平日 10–17 點；週一、週二 19–22 點（共 26 個候選時段） | 50–90% 的重抽進入前 25%；每時段每週 R$ 1.69K–1.86K |
   | ⬇️ 低 | 01–07 點（T2 與 T3）；週六、週日白天 | 夜間兩群只占 4.3% 訂單；週末單一時段每週營收中位數 R$ 1.16K–1.20K，週一為 R$ 1.73K。週末中以週日 18–22 點最忙（每小時 864–956 筆） |

   - 推送要衝的是**訂單量，不是客單價**：黃金時段和其他 T1 時段的差別主要在訂單數（每週 11.7 vs 8.8 筆），訂單金額只差一點（R$ 167 vs R$ 160）；各時段的營收跟著訂單量走（ρ = 0.98），多於跟著訂單金額（ρ = 0.53）。
   - 價格或分期優惠不要依小時安排：各時段的訂單金額與分期樣態在不同時期之間不會重現。
   - 主要與次要時段要當成一整段來用：週一至週三 14–16 點的核心很穩，但單一時段的邊界會移動（奇數週與偶數週各自找出的黃金時段，Jaccard 重疊只有 0.44）。
   - 限制：歷史購買時間不等於對推送的反應，時間戳記也是照資料原樣使用；實際成效還是要靠推送時間的 A/B 測試確認。

   圖表：`time_matrix/charts/11_t1_price_volume.png`、`12_t1_revenue_matrix.png`；統計表：`time_matrix/outputs/golden_cells.csv`、`golden_summary.csv`。

<p align="right"><a href="#top">↑ 回到頂端</a></p>
