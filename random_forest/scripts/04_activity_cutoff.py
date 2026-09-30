"""Step 04: split customers into active / one-time and compare the two tiers.

Purchase count = distinct purchase dates per customer across all sellers
(valid orders). Orders placed on the same day are one purchase occasion:
28.5% of multi-order customers placed all of their orders on a single day,
and a quarter of the gaps between consecutive orders are under 7 minutes
(split checkouts).

Tiers follow the business rule in rf_common.ACTIVE_MIN_PURCHASE_DAYS: a
customer who purchased on more than one date re-uses the platform (with any
seller) and is active; everyone else is one-time.

For reference, the distribution is also fitted with a two-component geometric
mixture:
    P(k) = w * (1 - p1) * p1^(k-1) + (1 - w) * (1 - p2) * p2^(k-1)
where p is the probability of buying again after each purchase (one-off vs
repeat buyers). The smallest k whose posterior probability of belonging to the
repeat component exceeds 0.5 is reported as the statistical cut-off; it does
not define the tiers.

Tiers are then compared on every customer feature: medians plus Cliff's
delta (active vs one-time), with Romano et al. thresholds (< 0.147
negligible, < 0.33 small, < 0.474 medium, otherwise large). Features that grow
mechanically with the number of purchases (MECHANICAL) are flagged, since a
difference there follows from the tier definition itself.

Outputs: outputs/customer_activity.csv, activity_distribution_fit.csv,
activity_cutoff.csv, activity_tier_comparison.csv;
charts/activity_purchase_distribution.png, activity_tier_comparison.png,
activity_effect_sizes.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from rf_common import ACTIVE_MIN_PURCHASE_DAYS, FEATURE_DIR
from eda_utils import (BASELINE, DPI, GRID, INK_2, MUTED, OTHER, SERIES,  # noqa: E402
                       SURFACE, WHISKER_NOTE, box_legend, box_rows, connect, fmt_brl, legend,
                       new_figure, save, save_table, set_titles, style_axes)

POSTERIOR_THRESHOLD = 0.5
MAX_BIN = 8  # counts >= MAX_BIN are shown as one "8+" bin in the chart
TIERS = ["one_time", "active"]
MECHANICAL = {"n_orders", "orders_per_year", "n_sellers", "n_categories", "total_spend",
              "recency_days"}
COMPARE = [("avg_order_payment", "Avg spend per order (BRL)", fmt_brl),
           ("avg_order_product_value", "Avg product value per order (BRL)", fmt_brl),
           ("avg_item_price", "Avg item price (BRL)", fmt_brl),
           ("freight_ratio", "Freight / product value", lambda v: f"{v:.2f}"),
           ("avg_distance_km", "Avg seller distance (km)", lambda v: f"{v:,.0f}"),
           ("avg_delivery_days", "Avg delivery days", lambda v: f"{v:.1f}")]

PURCHASE_SQL = """
SELECT c.customer_unique_id,
       count(DISTINCT o.order_id) AS n_orders,
       count(DISTINCT CAST(o.order_purchase_timestamp AS DATE)) AS purchase_days
FROM orders o JOIN customers c USING (customer_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1
ORDER BY 1
"""


def geometric(k, p):
    return (1 - p) * p ** (k - 1)


def fit_mixture(k: np.ndarray, n: np.ndarray, iters: int = 5000) -> dict:
    """EM for a two-component geometric mixture on k >= 1 (component 2 = repeat)."""
    w, p1, p2 = 0.9, 0.01, 0.3
    for _ in range(iters):
        a, b = w * geometric(k, p1), (1 - w) * geometric(k, p2)
        r = b / (a + b)
        w = ((1 - r) * n).sum() / n.sum()
        p1 = ((1 - r) * n * (k - 1)).sum() / ((1 - r) * n * k).sum()
        p2 = (r * n * (k - 1)).sum() / (r * n * k).sum()
    a, b = w * geometric(k, p1), (1 - w) * geometric(k, p2)
    p0 = (n * (k - 1)).sum() / (n * k).sum()  # single geometric MLE
    ll_mix = (n * np.log(a + b)).sum()
    ll_one = (n * np.log(geometric(k, p0))).sum()
    return {"w_one_time": w, "p_one_time": p1, "w_repeat": 1 - w, "p_repeat": p2,
            "p_single": p0, "loglik_mixture": ll_mix, "loglik_single": ll_one,
            "likelihood_ratio": 2 * (ll_mix - ll_one)}


def posterior_repeat(k, fit):
    a = fit["w_one_time"] * geometric(k, fit["p_one_time"])
    b = fit["w_repeat"] * geometric(k, fit["p_repeat"])
    return b / (a + b)


def cliffs_delta(x: pd.Series, y: pd.Series) -> float:
    u = mannwhitneyu(x, y, alternative="two-sided").statistic
    return 2 * u / (len(x) * len(y)) - 1


def magnitude(d: float) -> str:
    d = abs(d)
    return "negligible" if d < 0.147 else "small" if d < 0.33 else "medium" if d < 0.474 else "large"


def chart_distribution(dist: pd.DataFrame, fit: dict, cutoff: int, mixture_cutoff: int) -> None:
    fig = plt.figure(figsize=(1600 / DPI, 640 / DPI), dpi=DPI)
    ax1 = fig.add_axes([0.07, 0.13, 0.42, 0.62])
    ax2 = fig.add_axes([0.57, 0.13, 0.4, 0.62])
    x = np.arange(len(dist))
    labels = dist["bin"].tolist()

    style_axes(ax1, "y")
    ax1.set_yscale("log")
    ax1.plot(x, dist["single_expected"].where(dist["single_expected"] >= 0.1), color=SERIES[2],
             linewidth=2 * 72 / DPI, label="Single geometric fit", zorder=2)
    ax1.plot(x, dist["mixture_expected"], color=SERIES[1], linewidth=2 * 72 / DPI,
             label="Two-component mixture fit", zorder=3)
    ax1.plot(x, dist["customers"], "o", color=SERIES[0], markersize=8 * 72 / DPI + 2,
             markeredgecolor=SURFACE, markeredgewidth=2 * 72 / DPI, label="Observed", zorder=4)
    for xi, v in zip(x, dist["customers"]):
        ax1.annotate(f"{v:,}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center",
                     fontsize=8, color=INK_2)
    ax1.set_xticks(x, labels)
    ax1.set_xlim(-0.5, len(x) - 0.5)
    ax1.set_ylim(0.3, dist["customers"].max() * 4)
    ax1.yaxis.set_major_formatter(lambda y, _: f"{y:,.0f}")
    ax1.set_xlabel("Purchase days per customer", labelpad=6)
    ax1.set_ylabel("Customers (log scale)", labelpad=6)
    ax1.legend(loc="upper right", frameon=False, fontsize=8.5, labelcolor=INK_2)

    style_axes(ax2, "y")
    post = dist["posterior_repeat"]
    colors = [SERIES[0] if b_ >= cutoff else "#b4b2a9" for b_ in dist["k_min"]]
    ax2.bar(x, post, width=0.5, color=colors)
    ax2.axhline(POSTERIOR_THRESHOLD, color=MUTED, linewidth=1 * 72 / DPI)
    ax2.text(-0.45, POSTERIOR_THRESHOLD + 0.02, f"threshold {POSTERIOR_THRESHOLD:.1f}",
             ha="left", va="bottom", fontsize=8, color=MUTED)
    for xi, v in zip(x, post):
        ax2.text(xi, v + 0.02, f"{v:.0%}" if v >= 0.01 else f"{v:.1%}", ha="center",
                 va="bottom", fontsize=8, color=INK_2)
    ax2.set_xticks(x, labels)
    ax2.set_xlim(-0.5, len(x) - 0.5)
    ax2.set_ylim(0, 1.12)
    ax2.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
    ax2.set_xlabel("Purchase days per customer", labelpad=6)
    ax2.set_ylabel("P(repeat-buyer component)", labelpad=6)

    fig.text(0.07, 0.8, "Distribution and model fits", fontsize=9.5, fontweight="semibold",
             color=INK_2)
    fig.text(0.57, 0.8, f"Posterior of the repeat component (blue = active, ≥ {cutoff})",
             fontsize=9.5, fontweight="semibold", color=INK_2)
    active = int(dist.loc[dist["k_min"] >= cutoff, "customers"].sum())
    set_titles(fig, "Purchase days per customer and the active cut-off",
               f"Active = purchases on ≥ {cutoff} dates with any seller ({active:,} customers). "
               f"Reference: a two-component geometric mixture (one-off {fit['w_one_time']:.2%}, "
               f"buy again {fit['p_one_time']:.1%};\nrepeat {fit['w_repeat']:.2%}, buy again "
               f"{fit['p_repeat']:.1%}; likelihood ratio vs one geometric "
               f"{fit['likelihood_ratio']:.0f}) crosses the 0.5 posterior at {mixture_cutoff} "
               "purchase days", left=0.07)
    save(fig, "activity_purchase_distribution")


def chart_tiers(merged: pd.DataFrame, comparison: pd.DataFrame, cutoff: int) -> None:
    n_tier = merged["tier"].value_counts().reindex(TIERS)
    tier_labels = {"one_time": f"One-time (1)\nn={n_tier['one_time']:,}",
                   "active": f"Active (≥ {cutoff})\nn={n_tier['active']:,}"}
    cols, rows_n = 3, int(np.ceil(len(COMPARE) / 3))
    height = 180 + rows_n * 270
    fig = plt.figure(figsize=(1600 / DPI, height / DPI), dpi=DPI)
    for i, (feat, title, fmt) in enumerate(COMPARE):
        r, c = divmod(i, cols)
        x0 = 0.11 + c * 0.305
        y0 = 1 - (180 + (r + 1) * 270 - 70) / height
        ax = fig.add_axes([x0, y0, 0.2, 150 / height])
        style_axes(ax, "x")
        data = [merged.loc[merged["tier"] == t, feat].dropna() for t in TIERS]
        box_rows(ax, [tier_labels[t] if c == 0 else "" for t in TIERS], data)
        ax.tick_params(axis="y", labelsize=7.5)
        ax.xaxis.set_major_formatter(lambda v, _, f=fmt: f(v))
        ax.tick_params(axis="x", labelsize=7.5)
        row = comparison.set_index("feature").loc[feat]
        fig.text(x0, y0 + 150 / height + 12 / height,
                 f"{title}\nCliff's δ active vs one-time {row['cliffs_delta']:+.2f} "
                 f"({row['magnitude']})", fontsize=8.5, color=INK_2, va="bottom")
    box_legend(fig, 0.11, 108)
    shown = comparison.set_index("feature").loc[[f for f, *_ in COMPARE]]
    big = shown.index[shown["magnitude"].isin(["medium", "large"])].tolist()
    set_titles(fig, "Do active customers differ from one-time customers per order?",
               f"Per-customer averages by activity tier; {WHISKER_NOTE}. "
               f"Medium or large differences among these: {', '.join(big) if big else 'none'}",
               left=0.11)
    save(fig, "activity_tier_comparison")


def chart_effect_sizes(comparison: pd.DataFrame, cutoff: int) -> None:
    d = comparison.sort_values("cliffs_delta", key=abs, ascending=False).reset_index(drop=True)
    n = len(d)
    height = 170 + 24 * n + 75
    fig, ax = new_figure(1400, height, left=0.3, right=0.9, top=1 - 170 / height,
                         bottom=75 / height)
    style_axes(ax, "x")
    ax.spines["left"].set_visible(False)
    ax.axvline(0, color=BASELINE, linewidth=1 * 72 / DPI)
    for x in (-0.474, -0.33, -0.147, 0.147, 0.33, 0.474):
        ax.axvline(x, color=GRID, linewidth=1 * 72 / DPI, zorder=0)
    colors = [OTHER if m else SERIES[0] for m in d["mechanical"]]
    ax.barh(range(n), d["cliffs_delta"], height=14 / 24, color=colors)
    for i, (v, mag) in enumerate(zip(d["cliffs_delta"], d["magnitude"])):
        ax.text(v + (0.015 if v >= 0 else -0.015), i, f"{v:+.2f} {mag}", va="center",
                ha="left" if v >= 0 else "right", fontsize=7.5, color=INK_2)
    ax.set_yticks(range(n), d["feature"])
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_xlim(-1.15, 1.25)
    ax.grid(False)
    ax.set_xlabel("Cliff's δ (active vs one-time)", labelpad=6)
    legend(fig, ["Grows with purchase count by definition", "Other features"],
           [OTHER, SERIES[0]], y_px_from_top=122, left=0.3)
    other = d[~d["mechanical"]]
    notable = other[other["magnitude"] != "negligible"]
    set_titles(fig, f"Active (≥ {cutoff} purchase days) vs one-time customers: every feature",
               "Cliff's δ, thin lines at the small / medium / large thresholds (0.147, 0.33, "
               "0.474).\nNon-mechanical features beyond negligible: "
               + (", ".join(f"{f} ({v:+.2f})" for f, v in
                            zip(notable["feature"], notable["cliffs_delta"])) or "none"),
               left=0.02)
    save(fig, "activity_effect_sizes")


def main() -> None:
    con = connect()
    customers = con.execute(PURCHASE_SQL).df()
    con.close()

    counts = customers["purchase_days"].value_counts().sort_index()
    k, n = counts.index.to_numpy(), counts.to_numpy(dtype=float)
    fit = fit_mixture(k, n)
    post = posterior_repeat(k, fit)
    mixture_cutoff = int(k[post > POSTERIOR_THRESHOLD].min())  # reference only
    cutoff = ACTIVE_MIN_PURCHASE_DAYS

    customers["posterior_repeat"] = posterior_repeat(customers["purchase_days"].to_numpy(), fit)
    customers["tier"] = np.where(customers["purchase_days"] >= cutoff, "active", "one_time")
    save_table(customers, "customer_activity")

    # Fit table, with the long tail folded into one bin for display
    total = n.sum()
    bins = list(range(1, MAX_BIN)) + [MAX_BIN]
    rows = []
    for b in bins:
        mask = k >= b if b == MAX_BIN else k == b
        ks = np.arange(b, 200) if b == MAX_BIN else np.array([b])
        mix = (fit["w_one_time"] * geometric(ks, fit["p_one_time"])
               + fit["w_repeat"] * geometric(ks, fit["p_repeat"])).sum() * total
        rows.append({"bin": f"{b}+" if b == MAX_BIN else str(b), "k_min": b,
                     "customers": int(n[mask].sum()), "mixture_expected": mix,
                     "single_expected": geometric(ks, fit["p_single"]).sum() * total,
                     "posterior_repeat": float(posterior_repeat(b, fit))})
    dist = pd.DataFrame(rows)
    save_table(dist, "activity_distribution_fit")
    tier_n = customers["tier"].value_counts().reindex(TIERS)
    save_table(pd.DataFrame([{**fit, "posterior_threshold": POSTERIOR_THRESHOLD,
                              "cutoff_purchase_days": cutoff,
                              "mixture_cutoff_purchase_days": mixture_cutoff,
                              **{f"{t}_customers": int(tier_n[t]) for t in TIERS},
                              "multi_order_same_day_customers": int(
                                  ((customers["n_orders"] > 1)
                                   & (customers["purchase_days"] == 1)).sum())}]),
               "activity_cutoff")
    chart_distribution(dist, fit, cutoff, mixture_cutoff)

    feats = pd.read_csv(FEATURE_DIR / "customer_features.csv")
    merged = feats.merge(customers[["customer_unique_id", "tier"]], on="customer_unique_id")
    comp = []
    for feat in feats.columns.drop(["customer_unique_id", "customer_state"]):
        groups = {t: merged.loc[merged["tier"] == t, feat].dropna() for t in TIERS}
        d = cliffs_delta(groups["active"], groups["one_time"])
        comp.append({"feature": feat, **{f"{t}_median": groups[t].median() for t in TIERS},
                     **{f"{t}_mean": groups[t].mean() for t in TIERS},
                     "cliffs_delta": d, "magnitude": magnitude(d),
                     "mechanical": feat in MECHANICAL})
    comparison = pd.DataFrame(comp).sort_values("cliffs_delta", key=abs, ascending=False)
    save_table(comparison, "activity_tier_comparison")
    chart_tiers(merged, comparison, cutoff)
    chart_effect_sizes(comparison, cutoff)

    print(f"cut-off: {cutoff} purchase days (mixture reference: {mixture_cutoff}); "
          f"tiers: {tier_n.to_dict()}")
    print(comparison[["feature", "cliffs_delta", "magnitude", "mechanical"]].head(10)
          .round(3).to_string(index=False))


if __name__ == "__main__":
    main()
