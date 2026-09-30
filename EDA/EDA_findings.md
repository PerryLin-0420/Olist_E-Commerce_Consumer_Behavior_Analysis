# EDA Findings

**English** | [繁體中文](../docs/EDA_findings.zh-TW.md)

This document describes **what the data shows**. It reports observed patterns only and does not claim causes; any "why" is left for later hypothesis testing.

- Source: `DB/olist.duckdb` built by `ETL_scripts/Auto_ETL.bat`
- Scripts: `EDA/scipts/01_*.py` – `08_*.py` and `random_forest/scripts/04_*.py` – `07_*.py`; charts in `EDA/charts/` and `random_forest/charts/`, tables in the matching `outputs/` folders
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

- At customer level, 97.0% of buying customers placed only one valid order (97.8% when same-day orders are merged into one purchase date, see 5.1).
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

## 5. Customer Activity

Scripts: `random_forest/scripts/04_*.py` – `07_*.py`; charts in `random_forest/charts/`.

### 5.1 Purchase count and the active cut-off
![Purchase distribution](../random_forest/charts/activity_purchase_distribution.png)

- Purchase count = distinct purchase dates per customer (any seller). 823 of 2,888 multi-order customers placed all of their orders on one day, and a quarter of the gaps between consecutive orders are under 7 minutes.
- Active = purchases on ≥ 2 dates: 2,065 customers (2.17%); one-time: 92,925.
- A two-component geometric mixture fits the distribution far better than one geometric distribution (likelihood ratio 409): 99.05% of customers buy again with probability 1.9%, 0.95% with probability 36.2%.

### 5.2 Active vs one-time customers
![Effect sizes](../random_forest/charts/activity_effect_sizes.png)
![Review](../random_forest/charts/active_vs_one_time_review.png)
![Spend](../random_forest/charts/active_vs_one_time_spend.png)

- Large differences appear only in features that grow with the number of purchases (orders, sellers, categories, total spend). All other features differ negligibly (|Cliff's δ| ≤ 0.13): order value, item price, freight ratio, distance, delivery time, category mix, payment and review.
- 5-star share: one-time 58.1%, active customers' first purchase 63.0%, later purchases 65.7% (Cliff's δ 0.05–0.08).
- Median spend per purchase: R$ 106 (one-time) and R$ 107 (active, first and later purchases).
- Segmenting active customers with a random forest gives lower separation and stability than same-size random samples of one-time customers on all four quality metrics.

### 5.3 Location
![Activity geography](../random_forest/charts/activity_geography_map.png)

- State shares of active and one-time customers correlate at 0.9988; state × tier chi-square p = 0.093, Cramér's V = 0.019.
- Active rate by region: Southeast 2.30%, South 2.06%, Center-West 1.98%, North 1.80%, Northeast 1.63% (region × tier p = 0.0005, Cramér's V = 0.015).

## 6. Purchases Over Time

### 6.1 Weekly volume
![Weekly purchases](charts/21_weekly_purchases_by_category.png)
![All categories](charts/24_weekly_orders_all_categories.png)

- Weekly orders averaged 853 in 2017 and 1,571 in January–August 2018.
- Two spike weeks stand out (robust z ≥ 3 vs the centered 9-week rolling median): 2017-11-20 with 2,972 orders (×2.3) and 2017-11-27 with 2,077 (×1.6). The next highest week has z = 2.6.
- In the 2017-11-20 week 2,881 of 2,931 customers were new; returning customers are 2.2% of weekly customers across the whole period.
- 38 of 74 categories reach ≥ ×1.5 their own rolling baseline in the spike weeks.

### 6.2 Price and volume
![Price and volume](charts/25_weekly_price_volume.png)

- Mean order value: R$ 155 in the spike weeks vs R$ 161 in other weeks; median R$ 103 vs R$ 104.
- Spearman ρ between weekly orders and weekly mean order value: −0.07.

### 6.3 Spike-week buyers
![Cohort repurchase](charts/22_cohort_repurchase_by_week.png)
![Spike category mix](charts/23_spike_category_mix.png)

- 180-day repurchase rate: 1.70% [1.37–2.10] for customers whose first purchase fell in a spike week vs 2.02% [1.91–2.15] for other weeks (difference −0.33 pp, p = 0.13).
- Category shares rising most in the spike weeks: `toys` 3.7% → 7.7%, `garden_tools` 3.4% → 5.7%, `perfumery` 3.1% → 4.3%.

## 7. Repeat Buyers

### 7.1 Funnel
![Purchase funnel](charts/26_purchase_funnel.png)

- Customers reaching each purchase: 94,990 → 2,065 → 156 → 32 → 14 → 8 → 3 → 1 (maximum 16 purchase dates).
- Step conversion: 2.2% from the 1st to the 2nd purchase, then 7.6%, 20.5%, 43.8%, 57.1%.

### 7.2 Spend and category by purchase number
![Spend by purchase](charts/27_repeat_spend_by_purchase.png)
![Category by purchase](charts/28_repeat_category_by_purchase.png)

- Same 2,065 customers, 1st vs 2nd purchase: median R$ 107 → R$ 108, 48.3% spent more the second time, Wilcoxon signed-rank p = 0.50.
- The category mix of 1st and 2nd purchases is close (e.g. `bed_bath_table` 12.3% → 12.1%, `sports_leisure` 9.8% → 9.4%).
- 35–41% of repeat purchases are in the same category as the purchase before.

## 8. Freight, Value, Distance and Weight

### 8.1 Freight share by product value
![Value vs freight ratio](charts/29_category_value_vs_freight_ratio.png)

- Median freight per shipment R$ 17.07, median product value R$ 84.99.
- Spearman ρ between product value and freight ratio: −0.71 across 32 categories, −0.78 across 99,542 shipments.
- Median freight ratio: `electronics` 63% (median value R$ 22), `telephony` 44% (R$ 30), `watches_gifts` 11% (R$ 140).

### 8.2 Freight by distance and weight
![Freight vs distance](charts/30_freight_vs_distance_by_weight.png)

- Freight rises with distance in every weight tier. Straight-line fits of the binned medians: < 0.5 kg R$ 11.7 + R$ 0.60 per 100 km; 0.5–2 kg R$ 12.0 + R$ 0.88; 2–10 kg R$ 18.4 + R$ 1.08; ≥ 10 kg R$ 38.9 + R$ 2.53.
- Spearman ρ between distance and freight: 0.58 overall, 0.78 to 0.41 from the lightest to the heaviest tier.

### 8.3 Distance mix by category
![Distance mix](charts/31_category_distance_mix.png)
![Far share](charts/32_far_share_vs_value_and_weight.png)

- Share of shipments ≥ 1,000 km ranges from 8.5% (`bed_bath_table`) to 23.9% (`telephony`).
- Across categories, the far share correlates with median weight at ρ = −0.37, with median product value at +0.08 and with freight ratio at −0.06.
