"""Step 05: segment active customers with the unsupervised random forest.

Active customers come from step 04: purchases on >= ACTIVE_MIN_PURCHASE_DAYS
distinct dates with any seller (platform re-use). On top of the
customer features from step 01 they get repeat-behaviour features, computed
over purchase occasions (distinct purchase dates):
- mean_gap_days, median_gap_days: days between consecutive purchase occasions
- tenure_days: first to last purchase occasion
- repeat_category_share: share of later occasions that include a category
  bought on an earlier occasion
- repeat_seller_share: same, for sellers
- spend_trend: last occasion spend / first occasion spend
- spend_cv: std / mean of spend across occasions

The segmentation quality (silhouette, seed-stability ARI, supervised OOB
accuracy) tells whether active customers split into distinct types.

A baseline repeats the same pipeline on N_BASELINE random samples of one-time
customers of the same size and features, to separate "active customers have
no distinct types" from "this many rows are too few to find any".

Outputs: outputs/active_customer_*.csv (incl. _features, _baseline);
charts/active_customer_cluster_profile.png, active_customer_feature_importance.png,
active_customer_vs_baseline.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import adjusted_rand_score

from rf_common import FEATURE_DIR, N_TREES, OUTPUT_DIR, RANDOM_STATE, STABILITY_SEED
from rf_segment import run_segmentation, segment
from eda_utils import (DPI, INK_2, OTHER, SERIES, SURFACE, connect, legend,  # noqa: E402
                       save, save_table, set_titles, style_axes)

MIN_LEAF = 5               # ~2K real rows, same leaf size as the ~3K sellers
MIN_CLUSTER_SHARE = 0.05   # every segment keeps >= 5% of active customers
N_BASELINE = 5             # random same-size samples of one-time customers

OCCASION_SQL = """
SELECT c.customer_unique_id,
       CAST(o.order_purchase_timestamp AS DATE) AS purchase_date,
       coalesce(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
       i.seller_id
FROM orders o
JOIN customers c USING (customer_id)
JOIN order_items i USING (order_id)
JOIN products p USING (product_id)
LEFT JOIN product_category_name_translation t USING (product_category_name)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
ORDER BY 1, 2
"""

SPEND_SQL = """
SELECT c.customer_unique_id, CAST(o.order_purchase_timestamp AS DATE) AS purchase_date,
       sum(p.payment_value) AS spend
FROM orders o
JOIN customers c USING (customer_id)
JOIN order_payments p USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2
ORDER BY 1, 2
"""


def repeat_share(occasions: pd.DataFrame, col: str) -> float:
    """Share of later occasions containing a value of `col` seen on an earlier one."""
    seen, hits, later = set(), 0, 0
    for i, (_, g) in enumerate(occasions.groupby("purchase_date", sort=True)):
        values = set(g[col])
        if i > 0:
            later += 1
            hits += bool(values & seen)
        seen |= values
    return hits / later if later else np.nan


def activity_features(items: pd.DataFrame, spend: pd.DataFrame) -> pd.DataFrame:
    rows = []
    spend_by_customer = dict(tuple(spend.groupby("customer_unique_id")))
    for cid, g in items.groupby("customer_unique_id"):
        paid = spend_by_customer.get(cid, spend.iloc[0:0]).sort_values("purchase_date")
        # Some occasions only have payments (orders without items), so use both sources
        dates = np.union1d(g["purchase_date"].to_numpy(dtype="datetime64[D]"),
                           paid["purchase_date"].to_numpy(dtype="datetime64[D]"))
        gaps = np.diff(dates).astype("timedelta64[D]").astype(float)
        s = paid["spend"]
        rows.append({
            "customer_unique_id": cid,
            "mean_gap_days": gaps.mean() if len(gaps) else np.nan,
            "median_gap_days": np.median(gaps) if len(gaps) else np.nan,
            "tenure_days": float((dates[-1] - dates[0]).astype("timedelta64[D]").astype(float)),
            "repeat_category_share": repeat_share(g, "category"),
            "repeat_seller_share": repeat_share(g, "seller_id"),
            "spend_trend": s.iloc[-1] / s.iloc[0] if len(s) and s.iloc[0] else np.nan,
            "spend_cv": s.std() / s.mean() if len(s) > 1 else np.nan,
        })
    return pd.DataFrame(rows)


def main() -> None:
    activity = pd.read_csv(OUTPUT_DIR / "customer_activity.csv")
    active_ids = set(activity.loc[activity["tier"] == "active", "customer_unique_id"])

    con = connect()
    items = con.execute(OCCASION_SQL).df()
    spend = con.execute(SPEND_SQL).df()
    con.close()
    items = items[items["customer_unique_id"].isin(active_ids)]
    spend = spend[spend["customer_unique_id"].isin(active_ids)]
    items["purchase_date"] = pd.to_datetime(items["purchase_date"]).values.astype("datetime64[D]")
    spend["purchase_date"] = pd.to_datetime(spend["purchase_date"])

    base = pd.read_csv(FEATURE_DIR / "customer_features.csv")
    feats = base[base["customer_unique_id"].isin(active_ids)].merge(
        activity[["customer_unique_id", "purchase_days"]], on="customer_unique_id") \
        .merge(activity_features(items, spend), on="customer_unique_id") \
        .sort_values("customer_unique_id").reset_index(drop=True)
    save_table(feats, "active_customer_features")

    X = feats.drop(columns=["customer_unique_id", "customer_state"])
    X = X.fillna(X.median())
    print(f"active customers: {len(X)}; features: {X.shape[1]}")
    print(feats[["purchase_days", "mean_gap_days", "tenure_days", "repeat_category_share",
                 "repeat_seller_share"]].describe().round(2).to_string())
    run_segmentation("active_customer", "Active customer", feats[["customer_unique_id"]], X,
                     "A", MIN_LEAF, MIN_CLUSTER_SHARE)
    baseline_comparison(base, activity, active_ids)


def evaluate(X: pd.DataFrame) -> dict:
    """Segmentation quality metrics for one feature matrix (same settings as above)."""
    X = X.fillna(X.median()).reset_index(drop=True)
    labels, k_table, oob, _ = segment(X, MIN_LEAF, RANDOM_STATE,
                                      min_cluster_share=MIN_CLUSTER_SHARE)
    chosen = k_table.loc[k_table["chosen"]].iloc[0]
    alt, *_ = segment(X, MIN_LEAF, STABILITY_SEED, int(chosen["k"]), MIN_CLUSTER_SHARE)
    sup = RandomForestClassifier(n_estimators=N_TREES, oob_score=True,
                                 random_state=RANDOM_STATE).fit(X, labels)
    return {"k": int(chosen["k"]), "oob_real_vs_synthetic": oob,
            "silhouette": chosen["silhouette"],
            "seed_stability_ari": adjusted_rand_score(labels, alt),
            "supervised_oob_accuracy": sup.oob_score_}


def baseline_comparison(base: pd.DataFrame, activity: pd.DataFrame, active_ids: set) -> None:
    """Compare active customers with same-size random samples of one-time customers.

    Both use only the shared customer features, so a difference reflects the
    customers rather than the extra repeat-behaviour features or sample size.
    """
    cols = base.columns.drop(["customer_unique_id", "customer_state"])
    active = base[base["customer_unique_id"].isin(active_ids)]
    one_time_ids = set(activity.loc[activity["tier"] == "one_time", "customer_unique_id"])
    one_time = base[base["customer_unique_id"].isin(one_time_ids)]
    rows = [{"group": "active", "sample": 0, **evaluate(active[cols])}]
    for s in range(N_BASELINE):
        sample = one_time.sample(len(active), random_state=RANDOM_STATE + s)
        rows.append({"group": "one_time_random", "sample": s + 1, **evaluate(sample[cols])})
    table = pd.DataFrame(rows)
    save_table(table, "active_customer_baseline")
    chart_baseline(table, len(active))
    print(table.round(3).to_string(index=False))


def chart_baseline(table: pd.DataFrame, n: int) -> None:
    metrics = [("oob_real_vs_synthetic", "Real vs synthetic OOB accuracy"),
               ("silhouette", "Silhouette"),
               ("seed_stability_ari", "Seed-stability ARI"),
               ("supervised_oob_accuracy", "Supervised OOB accuracy on segments")]
    act = table[table["group"] == "active"].iloc[0]
    ref = table[table["group"] == "one_time_random"]
    height = 170 + 90 * len(metrics) + 40
    fig = plt.figure(figsize=(1300 / DPI, height / DPI), dpi=DPI)
    for i, (col, title) in enumerate(metrics):
        y0 = 1 - (170 + 90 * (i + 1) - 25) / height
        ax = fig.add_axes([0.3, y0, 0.62, 40 / height])
        style_axes(ax, "x")
        ax.spines["left"].set_visible(False)
        hi = max(0.06, table[col].max() * 1.3) if col == "silhouette" else 1
        ax.set_xlim(0, hi)
        ax.set_ylim(-0.5, 0.5)
        ax.set_yticks([])
        ax.plot(ref[col], np.zeros(len(ref)), "o", color=OTHER, markersize=8 * 72 / DPI + 2,
                markeredgecolor=SURFACE, markeredgewidth=2 * 72 / DPI, zorder=3)
        ax.plot([act[col]], [0], "o", color=SERIES[0], markersize=9 * 72 / DPI + 2,
                markeredgecolor=SURFACE, markeredgewidth=2 * 72 / DPI, zorder=4)
        ax.text(act[col], 0.42, f"{act[col]:.3f}", ha="center", va="bottom", fontsize=8,
                color=INK_2)
        fig.text(0.02, y0 + 20 / height, f"{title}\nrandom mean {ref[col].mean():.3f}",
                 fontsize=8.5, color=INK_2, va="center")
    legend(fig, [f"Active customers (n={n})", f"Random one-time samples (n={n} each)"],
           [SERIES[0], OTHER], y_px_from_top=100, left=0.02)
    lower = sum(act[c] < ref[c].mean() for c, _ in metrics)
    set_titles(fig, "Is there more structure among active customers than among random ones?",
               f"Same {len(metrics)} quality metrics, same settings and "
               f"features; higher = clearer segments. Active customers score below the random "
               f"mean on {lower} of {len(metrics)}", left=0.02)
    save(fig, "active_customer_vs_baseline")


if __name__ == "__main__":
    main()
