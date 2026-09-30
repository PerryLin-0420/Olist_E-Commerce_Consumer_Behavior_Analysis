"""EDA 06: weekly purchase time series, spike weeks and whether spike buyers come back.

Unit: valid orders with at least one item, by purchase week (weeks start on
Monday). Each order is assigned to the category of its highest-priced item
(ties broken alphabetically). The analysis window keeps full weeks with
normal volume: ANALYSIS_START to ANALYSIS_END (data before 2017 is sparse and
the last weeks of 2018 are truncated).

Spike weeks: log(orders / centered 9-week rolling median), turned into a robust
z-score with the median absolute deviation over the window; z >= SPIKE_Z.

Habit check: customers are grouped by the week of their first purchase date.
A customer repurchases when they buy again on another date within
REPURCHASE_DAYS. Only cohorts with a full REPURCHASE_DAYS window before
ANALYSIS_END are used. Spike-week cohorts are compared with the other cohorts
(Wilson 95% intervals).

Charts (charts/) and tables (outputs/)
- 21_weekly_purchases_by_category   orders per week by category + new vs returning customers
- 22_cohort_repurchase_by_week      180-day repurchase rate per first-purchase week
- 23_spike_category_mix             category share in spike weeks vs other weeks
- 24_weekly_orders_all_categories   every category, weekly orders vs its own rolling baseline
- 25_weekly_price_volume            average order value (line) over order count (bars)
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from eda_utils import (DIV_CMAP, DPI, GRID, INK, INK_2, MUTED, OTHER, SERIES, SURFACE, connect,
                       legend,
                       new_figure, save, save_table, set_titles, style_axes)

ANALYSIS_START = pd.Timestamp("2017-01-02")
ANALYSIS_END = pd.Timestamp("2018-08-26")  # last day of the last full week
ROLLING_WEEKS = 9  # centered window: the week itself plus 4 weeks on each side
BASELINE_LABEL = f"Baseline: centered {ROLLING_WEEKS}-week rolling median"
SPIKE_Z = 3.0
REPURCHASE_DAYS = 180
TOP_CATEGORIES = 7

ORDER_SQL = """
WITH items AS (
    SELECT i.order_id, i.price,
           coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
               AS category
    FROM order_items i
    JOIN products p USING (product_id)
    LEFT JOIN product_category_name_translation t USING (product_category_name)
),
pay AS (
    SELECT order_id, sum(payment_value) AS order_value FROM order_payments GROUP BY 1
)
SELECT o.order_id, c.customer_unique_id, o.order_purchase_timestamp AS purchased_at,
       first(it.category ORDER BY it.price DESC, it.category) AS category,
       any_value(pay.order_value) AS order_value
FROM orders o
JOIN customers c USING (customer_id)
JOIN items it USING (order_id)
LEFT JOIN pay USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2, 3
ORDER BY 3, 1
"""


def wilson(k, n, z: float = 1.96):
    k, n = np.asarray(k, float), np.asarray(n, float)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def weekly_series(orders: pd.DataFrame) -> pd.DataFrame:
    """Orders, customers and spike flag per week inside the analysis window."""
    w = orders[(orders["week"] >= ANALYSIS_START) & (orders["week"] <= ANALYSIS_END)]
    weekly = w.groupby("week").agg(orders=("order_id", "size"),
                                   customers=("customer_unique_id", "nunique"))
    new = w[w["is_first_date"]].groupby("week")["customer_unique_id"].nunique()
    weekly["new_customers"] = new.reindex(weekly.index, fill_value=0)
    weekly["returning_customers"] = weekly["customers"] - weekly["new_customers"]
    weekly["baseline"] = weekly["orders"].rolling(ROLLING_WEEKS, center=True, min_periods=5).median()
    resid = np.log(weekly["orders"] / weekly["baseline"])
    mad = 1.4826 * (resid - resid.median()).abs().median()
    weekly["ratio_to_baseline"] = weekly["orders"] / weekly["baseline"]
    weekly["robust_z"] = (resid - resid.median()) / mad
    weekly["spike"] = weekly["robust_z"] >= SPIKE_Z
    return weekly


def chart_weekly(orders: pd.DataFrame, weekly: pd.DataFrame, top: list[str]) -> None:
    w = orders[(orders["week"] >= ANALYSIS_START) & (orders["week"] <= ANALYSIS_END)]
    cat = w["category"].where(w["category"].isin(top), "Other")
    stack = pd.crosstab(w["week"], cat).reindex(columns=top + ["Other"], fill_value=0)
    x = np.arange(len(weekly))
    colors = SERIES[:len(top)] + [OTHER]

    fig = plt.figure(figsize=(1700 / DPI, 1000 / DPI), dpi=DPI)
    ax1 = fig.add_axes([0.06, 0.4, 0.92, 0.39])
    ax2 = fig.add_axes([0.06, 0.08, 0.92, 0.22])
    # Panel 1: stacked bars by category, total line, baseline line
    style_axes(ax1, "y")
    bottom = np.zeros(len(x))
    for name, color in zip(stack.columns, colors):
        ax1.bar(x, stack[name].to_numpy(), bottom=bottom, width=0.78, color=color,
                edgecolor=SURFACE, linewidth=0.5 * 72 / DPI, label=name)
        bottom += stack[name].to_numpy()
    ax1.plot(x, weekly["orders"], color=INK, linewidth=1.6 * 72 / DPI, zorder=4)
    ax1.plot(x, weekly["baseline"], color=MUTED, linewidth=2 * 72 / DPI, zorder=4)
    ymax = weekly["orders"].max() * 1.18
    ax1.set_ylim(0, ymax)
    ax1.set_xlim(-0.8, len(x) - 0.2)
    for i in np.flatnonzero(weekly["spike"].to_numpy()):
        row = weekly.iloc[i]
        ax1.annotate(f"{weekly.index[i]:%Y-%m-%d}\n{int(row['orders']):,} orders "
                     f"(×{row['ratio_to_baseline']:.1f})", (x[i], row["orders"]),
                     textcoords="offset points", xytext=(12, 4), fontsize=8, color=INK_2,
                     ha="left", va="bottom")
    ax1.yaxis.set_major_formatter(lambda y, _: f"{y:,.0f}")
    ax1.set_ylabel("Orders per week", labelpad=6)
    month_ticks = [i for i, d in enumerate(weekly.index) if d.day <= 7 and d.month % 3 == 1]
    for ax in (ax1, ax2):
        ax.set_xticks(month_ticks, [f"{weekly.index[i]:%Y-%m}" for i in month_ticks])
    fig.text(0.06, 0.815, "Orders per week, by the category of the order's highest-priced item "
             "(line = total)", fontsize=9.5, fontweight="semibold", color=INK_2)

    # Panel 2: customers per week, new vs returning (stacked)
    style_axes(ax2, "y")
    ax2.bar(x, weekly["new_customers"], width=0.78, color=SERIES[0], edgecolor=SURFACE,
            linewidth=0.5 * 72 / DPI)
    ax2.bar(x, weekly["returning_customers"], bottom=weekly["new_customers"], width=0.78,
            color=SERIES[1], edgecolor=SURFACE, linewidth=0.5 * 72 / DPI)
    ax2.set_xlim(-0.8, len(x) - 0.2)
    ax2.set_ylim(0, weekly["customers"].max() * 1.15)
    ax2.yaxis.set_major_formatter(lambda y, _: f"{y:,.0f}")
    ax2.set_ylabel("Customers per week", labelpad=6)
    ret_share = weekly["returning_customers"].sum() / weekly["customers"].sum()
    fig.text(0.06, 0.315, f"Customers per week: new (first purchase date) vs returning "
             f"(returning = {ret_share:.1%} of weekly customers overall)", fontsize=9.5,
             fontweight="semibold", color=INK_2)
    handles2 = [plt.Rectangle((0, 0), 1, 1, color=SERIES[0]),
                plt.Rectangle((0, 0), 1, 1, color=SERIES[1])]
    ax2.legend(handles2, ["New customers", "Returning customers"], loc="upper left",
               frameon=False, fontsize=8.5, labelcolor=INK_2, ncol=2)

    n_other = w["category"].nunique() - len(top)
    names = top + [f"Other ({n_other} categories, see chart 24)"]
    legend(fig, names + ["Total orders", BASELINE_LABEL],
           colors + [INK, MUTED], y_px_from_top=100, ncol=5, left=0.06)
    spikes = weekly[weekly["spike"]]
    set_titles(fig, "Weekly purchases: where the volume jumps",
               f"{ANALYSIS_START:%Y-%m-%d} to {ANALYSIS_END:%Y-%m-%d}, valid orders with items. "
               f"Spike weeks (robust z ≥ {SPIKE_Z:.0f} vs the baseline): "
               + (", ".join(f"{d:%Y-%m-%d}" for d in spikes.index) or "none"), left=0.06)
    save(fig, "21_weekly_purchases_by_category")


def cohort_repurchase(orders: pd.DataFrame, weekly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = orders[["customer_unique_id", "date"]].drop_duplicates().sort_values(
        ["customer_unique_id", "date"])
    first = dates.groupby("customer_unique_id")["date"].min().rename("first_date")
    nxt = dates.merge(first, on="customer_unique_id")
    nxt = nxt[nxt["date"] > nxt["first_date"]].groupby("customer_unique_id")["date"].min()
    cust = first.to_frame().join(nxt.rename("second_date"))
    cust["days_to_second"] = (cust["second_date"] - cust["first_date"]).dt.days
    cust["first_week"] = cust["first_date"] - pd.to_timedelta(cust["first_date"].dt.weekday, "D")
    cutoff = ANALYSIS_END - pd.Timedelta(days=REPURCHASE_DAYS)
    cust = cust[(cust["first_week"] >= ANALYSIS_START) & (cust["first_date"] <= cutoff)].copy()
    cust["repurchased"] = cust["days_to_second"].le(REPURCHASE_DAYS)
    cust["spike_cohort"] = cust["first_week"].map(weekly["spike"]).fillna(False).astype(bool)

    by_week = cust.groupby("first_week").agg(new_customers=("repurchased", "size"),
                                             repurchased=("repurchased", "sum"))
    by_week["rate"] = by_week["repurchased"] / by_week["new_customers"]
    by_week["rate_lo"], by_week["rate_hi"] = wilson(by_week["repurchased"],
                                                    by_week["new_customers"])
    by_week["spike"] = by_week.index.map(weekly["spike"]).fillna(False).astype(bool)

    groups = cust.groupby("spike_cohort").agg(customers=("repurchased", "size"),
                                             repurchased=("repurchased", "sum"),
                                             median_days_to_second=("days_to_second", "median"))
    groups["rate"] = groups["repurchased"] / groups["customers"]
    groups["rate_lo"], groups["rate_hi"] = wilson(groups["repurchased"], groups["customers"])
    groups.index = groups.index.map({True: "spike_weeks", False: "other_weeks"})
    # Two-proportion test (chi-square on the 2x2 table, Yates-corrected)
    table = np.array([[groups.loc[g, "repurchased"], groups.loc[g, "customers"]
                       - groups.loc[g, "repurchased"]] for g in ["spike_weeks", "other_weeks"]])
    groups["test_p_value"] = chi2_contingency(table)[1]
    groups["rate_diff_pp"] = (groups.loc["spike_weeks", "rate"]
                              - groups.loc["other_weeks", "rate"]) * 100
    return by_week, groups


def chart_cohorts(by_week: pd.DataFrame, groups: pd.DataFrame) -> None:
    fig, ax = new_figure(1700, 660, left=0.06, right=0.98, top=0.7, bottom=0.12)
    style_axes(ax, "y")
    x = np.arange(len(by_week))
    other = groups.loc["other_weeks"]
    ax.axhspan(other["rate_lo"] * 100, other["rate_hi"] * 100, color=GRID, zorder=0)
    ax.axhline(other["rate"] * 100, color=MUTED, linewidth=1 * 72 / DPI, zorder=1)
    n_spike = 0
    for i, (_, row) in enumerate(by_week.iterrows()):
        color = SERIES[1] if row["spike"] else SERIES[0]
        ax.plot([i, i], [row["rate_lo"] * 100, row["rate_hi"] * 100], color=color,
                alpha=0.35, linewidth=2 * 72 / DPI, zorder=2)
        ax.plot(i, row["rate"] * 100, "o", color=color, markersize=7 * 72 / DPI + 2,
                markeredgecolor=SURFACE, markeredgewidth=2 * 72 / DPI, zorder=3)
        if row["spike"]:
            # Stack spike labels above the plot area so adjacent weeks never collide
            ax.annotate(f"{by_week.index[i]:%Y-%m-%d}: {row['rate']:.2%} of "
                        f"{int(row['new_customers']):,} new", (i, row["rate"] * 100),
                        textcoords="offset points", xytext=(40, 150 - 22 * n_spike),
                        fontsize=8, color=INK_2, va="center",
                        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.6})
            n_spike += 1
    ax.set_xlim(-0.8, len(x) - 0.2)
    ax.set_ylim(0, max(6, (by_week["rate_hi"] * 100).quantile(0.98) * 1.1))
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%")
    ticks = [i for i, d in enumerate(by_week.index) if d.day <= 7 and d.month % 3 == 1]
    ax.set_xticks(ticks, [f"{by_week.index[i]:%Y-%m}" for i in ticks])
    ax.set_ylabel(f"Repurchase within {REPURCHASE_DAYS} days", labelpad=6)
    legend(fig, ["First purchase in a spike week", "First purchase in another week",
                 "Other weeks pooled (band = 95% CI)"], [SERIES[1], SERIES[0], MUTED],
           y_px_from_top=120, left=0.06)
    spike = groups.loc["spike_weeks"] if "spike_weeks" in groups.index else None
    tail = (f"spike-week cohorts {spike['rate']:.2%} [{spike['rate_lo']:.2%}–"
            f"{spike['rate_hi']:.2%}] of {int(spike['customers']):,} "
            f"(difference {spike['rate_diff_pp']:+.2f} pp, p = {spike['test_p_value']:.2f})"
            if spike is not None
            else "no spike-week cohort")
    set_titles(fig, f"Do customers acquired in spike weeks come back?",
               f"{REPURCHASE_DAYS}-day repurchase rate by first-purchase week (bar = Wilson 95% "
               f"interval)." + chr(10) + f"Other weeks {other['rate']:.2%} [{other['rate_lo']:.2%}–"
               f"{other['rate_hi']:.2%}] of {int(other['customers']):,}; {tail}", left=0.06)
    save(fig, "22_cohort_repurchase_by_week")


def chart_spike_mix(orders: pd.DataFrame, weekly: pd.DataFrame, top_n: int = 12) -> pd.DataFrame:
    w = orders[(orders["week"] >= ANALYSIS_START) & (orders["week"] <= ANALYSIS_END)].copy()
    w["spike"] = w["week"].map(weekly["spike"]).astype(bool)
    mix = pd.crosstab(w["category"], w["spike"], normalize="columns") * 100
    mix.columns = ["other_weeks", "spike_weeks"]
    counts = pd.crosstab(w["category"], w["spike"])
    mix["spike_orders"] = counts[True]
    mix["gap_pp"] = mix["spike_weeks"] - mix["other_weeks"]
    mix["lift"] = mix["spike_weeks"] / mix["other_weeks"]
    top = mix.sort_values("spike_orders", ascending=False).head(top_n) \
        .sort_values("gap_pp", ascending=False)
    save_table(mix.sort_values("spike_orders", ascending=False).reset_index(), "spike_category_mix")

    n = len(top)
    height = 130 + 34 * n + 55
    fig, ax = new_figure(1400, height, left=0.24, right=0.78, top=1 - 130 / height,
                         bottom=55 / height)
    style_axes(ax, "x")
    ax.spines["left"].set_visible(False)
    ax.axvline(0, color=INK_2, linewidth=1 * 72 / DPI)
    colors = [SERIES[1] if v > 0 else SERIES[0] for v in top["gap_pp"]]
    ax.barh(range(n), top["gap_pp"], height=18 / 34, color=colors)
    lim = max(abs(top["gap_pp"]).max() * 1.35, 1)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), top.index)
    ax.grid(axis="x", color=GRID, linewidth=1 * 72 / DPI)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.0f} pp")
    for i, (cat, row) in enumerate(top.iterrows()):
        y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
        fig.text(0.98, y, f"{row['other_weeks']:.1f}% → {row['spike_weeks']:.1f}%  "
                 f"(×{row['lift']:.2f}, {int(row['spike_orders']):,} orders)",
                 ha="right", va="center", fontsize=8, color=INK_2)
    spike_weeks = ", ".join(f"{d:%Y-%m-%d}" for d in weekly.index[weekly["spike"]])
    set_titles(fig, "Category mix in spike weeks vs other weeks",
               f"Top {top_n} categories by spike-week orders; bar = change in share of orders "
               f"(percentage points). Spike weeks: {spike_weeks}", left=0.02)
    save(fig, "23_spike_category_mix")
    return mix


def chart_all_categories(orders: pd.DataFrame, weekly: pd.DataFrame) -> None:
    """Heatmap of every category: weekly orders relative to its own rolling baseline.

    A color per category is impossible past 8 hues, so each category gets a row
    instead. The baseline is the category's centered ROLLING_WEEKS-week rolling
    mean (the same window as the spike baseline), so platform growth over time
    does not show up as a colour trend; log2 of (orders + 0.5) / (baseline + 0.5)
    is shown on a diverging scale.
    """
    w = orders[(orders["week"] >= ANALYSIS_START) & (orders["week"] <= ANALYSIS_END)]
    counts = pd.crosstab(w["category"], w["week"]).reindex(columns=weekly.index, fill_value=0)
    counts = counts.loc[counts.sum(axis=1).sort_values(ascending=False).index]
    baseline = counts.T.rolling(ROLLING_WEEKS, center=True, min_periods=5).mean().T
    index = (counts + 0.5) / (baseline + 0.5)
    save_table(counts.reset_index(), "weekly_orders_by_category")
    log_index = np.log2(index.clip(lower=0.25))  # weeks with 0 orders show at the floor
    lim = 2.0

    n_cat, n_wk = counts.shape
    row_px = 15
    height = 190 + row_px * n_cat + 60
    fig, ax = new_figure(1700, height, left=0.2, right=0.89, top=1 - 190 / height,
                         bottom=60 / height)
    im = ax.imshow(np.clip(log_index.values, -lim, lim), cmap=DIV_CMAP, vmin=-lim, vmax=lim,
                   aspect="auto", interpolation="nearest")
    ax.set_yticks(range(n_cat), [f"{c} ({int(t):,})" for c, t in counts.sum(axis=1).items()])
    ax.tick_params(axis="y", labelsize=6.5, length=0, pad=4)
    ticks = [i for i, d in enumerate(counts.columns) if d.day <= 7 and d.month % 3 == 1]
    ax.set_xticks(ticks, [f"{counts.columns[i]:%Y-%m}" for i in ticks])
    ax.tick_params(axis="x", length=0, labelsize=8, labeltop=True, labelbottom=True)
    for side in ax.spines.values():
        side.set_visible(False)
    for i in np.flatnonzero(weekly["spike"].to_numpy()):
        ax.axvline(i - 0.5, color=INK, linewidth=0.6, zorder=3)
        ax.axvline(i + 0.5, color=INK, linewidth=0.6, zorder=3)
    cax = fig.add_axes([0.915, 1 - (190 + 260) / height, 0.012, 240 / height])
    cb = fig.colorbar(im, cax=cax, ticks=[-2, -1, 0, 1, 2])
    cb.ax.set_yticklabels(["≤ ×0.25", "×0.5", "×1", "×2", "≥ ×4"], fontsize=7.5)
    cb.ax.set_title("vs own\nbaseline", fontsize=7.5, color=INK_2, loc="left")
    cb.outline.set_visible(False)
    in_spike = index.loc[:, weekly["spike"].to_numpy()].mean(axis=1)
    rising = (in_spike >= 1.5).sum()
    set_titles(fig, f"Weekly orders for all {n_cat} categories",
               "Row = category (total orders in brackets), sorted by volume; color = that week's "
               f"orders vs the category's own centered {ROLLING_WEEKS}-week rolling mean (log "
               "scale), so platform growth is removed.\nBlack lines frame the "
               f"spike weeks; {rising} of {n_cat} categories average ≥ ×1.5 their baseline in those "
               "weeks. Small categories look speckled because a few orders swing the ratio",
               left=0.02)
    save(fig, "24_weekly_orders_all_categories")


def chart_price_volume(orders: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    """Price-volume chart: average order value on top, order count below, shared weeks."""
    w = orders[(orders["week"] >= ANALYSIS_START) & (orders["week"] <= ANALYSIS_END)]
    pv = w.groupby("week")["order_value"].agg(mean_order_value="mean",
                                              median_order_value="median")
    pv = pv.reindex(weekly.index).join(weekly[["orders", "spike"]])
    save_table(pv.reset_index(), "weekly_price_volume")
    rho = pv["orders"].corr(pv["mean_order_value"], method="spearman")
    x = np.arange(len(pv))

    fig = plt.figure(figsize=(1700 / DPI, 900 / DPI), dpi=DPI)
    ax1 = fig.add_axes([0.07, 0.45, 0.9, 0.33])
    ax2 = fig.add_axes([0.07, 0.09, 0.9, 0.27])
    style_axes(ax1, "y")
    for i in np.flatnonzero(pv["spike"].to_numpy()):
        for ax in (ax1, ax2):
            ax.axvspan(i - 0.5, i + 0.5, color=GRID, zorder=0)
    ax1.plot(x, pv["mean_order_value"], color=SERIES[0], linewidth=2 * 72 / DPI, zorder=3)
    ax1.plot(x, pv["median_order_value"], color=SERIES[1], linewidth=2 * 72 / DPI, zorder=3)
    ax1.set_xlim(-0.8, len(x) - 0.2)
    ax1.set_ylim(0, pv["mean_order_value"].max() * 1.2)
    ax1.yaxis.set_major_formatter(lambda y, _: f"R$ {y:,.0f}")
    ax1.set_ylabel("Order value", labelpad=6)
    style_axes(ax2, "y")
    ax2.bar(x, pv["orders"], width=0.78, color=SERIES[0], edgecolor=SURFACE,
            linewidth=0.5 * 72 / DPI, zorder=2)
    ax2.set_xlim(-0.8, len(x) - 0.2)
    ax2.set_ylim(0, pv["orders"].max() * 1.15)
    ax2.yaxis.set_major_formatter(lambda y, _: f"{y:,.0f}")
    ax2.set_ylabel("Orders", labelpad=6)
    ticks = [i for i, d in enumerate(pv.index) if d.day <= 7 and d.month % 3 == 1]
    for ax in (ax1, ax2):
        ax.set_xticks(ticks, [f"{pv.index[i]:%Y-%m}" for i in ticks])
    fig.text(0.07, 0.8, "Average order value per week (payment value)", fontsize=9.5,
             fontweight="semibold", color=INK_2)
    fig.text(0.07, 0.38, "Orders per week", fontsize=9.5, fontweight="semibold", color=INK_2)
    legend(fig, ["Mean order value", "Median order value", "Spike weeks"],
           [SERIES[0], SERIES[1], GRID], y_px_from_top=100, left=0.07)
    spike, other = pv[pv["spike"]], pv[~pv["spike"]]
    set_titles(fig, "Price and volume per week",
               f"Spike weeks: mean order value R$ {spike['mean_order_value'].mean():,.0f} vs "
               f"R$ {other['mean_order_value'].mean():,.0f} in other weeks (median "
               f"R$ {spike['median_order_value'].mean():,.0f} vs "
               f"R$ {other['median_order_value'].mean():,.0f}). Spearman ρ between weekly orders "
               f"and mean order value: {rho:+.2f}", left=0.07)
    save(fig, "25_weekly_price_volume")
    return pv


def main() -> None:
    con = connect()
    orders = con.execute(ORDER_SQL).df()
    con.close()
    orders["date"] = orders["purchased_at"].dt.normalize()
    orders["week"] = orders["date"] - pd.to_timedelta(orders["date"].dt.weekday, "D")
    first_date = orders.groupby("customer_unique_id")["date"].transform("min")
    orders["is_first_date"] = orders["date"] == first_date

    weekly = weekly_series(orders)
    save_table(weekly.reset_index(), "weekly_purchases")
    w = orders[(orders["week"] >= ANALYSIS_START) & (orders["week"] <= ANALYSIS_END)]
    top = w["category"].value_counts().head(TOP_CATEGORIES).index.tolist()
    chart_weekly(orders, weekly, top)

    by_week, groups = cohort_repurchase(orders, weekly)
    save_table(by_week.reset_index(), "cohort_repurchase_by_week")
    save_table(groups.reset_index(names="cohort"), "cohort_repurchase_spike_vs_other")
    chart_cohorts(by_week, groups)
    chart_spike_mix(orders, weekly)
    chart_all_categories(orders, weekly)
    chart_price_volume(orders, weekly)

    print(weekly[weekly["spike"]].round(2).to_string())
    print(groups.round(4).to_string())


if __name__ == "__main__":
    main()
