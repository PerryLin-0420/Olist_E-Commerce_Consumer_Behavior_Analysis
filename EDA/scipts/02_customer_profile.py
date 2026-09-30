"""EDA 02: customer profile - classification statistics.

Customer entity = customer_unique_id (one person across orders); customer_id is
per order. Spend / payment / review / category stats use valid orders only
(order_status not in canceled, unavailable). Location = state of the latest order.

Charts (charts/) and tables (outputs/)
- 04_customers_map_by_state          state choropleth with region borders + columns
- 06_spend_by_quarter                total spend per quarter, one series per year
- 07_spend_tier_by_quarter           customer spend tier mix within each quarter
- 08_preferred_payment_type          - 09_credit_card_installments
- 10_review_score_by_category        review counts per score, stacked by category
- 11_top_categories_orders_spend     orders and spend side by side
- 12_spending_tier_by_region         tier mix vs national mix
- 13_price_freight_by_region         avg product value vs freight per customer
(05 is produced by 03_seller_repeat_rate.py)
"""
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MultipleLocator

from eda_geo import REGIONS, STATE_TO_REGION, draw_state_map
from eda_utils import (DIV_CMAP, DPI, INK_2, MUTED, ORDINAL_BLUE, OTHER, SERIES, bar, barh,
                       connect, fmt_brl, fmt_pct, grouped_bar, heatmap, legend, new_figure,
                       save, save_table, set_titles, stacked_bar, style_axes)

SPEND_BINS = [0, 50, 100, 200, 500, 1000, float("inf")]
SPEND_LABELS = ["< 50", "50–100", "100–200", "200–500", "500–1,000", "≥ 1,000"]
MAP_BINS = [0, 500, 1000, 3000, 10000, float("inf")]
MAP_LABELS = ["< 500", "500–1K", "1K–3K", "3K–10K", "≥ 10K"]
# Quarters with incomplete data: platform launch (Sep 2016, Nov 2016 missing) and cut-off (Sep 2018)
PARTIAL_QUARTERS = {(2016, 3), (2016, 4), (2018, 3), (2018, 4)}
MIN_QUARTER_CUSTOMERS = 100

CUSTOMER_SQL = """
WITH o AS (
    SELECT o.order_id, o.order_purchase_timestamp, c.customer_unique_id, c.customer_state,
           o.order_status NOT IN ('canceled', 'unavailable') AS is_valid
    FROM orders o JOIN customers c USING (customer_id)
),
pay AS (
    SELECT order_id, sum(payment_value) AS order_value FROM order_payments GROUP BY 1
),
items AS (
    SELECT order_id, sum(price) AS product_value, sum(freight_value) AS freight_value
    FROM order_items GROUP BY 1
),
pay_type AS (
    -- Ties on value are broken alphabetically so reruns are deterministic
    SELECT o.customer_unique_id,
           first(p.payment_type ORDER BY p.type_value DESC, p.payment_type) AS preferred_payment_type
    FROM (SELECT order_id, payment_type, sum(payment_value) AS type_value
          FROM order_payments GROUP BY 1, 2) p
    JOIN o USING (order_id) WHERE o.is_valid
    GROUP BY 1
),
cc AS (
    SELECT o.customer_unique_id, max(p.payment_installments) AS max_installments
    FROM order_payments p JOIN o USING (order_id)
    WHERE o.is_valid AND p.payment_type = 'credit_card'
    GROUP BY 1
)
SELECT o.customer_unique_id,
       first(o.customer_state ORDER BY o.order_purchase_timestamp DESC, o.customer_state)
           AS customer_state,
       count(DISTINCT o.order_id) FILTER (WHERE o.is_valid) AS valid_orders,
       coalesce(sum(pay.order_value) FILTER (WHERE o.is_valid), 0) AS total_spend,
       coalesce(sum(items.product_value) FILTER (WHERE o.is_valid), 0) AS product_value,
       coalesce(sum(items.freight_value) FILTER (WHERE o.is_valid), 0) AS freight_value,
       any_value(pt.preferred_payment_type) AS preferred_payment_type,
       any_value(cc.max_installments) AS max_installments
FROM o
LEFT JOIN pay USING (order_id)
LEFT JOIN items USING (order_id)
LEFT JOIN pay_type pt USING (customer_unique_id)
LEFT JOIN cc USING (customer_unique_id)
GROUP BY o.customer_unique_id
"""

# Customer spend within each purchase quarter (payment value of valid orders)
QUARTER_SQL = """
SELECT year(o.order_purchase_timestamp) AS year,
       quarter(o.order_purchase_timestamp) AS quarter,
       c.customer_unique_id,
       sum(p.payment_value) AS spend
FROM orders o
JOIN customers c USING (customer_id)
JOIN order_payments p USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2, 3
"""

CATEGORY_EXPR = "coalesce(t.product_category_name_english, p.product_category_name, 'unknown')"

CATEGORY_SQL = f"""
SELECT {CATEGORY_EXPR} AS category,
       count(DISTINCT o.order_id) AS orders,
       count(DISTINCT c.customer_unique_id) AS customers,
       sum(i.price) AS product_value,
       sum(i.freight_value) AS freight_value,
       sum(i.price + i.freight_value) AS spend
FROM orders o
JOIN customers c USING (customer_id)
JOIN order_items i USING (order_id)
JOIN products p USING (product_id)
LEFT JOIN product_category_name_translation t USING (product_category_name)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1 ORDER BY spend DESC, category
"""

# One row per (review, category); an order spanning several categories counts in each
REVIEW_SQL = f"""
SELECT r.review_score, {CATEGORY_EXPR} AS category,
       count(DISTINCT (r.review_id, r.order_id)) AS reviews
FROM order_reviews r
JOIN orders o USING (order_id)
JOIN order_items i USING (order_id)
JOIN products p USING (product_id)
LEFT JOIN product_category_name_translation t USING (product_category_name)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2
"""


def share_labels(counts, total):
    return [f"{n:,}  ({fmt_pct(n / total * 100)})" for n in counts]


def count_table(series: pd.Series, order: list, name: str) -> pd.DataFrame:
    counts = series.value_counts().reindex(order, fill_value=0)
    df = counts.rename_axis(name).reset_index(name="customers")
    df["share"] = df["customers"] / df["customers"].sum()
    return df


def hbar_chart(df, label_col, title, subtitle, filename, left=0.2, total=None):
    # Fixed pixel margins: 115px for titles, 50px for x tick labels
    height = 115 + 34 * len(df) + 50
    fig, ax = new_figure(1300, height, left=left, right=0.9,
                         top=1 - 115 / height, bottom=50 / height)
    style_axes(ax, "x")
    total = total or df["customers"].sum()
    barh(ax, df[label_col].tolist(), df["customers"].tolist(),
         share_labels(df["customers"], total))
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:,.0f}")
    set_titles(fig, title, subtitle)
    save(fig, filename)


def vbar_chart(df, label_col, title, subtitle, filename, xlabel=None):
    fig, ax = new_figure(1300, 620, left=0.08, right=0.97, top=0.8, bottom=0.14)
    style_axes(ax, "y")
    total = df["customers"].sum()
    bar(ax, df[label_col].tolist(), df["customers"].tolist(), share_labels(df["customers"], total))
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:,.0f}")
    if xlabel:
        ax.set_xlabel(xlabel, labelpad=8)
    set_titles(fig, title, subtitle)
    save(fig, filename)


# ---------------------------------------------------------------- 04 map + columns

def chart_state_map(state: pd.DataFrame, n_all: int) -> None:
    counts = state.set_index("state")["customers"]
    classes = pd.cut(counts, MAP_BINS, labels=False, right=False).to_dict()

    fig = plt.figure(figsize=(1700 / DPI, 900 / DPI), dpi=DPI)
    ax_map = fig.add_axes([0.01, 0.03, 0.42, 0.8])
    ax_col = fig.add_axes([0.5, 0.2, 0.48, 0.58])

    region_totals = state.groupby("region")["customers"].sum()
    draw_state_map(ax_map, classes, ORDINAL_BLUE, MAP_LABELS, "Customers",
                   {r: fmt_pct(v / n_all * 100) for r, v in region_totals.items()})

    # Columns: states grouped by region (largest region first), sorted within region
    order = region_totals.sort_values(ascending=False).index.tolist()
    cols = pd.concat([state[state["region"] == r].sort_values("customers", ascending=False)
                      for r in order])
    style_axes(ax_col, "y")
    values = cols["customers"].tolist()
    top_in_region = cols.groupby("region")["customers"].transform("max") == cols["customers"]
    labels = [f"{v:,}" if top else "" for v, top in zip(values, top_in_region)]
    bar(ax_col, cols["state"].tolist(), values, labels, ymax=max(values) * 1.12)
    ax_col.yaxis.set_major_formatter(lambda y, _: f"{y:,.0f}")
    ax_col.tick_params(axis="x", labelsize=7.5)
    # Region brackets under the state ticks
    pos = 0
    for region in order:
        n = (cols["region"] == region).sum()
        y = -0.1
        ax_col.plot([pos - 0.35, pos + n - 0.65], [y, y], color=MUTED, linewidth=1 * 72 / DPI,
                    transform=ax_col.get_xaxis_transform(), clip_on=False)
        ax_col.text(pos + (n - 1) / 2, y - 0.04, region, ha="center", va="top", fontsize=8,
                    color=INK_2, transform=ax_col.get_xaxis_transform())
        pos += n

    top3 = state["share"].head(3).sum() * 100
    set_titles(fig, "Customers by state and region",
               f"{n_all:,} unique customers by the state of their latest order; thick lines mark "
               f"the five macro-regions. SP, RJ and MG hold {top3:.1f}%", left=0.02)
    save(fig, "04_customers_map_by_state")


# ---------------------------------------------------------------- 06 / 07 quarters

def chart_spend_by_quarter(con) -> None:
    q = con.execute(QUARTER_SQL).df()
    summary = q.groupby(["year", "quarter"]).agg(
        customers=("customer_unique_id", "nunique"), spend=("spend", "sum")).reset_index()
    summary["spend_per_customer"] = summary["spend"] / summary["customers"]
    summary["partial"] = [(y, qt) in PARTIAL_QUARTERS
                          for y, qt in zip(summary["year"], summary["quarter"])]
    save_table(summary, "spend_by_quarter")

    years = sorted(summary["year"].unique())
    series, labels = {}, []
    for year in years:
        vals, labs = [], []
        for qt in range(1, 5):
            row = summary[(summary["year"] == year) & (summary["quarter"] == qt)]
            if row.empty:
                vals.append(None)
                labs.append("")
                continue
            v = row["spend"].iat[0]
            vals.append(v)
            labs.append(fmt_brl(v) + ("*" if (year, qt) in PARTIAL_QUARTERS else ""))
        series[str(year)] = vals
        labels.append(labs)

    fig, ax = new_figure(1300, 640, left=0.08, right=0.97, top=0.76, bottom=0.1)
    style_axes(ax, "y")
    grouped_bar(ax, ["Q1", "Q2", "Q3", "Q4"], series, SERIES[:len(years)], labels)
    ax.yaxis.set_major_formatter(lambda y, _: fmt_brl(y))
    full = summary[~summary["partial"]]
    best = full.loc[full["spend"].idxmax()]
    set_titles(fig, "Total spend by quarter",
               f"Payment value of valid orders; peak full quarter {int(best['year'])} "
               f"Q{int(best['quarter'])} at {fmt_brl(best['spend'])}. "
               "* partial quarter (data starts Sep 2016, Nov 2016 missing, ends Sep 2018)")
    legend(fig, [str(y) for y in years], SERIES[:len(years)], y_px_from_top=95)
    save(fig, "06_spend_by_quarter")

    # 07: spend tier mix within each quarter
    q["tier"] = pd.cut(q["spend"], SPEND_BINS, labels=SPEND_LABELS, right=False)
    q["period"] = q["year"].astype(str) + " Q" + q["quarter"].astype(str)
    # Quarters with a handful of customers (2016 Q3, 2018 Q4) would distort the scale
    period_n = q["period"].value_counts()
    dropped = sorted(period_n[period_n < MIN_QUARTER_CUSTOMERS].index)
    periods = sorted(period_n[period_n >= MIN_QUARTER_CUSTOMERS].index)
    q = q[q["period"].isin(periods)]
    ct = pd.crosstab(q["period"], q["tier"], normalize="index") \
        .reindex(index=periods, columns=SPEND_LABELS).fillna(0) * 100
    n = q["period"].value_counts().reindex(periods)
    save_table(ct.reset_index(), "spend_tier_by_quarter")
    partial_names = {f"{y} Q{qt}" for y, qt in PARTIAL_QUARTERS}
    rows = [f"{p}{'*' if p in partial_names else ''}  (n={c:,})" for p, c in n.items()]
    cells = {(r, c): f"{ct.iat[r, c]:.1f}%" for r in range(len(ct)) for c in range(len(SPEND_LABELS))}
    height = 130 + 44 * len(ct)
    fig, ax = new_figure(1300, height, left=0.19, right=0.97, top=1 - 150 / height,
                         bottom=10 / height)
    heatmap(ax, ct.values, rows, [f"{s} BRL" for s in SPEND_LABELS], cells, vmax=ct.values.max())
    dropped_note = f"; {', '.join(dropped)} omitted (< {MIN_QUARTER_CUSTOMERS} customers)" \
        if dropped else ""
    set_titles(fig, "Customer spend tier by quarter",
               "Row share of customers by their total spend within each quarter; "
               f"* partial quarter{dropped_note}")
    save(fig, "07_spend_tier_by_quarter")


# ---------------------------------------------------------------- 10 review x category

def chart_review_by_category(con, top_n: int = 7) -> None:
    df = con.execute(REVIEW_SQL).df()
    totals = df.groupby("category")["reviews"].sum().sort_values(ascending=False)
    top = totals.head(top_n).index.tolist()
    df["group"] = df["category"].where(df["category"].isin(top), "Other")
    pivot = df.pivot_table(index="review_score", columns="group", values="reviews",
                           aggfunc="sum", fill_value=0).reindex(index=[1, 2, 3, 4, 5],
                                                                columns=top + ["Other"])
    save_table(pivot.reset_index(), "review_score_by_category")

    names = top + ["Other"]
    colors = SERIES[:top_n] + [OTHER]
    stacks = [pivot[name].tolist() for name in names]
    totals_by_score = pivot.sum(axis=1)
    grand = totals_by_score.sum()
    total_labels = [f"{v:,}  ({fmt_pct(v / grand * 100)})" for v in totals_by_score]

    # Horizontal: segment length gets the full plot width, so small categories stay visible
    height = 150 + 44 * 5 + 60
    fig, ax = new_figure(1400, height, left=0.1, right=0.86, top=1 - 150 / height,
                         bottom=60 / height)
    style_axes(ax, "x")
    stacked_bar(ax, [f"{s} ★" for s in pivot.index], stacks, colors, horizontal=True,
                total_labels=total_labels)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:,.0f}")
    ax.set_ylabel("Review score", labelpad=8)
    ax.set_xlabel("Reviews", labelpad=6)
    set_titles(fig, "Review score by category",
               f"Review count per score, stacked by the top {top_n} categories "
               "(orders spanning several categories count once in each)")
    legend(fig, names, colors, y_px_from_top=95, ncol=4)
    save(fig, "10_review_score_by_category")


# ---------------------------------------------------------------- 11 categories

def chart_categories(con, n_buyers: int, top_n: int = 15) -> None:
    cat = con.execute(CATEGORY_SQL).df()
    save_table(cat, "category_orders_spend")
    top = cat.head(top_n)
    n = len(top)
    height = 140 + 34 * n + 50
    fig = plt.figure(figsize=(1500 / DPI, height / DPI), dpi=DPI)
    top_frac, bottom_frac = 1 - 140 / height, 50 / height
    ax_o = fig.add_axes([0.2, bottom_frac, 0.33, top_frac - bottom_frac])
    ax_s = fig.add_axes([0.62, bottom_frac, 0.33, top_frac - bottom_frac])

    style_axes(ax_o, "x")
    barh(ax_o, top["category"].tolist(), top["orders"].tolist(),
         [f"{v:,}" for v in top["orders"]], color=SERIES[0])
    ax_o.xaxis.set_major_formatter(lambda x, _: f"{x:,.0f}")

    style_axes(ax_s, "x")
    total_spend = cat["spend"].sum()
    barh(ax_s, top["category"].tolist(), top["spend"].tolist(),
         [f"{fmt_brl(v)}  ({fmt_pct(v / total_spend * 100)})" for v in top["spend"]],
         color=SERIES[0], xmax=top["spend"].max() * 1.32)
    ax_s.set_yticklabels([])
    ax_s.xaxis.set_major_locator(MultipleLocator(500_000))
    ax_s.xaxis.set_major_formatter(lambda x, _: f"R$ {x / 1e6:.1f}M" if x else "0")

    y_head = 1 - 118 / height
    fig.text(0.2, y_head, "Orders", fontsize=9.5, fontweight="semibold", color=INK_2)
    fig.text(0.62, y_head, "Spend (price + freight)", fontsize=9.5, fontweight="semibold",
             color=INK_2)
    share = top["spend"].sum() / total_spend * 100
    set_titles(fig, f"Top {top_n} categories by spend",
               f"Valid orders; ranked by spend. These {top_n} categories take {share:.1f}% "
               "of total spend", left=0.2)
    save(fig, "11_top_categories_orders_spend")


# ---------------------------------------------------------------- 12 / 13 regions

def chart_tier_by_region(buyers: pd.DataFrame) -> None:
    ct = pd.crosstab(buyers["region"], buyers["spend_tier"], normalize="index") \
        .reindex(index=list(REGIONS), columns=SPEND_LABELS) * 100
    national = buyers["spend_tier"].value_counts(normalize=True).reindex(SPEND_LABELS) * 100
    diff = (ct - national).round(1) + 0.0  # + 0.0 turns -0.0 into 0.0
    ct_n = buyers["region"].value_counts().reindex(list(REGIONS))
    save_table(ct.reset_index(), "spending_tier_by_region")
    cells = {(r, c): f"{ct.iat[r, c]:.1f}%\n{diff.iat[r, c]:+.1f} pp"
             for r in range(len(ct)) for c in range(len(SPEND_LABELS))}
    fig, ax = new_figure(1300, 620, left=0.17, right=0.97, top=0.72, bottom=0.03)
    lim = abs(diff.values).max()
    heatmap(ax, diff.values, [f"{r}  (n={n:,})" for r, n in ct_n.items()],
            [f"{s} BRL" for s in SPEND_LABELS], cells, vmin=-lim, vmax=lim, cmap=DIV_CMAP)
    high = ct[SPEND_LABELS[3:]].sum(axis=1)  # share spending >= 200 BRL
    set_titles(fig, "Spending tier mix by region",
               f"Share per tier; color = gap vs national mix (blue above, red below). "
               f"≥ 200 BRL: {high.idxmax()} {high.max():.1f}% vs {high.idxmin()} {high.min():.1f}%")
    save(fig, "12_spending_tier_by_region")


def chart_price_freight_by_region(buyers: pd.DataFrame) -> None:
    g = buyers.groupby("region")[["product_value", "freight_value"]].mean() \
        .reindex(list(REGIONS))
    g["freight_share"] = g["freight_value"] / (g["product_value"] + g["freight_value"])
    save_table(g.reset_index(), "price_freight_by_region")

    names = ["Product price", "Freight"]
    stacks = [g["product_value"].tolist(), g["freight_value"].tolist()]
    labels = [f"{fmt_brl(p + f)}  (freight {s:.0%})"
              for p, f, s in zip(g["product_value"], g["freight_value"], g["freight_share"])]
    fig, ax = new_figure(1300, 420, left=0.14, right=0.9, top=0.68, bottom=0.12)
    style_axes(ax, "x")
    stacked_bar(ax, g.index.tolist(), stacks, SERIES[:2], horizontal=True, total_labels=labels)
    ax.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
    north, se = g.loc["North"], g.loc["Southeast"]
    set_titles(fig, "Average spend per customer: product price vs freight",
               f"North vs Southeast: product price +{north['product_value'] / se['product_value'] - 1:.0%}, "
               f"freight {north['freight_value'] / se['freight_value']:.1f}×")
    legend(fig, names, SERIES[:2], y_px_from_top=95)
    save(fig, "13_price_freight_by_region")


def main() -> None:
    con = connect()
    cust = con.execute(CUSTOMER_SQL).df()
    cust["region"] = cust["customer_state"].map(STATE_TO_REGION)
    n_all = len(cust)
    buyers = cust[cust["valid_orders"] > 0].copy()
    n_buyers = len(buyers)
    buyers["spend_tier"] = pd.cut(buyers["total_spend"], SPEND_BINS, labels=SPEND_LABELS,
                                  right=False)
    print(f"customers: {n_all:,}; with valid orders: {n_buyers:,}")

    # 04 state map + columns
    state = cust["customer_state"].value_counts().rename_axis("state").reset_index(name="customers")
    state["region"] = state["state"].map(STATE_TO_REGION)
    state["share"] = state["customers"] / n_all
    save_table(state, "customers_by_state")
    chart_state_map(state, n_all)

    # 06 / 07 quarters
    chart_spend_by_quarter(con)

    # 08 preferred payment type
    pay_type = buyers["preferred_payment_type"].fillna("no payment record")
    pay = count_table(pay_type, pay_type.value_counts().index.tolist(), "payment_type")
    save_table(pay, "preferred_payment_type")
    hbar_chart(pay, "payment_type", "Preferred payment type",
               "Payment type with the largest total value per customer",
               "08_preferred_payment_type", left=0.16)

    # 09 credit card installments
    inst_labels = ["1 (single payment)", "2–3", "4–6", "7–10", "11+"]
    cc_users = buyers.dropna(subset=["max_installments"]).copy()
    cc_users["inst_band"] = pd.cut(cc_users["max_installments"], [-1, 1, 3, 6, 10, float("inf")],
                                   labels=inst_labels)
    inst = count_table(cc_users["inst_band"], inst_labels, "max_installments")
    save_table(inst, "credit_card_installments")
    multi = (1 - inst["share"].iloc[0]) * 100
    vbar_chart(inst, "max_installments", "Credit card installments",
               f"{len(cc_users):,} credit-card customers by the most installments used; "
               f"{multi:.1f}% split a payment", "09_credit_card_installments",
               xlabel="Max installments per customer")

    # 10 / 11 review and categories
    chart_review_by_category(con)
    chart_categories(con, n_buyers)

    # 12 / 13 regions
    chart_tier_by_region(buyers)
    chart_price_freight_by_region(buyers)
    con.close()


if __name__ == "__main__":
    main()
