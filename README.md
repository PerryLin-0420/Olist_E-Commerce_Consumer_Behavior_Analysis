# Olist_E-Commerce_Consumer_Behavior_Analysis

**English** | [繁體中文](docs/README.zh-TW.md)

It's an analysis about consumer behavior on Olist store. Especially modeling the consumer behavior to predict consume trends.

## Documents

- [EDA Findings](EDA/EDA_findings.md): observed patterns from the exploratory analysis (phenomena only, no causal claims)

## ETL: Raw_data → DuckDB

Loads the 9 Olist CSV files in `Raw_data/` into `DB/olist.duckdb`.

> `DB/` is not version-controlled (with PK/FK indexes the file is ~140 MB, over GitHub's 100 MB per-file limit). After cloning, rebuild it locally with the commands below.

### Usage

```bash
pip install -r requirements.txt
ETL_scripts\Auto_ETL.bat
```

`Auto_ETL.bat` runs the steps below in order. It aborts at the first failure and **never overwrites** the existing production DB in that case:

| Step | Script | Description |
|---|---|---|
| 01 | `01_validate_raw.py` | Checks that every raw CSV exists and its header matches the schema |
| 02 | `02_load_raw.py` | Creates `DB/olist_staging.duckdb`, builds tables from `sql/schema.sql` (with PK/FK) and loads data with explicit types |
| 03 | `03_build_derived.py` | Builds the derived table `geolocation_zip` from `sql/derived.sql` |
| 04 | `04_quality_check.py` | Reconciles row counts against the CSVs and checks money precision (hard checks); reports known data issues (info) |
| 05 | `05_publish.py` | Replaces `DB/olist.duckdb` with the validated staging DB |

Run logs are written to `ETL_scripts/logs/etl.log` (not version-controlled).

### Tables

| Table | Primary Key (PK) | Foreign Key (FK) |
|---|---|---|
| `customers` | `customer_id` | |
| `sellers` | `seller_id` | |
| `product_category_name_translation` | `product_category_name` | |
| `products` | `product_id` | |
| `orders` | `order_id` | `customer_id` → `customers` |
| `order_items` | (`order_id`, `order_item_id`) | `order_id` → `orders`, `product_id` → `products`, `seller_id` → `sellers` |
| `order_payments` | (`order_id`, `payment_sequential`) | `order_id` → `orders` |
| `order_reviews` | (`review_id`, `order_id`) | `order_id` → `orders` |
| `geolocation` | None (source data contains duplicate rows) | |
| `geolocation_zip` | No declared constraint (derived table, one row per `geolocation_zip_code_prefix`) | |

### Design Notes

- **PK/FK enforced by DuckDB**: any duplicate primary key or orphan foreign key fails the load. The production DB keeps all constraints; inspect them with `SELECT * FROM duckdb_constraints()`.
- **Build in staging, then swap**: every step runs against `DB/olist_staging.duckdb`, and the production DB is replaced only after all checks pass, so a failed run never leaves a half-built DB.
- **Column names match the source CSVs** (including the original typos `product_name_lenght` and `product_description_lenght`) to keep them traceable to the raw files.
- Money columns use `DECIMAL(12, 2)` to avoid floating-point errors.

### Known Data Issues

- 2 categories in `products` (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`, 13 products in total) are missing from the translation table, so no FK is declared there. Another 610 products have a NULL category.
- `geolocation` contains 261,831 exact duplicate rows and 42 points outside Brazil. `geolocation_zip` removes duplicates, excludes out-of-bounds points and aggregates by zip prefix.
- 158 customer zip prefixes and 7 seller zip prefixes are not found in `geolocation_zip`.
- `customer_unique_id` is not unique: the same person gets a different `customer_id` for every order, and 2,997 `customer_unique_id` values map to more than one `customer_id`.

## Random Forest Segmentation

Segments sellers and customers with an unsupervised random forest (50 trees), then enumerates every seller segment × customer segment pairing to check whether seller types have fixed customer types.

```bash
random_forest\Auto_RF.bat
```

| Step | Script | Description |
|---|---|---|
| 01 | `01_build_features.py` | One feature row per seller (location, category mix, product size, diversity, sales, service) and per customer (location, category mix, order value, frequency, payment, experience) |
| 02 | `02_cluster.py` | Unsupervised random forest (real vs column-shuffled synthetic data) → leaf proximity → Ward clustering, k chosen by silhouette; a supervised forest explains the segments |
| 03 | `03_overlap.py` | Every seller × customer segment pair via shipments: share, lift, standardized residual, Cramér's V |
| 04 | `04_activity_cutoff.py` | Purchase count = distinct purchase days with any seller; active = purchases on ≥ 2 dates (platform re-use), with a two-component geometric mixture as a statistical reference; active vs one-time compared with Cliff's delta |
| 05 | `05_active_segments.py` | Active customers segmented with repeat-behaviour features, compared with same-size random samples of one-time customers |
| 06 | `06_active_vs_one_time.py` | Review score and spend per purchase occasion: one-time vs active customers' first and later purchases (Wilson / bootstrap intervals, Cliff's delta) |
| 07 | `07_activity_geography.py` | State and region distribution of active vs one-time customers: shares, active rate with Wilson intervals, chi-square and Cramér's V |
| 08 | `08_freight_simulation.py` | Freight-ratio tolerance, weight × distance mix, a random forest freight model, the within-category freight vs purchase-share association across states, and a 20% freight-ratio what-if |

Outputs: `random_forest/features/`, `random_forest/outputs/`, `random_forest/charts/`.

## Conclusions and Recommendations

These are the project author's inferences, drawn from the observed patterns in [EDA Findings](EDA/EDA_findings.md) and the random forest analyses. Each point lists the evidence behind it; where the data does not support part of a point, that is stated.

### Inferences

1. **No long-term platform usage habit.**
   - 97.8% of customers bought on a single date; a two-component mixture puts 99.05% of customers at a 1.9% chance of buying again.
   - Customers first acquired in the Black Friday spike weeks repurchase within 180 days at 1.70%, the same as other weeks (2.02%, p = 0.13).
   - Active customers do not form distinct segments: their random forest segmentation is weaker than that of same-size random samples of one-time customers.
2. **Platform stickiness is extremely low.**
   - Only 2.2% of customers reach a second purchase date; returning customers are 2.2% of weekly customers, including in the spike weeks.
   - In 63% of seller × category pairs (sellers with ≥ 30 customers in the category) not a single customer came back.
3. **Revenue depends almost entirely on new-customer acquisition, so a slowdown carries a high risk of a sharp fall in volume and revenue.**
   - Weekly orders grew from 853 (2017) to 1,571 (Jan–Aug 2018), but were flat within 2018 (trend −4.4 orders/week, p = 0.37); weekly new customers were also flat (~1,516, p = 0.38).
   - The largest spike (Black Friday week) was 2.3× the rolling baseline and 1.9× the 2018 weekly mean; order value did not rise in spike weeks (mean R$ 155 vs R$ 161), so spikes add volume but not value per order.
   - With 97.8% one-time buyers there is almost no retained base to absorb a drop in acquisition.
   - Limits: the data is a public sample of the marketplace ending in August 2018, and it contains no market-size, demographic or acquisition-cost data; the 2018 pattern is a plateau, not yet a measured decline, and a population-level saturation ("demographic dividend") cannot be measured from it.
4. **Heavy goods do not concentrate among nearby buyers.**
   - Shipments ≥ 10 kg within 100 km are ×0.96 the overall share (not over-represented); heavy goods concentrate at 100–300 km (×1.30), while items < 0.5 kg are over-represented within 100 km (×1.19).

### Recommendations

1. **Push the categories with stable, repeated demand harder in recommendations.**
   - Supported for bedding: `bed_bath_table` has the most stable weekly volume in 2018 (coefficient of variation 0.175, lowest of all large categories) and a repeat rate of 2.9% vs 2.2% overall; `furniture_decor` (2.9%) and `sports_leisure` (2.8%) repeat at a similar rate.
   - Not supported for electronics: `electronics` repeats at 1.4% (among the lowest) with a weekly CV of 0.365; `computers_accessories` 1.7%, `telephony` 2.1%.
2. **Target customers by region with freight-aware recommendations (weight, distance, value).**
   - Supported premises: the freight share falls as product value rises (Spearman ρ −0.78 across shipments); freight grows with distance in every weight tier, with a fixed part (R$ 11.7 + R$ 0.60 per 100 km for items < 0.5 kg); a random forest freight model explains 73% of freight variance (median error R$ 1.57).
   - Correction: a freight share below 20% is not the typical case — 44.7% of shipments are at or below 20% (median 22%; 34.6% for items < 0.5 kg).
   - Not confirmed by the simulation: within a category, states facing a higher predicted freight share do not buy measurably less of it (slope −0.07, 95% CI −0.33 to +0.15), and freight share overlaps almost fully with region, so regional taste cannot be separated from freight. Capping every category × state at a 20% freight share gives +1.7% shipments overall (95% CI −3.4% to +8.6%), +5–6% in the North and Northeast with wide intervals. An A/B test with exposure (impression and click) data is needed to test this recommendation.

Charts: `random_forest/charts/sim_*.png`; tables: `random_forest/outputs/sim_*.csv`.
