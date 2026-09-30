"""EDA 04: seller geography, shipping flows and distance vs order value.

Seller location comes from sellers.seller_zip_code_prefix joined to
geolocation_zip (zip-prefix centroid), the same way as customers, so the
seller-customer distance is a great-circle distance between zip centroids.

A "shipment" is the set of items one seller ships in one order
(order_id x seller_id); each seller dispatches its items separately.
Only valid orders (order_status not in canceled, unavailable) are used.

Charts (charts/) and tables (outputs/)
- 14_seller_vs_customer_map          seller and customer share by state, same scale
- 15_seller_customer_share_by_region
- 16_shipping_flow_by_region         seller region -> customer region
- 17_category_destination_region     where each category ships to
- 18_distance_vs_order_value         product price / freight per shipment by distance
"""
import matplotlib.pyplot as plt
import pandas as pd

from eda_geo import REGIONS, STATE_TO_REGION, draw_state_map, load_state_rings
from eda_utils import (DIV_CMAP, DPI, INK_2, ORDINAL_BLUE, SERIES, WHISKER_NOTE, box_legend,
                       box_rows, connect, fmt_brl, fmt_pct, grouped_bar, heatmap, legend,
                       new_figure, save, save_table, set_titles, style_axes)

SHARE_BINS = [0, 0.5, 1, 3, 10, float("inf")]
SHARE_LABELS = ["< 0.5%", "0.5–1%", "1–3%", "3–10%", "≥ 10%"]
DIST_BINS = [0, 100, 300, 600, 1000, 2000, float("inf")]
DIST_LABELS = ["< 100 km", "100–300 km", "300–600 km", "600–1,000 km", "1,000–2,000 km",
               "≥ 2,000 km"]
MIN_CATEGORY_SHIPMENTS = 500  # for per-category correlations

CUSTOMER_STATE_SQL = """
SELECT customer_state AS state, count(*) AS customers
FROM (
    SELECT c.customer_unique_id,
           first(c.customer_state ORDER BY o.order_purchase_timestamp DESC, c.customer_state)
               AS customer_state
    FROM orders o JOIN customers c USING (customer_id)
    GROUP BY 1
)
GROUP BY 1
"""

# Grain: (order, seller, category); distance in km between zip-prefix centroids
SHIPMENT_CATEGORY_SQL = """
SELECT o.order_id, i.seller_id,
       coalesce(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
       cu.customer_state, se.seller_state,
       sum(i.price) AS product_value,
       sum(i.freight_value) AS freight_value,
       any_value(2 * 6371 * asin(sqrt(
           pow(sin(radians(gc.geolocation_lat - gs.geolocation_lat) / 2), 2)
           + cos(radians(gs.geolocation_lat)) * cos(radians(gc.geolocation_lat))
             * pow(sin(radians(gc.geolocation_lng - gs.geolocation_lng) / 2), 2)))) AS distance_km
FROM orders o
JOIN customers cu USING (customer_id)
JOIN order_items i USING (order_id)
JOIN sellers se USING (seller_id)
JOIN products p USING (product_id)
LEFT JOIN product_category_name_translation t USING (product_category_name)
LEFT JOIN geolocation_zip gs ON gs.geolocation_zip_code_prefix = se.seller_zip_code_prefix
LEFT JOIN geolocation_zip gc ON gc.geolocation_zip_code_prefix = cu.customer_zip_code_prefix
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 2, 3
"""


def chart_dual_map(sellers: pd.DataFrame, customers: pd.DataFrame) -> None:
    rings = load_state_rings()
    fig = plt.figure(figsize=(1700 / DPI, 860 / DPI), dpi=DPI)
    panels = [(sellers, "sellers", "Sellers", [0.0, 0.03, 0.5, 0.78]),
              (customers, "customers", "Customers", [0.5, 0.03, 0.5, 0.78])]
    for i, (df, col, title, rect) in enumerate(panels):
        share = df.set_index("state")[col] / df[col].sum() * 100
        classes = pd.cut(share, SHARE_BINS, labels=False, right=False).to_dict()
        region_share = df.groupby("region")[col].sum() / df[col].sum() * 100
        ax = fig.add_axes(rect)
        draw_state_map(ax, classes, ORDINAL_BLUE, SHARE_LABELS, "Share of total",
                       {r: fmt_pct(v) for r, v in region_share.items()}, rings=rings,
                       show_legend=i == 0)
        fig.text(rect[0] + 0.02, rect[1] + rect[3] + 0.005,
                 f"{title}  (n={df[col].sum():,})", fontsize=10, fontweight="semibold",
                 color=INK_2)
    sp_s = sellers.set_index("state")["sellers"]["SP"] / sellers["sellers"].sum() * 100
    sp_c = customers.set_index("state")["customers"]["SP"] / customers["customers"].sum() * 100
    set_titles(fig, "Where sellers are vs where customers are",
               f"Share of sellers and of unique customers per state, same color scale. "
               f"SP hosts {sp_s:.1f}% of sellers but {sp_c:.1f}% of customers", left=0.02)
    save(fig, "14_seller_vs_customer_map")


def chart_region_share(sellers: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "sellers": sellers.groupby("region")["sellers"].sum(),
        "customers": customers.groupby("region")["customers"].sum(),
    }).reindex(list(REGIONS))
    df["seller_share"] = df["sellers"] / df["sellers"].sum()
    df["customer_share"] = df["customers"] / df["customers"].sum()
    df["customers_per_seller"] = df["customers"] / df["sellers"]
    df = df.sort_values("customer_share", ascending=False)

    series = {"Sellers": (df["seller_share"] * 100).tolist(),
              "Customers": (df["customer_share"] * 100).tolist()}
    labels = [[fmt_pct(v) for v in vals] for vals in series.values()]
    fig, ax = new_figure(1300, 620, left=0.08, right=0.97, top=0.76, bottom=0.14)
    style_axes(ax, "y")
    ticks = [f"{r}\n{c:,.0f} customers / seller" for r, c in
             zip(df.index, df["customers_per_seller"])]
    grouped_bar(ax, ticks, series, SERIES[:2], labels, ymax=90)
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%")
    over = df.index[df["seller_share"] > df["customer_share"]].tolist()
    under = df.index[df["seller_share"] < df["customer_share"]].tolist()
    set_titles(fig, "Seller vs customer share by region",
               f"Seller share exceeds customer share in {' and '.join(over)}; "
               f"{', '.join(under)} depend on sellers from other regions")
    legend(fig, list(series), SERIES[:2], y_px_from_top=95)
    save(fig, "15_seller_customer_share_by_region")
    return df.reset_index(names="region")


def chart_flow(ship: pd.DataFrame) -> None:
    ship = ship.assign(seller_region=ship["seller_state"].map(STATE_TO_REGION),
                       customer_region=ship["customer_state"].map(STATE_TO_REGION))
    ct = pd.crosstab(ship["seller_region"], ship["customer_region"], normalize="all") \
        .reindex(index=list(REGIONS), columns=list(REGIONS)).fillna(0) * 100
    save_table(ct.reset_index(names="seller_region"), "shipping_flow_by_region")
    row_total, col_total = ct.sum(axis=1), ct.sum(axis=0)
    cells = {(r, c): fmt_pct(ct.iat[r, c]) for r in range(5) for c in range(5)}
    fig, ax = new_figure(1300, 600, left=0.24, right=0.97, top=0.7, bottom=0.03)
    heatmap(ax, ct.values, [f"from {r}  ({fmt_pct(v)})" for r, v in row_total.items()],
            [f"to {c}\n({fmt_pct(v)})" for c, v in col_total.items()], cells,
            vmax=ct.values.max())
    same_state = (ship["seller_state"] == ship["customer_state"]).mean() * 100
    se_se = ct.loc["Southeast", "Southeast"]
    set_titles(fig, "Shipping flow: seller region → customer region",
               f"Share of all {len(ship):,} shipments. Southeast → Southeast alone is "
               f"{se_se:.1f}%; only {same_state:.1f}% of shipments stay within one state")
    save(fig, "16_shipping_flow_by_region")


def chart_category_destination(ship_cat: pd.DataFrame, top_n: int = 15) -> None:
    ship_cat = ship_cat.assign(customer_region=ship_cat["customer_state"].map(STATE_TO_REGION))
    top = ship_cat["category"].value_counts().head(top_n).index.tolist()
    sub = ship_cat[ship_cat["category"].isin(top)]
    ct = pd.crosstab(sub["category"], sub["customer_region"], normalize="index") \
        .reindex(index=top, columns=list(REGIONS)) * 100
    overall = ship_cat["customer_region"].value_counts(normalize=True).reindex(list(REGIONS)) * 100
    diff = (ct - overall).round(1) + 0.0
    med_km = sub.groupby("category")["distance_km"].median().reindex(top)
    n = sub["category"].value_counts().reindex(top)
    out = ct.copy()
    out["shipments"], out["median_distance_km"] = n, med_km
    save_table(out.reset_index(names="category"), "category_destination_region")

    cells = {(r, c): f"{ct.iat[r, c]:.1f}%\n{diff.iat[r, c]:+.1f} pp"
             for r in range(len(ct)) for c in range(len(REGIONS))}
    height = 185 + 46 * len(ct)
    fig, ax = new_figure(1500, height, left=0.33, right=0.97, top=1 - 185 / height,
                         bottom=10 / height)
    lim = abs(diff.values).max()
    heatmap(ax, diff.values,
            [f"{c}  (n={k:,}, median {d:,.0f} km)" for c, k, d in zip(top, n, med_km)],
            [f"to {r}\n(all: {overall[r]:.1f}%)" for r in REGIONS], cells, vmin=-lim, vmax=lim,
            cmap=DIV_CMAP)
    set_titles(fig, "Where each category ships to",
               f"Top {top_n} categories by shipments; cell = share of the category's shipments "
               "to each customer region,\ncolor = gap vs all categories (blue above, red below)",
               left=0.02)
    save(fig, "17_category_destination_region")


def chart_distance(ship: pd.DataFrame, ship_cat: pd.DataFrame) -> None:
    d = ship.dropna(subset=["distance_km"]).copy()
    d["band"] = pd.cut(d["distance_km"], DIST_BINS, labels=DIST_LABELS, right=False)
    rows = []
    for band, g in d.groupby("band", observed=True):
        row = {"band": band, "shipments": len(g)}
        for col in ["product_value", "freight_value"]:
            q1, med, q3 = g[col].quantile([0.25, 0.5, 0.75])
            row |= {f"{col}_q1": q1, f"{col}_median": med, f"{col}_q3": q3,
                    f"{col}_mean": g[col].mean()}
        rows.append(row)
    table = pd.DataFrame(rows)
    groups = [g for _, g in d.groupby("band", observed=True)]

    rho_price = d["distance_km"].corr(d["product_value"], method="spearman")
    rho_freight = d["distance_km"].corr(d["freight_value"], method="spearman")
    # Within-category correlations rule out category mix as the driver
    dc = ship_cat.dropna(subset=["distance_km"])
    per_cat = []
    for cat, g in dc.groupby("category"):
        if len(g) >= MIN_CATEGORY_SHIPMENTS:
            per_cat.append({"category": cat, "shipments": len(g),
                            "rho_distance_price": g["distance_km"].corr(g["product_value"],
                                                                         method="spearman"),
                            "rho_distance_freight": g["distance_km"].corr(g["freight_value"],
                                                                           method="spearman")})
    per_cat = pd.DataFrame(per_cat).sort_values("rho_distance_price", ascending=False)
    save_table(per_cat, "distance_correlation_by_category")

    n = len(table)
    height = 190 + 44 * n + 55
    fig = plt.figure(figsize=(1600 / DPI, height / DPI), dpi=DPI)
    top, bottom = 1 - 190 / height, 55 / height
    labels = [f"{b}  (n={k:,})" for b, k in zip(table["band"], table["shipments"])]
    for i, (col, title, x0) in enumerate([("product_value", "Product price per shipment", 0.17),
                                          ("freight_value", "Freight per shipment", 0.6)]):
        ax = fig.add_axes([x0, bottom, 0.36, top - bottom])
        style_axes(ax, "x")
        stats = box_rows(ax, labels, [g[col] for g in groups])
        table[f"{col}_whisker_low"] = [st["whislo"] for st in stats]
        table[f"{col}_whisker_high"] = [st["whishi"] for st in stats]
        ax.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
        if i == 1:
            ax.set_yticklabels([])
        med_first, med_last = table[f"{col}_median"].iloc[0], table[f"{col}_median"].iloc[-1]
        fig.text(x0, top + 22 / height, f"{title}   median {fmt_brl(med_first)} → "
                 f"{fmt_brl(med_last)}", fontsize=9.5, fontweight="semibold", color=INK_2)
    box_legend(fig, 0.17, 118)
    med_rho = per_cat["rho_distance_price"].median()
    set_titles(fig, "Seller–customer distance vs order value",
               f"Spearman ρ with distance: freight {rho_freight:.2f}, product price "
               f"{rho_price:.2f} (median within-category ρ for price {med_rho:.2f}, "
               f"{len(per_cat)} categories).\nDistance between zip-prefix centroids; "
               f"{WHISKER_NOTE}", left=0.17)
    save(fig, "18_distance_vs_order_value")
    save_table(table, "distance_vs_order_value")


def main() -> None:
    con = connect()
    sellers = con.execute(
        "SELECT seller_state AS state, count(*) AS sellers FROM sellers GROUP BY 1").df()
    customers = con.execute(CUSTOMER_STATE_SQL).df()
    ship_cat = con.execute(SHIPMENT_CATEGORY_SQL).df()
    con.close()

    # Some states may have no seller at all; the map still needs every state
    all_states = pd.DataFrame({"state": list(STATE_TO_REGION)})
    sellers = all_states.merge(sellers, how="left").fillna({"sellers": 0})
    sellers["sellers"] = sellers["sellers"].astype(int)
    for df in (sellers, customers):
        df["region"] = df["state"].map(STATE_TO_REGION)
    state = sellers.merge(customers, on=["state", "region"])
    state["seller_share"] = state["sellers"] / state["sellers"].sum()
    state["customer_share"] = state["customers"] / state["customers"].sum()
    save_table(state.sort_values("sellers", ascending=False), "seller_customer_by_state")

    ship = ship_cat.groupby(["order_id", "seller_id", "customer_state", "seller_state"],
                            as_index=False).agg(product_value=("product_value", "sum"),
                                                freight_value=("freight_value", "sum"),
                                                distance_km=("distance_km", "first"))
    print(f"shipments: {len(ship):,}; with distance: {ship['distance_km'].notna().sum():,}")

    chart_dual_map(sellers, customers)
    save_table(chart_region_share(sellers, customers), "seller_customer_share_by_region")
    chart_flow(ship)
    chart_category_destination(ship_cat)
    chart_distance(ship, ship_cat)


if __name__ == "__main__":
    main()
