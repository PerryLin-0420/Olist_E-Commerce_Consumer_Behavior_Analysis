"""EDA 03: seller-level repeat purchase rate, summarized by product category.

Repeat rate is measured per (seller, category) pair:
    repeat_rate = customers with >= 2 valid orders from that seller in that category
                  / distinct customers of that seller in that category
Customers are customer_unique_id. The distribution of seller repeat rates is
then summarized per category (Q1 / median / Q3 / IQR).

Small sellers make the rate unstable (1 of 2 customers = 50%), so only sellers
with >= MIN_CUSTOMERS customers in the category are kept, and only categories
with >= MIN_SELLERS such sellers are reported.

Outputs
- outputs/seller_repeat_rate_by_seller_category.csv  one row per (seller, category)
- outputs/seller_repeat_rate_iqr_by_category.csv     IQR table per category
- charts/05_seller_repeat_rate_iqr_by_category.png
"""
import pandas as pd
from matplotlib.lines import Line2D

from eda_utils import (DPI, GRID, INK, INK_2, MUTED, SERIES, SURFACE, connect, new_figure,
                       save, save_table, set_titles, style_axes)

MIN_CUSTOMERS = 30
MIN_SELLERS = 5

PAIR_SQL = """
WITH sc AS (
    SELECT i.seller_id,
           coalesce(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
           cu.customer_unique_id,
           count(DISTINCT o.order_id) AS orders
    FROM orders o
    JOIN customers cu USING (customer_id)
    JOIN order_items i USING (order_id)
    JOIN products p USING (product_id)
    LEFT JOIN product_category_name_translation t USING (product_category_name)
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY 1, 2, 3
)
SELECT category, seller_id,
       count(*) AS customers,
       count(*) FILTER (WHERE orders >= 2) AS repeat_customers
FROM sc
GROUP BY 1, 2
ORDER BY 1, 2
"""


def iqr_table(pairs: pd.DataFrame) -> pd.DataFrame:
    def summarize(g: pd.DataFrame) -> pd.Series:
        r = g["repeat_rate"]
        q1, med, q3 = r.quantile([0.25, 0.5, 0.75])
        return pd.Series({
            "sellers": len(g),
            "customers": g["customers"].sum(),
            "repeat_customers": g["repeat_customers"].sum(),
            "pooled_rate": g["repeat_customers"].sum() / g["customers"].sum(),
            "mean": r.mean(),
            "q1": q1, "median": med, "q3": q3, "iqr": q3 - q1,
            "sellers_with_zero_repeat": (r == 0).mean(),
        })

    by_cat = pairs.groupby("category").apply(summarize, include_groups=False)
    by_cat = by_cat[by_cat["sellers"] >= MIN_SELLERS]
    by_cat = by_cat.sort_values(["median", "q3", "pooled_rate"], ascending=False)
    overall = summarize(pairs).rename("All categories")
    table = pd.concat([by_cat, overall.to_frame().T])
    table[["sellers", "customers", "repeat_customers"]] = \
        table[["sellers", "customers", "repeat_customers"]].astype(int)
    return table.rename_axis("category").reset_index()


def chart(table: pd.DataFrame) -> None:
    n = len(table)
    height = 175 + 30 * n + 50
    fig, ax = new_figure(1600, height, left=0.2, right=0.53,
                         top=1 - 175 / height, bottom=50 / height)
    style_axes(ax, "x")
    xmax = max(0.06, table["q3"].max() * 1.15)
    ax.set_xlim(0, xmax)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), table["category"])
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    # Separate the overall row from the categories
    ax.axhline(n - 1.5, color=GRID, linewidth=1 * 72 / DPI)
    ax.get_yticklabels()[-1].set_fontweight("semibold")

    for i, row in table.iterrows():
        if row["q3"] > row["q1"]:
            ax.plot([row["q1"], row["q3"]], [i, i], color=SERIES[0], linewidth=10 * 72 / DPI,
                    solid_capstyle="butt")
        # Median dot with a 2px surface ring
        ax.plot(row["median"], i, "o", markersize=8 * 72 / DPI + 2, color=INK,
                markeredgecolor=SURFACE, markeredgewidth=2 * 72 / DPI, zorder=3, clip_on=False)

    # Table columns to the right of the plot
    columns = [("Sellers", "sellers", "{:,.0f}"), ("Q1", "q1", "{:.2%}"),
               ("Median", "median", "{:.2%}"), ("Q3", "q3", "{:.2%}"),
               ("IQR", "iqr", "{:.2%}"), ("Pooled\nrate", "pooled_rate", "{:.2%}"),
               ("Zero-repeat\nsellers", "sellers_with_zero_repeat", "{:.0%}")]
    x_positions = [0.6, 0.66, 0.725, 0.785, 0.845, 0.91, 0.98]
    header_y = 1 - 160 / height
    for (title, col, fmt), x in zip(columns, x_positions):
        fig.text(x, header_y, title, ha="right", va="bottom", fontsize=8.5, color=MUTED)
        for i, value in enumerate(table[col]):
            y_disp = ax.transData.transform((0, i))[1]
            y_fig = fig.transFigure.inverted().transform((0, y_disp))[1]
            weight = "semibold" if i == n - 1 else "normal"
            fig.text(x, y_fig, fmt.format(value), ha="right", va="center", fontsize=8.5,
                     color=INK if i == n - 1 else INK_2, fontweight=weight)

    handles = [Line2D([], [], color=SERIES[0], linewidth=10 * 72 / DPI, label="IQR (Q1–Q3)"),
               Line2D([], [], marker="o", color=INK, linestyle="none", markersize=6,
                      label="Median")]
    fig.legend(handles=handles, loc="upper left", frameon=False, ncol=2, fontsize=8.5,
               labelcolor=INK_2, bbox_to_anchor=(0.2, 1 - 118 / height), borderaxespad=0)
    set_titles(fig, "Seller repeat purchase rate by category (IQR)",
               "Per seller × category: share of the seller's customers who placed 2+ orders "
               "with that seller in that category.\n"
               f"Sellers with ≥ {MIN_CUSTOMERS} customers in the category; categories with "
               f"≥ {MIN_SELLERS} such sellers. Pooled rate = all repeat customers / all customers")
    save(fig, "05_seller_repeat_rate_iqr_by_category")


def main() -> None:
    con = connect()
    pairs = con.execute(PAIR_SQL).df()
    con.close()
    pairs["repeat_rate"] = pairs["repeat_customers"] / pairs["customers"]
    save_table(pairs, "seller_repeat_rate_by_seller_category")

    kept = pairs[pairs["customers"] >= MIN_CUSTOMERS]
    print(f"(seller, category) pairs: {len(pairs):,}; with >= {MIN_CUSTOMERS} customers: "
          f"{len(kept):,}")
    table = iqr_table(kept)
    save_table(table, "seller_repeat_rate_iqr_by_category")
    chart(table)


if __name__ == "__main__":
    main()
