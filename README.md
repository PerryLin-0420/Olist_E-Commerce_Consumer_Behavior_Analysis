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
