"""EDA 01: data quality - missing value statistics.

Outputs
- outputs/missing_by_column.csv          null count / rate for every column of every table
- charts/01_missing_rate_by_column.png   columns with any NULL, ranked by missing rate
- charts/02_orders_missing_by_status.png order timestamp NULL rate per order_status
- charts/03_relational_gaps.png          records with no matching row in a related table
"""
import pandas as pd

from eda_utils import (barh, connect, fmt_pct, heatmap, new_figure, save, save_table,
                       set_titles, style_axes)

RAW_TABLES = ["customers", "sellers", "product_category_name_translation", "products",
              "orders", "order_items", "order_payments", "order_reviews", "geolocation"]

# Lifecycle order of order_status, then terminal failure states
STATUS_ORDER = ["created", "approved", "invoiced", "processing", "shipped",
                "delivered", "canceled", "unavailable"]
ORDER_TS_COLUMNS = ["order_approved_at", "order_delivered_carrier_date",
                    "order_delivered_customer_date"]


def missing_by_column(con) -> pd.DataFrame:
    rows = []
    for table in RAW_TABLES:
        cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
        exprs = ", ".join(f'count(*) FILTER (WHERE "{c}" IS NULL)' for c in cols)
        total, *nulls = con.execute(f"SELECT count(*), {exprs} FROM {table}").fetchone()
        for col, n in zip(cols, nulls):
            rows.append({"table": table, "column": col, "total_rows": total,
                         "missing": n, "missing_rate": n / total})
    return pd.DataFrame(rows)


def chart_missing_rate(df: pd.DataFrame) -> None:
    d = df[df["missing"] > 0].sort_values("missing_rate", ascending=False)
    labels = [f"{t}.{c}" for t, c in zip(d["table"], d["column"])]
    rates = (d["missing_rate"] * 100).tolist()
    value_labels = [f"{fmt_pct(r)}  ({n:,})" for r, n in zip(rates, d["missing"])]

    fig, ax = new_figure(1300, 120 + 34 * len(d), left=0.33, right=0.93, top=0.78, bottom=0.08)
    style_axes(ax, "x")
    barh(ax, labels, rates, value_labels, xmax=100)
    ax.set_xticks(range(0, 101, 20), [f"{x}%" for x in range(0, 101, 20)])
    n_cols, n_all = len(d), len(df)
    set_titles(fig, "Missing rate by column",
               f"{n_cols} of {n_all} columns across 9 raw tables contain NULLs; "
               "the other columns are complete")
    save(fig, "01_missing_rate_by_column")


def chart_orders_by_status(con) -> pd.DataFrame:
    exprs = ", ".join(f"count(*) FILTER (WHERE {c} IS NULL) AS {c}" for c in ORDER_TS_COLUMNS)
    df = con.execute(f"""
        SELECT order_status, count(*) AS orders, {exprs}
        FROM orders GROUP BY order_status
    """).df().set_index("order_status").loc[STATUS_ORDER]

    rates = df[ORDER_TS_COLUMNS].div(df["orders"], axis=0) * 100
    cells = {}
    for r, status in enumerate(STATUS_ORDER):
        for c, col in enumerate(ORDER_TS_COLUMNS):
            n = df.loc[status, col]
            cells[(r, c)] = f"{fmt_pct(rates.loc[status, col])}\n({n:,})" if n else "0%"

    fig, ax = new_figure(1300, 820, left=0.2, right=0.97, top=0.76, bottom=0.03)
    heatmap(ax, rates.values, [f"{s}  (n={n:,})" for s, n in zip(STATUS_ORDER, df["orders"])],
            ["order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date"],
            cells, vmax=100)
    set_titles(fig, "Orders: timestamp NULL rate by order_status",
               "NULLs are mostly structural (the order never reached that stage); "
               "only the 'delivered' row signals real data gaps")
    save(fig, "02_orders_missing_by_status")
    return df.reset_index()


def chart_relational_gaps(con) -> pd.DataFrame:
    checks = [
        ("Orders without order_items", "orders",
         "SELECT count(*) FROM orders o WHERE NOT EXISTS "
         "(SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)"),
        ("Orders without order_reviews", "orders",
         "SELECT count(*) FROM orders o WHERE NOT EXISTS "
         "(SELECT 1 FROM order_reviews r WHERE r.order_id = o.order_id)"),
        ("Orders without order_payments", "orders",
         "SELECT count(*) FROM orders o WHERE NOT EXISTS "
         "(SELECT 1 FROM order_payments p WHERE p.order_id = o.order_id)"),
        ("Products with NULL category", "products",
         "SELECT count(*) FROM products WHERE product_category_name IS NULL"),
        ("Products with untranslated category", "products",
         "SELECT count(*) FROM products p WHERE product_category_name IS NOT NULL AND NOT EXISTS "
         "(SELECT 1 FROM product_category_name_translation t "
         "WHERE t.product_category_name = p.product_category_name)"),
        ("Customers whose zip is not in geolocation", "customers",
         "SELECT count(*) FROM customers c WHERE NOT EXISTS (SELECT 1 FROM geolocation_zip g "
         "WHERE g.geolocation_zip_code_prefix = c.customer_zip_code_prefix)"),
        ("Sellers whose zip is not in geolocation", "sellers",
         "SELECT count(*) FROM sellers s WHERE NOT EXISTS (SELECT 1 FROM geolocation_zip g "
         "WHERE g.geolocation_zip_code_prefix = s.seller_zip_code_prefix)"),
    ]
    rows = []
    for desc, base, query in checks:
        n = con.execute(query).fetchone()[0]
        total = con.execute(f"SELECT count(*) FROM {base}").fetchone()[0]
        rows.append({"check": desc, "base_table": base, "base_rows": total,
                     "affected": n, "affected_rate": n / total})
    df = pd.DataFrame(rows)

    rates = (df["affected_rate"] * 100).tolist()
    value_labels = [f"{fmt_pct(r)}  ({n:,} of {t:,})"
                    for r, n, t in zip(rates, df["affected"], df["base_rows"])]
    fig, ax = new_figure(1300, 440, left=0.3, right=0.93, top=0.74, bottom=0.1)
    style_axes(ax, "x")
    barh(ax, df["check"].tolist(), rates, value_labels, xmax=2.5)
    ax.set_xticks([0, 0.5, 1, 1.5, 2, 2.5], ["0%", "0.5%", "1%", "1.5%", "2%", "2.5%"])
    set_titles(fig, "Relational gaps: records with no matching related data",
               "Share of each base table affected; all gaps are under 2%")
    save(fig, "03_relational_gaps")
    return df


def main() -> None:
    con = connect()
    df = missing_by_column(con)
    save_table(df, "missing_by_column")
    chart_missing_rate(df)
    save_table(chart_orders_by_status(con), "orders_missing_by_status")
    save_table(chart_relational_gaps(con), "relational_gaps")

    # Co-missing patterns worth reporting alongside the charts
    products_all4 = con.execute("""
        SELECT count(*) FROM products WHERE product_category_name IS NULL
          AND product_name_lenght IS NULL AND product_description_lenght IS NULL
          AND product_photos_qty IS NULL""").fetchone()[0]
    reviews_no_text = con.execute("""
        SELECT count(*) FROM order_reviews
        WHERE review_comment_title IS NULL AND review_comment_message IS NULL""").fetchone()[0]
    print(f"products missing all 4 descriptive columns together: {products_all4}")
    print(f"reviews with neither title nor message: {reviews_no_text}")
    con.close()


if __name__ == "__main__":
    main()
