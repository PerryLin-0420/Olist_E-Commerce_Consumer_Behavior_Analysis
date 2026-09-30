"""EDA 05: order value - mean vs median by category, single-order spend by region.

- Category: per (order, category), product value = sum of item prices of that
  category in the order (freight excluded, since it depends on distance).
- Region: per order, spend = total payment value; region = customer state on
  that order. Spend per customer = orders per customer x average order value.
Only valid orders (order_status not in canceled, unavailable) are used.

Charts (charts/) and tables (outputs/)
- 19_category_order_value_mean_median
- 20_region_order_value
"""
import pandas as pd

from eda_geo import REGIONS, STATE_TO_REGION
from eda_utils import (WHISKER_NOTE, box_legend, box_rows, connect, fmt_brl, new_figure, save,
                       save_table, set_titles, side_table, style_axes)

CATEGORY_ORDER_SQL = """
SELECT o.order_id,
       coalesce(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
       count(*) AS items,
       sum(i.price) AS product_value,
       sum(i.freight_value) AS freight_value
FROM orders o
JOIN order_items i USING (order_id)
JOIN products p USING (product_id)
LEFT JOIN product_category_name_translation t USING (product_category_name)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2
ORDER BY 1, 2
"""

REGION_ORDER_SQL = """
SELECT o.order_id, c.customer_unique_id, c.customer_state, sum(p.payment_value) AS order_value
FROM orders o
JOIN customers c USING (customer_id)
JOIN order_payments p USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2, 3
ORDER BY 1
"""


def summarize(values: pd.Series) -> dict:
    q1, med, q3 = values.quantile([0.25, 0.5, 0.75])
    return {"q1": q1, "median": med, "q3": q3, "mean": values.mean()}


def box_chart(table, datasets, label_col, columns, x_positions, title, subtitle, filename,
              width=1600, plot_right=0.55):
    """Box plot rows (datasets aligned with table rows) plus a numeric side table."""
    n = len(table)
    height = 170 + 30 * n + 55
    fig, ax = new_figure(width, height, left=0.19, right=plot_right,
                         top=1 - 170 / height, bottom=55 / height)
    style_axes(ax, "x")
    box_rows(ax, table[label_col].tolist(), datasets)
    ax.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
    ax.axhline(n - 1.5, color="#e1e0d9", linewidth=0.5)
    ax.get_yticklabels()[-1].set_fontweight("semibold")
    side_table(fig, ax, table, columns, x_positions, header_px_from_top=160, bold_last=True)
    box_legend(fig, 0.19, 118)
    set_titles(fig, title, f"{subtitle}\nBox = Q1–Q3, dashed line = median; {WHISKER_NOTE}")
    save(fig, filename)


def chart_category(con, top_n: int = 20) -> None:
    df = con.execute(CATEGORY_ORDER_SQL).df()
    rows = []
    for cat, g in df.groupby("category"):
        rows.append({"category": cat, "orders": len(g), "items_per_order": g["items"].mean(),
                     **summarize(g["product_value"]),
                     "freight_mean": g["freight_value"].mean()})
    table = pd.DataFrame(rows)
    table["mean_to_median"] = table["mean"] / table["median"]
    table = table.sort_values("orders", ascending=False)
    save_table(table, "category_order_value")

    top = table.head(top_n).sort_values("median", ascending=False)
    per_order = df.groupby("order_id")["product_value"].sum()
    overall = {"category": "All orders", "orders": len(per_order),
               "items_per_order": df.groupby("order_id")["items"].sum().mean(),
               **summarize(per_order)}
    overall["mean_to_median"] = overall["mean"] / overall["median"]
    top = pd.concat([top, pd.DataFrame([overall])], ignore_index=True)

    groups = dict(tuple(df.groupby("category")["product_value"]))
    datasets = [groups[c] for c in top["category"].iloc[:-1]] + [per_order]
    skew = top.iloc[:-1].sort_values("mean_to_median", ascending=False).iloc[0]
    columns = [("Orders", "orders", "{:,.0f}"), ("Median", "median", fmt_brl),
               ("Mean", "mean", fmt_brl), ("Mean ÷\nmedian", "mean_to_median", "{:.2f}×")]
    box_chart(top, datasets, "category", columns, [0.66, 0.75, 0.84, 0.93],
              "Product value per order by category: mean vs median",
              f"Top {top_n} categories by orders, sorted by median; product price only "
              f"(freight excluded). Mean exceeds median everywhere; most skewed: "
              f"{skew['category']} ({skew['mean_to_median']:.2f}×)",
              "19_category_order_value_mean_median")


def chart_region(con) -> None:
    df = con.execute(REGION_ORDER_SQL).df()
    df["region"] = df["customer_state"].map(STATE_TO_REGION)
    rows = []
    for region in REGIONS:
        g = df[df["region"] == region]
        rows.append({"region": region, "orders": len(g),
                     "customers": g["customer_unique_id"].nunique(),
                     **summarize(g["order_value"])})
    rows.append({"region": "All regions", "orders": len(df),
                 "customers": df["customer_unique_id"].nunique(), **summarize(df["order_value"])})
    table = pd.DataFrame(rows)
    table["orders_per_customer"] = table["orders"] / table["customers"]
    table["spend_per_customer"] = table["orders_per_customer"] * table["mean"]
    body = table.iloc[:-1].sort_values("median", ascending=False)
    table = pd.concat([body, table.iloc[[-1]]], ignore_index=True)
    save_table(table, "region_order_value")

    # State-level detail for later drill-down
    state = df.groupby("customer_state")["order_value"].agg(
        orders="count", median="median", mean="mean").reset_index()
    save_table(state.sort_values("median", ascending=False), "state_order_value")

    hi, lo = body.iloc[0], body.iloc[-1]
    datasets = [df.loc[df["region"] == r, "order_value"] for r in table["region"].iloc[:-1]]
    datasets.append(df["order_value"])
    columns = [("Orders", "orders", "{:,.0f}"), ("Orders /\ncustomer", "orders_per_customer",
                                                 "{:.3f}"),
               ("Median", "median", fmt_brl), ("Mean", "mean", fmt_brl),
               ("Spend /\ncustomer", "spend_per_customer", fmt_brl)]
    box_chart(table, datasets, "region", columns, [0.64, 0.72, 0.8, 0.88, 0.97],
              "Single-order spend by region",
              f"Payment value per order. Median order: {hi['region']} {fmt_brl(hi['median'])} vs "
              f"{lo['region']} {fmt_brl(lo['median'])}; orders per customer are nearly equal, so "
              "the spend gap comes from order size", "20_region_order_value", plot_right=0.52)


def main() -> None:
    con = connect()
    chart_category(con)
    chart_region(con)
    con.close()


if __name__ == "__main__":
    main()
