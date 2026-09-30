"""Step 01: build one feature row per seller and per customer.

Only valid orders (order_status not in canceled, unavailable) are used.
Customers are customer_unique_id. Locations are zip-prefix centroids.

Seller features
- location: seller_lat, seller_lng
- category mix: revenue share of the top categories + other, n_categories,
  top_category_share, category_entropy
- product size: avg_weight_g, avg_volume_cm3
- diversity: size_cv (std / mean of item volume), n_products, and
  diversity_index = mean percentile rank of category_entropy and size_cv
  (bigger spread in category and size = more diverse)
- sales: orders, revenue, avg_item_price, freight_ratio, active_months,
  orders_per_month
- service: avg_distance_km, out_of_state_share, avg_delivery_days, late_rate,
  avg_review_score, customer_repeat_rate

Customer features
- location: customer_lat, customer_lng
- category mix: spend share of the same top categories + other, n_categories
- value: avg_order_product_value (average purchase amount, product price only),
  avg_order_payment (average spend incl. freight), total_spend, avg_item_price,
  items_per_order
- frequency: n_orders, orders_per_year (orders / observed years, windows under
  one year count as one year), recency_days
- payment: avg_installments, credit_card_share, boleto_share, voucher_share
- experience: avg_review_score, avg_delivery_days, late_rate, freight_ratio,
  avg_distance_km, n_sellers
"""
import numpy as np
import pandas as pd

from rf_common import FEATURE_DIR, N_TOP_CATEGORIES  # also puts EDA/scipts on sys.path
from eda_utils import connect  # noqa: E402  (import order matters)

ITEM_SQL = """
SELECT o.order_id, i.order_item_id, i.seller_id, cu.customer_unique_id,
       cu.customer_state, se.seller_state,
       coalesce(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
       i.product_id, i.price, i.freight_value,
       p.product_weight_g AS weight_g,
       p.product_length_cm * p.product_height_cm * p.product_width_cm AS volume_cm3,
       o.order_purchase_timestamp AS purchased_at,
       o.order_delivered_customer_date AS delivered_at,
       o.order_estimated_delivery_date AS estimated_at,
       gc.geolocation_lat AS customer_lat, gc.geolocation_lng AS customer_lng,
       gs.geolocation_lat AS seller_lat, gs.geolocation_lng AS seller_lng
FROM orders o
JOIN customers cu USING (customer_id)
JOIN order_items i USING (order_id)
JOIN sellers se USING (seller_id)
JOIN products p USING (product_id)
LEFT JOIN product_category_name_translation t USING (product_category_name)
LEFT JOIN geolocation_zip gc ON gc.geolocation_zip_code_prefix = cu.customer_zip_code_prefix
LEFT JOIN geolocation_zip gs ON gs.geolocation_zip_code_prefix = se.seller_zip_code_prefix
WHERE o.order_status NOT IN ('canceled', 'unavailable')
ORDER BY o.order_id, i.order_item_id
"""

PAYMENT_SQL = """
SELECT p.order_id, p.payment_type, p.payment_installments, p.payment_value
FROM order_payments p JOIN orders o USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
"""

REVIEW_SQL = """
SELECT r.order_id, avg(r.review_score) AS review_score
FROM order_reviews r JOIN orders o USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1
"""


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def entropy(shares: pd.DataFrame) -> pd.Series:
    """Shannon entropy (nats) of each row of a share matrix."""
    p = shares.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return pd.Series(-(np.where(p > 0, p * np.log(p), 0)).sum(axis=1), index=shares.index)


def category_shares(items: pd.DataFrame, key: str, top: list[str]) -> pd.DataFrame:
    """Revenue share per top category (+ other) for each key."""
    cat = items["category"].where(items["category"].isin(top), "other")
    spend = items.assign(cat=cat).pivot_table(index=key, columns="cat", values="price",
                                              aggfunc="sum", fill_value=0)
    spend = spend.reindex(columns=top + ["other"], fill_value=0)
    shares = spend.div(spend.sum(axis=1), axis=0)
    return shares.add_prefix("cat_share_")


def order_level(items: pd.DataFrame, payments: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    orders = items.groupby("order_id").agg(
        customer_unique_id=("customer_unique_id", "first"),
        product_value=("price", "sum"), freight=("freight_value", "sum"),
        n_items=("order_item_id", "count"), purchased_at=("purchased_at", "first"),
        delivered_at=("delivered_at", "first"), estimated_at=("estimated_at", "first"))
    pay = payments.groupby("order_id").agg(payment=("payment_value", "sum"),
                                           installments=("payment_installments", "max"))
    orders = orders.join(pay).join(reviews.set_index("order_id"))
    orders["delivery_days"] = (orders["delivered_at"] - orders["purchased_at"]).dt.total_seconds() / 86400
    orders["late"] = (orders["delivered_at"] > orders["estimated_at"]).astype(float) \
        .where(orders["delivered_at"].notna())
    return orders


def seller_features(items: pd.DataFrame, orders: pd.DataFrame, top: list[str]) -> pd.DataFrame:
    g = items.groupby("seller_id")
    f = pd.DataFrame({
        "seller_lat": g["seller_lat"].first(),
        "seller_lng": g["seller_lng"].first(),
        "seller_state": g["seller_state"].first(),
        "orders": g["order_id"].nunique(),
        "items": g["order_item_id"].count(),
        "revenue": g["price"].sum(),
        "avg_item_price": g["price"].mean(),
        "freight_ratio": g["freight_value"].sum() / g["price"].sum(),
        "n_products": g["product_id"].nunique(),
        "n_categories": g["category"].nunique(),
        "avg_weight_g": g["weight_g"].mean(),
        "avg_volume_cm3": g["volume_cm3"].mean(),
        "size_cv": g["volume_cm3"].std() / g["volume_cm3"].mean(),
        "avg_distance_km": g["distance_km"].mean(),
        "out_of_state_share": g["out_of_state"].mean(),
    })
    f["size_cv"] = f["size_cv"].fillna(0)  # single-item sellers have no spread
    shares = category_shares(items, "seller_id", top)
    f["top_category_share"] = shares.max(axis=1)
    f["category_entropy"] = entropy(
        items.pivot_table(index="seller_id", columns="category", values="price",
                          aggfunc="sum", fill_value=0).pipe(lambda d: d.div(d.sum(axis=1), axis=0)))
    f["diversity_index"] = (f["category_entropy"].rank(pct=True) + f["size_cv"].rank(pct=True)) / 2

    # Order-level service metrics per seller (an order counts once per seller)
    so = items[["seller_id", "order_id", "customer_unique_id"]].drop_duplicates() \
        .join(orders[["delivery_days", "late", "review_score", "purchased_at"]], on="order_id")
    gs = so.groupby("seller_id")
    f["avg_delivery_days"] = gs["delivery_days"].mean()
    f["late_rate"] = gs["late"].mean()
    f["avg_review_score"] = gs["review_score"].mean()
    months = so["purchased_at"].dt.to_period("M")
    span = so.assign(m=months).groupby("seller_id")["m"].agg(lambda m: (m.max() - m.min()).n + 1)
    f["active_months"] = span
    f["orders_per_month"] = f["orders"] / f["active_months"]
    per_cust = so.groupby(["seller_id", "customer_unique_id"])["order_id"].nunique()
    f["customer_repeat_rate"] = (per_cust >= 2).groupby("seller_id").mean()
    return f.join(shares)


def customer_features(items: pd.DataFrame, orders: pd.DataFrame, payments: pd.DataFrame,
                      top: list[str], data_end: pd.Timestamp) -> pd.DataFrame:
    latest = items.sort_values("purchased_at").groupby("customer_unique_id").last()
    g = items.groupby("customer_unique_id")
    go = orders.groupby("customer_unique_id")
    f = pd.DataFrame({
        "customer_lat": latest["customer_lat"],
        "customer_lng": latest["customer_lng"],
        "customer_state": latest["customer_state"],
        "n_orders": go.size(),
        "avg_order_product_value": go["product_value"].mean(),
        "avg_order_payment": go["payment"].mean(),
        "total_spend": go["payment"].sum(),
        "avg_item_price": g["price"].mean(),
        "items_per_order": go["n_items"].mean(),
        "n_categories": g["category"].nunique(),
        "n_sellers": g["seller_id"].nunique(),
        "freight_ratio": g["freight_value"].sum() / g["price"].sum(),
        "avg_distance_km": g["distance_km"].mean(),
        "avg_installments": go["installments"].mean(),
        "avg_review_score": go["review_score"].mean(),
        "avg_delivery_days": go["delivery_days"].mean(),
        "late_rate": go["late"].mean(),
    })
    first, last = go["purchased_at"].min(), go["purchased_at"].max()
    observed_years = ((data_end - first).dt.days / 365.25).clip(lower=1)
    f["orders_per_year"] = f["n_orders"] / observed_years
    f["recency_days"] = (data_end - last).dt.days

    pay = payments.merge(orders[["customer_unique_id"]], left_on="order_id", right_index=True)
    by_type = pay.pivot_table(index="customer_unique_id", columns="payment_type",
                              values="payment_value", aggfunc="sum", fill_value=0)
    by_type = by_type.div(by_type.sum(axis=1), axis=0)
    for t in ["credit_card", "boleto", "voucher"]:
        f[f"{t}_share"] = by_type.get(t, 0)
    return f.join(category_shares(items, "customer_unique_id", top))


def main() -> None:
    con = connect()
    items = con.execute(ITEM_SQL).df()
    payments = con.execute(PAYMENT_SQL).df()
    reviews = con.execute(REVIEW_SQL).df()
    con.close()

    items["distance_km"] = haversine_km(items["seller_lat"], items["seller_lng"],
                                        items["customer_lat"], items["customer_lng"])
    items["out_of_state"] = (items["seller_state"] != items["customer_state"]).astype(float)
    top = items.groupby("category")["price"].sum().nlargest(N_TOP_CATEGORIES).index.tolist()
    data_end = items["purchased_at"].max()

    orders = order_level(items, payments, reviews)
    sellers = seller_features(items, orders, top)
    customers = customer_features(items, orders, payments, top, data_end)

    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    sellers.rename_axis("seller_id").reset_index().to_csv(
        FEATURE_DIR / "seller_features.csv", index=False)
    customers.rename_axis("customer_unique_id").reset_index().to_csv(
        FEATURE_DIR / "customer_features.csv", index=False)
    print(f"top categories: {top}")
    print(f"sellers: {len(sellers):,} rows x {sellers.shape[1]} columns")
    print(f"customers: {len(customers):,} rows x {customers.shape[1]} columns")
    for name, df in [("sellers", sellers), ("customers", customers)]:
        na = df.isna().mean()
        print(f"{name} columns with NaN: {na[na > 0].round(4).to_dict()}")


if __name__ == "__main__":
    main()
