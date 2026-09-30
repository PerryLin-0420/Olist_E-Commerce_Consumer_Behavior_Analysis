"""Shared paths, settings and the order loader for the weekday x hour analysis."""
import math
import sys
from pathlib import Path

import pandas as pd

TM_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = TM_DIR.parent
OUTPUT_DIR = TM_DIR / "outputs"
CHART_DIR = TM_DIR / "charts"

# Reuse the EDA chart style and DB helpers
sys.path.insert(0, str(PROJECT_DIR / "EDA" / "scipts"))
import eda_utils  # noqa: E402

eda_utils.CHART_DIR = CHART_DIR
eda_utils.OUTPUT_DIR = OUTPUT_DIR

RANDOM_STATE = 42
START_K = 10                  # the k the analysis started from; kept as a reference
K_RANGE = range(2, 16)
N_BOOT = 100                  # week-block bootstrap samples for the k selection
K_CHOICE_FILE = "k_choice.csv"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOURS = list(range(24))
# Weeks flagged as spikes in EDA/scipts/06_weekly_purchases.py (Black Friday and the week after)
SPIKE_WEEKS = [pd.Timestamp("2017-11-20"), pd.Timestamp("2017-11-27")]
# Periods used to check that the weekday x hour pattern holds across the timeline
PERIODS = [("2017 H1", "2017-01-01", "2017-07-01"), ("2017 H2", "2017-07-01", "2018-01-01"),
           ("2018 H1", "2018-01-01", "2018-07-01"), ("2018 Jul–Aug", "2018-07-01", "2018-09-01")]

# One row per valid order. installments = credit-card installments when > 1,
# otherwise 0 (paid in full: single credit-card payment, boleto, voucher, debit card)
ORDER_SQL = """
WITH pay AS (
    SELECT order_id,
           sum(payment_value) AS order_value,
           max(CASE WHEN payment_type = 'credit_card' AND payment_installments > 1
                    THEN payment_installments ELSE 0 END) AS installments,
           arg_max(payment_type, payment_value) AS main_payment_type
    FROM order_payments GROUP BY 1
),
items AS (
    SELECT i.order_id, count(*) AS items, sum(i.price) AS product_value,
           sum(i.freight_value) AS freight,
           first(coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
                 ORDER BY i.price DESC) AS category
    FROM order_items i
    JOIN products p USING (product_id)
    LEFT JOIN product_category_name_translation t USING (product_category_name)
    GROUP BY 1
),
rev AS (SELECT order_id, avg(review_score) AS review_score FROM order_reviews GROUP BY 1)
SELECT o.order_id, c.customer_unique_id, c.customer_state, o.order_purchase_timestamp AS purchased_at,
       pay.order_value, pay.installments, pay.main_payment_type,
       items.items, items.product_value, items.freight, items.category, rev.review_score
FROM orders o
JOIN customers c USING (customer_id)
JOIN pay USING (order_id)
LEFT JOIN items USING (order_id)
LEFT JOIN rev USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
ORDER BY o.order_purchase_timestamp, o.order_id
"""


def load_orders() -> pd.DataFrame:
    con = eda_utils.connect()
    df = con.execute(ORDER_SQL).df()
    con.close()
    df["weekday"] = df["purchased_at"].dt.weekday          # 0 = Monday
    df["hour"] = df["purchased_at"].dt.hour
    day = df["purchased_at"].dt.normalize()
    df["week"] = day - pd.to_timedelta(df["weekday"], "D")
    df["in_installments"] = (df["installments"] > 0).astype(float)
    df["freight_ratio"] = (df["freight"] / df["product_value"]).where(df["product_value"] > 0)
    df["spike_week"] = df["week"].isin(SPIKE_WEEKS)
    return df


def matrix(df: pd.DataFrame, value: str | None = None, agg: str = "mean") -> pd.DataFrame:
    """7 x 24 weekday x hour matrix; value=None counts orders."""
    if value is None:
        # Empty cells hold zero orders (not missing)
        m = df.groupby(["weekday", "hour"]).size()
        return m.unstack("hour").reindex(index=range(7), columns=HOURS, fill_value=0).fillna(0)
    m = df.groupby(["weekday", "hour"])[value].agg(agg)
    return m.unstack("hour").reindex(index=range(7), columns=HOURS)


def cell_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per weekday x hour cell with the behaviour metrics."""
    g = df.groupby(["weekday", "hour"])
    t = pd.DataFrame({
        "orders": g.size(),
        "mean_order_value": g["order_value"].mean(),
        "median_order_value": g["order_value"].median(),
        "mean_installments": g["installments"].mean(),
        "installment_share": g["in_installments"].mean(),
        "boleto_share": g["main_payment_type"].apply(lambda s: (s == "boleto").mean()),
        "voucher_share": g["main_payment_type"].apply(lambda s: (s == "voucher").mean()),
        "items_per_order": g["items"].mean(),
        "median_freight_ratio": g["freight_ratio"].median(),
        "mean_review_score": g["review_score"].mean(),
    }).reindex(pd.MultiIndex.from_product([range(7), HOURS], names=["weekday", "hour"]))
    t["orders_share"] = t["orders"] / t["orders"].sum()
    return t


def cell_features(orders, value_sum, inst_sum, n_weeks: int) -> pd.DataFrame:
    """Clustering features per cell from order counts and sums (arrays of 168).

    log orders per week, mean order value, mean installments; a cell with no
    orders (possible in a bootstrap sample) gets the overall means.
    """
    orders = pd.Series(orders, dtype=float)
    X = pd.DataFrame({
        "log_orders_per_week": (orders.clip(lower=0.5) / n_weeks).map(math.log),
        "mean_order_value": pd.Series(value_sum, dtype=float) / orders.where(orders > 0),
        "mean_installments": pd.Series(inst_sum, dtype=float) / orders.where(orders > 0),
    })
    return X.fillna(X.mean())


def standardize(X: pd.DataFrame):
    return ((X - X.mean()) / X.std(ddof=0)).to_numpy()


def weekly_cell_sums(df: pd.DataFrame):
    """Per week x cell sums (weeks, 168) of orders, order value and installments."""
    cell = df["weekday"] * 24 + df["hour"]
    weeks = sorted(df["week"].unique())
    idx = pd.MultiIndex.from_product([weeks, range(168)], names=["week", "cell"])
    g = df.assign(cell=cell).groupby(["week", "cell"])
    sums = pd.DataFrame({"orders": g.size(), "value": g["order_value"].sum(),
                         "inst": g["installments"].sum()}).reindex(idx, fill_value=0)
    shape = (len(weeks), 168)
    return (weeks, sums["orders"].to_numpy().reshape(shape),
            sums["value"].to_numpy().reshape(shape), sums["inst"].to_numpy().reshape(shape))


def chosen_k() -> int:
    """The k picked by 02_k_selection.py."""
    return int(pd.read_csv(OUTPUT_DIR / K_CHOICE_FILE)["k"].iat[0])
