# EDA Findings

**English** | [繁體中文](../docs/EDA_findings.zh-TW.md)

This document describes **what the data shows**. It reports observed patterns only and does not claim causes; any "why" is left for later hypothesis testing.

- Source: `DB/olist.duckdb` built by `ETL_scripts/Auto_ETL.bat`
- Scripts: `EDA/scipts/01_*.py` – `05_*.py`; charts in `EDA/charts/`, tables in `EDA/outputs/`
- Period: 2016-09-04 to 2018-10-17 (2016 Q3/Q4 and 2018 Q3/Q4 are partial quarters)

## Definitions

| Term | Definition |
|---|---|
| Customer | `customer_unique_id` (one person across orders). `customer_id` is per order |
| Valid order | `order_status` not in `canceled`, `unavailable` |
| Customer location | State of the customer's latest order |
| Seller location | `seller_zip_code_prefix` → zip-prefix centroid in `geolocation_zip` |
| Shipment | Items one seller ships in one order (`order_id` × `seller_id`) |
| Distance | Great-circle distance between seller and customer zip-prefix centroids |
| Box plot | Box = Q1–Q3, dashed line = median, whiskers = 1.5 × IQR, outliers not drawn |

## 1. Data Quality

### 1.1 Missing values by column
![Missing rate by column](charts/01_missing_rate_by_column.png)

- 13 of 52 columns contain NULLs; the other 39 are complete.
- `review_comment_title` is NULL in 88.3% of reviews and `review_comment_message` in 58.7%; 56,518 reviews have neither.
- In `products`, the same 610 rows (1.9%) are NULL in all four descriptive columns (category, name length, description length, photo count). 2 products have no dimensions or weight.

### 1.2 Order timestamps by status
![Orders missing by status](charts/02_orders_missing_by_status.png)

- Timestamp NULLs line up with `order_status`: every `created` order lacks all three timestamps, every `invoiced` / `processing` / `unavailable` order lacks both delivery dates, and every `shipped` order lacks the customer delivery date.
- Among 96,478 `delivered` orders, 14 lack `order_approved_at`, 2 lack `order_delivered_carrier_date`, and 8 lack `order_delivered_customer_date`.

### 1.3 Relational gaps
![Relational gaps](charts/03_relational_gaps.png)

- 775 orders (0.78%) have no items, 768 (0.77%) have no review, and 1 has no payment.
- 13 products belong to 2 categories missing from the translation table (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`).
- 279 customers and 7 sellers have a zip prefix not found in the geolocation data.

## 2. Customers

### 2.1 Location
![Customers map](charts/04_customers_map_by_state.png)

- 96,096 unique customers. SP, RJ and MG together hold 66.5%; SP alone holds 41.9%.
- By region: Southeast 68.6%, South 14.2%, Northeast 9.5%, Center-West 5.8%, North 1.9%.

### 2.2 Spend over time
![Spend by quarter](charts/06_spend_by_quarter.png)
![Spend tier by quarter](charts/07_spend_tier_by_quarter.png)

- Among full quarters, total spend rises from R$ 846K (2017 Q1) to R$ 3.3M (2018 Q2), the peak.
- Customer count per quarter grows from 5,014 (2017 Q1) to 20,556 (2018 Q1), while spend per customer stays between R$ 157 and R$ 169.
- The spend-tier mix within each quarter is stable: 50–100 and 100–200 BRL are the two largest tiers in every quarter from 2016 Q4 onward, together 59–64% of customers.

### 2.3 Payment
![Preferred payment type](charts/08_preferred_payment_type.png)
![Credit card installments](charts/09_credit_card_installments.png)

- Preferred payment type (largest value per customer): credit card 75.5%, boleto 19.9%, voucher 3.1%, debit card 1.5%.
- Among 73,270 credit-card customers, 33.0% always paid in a single installment; 67.0% used 2 or more, and 15.6% used 7–10.

### 2.4 Reviews
![Review score by category](charts/10_review_score_by_category.png)

- Score distribution: 5 ★ 58.2%, 4 ★ 19.4%, 3 ★ 8.3%, 2 ★ 3.2%, 1 ★ 10.9%.
- The distribution is U-shaped: 1 ★ reviews outnumber 2 ★ and 3 ★ reviews.

### 2.5 Categories
![Top categories](charts/11_top_categories_orders_spend.png)

- The top 15 categories take 76.4% of spend.
- Order rank and spend rank differ: `bed_bath_table` has the most orders (9,399) but ranks 3rd by spend; `watches_gifts` ranks 7th by orders and 2nd by spend (R$ 1.3M).

### 2.6 Spend by region
![Spending tier by region](charts/12_spending_tier_by_region.png)
![Price and freight by region](charts/13_price_freight_by_region.png)

- Share of customers spending ≥ 200 BRL: North 34.7%, Southeast 19.7%.
- Average spend per customer: North R$ 230, Northeast R$ 207, Center-West R$ 183, South R$ 168, Southeast R$ 156.
- Compared with the Southeast, North customers show 38% higher average product value and 2.1× the average freight. Freight is 19% of spend in the North and 13% in the Southeast.

## 3. Sellers

### 3.1 Repeat purchase rate per seller
![Seller repeat rate](charts/05_seller_repeat_rate_iqr_by_category.png)

- At customer level, 97.0% of buying customers placed only one valid order.
- Per seller × category (sellers with ≥ 30 customers, 635 pairs): 63% of sellers have no repeat customer at all; overall Q1 = 0%, median = 0%, Q3 = 1.1%.
- Only 3 categories have a median above 0%: `construction_tools_construction` 1.35%, `bed_bath_table` 0.41%, `fashion_bags_accessories` 0.31%. `fashion_bags_accessories` has the widest spread (Q3 4.33%).

### 3.2 Seller vs customer location
![Seller vs customer map](charts/14_seller_vs_customer_map.png)
![Seller vs customer share by region](charts/15_seller_customer_share_by_region.png)

- 3,088 of 3,095 sellers (99.8%) can be located.
- SP hosts 59.7% of sellers and 41.9% of customers.
- Seller share is above customer share in the Southeast (73.9% vs 68.6%) and South (21.6% vs 14.2%), and below it in the Northeast (1.8% vs 9.5%), Center-West (2.6% vs 5.8%) and North (0.16% vs 1.9%).
- Customers per seller: North 359, Northeast 163, Center-West 71, Southeast 29, South 20.

### 3.3 Shipping flows
![Shipping flow](charts/16_shipping_flow_by_region.png)
![Category destination](charts/17_category_destination_region.png)

- 83.5% of shipments leave from the Southeast; Southeast → Southeast alone is 58.4%.
- 35.9% of shipments stay within one state.
- Destination mix differs by category: `telephony` sends 15.4% of shipments to the Northeast (all categories: 9.4%); `bed_bath_table` sends 75.8% to the Southeast (all: 68.6%).
- Median shipping distance among the top 15 categories ranges from 379 km (`housewares`, `toys`) to 506 km (`computers_accessories`).

## 4. Order Value

### 4.1 Distance vs order value
![Distance vs order value](charts/18_distance_vs_order_value.png)

- Freight rises with distance: median R$ 10 (< 100 km) to R$ 30 (≥ 2,000 km); Spearman ρ = 0.58.
- Product value per shipment shows a weak association with distance (ρ = 0.11; median within-category ρ also 0.11). Its median is R$ 67 below 100 km and R$ 87–100 beyond.

### 4.2 Mean vs median by category
![Category mean vs median](charts/19_category_order_value_mean_median.png)

- In all top-20 categories the mean product value per order is above the median (ratio 1.25× to 2.82×); across all orders the median is R$ 87 and the mean R$ 137.
- The largest gaps are in `electronics` (median R$ 22, mean R$ 62, 2.82×) and `telephony` (R$ 30 vs R$ 77, 2.57×).
- Highest median: `office_furniture` R$ 160; lowest: `electronics` R$ 22.

### 4.3 Single-order spend by region
![Region order value](charts/20_region_order_value.png)

- Median payment per order: North R$ 142, Northeast R$ 130, Center-West R$ 114, South R$ 108, Southeast R$ 100.
- Orders per customer are similar in every region (1.027–1.035), so the regional ranking of spend per customer matches the ranking of order value.
