"""Step 06: compare review score and spend between active and one-time customers.

Unit = purchase occasion (one customer, one purchase date; same-day orders merged):
- review score = mean score of the occasion's orders (each order's reviews averaged first)
- spend = total payment value of the occasion

Groups (tiers from step 04):
- one_time: the only occasion of a one-time customer
- active_first: the first occasion of an active customer (same position as one_time)
- active_repeat: every later occasion of an active customer

Statistics: score distribution (chi-square), share of 1 and 5 star with Wilson
95% intervals, median / mean spend with bootstrap 95% interval for the mean,
and Cliff's delta vs one_time. Customer level: each customer's average score
and average spend per occasion, active vs one-time.

Outputs: outputs/active_vs_one_time_occasions.csv, active_vs_one_time_summary.csv,
active_vs_one_time_score_dist.csv; charts/active_vs_one_time_review.png,
active_vs_one_time_spend.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
from scipy.stats import chi2_contingency, mannwhitneyu

from rf_common import OUTPUT_DIR, RANDOM_STATE
from eda_utils import (DPI, INK, INK_2, WHISKER_NOTE, box_legend, box_rows,  # noqa: E402
                       connect, fmt_brl, new_figure, save, save_table, set_titles, stacked_bar,
                       style_axes)

GROUPS = ["one_time", "active_first", "active_repeat"]
GROUP_LABELS = {"one_time": "One-time customers", "active_first": "Active: first purchase",
                "active_repeat": "Active: later purchases"}
# Diverging polarity: red (1 star) -> neutral gray (3) -> blue (5 stars)
SCORE_COLORS = ["#e34948", "#f0a3a2", "#c9c7c0", "#86b6ef", "#2a78d6"]
N_BOOT = 2000

OCCASION_SQL = """
WITH order_review AS (
    SELECT order_id, avg(review_score) AS review_score FROM order_reviews GROUP BY 1
),
order_pay AS (
    SELECT order_id, sum(payment_value) AS payment FROM order_payments GROUP BY 1
)
SELECT c.customer_unique_id,
       CAST(o.order_purchase_timestamp AS DATE) AS purchase_date,
       avg(r.review_score) AS review_score,
       sum(p.payment) AS spend
FROM orders o
JOIN customers c USING (customer_id)
LEFT JOIN order_review r USING (order_id)
LEFT JOIN order_pay p USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2
ORDER BY 1, 2
"""


def cliffs_delta(x, y) -> float:
    u = mannwhitneyu(x, y, alternative="two-sided").statistic
    return 2 * u / (len(x) * len(y)) - 1


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def bootstrap_mean_ci(values: np.ndarray, rng) -> tuple[float, float]:
    means = rng.choice(values, size=(N_BOOT, len(values)), replace=True).mean(axis=1) \
        if len(values) <= 5000 else np.array([rng.choice(values, len(values)).mean()
                                              for _ in range(N_BOOT)])
    return tuple(np.percentile(means, [2.5, 97.5]))


def summarize(occ: pd.DataFrame, rng) -> pd.DataFrame:
    base = occ[occ["group"] == "one_time"]
    rows = []
    for g in GROUPS:
        d = occ[occ["group"] == g]
        score = d["review_score"].dropna()
        spend = d["spend"].dropna()
        n_s = len(score)
        five, one = (score == 5).sum(), (score == 1).sum()
        lo5, hi5 = wilson(five, n_s)
        lo1, hi1 = wilson(one, n_s)
        mlo, mhi = bootstrap_mean_ci(spend.to_numpy(), rng)
        rows.append({
            "group": g, "occasions": len(d), "customers": d["customer_unique_id"].nunique(),
            "reviewed": n_s, "score_mean": score.mean(), "score_median": score.median(),
            "share_5_star": five / n_s, "share_5_star_lo": lo5, "share_5_star_hi": hi5,
            "share_1_star": one / n_s, "share_1_star_lo": lo1, "share_1_star_hi": hi1,
            "spend_median": spend.median(), "spend_mean": spend.mean(),
            "spend_mean_lo": mlo, "spend_mean_hi": mhi,
            "score_delta_vs_one_time": None if g == "one_time" else
            cliffs_delta(score, base["review_score"].dropna()),
            "spend_delta_vs_one_time": None if g == "one_time" else
            cliffs_delta(spend, base["spend"].dropna()),
        })
    return pd.DataFrame(rows)


def score_distribution(occ: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    """Share of each rounded score (1-5) per group, plus chi-square over all groups."""
    scored = occ.dropna(subset=["review_score"]).assign(
        star=lambda d: np.floor(d["review_score"] + 0.5).clip(1, 5).astype(int))
    counts = pd.crosstab(scored["group"], scored["star"]).reindex(index=GROUPS, columns=range(1, 6),
                                                                  fill_value=0)
    chi2, p, _, _ = chi2_contingency(counts.values)
    shares = counts.div(counts.sum(axis=1), axis=0)
    return shares, chi2, p


def chart_review(shares: pd.DataFrame, summary: pd.DataFrame, chi2: float, p: float) -> None:
    s = summary.set_index("group")
    labels = [f"{GROUP_LABELS[g]}\nn={int(s.loc[g, 'reviewed']):,}, mean {s.loc[g, 'score_mean']:.2f}"
              for g in GROUPS]
    stacks = [(shares[k] * 100).tolist() for k in range(1, 6)]
    height = 170 + 60 * len(GROUPS) + 60
    fig, ax = new_figure(1400, height, left=0.24, right=0.96, top=1 - 170 / height,
                         bottom=60 / height)
    style_axes(ax, "x")
    stacked_bar(ax, labels, stacks, SCORE_COLORS, horizontal=True, vmax=100)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    # Inside labels only where the segment is wide enough to hold them
    for i in range(len(GROUPS)):
        left = 0
        for k in range(5):
            v = stacks[k][i]
            if v >= 6:
                ax.text(left + v / 2, i, f"{v:.1f}%", ha="center", va="center", fontsize=8,
                        color="white" if k in (0, 4) else INK)
            left += v
    handles = [Patch(facecolor=c, label=f"{k} ★") for k, c in zip(range(1, 6), SCORE_COLORS)]
    fig.legend(handles=handles, loc="upper left", ncol=5, frameon=False, fontsize=8.5,
               labelcolor=INK_2, bbox_to_anchor=(0.24, 1 - 118 / height), borderaxespad=0)
    d1 = s.loc["active_first", "score_delta_vs_one_time"]
    d2 = s.loc["active_repeat", "score_delta_vs_one_time"]
    set_titles(fig, "Review score: active vs one-time customers",
               f"Share of purchase occasions by review score. Cliff's δ vs one-time: first "
               f"purchase {d1:+.3f}, later purchases {d2:+.3f}; chi-square {chi2:,.0f} "
               f"(p = {p:.2g})", left=0.02)
    save(fig, "active_vs_one_time_review")


def chart_spend(occ: pd.DataFrame, cust: pd.DataFrame, summary: pd.DataFrame,
                cust_delta: float) -> None:
    s = summary.set_index("group")
    height = 190 + 2 * 210 + 60
    fig = plt.figure(figsize=(1500 / DPI, height / DPI), dpi=DPI)
    # Panel 1: per purchase occasion
    ax1 = fig.add_axes([0.24, 1 - (190 + 150) / height, 0.44, 150 / height])
    style_axes(ax1, "x")
    labels = [f"{GROUP_LABELS[g]}\nn={int(s.loc[g, 'occasions']):,}" for g in GROUPS]
    box_rows(ax1, labels, [occ.loc[occ["group"] == g, "spend"].dropna() for g in GROUPS])
    ax1.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
    fig.text(0.24, 1 - 175 / height, "Spend per purchase occasion", fontsize=9.5,
             fontweight="semibold", color=INK_2)
    for i, g in enumerate(GROUPS):
        y = ax1.transData.transform((0, i))[1]
        y = fig.transFigure.inverted().transform((0, y))[1]
        delta = s.loc[g, "spend_delta_vs_one_time"]
        fig.text(0.97, y, f"median {fmt_brl(s.loc[g, 'spend_median'])}   mean "
                 f"{fmt_brl(s.loc[g, 'spend_mean'])} [{fmt_brl(s.loc[g, 'spend_mean_lo'])}–"
                 f"{fmt_brl(s.loc[g, 'spend_mean_hi'])}]"
                 + ("" if pd.isna(delta) else f"   δ {delta:+.3f}"),
                 ha="right", va="center", fontsize=8, color=INK_2)

    # Panel 2: per customer, average spend per occasion
    ax2 = fig.add_axes([0.24, 1 - (190 + 240 + 110) / height, 0.44, 110 / height])
    style_axes(ax2, "x")
    tiers = ["one_time", "active"]
    names = {"one_time": "One-time customers", "active": "Active customers"}
    data = [cust.loc[cust["tier"] == t, "avg_spend"].dropna() for t in tiers]
    box_rows(ax2, [f"{names[t]}\nn={len(d):,}" for t, d in zip(tiers, data)], data)
    ax2.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
    fig.text(0.24, 1 - (190 + 240 - 15) / height,
             "Average spend per occasion, per customer", fontsize=9.5, fontweight="semibold",
             color=INK_2)
    for i, d in enumerate(data):
        y = ax2.transData.transform((0, i))[1]
        y = fig.transFigure.inverted().transform((0, y))[1]
        fig.text(0.97, y, f"median {fmt_brl(d.median())}   mean {fmt_brl(d.mean())}"
                 + (f"   δ {cust_delta:+.3f}" if i == 1 else ""),
                 ha="right", va="center", fontsize=8, color=INK_2)
    box_legend(fig, 0.24, 118)
    set_titles(fig, "Spend: active vs one-time customers",
               f"Payment value; mean with bootstrap 95% interval; δ = Cliff's delta vs one-time; "
               f"{WHISKER_NOTE}", left=0.02)
    save(fig, "active_vs_one_time_spend")


def main() -> None:
    rng = np.random.default_rng(RANDOM_STATE)
    con = connect()
    occ = con.execute(OCCASION_SQL).df()
    con.close()
    tiers = pd.read_csv(OUTPUT_DIR / "customer_activity.csv")[["customer_unique_id", "tier"]]
    occ = occ.merge(tiers, on="customer_unique_id")
    occ["occasion_no"] = occ.groupby("customer_unique_id").cumcount() + 1
    occ["group"] = np.where(occ["tier"] == "one_time", "one_time",
                            np.where(occ["occasion_no"] == 1, "active_first", "active_repeat"))
    save_table(occ, "active_vs_one_time_occasions")

    summary = summarize(occ, rng)
    shares, chi2, p = score_distribution(occ)
    save_table(shares.reset_index(), "active_vs_one_time_score_dist")

    cust = occ.groupby(["customer_unique_id", "tier"]).agg(
        avg_score=("review_score", "mean"), avg_spend=("spend", "mean")).reset_index()
    act, one = cust[cust["tier"] == "active"], cust[cust["tier"] == "one_time"]
    cust_rows = []
    for col in ["avg_score", "avg_spend"]:
        a, o = act[col].dropna(), one[col].dropna()
        cust_rows.append({"metric": col, "active_median": a.median(), "active_mean": a.mean(),
                          "one_time_median": o.median(), "one_time_mean": o.mean(),
                          "cliffs_delta": cliffs_delta(a, o)})
    cust_table = pd.DataFrame(cust_rows)
    save_table(summary.assign(score_chi2=chi2, score_chi2_p=p), "active_vs_one_time_summary")
    save_table(cust_table, "active_vs_one_time_customer_level")

    chart_review(shares, summary, chi2, p)
    chart_spend(occ, cust, summary, cust_table.set_index("metric").loc["avg_spend", "cliffs_delta"])
    print(summary.round(3).T.to_string())
    print(cust_table.round(3).to_string(index=False))
    print(shares.round(3).to_string())


if __name__ == "__main__":
    main()
