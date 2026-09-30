"""EDA 07: repeat buyers - purchase funnel, spend and category by purchase number.

Unit: purchase occasion = one customer, one purchase date (valid orders; orders
on the same day are merged, see random_forest/scripts/04_activity_cutoff.py).
- spend = total payment value of the occasion
- category = category of the occasion's highest-priced item (ties alphabetical)
Repeat buyers = customers with >= 2 purchase occasions.

Charts (charts/) and tables (outputs/)
- 26_purchase_funnel                customers reaching the k-th purchase, k = 1 .. max
- 27_repeat_spend_by_purchase       spend per occasion by purchase number (box plots) and
                                    the paired 1st vs 2nd comparison (Wilcoxon signed-rank)
- 28_repeat_category_by_purchase    category share of each purchase number, every category
"""
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from eda_utils import (DPI, INK, INK_2, SEQ_CMAP, SERIES, WHISKER_NOTE, bar, box_legend,
                       box_rows, connect, fmt_brl, fmt_pct, new_figure, save, save_table,
                       set_titles, style_axes)

MAX_BOX_PURCHASE = 5  # purchase numbers >= this are pooled into one "5th+" row / column

OCCASION_SQL = """
WITH items AS (
    SELECT i.order_id, i.price,
           coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
               AS category
    FROM order_items i
    JOIN products p USING (product_id)
    LEFT JOIN product_category_name_translation t USING (product_category_name)
),
pay AS (
    SELECT order_id, sum(payment_value) AS payment FROM order_payments GROUP BY 1
),
valid AS (
    SELECT o.order_id, c.customer_unique_id,
           CAST(o.order_purchase_timestamp AS DATE) AS purchase_date
    FROM orders o JOIN customers c USING (customer_id)
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)
SELECT v.customer_unique_id, v.purchase_date,
       sum(pay.payment) AS spend,
       (SELECT first(it.category ORDER BY it.price DESC, it.category)
        FROM items it JOIN valid v2 USING (order_id)
        WHERE v2.customer_unique_id = v.customer_unique_id
          AND v2.purchase_date = v.purchase_date) AS category
FROM valid v
LEFT JOIN pay USING (order_id)
GROUP BY 1, 2
ORDER BY 1, 2
"""


def ordinal(k: int) -> str:
    return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def purchase_label(k: int) -> str:
    return f"{ordinal(MAX_BOX_PURCHASE)}+" if k >= MAX_BOX_PURCHASE else ordinal(k)


def chart_funnel(occ: pd.DataFrame) -> pd.DataFrame:
    per_customer = occ.groupby("customer_unique_id").size()
    max_k = int(per_customer.max())
    reached = pd.Series({k: int((per_customer >= k).sum()) for k in range(1, max_k + 1)})
    funnel = pd.DataFrame({"purchase": reached.index, "customers": reached.values})
    funnel["share_of_all"] = funnel["customers"] / funnel["customers"].iloc[0]
    funnel["step_conversion"] = funnel["customers"] / funnel["customers"].shift(1)
    save_table(funnel, "purchase_funnel")

    # Keep every step where the count changes, plus the maximum
    shown = funnel[(funnel["customers"].diff() != 0) | (funnel["purchase"] == max_k)]
    labels = [ordinal(int(k)) for k in shown["purchase"]]
    values = shown["customers"].tolist()
    value_labels = []
    for _, row in shown.iterrows():
        step = "" if pd.isna(row["step_conversion"]) else \
            f"  ← {row['step_conversion']:.1%} of previous step"
        value_labels.append(f"{int(row['customers']):,}  ({fmt_pct(row['share_of_all'] * 100)} of all)"
                            f"{step}")
    fig, ax = new_figure(1400, 130 + 40 * len(shown) + 60, left=0.14, right=0.6,
                         top=1 - 130 / (130 + 40 * len(shown) + 60),
                         bottom=60 / (130 + 40 * len(shown) + 60))
    style_axes(ax, "x")
    from eda_utils import barh  # local import keeps the top list short
    barh(ax, labels, values, value_labels, xmax=values[0] * 1.02)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:,.0f}")
    ax.set_ylabel("Reached the n-th purchase (distinct dates)", labelpad=8)
    skipped = sorted(set(funnel["purchase"]) - set(shown["purchase"]))
    note = (f"; {ordinal(skipped[0])}–{ordinal(skipped[-1])} purchases are omitted because "
            f"the count stays at {int(funnel.loc[funnel['purchase'] == skipped[0], 'customers'].iat[0])}"
            if skipped else "")
    set_titles(fig, "Purchase funnel: from the first purchase to the most repeated one",
               f"Customers with at least n purchase dates; the maximum is {max_k}{note}")
    save(fig, "26_purchase_funnel")
    return funnel


def chart_spend(rep: pd.DataFrame) -> pd.DataFrame:
    rep = rep.assign(bucket=rep["purchase_no"].clip(upper=MAX_BOX_PURCHASE))
    buckets = sorted(rep["bucket"].unique())
    data = [rep.loc[rep["bucket"] == b, "spend"].dropna() for b in buckets]
    rows = []
    for b, d in zip(buckets, data):
        q1, med, q3 = d.quantile([0.25, 0.5, 0.75])
        rows.append({"purchase": purchase_label(b), "occasions": len(d), "q1": q1,
                     "median": med, "q3": q3, "mean": d.mean()})
    table = pd.DataFrame(rows)

    # Paired: the same customers' 1st vs 2nd purchase
    pair = rep[rep["purchase_no"] <= 2].pivot_table(index="customer_unique_id",
                                                    columns="purchase_no", values="spend")
    pair = pair.dropna()
    diff = pair[2] - pair[1]
    w_stat, w_p = wilcoxon(pair[2], pair[1])
    paired = {"pairs": len(pair), "median_first": pair[1].median(),
              "median_second": pair[2].median(), "median_diff": diff.median(),
              "share_second_higher": (diff > 0).mean(), "wilcoxon_p": w_p}
    save_table(table, "repeat_spend_by_purchase")
    save_table(pd.DataFrame([paired]), "repeat_spend_first_vs_second")

    n = len(buckets)
    height = 170 + 50 * n + 60
    fig, ax = new_figure(1500, height, left=0.16, right=0.62, top=1 - 170 / height,
                         bottom=60 / height)
    style_axes(ax, "x")
    box_rows(ax, [f"{purchase_label(b)} purchase" for b in buckets], data)
    ax.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
    for i, row in table.iterrows():
        y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
        fig.text(0.98, y, f"n={int(row['occasions']):,}   median {fmt_brl(row['median'])}   "
                 f"mean {fmt_brl(row['mean'])}", ha="right", va="center", fontsize=8.5,
                 color=INK_2)
    box_legend(fig, 0.16, 118)
    set_titles(fig, "Repeat buyers: spend per purchase, first to latest",
               f"{paired['pairs']:,} repeat buyers; purchase numbers ≥ {MAX_BOX_PURCHASE} pooled; "
               f"{WHISKER_NOTE}.\nSame customers, 1st vs 2nd purchase: median "
               f"{fmt_brl(paired['median_first'])} → {fmt_brl(paired['median_second'])}, "
               f"{paired['share_second_higher']:.1%} spent more the 2nd time, "
               f"Wilcoxon signed-rank p = {paired['wilcoxon_p']:.2f}")
    save(fig, "27_repeat_spend_by_purchase")
    return table


def chart_categories(rep: pd.DataFrame) -> pd.DataFrame:
    rep = rep.assign(bucket=rep["purchase_no"].clip(upper=MAX_BOX_PURCHASE - 1))
    buckets = sorted(rep["bucket"].unique())
    col_labels = [f"{ordinal(b)}+" if b == MAX_BOX_PURCHASE - 1 else ordinal(b) for b in buckets]
    counts = pd.crosstab(rep["category"].fillna("no items"), rep["bucket"]).reindex(
        columns=buckets, fill_value=0)
    counts = counts.loc[counts.sum(axis=1).sort_values(ascending=False).index]
    share = counts / counts.sum() * 100
    save_table(share.reset_index(), "repeat_category_by_purchase")

    # Same category as the previous purchase, per purchase number
    rep = rep.sort_values(["customer_unique_id", "purchase_no"])
    rep["prev_category"] = rep.groupby("customer_unique_id")["category"].shift(1)
    same = rep[rep["purchase_no"] >= 2].assign(same=lambda d: d["category"] == d["prev_category"])
    same_rate = same.groupby("bucket")["same"].mean()

    n_cat, n_col = share.shape
    row_px = 17
    height = 200 + row_px * n_cat + 20
    fig, ax = new_figure(1100, height, left=0.36, right=0.97, top=1 - 200 / height,
                         bottom=20 / height)
    vmax = share.values.max()
    im = ax.imshow(share.values, cmap=SEQ_CMAP, vmin=0, vmax=vmax, aspect="auto",
                   interpolation="nearest")
    for r in range(n_cat):
        for c in range(n_col):
            v = share.iat[r, c]
            if v == 0:
                continue
            rgba = im.cmap(im.norm(v))
            lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            ax.text(c, r, f"{v:.1f}%" if v >= 0.1 else "<0.1%", ha="center", va="center",
                    fontsize=6.5,
                    color="white" if lum < 0.5 else INK)
    headers = []
    for b, lab in zip(buckets, col_labels):
        extra = "" if b == 1 else f"\nsame as previous {same_rate.get(b, np.nan):.0%}"
        headers.append(f"{lab} purchase\nn={int(counts[b].sum()):,}{extra}")
    ax.set_xticks(range(n_col), headers)
    ax.xaxis.tick_top()
    ax.set_yticks(range(n_cat), counts.index)
    ax.tick_params(axis="both", length=0, labelsize=7)
    ax.tick_params(axis="x", labelsize=8)
    for side in ax.spines.values():
        side.set_visible(False)
    set_titles(fig, "Repeat buyers: category of each purchase",
               f"Share of each purchase number's occasions by category ({n_cat} categories, "
               "sorted by total);\n'same as previous' = share of purchases in the same "
               "category as the purchase before", left=0.02)
    save(fig, "28_repeat_category_by_purchase")
    return share


def main() -> None:
    con = connect()
    occ = con.execute(OCCASION_SQL).df()
    con.close()
    occ = occ.sort_values(["customer_unique_id", "purchase_date"])
    occ["purchase_no"] = occ.groupby("customer_unique_id").cumcount() + 1
    save_table(occ, "purchase_occasions")

    funnel = chart_funnel(occ)
    repeaters = occ.groupby("customer_unique_id")["purchase_no"].transform("max") >= 2
    rep = occ[repeaters]
    chart_spend(rep)
    chart_categories(rep)
    print(funnel.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
