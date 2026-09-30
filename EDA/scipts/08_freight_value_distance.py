"""EDA 08: product value, freight share, distance and weight by category.

Unit: shipment = the items one seller ships in one order (valid orders).
- product value = sum of item prices, freight = sum of freight values,
  freight ratio = freight / product value, weight = sum of item weights
- category = category of the shipment's highest-priced item (ties alphabetical)
- distance = great-circle distance between seller and customer zip-prefix centroids
Categories with >= MIN_SHIPMENTS shipments are compared.

Charts (charts/) and tables (outputs/)
- 29_category_value_vs_freight_ratio   median product value vs median freight ratio
- 30_freight_vs_distance_by_weight     median freight by distance, per weight tier
- 31_category_distance_mix             distance-band mix per category vs all shipments
- 32_far_share_vs_value_and_weight     share of shipments >= FAR_KM vs value and weight
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from eda_utils import (DIV_CMAP, DPI, GRID, INK_2, MUTED, SERIES, SURFACE, connect, fmt_brl,
                       heatmap, legend, new_figure, save, save_table, set_titles, style_axes)

MIN_SHIPMENTS = 300
FAR_KM = 1000
VALUE_TICKS = [20, 50, 100, 200]
DIST_STEP_KM = 100
DIST_MAX_KM = 3000
MIN_BIN_SHIPMENTS = 30  # distance bins with fewer shipments are not drawn
WEIGHT_BINS = [0, 500, 2000, 10000, float("inf")]
WEIGHT_LABELS = ["< 0.5 kg", "0.5–2 kg", "2–10 kg", "≥ 10 kg"]
DIST_BANDS = [0, 100, 300, 600, 1000, 2000, float("inf")]
DIST_BAND_LABELS = ["< 100 km", "100–300", "300–600", "600–1,000", "1,000–2,000", "≥ 2,000"]

SHIPMENT_SQL = """
WITH it AS (
    SELECT i.order_id, i.seller_id, i.price, i.freight_value, p.product_weight_g AS weight_g,
           coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
               AS category
    FROM order_items i
    JOIN products p USING (product_id)
    LEFT JOIN product_category_name_translation t USING (product_category_name)
)
SELECT it.order_id, it.seller_id,
       sum(it.price) AS product_value,
       sum(it.freight_value) AS freight,
       sum(it.weight_g) AS weight_g,
       first(it.category ORDER BY it.price DESC, it.category) AS category,
       any_value(2 * 6371 * asin(sqrt(
           pow(sin(radians(gc.geolocation_lat - gs.geolocation_lat) / 2), 2)
           + cos(radians(gs.geolocation_lat)) * cos(radians(gc.geolocation_lat))
             * pow(sin(radians(gc.geolocation_lng - gs.geolocation_lng) / 2), 2)))) AS distance_km
FROM it
JOIN orders o USING (order_id)
JOIN customers cu USING (customer_id)
JOIN sellers se USING (seller_id)
LEFT JOIN geolocation_zip gs ON gs.geolocation_zip_code_prefix = se.seller_zip_code_prefix
LEFT JOIN geolocation_zip gc ON gc.geolocation_zip_code_prefix = cu.customer_zip_code_prefix
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2
ORDER BY 1, 2
"""


def spearman(a: pd.Series, b: pd.Series) -> float:
    return a.corr(b, method="spearman")


def category_table(ship: pd.DataFrame) -> pd.DataFrame:
    g = ship.groupby("category").agg(
        shipments=("product_value", "size"),
        median_product_value=("product_value", "median"),
        median_freight=("freight", "median"),
        median_freight_ratio=("freight_ratio", "median"),
        freight_ratio_of_totals=("freight", "sum"),
        median_weight_g=("weight_g", "median"),
        median_distance_km=("distance_km", "median"),
        far_share=("far", "mean"))
    g["freight_ratio_of_totals"] = g["freight_ratio_of_totals"] / \
        ship.groupby("category")["product_value"].sum()
    return g[g["shipments"] >= MIN_SHIPMENTS].sort_values("median_product_value")


def chart_value_ratio(cat: pd.DataFrame, ship: pd.DataFrame) -> None:
    rho = spearman(cat["median_product_value"], cat["median_freight_ratio"])
    rho_ship = spearman(ship["product_value"], ship["freight_ratio"])
    fixed = ship["freight"].median()
    fig, ax = new_figure(1500, 820, left=0.08, right=0.97, top=0.8, bottom=0.1)
    style_axes(ax, "y")
    ax.set_xscale("log")
    xs = np.geomspace(cat["median_product_value"].min() * 0.8,
                      cat["median_product_value"].max() * 1.25, 100)
    ax.plot(xs, fixed / xs * 100, color=MUTED, linewidth=2 * 72 / DPI, zorder=1)
    ax.text(xs[-1], fixed / xs[-1] * 100, f"  R$ {fixed:.0f} freight on every shipment",
            fontsize=8, color=MUTED, va="center", ha="right")
    ax.scatter(cat["median_product_value"], cat["median_freight_ratio"] * 100,
               s=(8 + 2) ** 2, color=SERIES[0], edgecolor=SURFACE, linewidth=2 * 72 / DPI,
               zorder=3)
    # Label the extremes only; the mid-price cluster is too dense for readable labels
    label = set(cat["median_freight_ratio"].nlargest(3).index) | \
        set(cat["median_freight_ratio"].nsmallest(3).index) | \
        {cat["median_product_value"].idxmax()}
    for name, row in cat.loc[sorted(label)].iterrows():
        ax.annotate(name, (row["median_product_value"], row["median_freight_ratio"] * 100),
                    textcoords="offset points", xytext=(7, 4), fontsize=8, color=INK_2)
    ax.set_ylim(0, cat["median_freight_ratio"].max() * 100 * 1.15)
    ax.set_xticks(VALUE_TICKS, [fmt_brl(v) for v in VALUE_TICKS])
    ax.xaxis.set_minor_formatter(lambda x, _: "")
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%")
    ax.set_xlabel("Median product value per shipment (log scale)", labelpad=6)
    ax.set_ylabel("Median freight / product value", labelpad=6)
    legend(fig, ["Category (≥ 300 shipments)", "Reference: fixed freight at the overall median"],
           [SERIES[0], MUTED], y_px_from_top=100, left=0.08)
    set_titles(fig, "Cheaper products carry a larger freight share",
               f"{len(cat)} categories. Spearman ρ across categories {rho:+.2f}; across "
               f"{len(ship):,} shipments {rho_ship:+.2f}. Median freight R$ {fixed:.2f}, "
               f"median product value R$ {ship['product_value'].median():.2f}")
    save(fig, "29_category_value_vs_freight_ratio")


def chart_freight_distance(ship: pd.DataFrame) -> pd.DataFrame:
    d = ship.dropna(subset=["distance_km", "weight_g"]).copy()
    d["tier"] = pd.cut(d["weight_g"], WEIGHT_BINS, labels=WEIGHT_LABELS, right=False)
    edges = np.arange(0, DIST_MAX_KM + DIST_STEP_KM, DIST_STEP_KM)
    d["dist_bin"] = pd.cut(d["distance_km"], edges, right=False)
    rows, fits = [], []
    fig, ax = new_figure(1500, 820, left=0.08, right=0.72, top=0.77, bottom=0.1)
    style_axes(ax, "y")
    for tier, color in zip(WEIGHT_LABELS, SERIES):
        t = d[d["tier"] == tier]
        b = t.groupby("dist_bin", observed=True)["freight"].agg(["median", "size"])
        b = b[b["size"] >= MIN_BIN_SHIPMENTS]
        mid = np.array([iv.mid for iv in b.index])
        ax.plot(mid, b["median"], color=color, linewidth=2 * 72 / DPI, zorder=3)
        # Straight-line fit of the binned medians: freight = intercept + slope * km
        slope, intercept = np.polyfit(mid, b["median"], 1)
        fits.append({"weight_tier": tier, "shipments": len(t),
                     "spearman_distance_freight": spearman(t["distance_km"], t["freight"]),
                     "intercept_brl": intercept, "slope_brl_per_100km": slope * 100,
                     "median_freight": t["freight"].median()})
        for m, (_, r) in zip(mid, b.iterrows()):
            rows.append({"weight_tier": tier, "distance_mid_km": m,
                         "median_freight": r["median"], "shipments": int(r["size"])})
    fit = pd.DataFrame(fits)
    save_table(pd.DataFrame(rows), "freight_by_distance_and_weight")
    save_table(fit, "freight_distance_fit")
    ax.set_xlim(0, DIST_MAX_KM)
    ax.set_ylim(0, None)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:,.0f} km")
    ax.yaxis.set_major_formatter(lambda y, _: fmt_brl(y))
    ax.set_xlabel(f"Seller–customer distance ({DIST_STEP_KM} km bins)", labelpad=6)
    ax.set_ylabel("Median freight per shipment", labelpad=6)
    # Side table: straight-line fit per tier
    fig.text(0.75, 0.78, "Straight-line fit of the medians", fontsize=9, fontweight="semibold",
             color=INK_2, va="top")
    for i, (row, color) in enumerate(zip(fit.itertuples(), SERIES)):
        y = 0.72 - i * 0.12
        fig.patches.append(plt.Rectangle((0.75, y - 0.012), 0.012, 0.024, color=color,
                                         transform=fig.transFigure, figure=fig))
        fig.text(0.77, y, f"{row.weight_tier}  (n={row.shipments:,})\n"
                 f"R$ {row.intercept_brl:.1f} + R$ {row.slope_brl_per_100km:.2f} per 100 km\n"
                 f"ρ(distance, freight) {row.spearman_distance_freight:+.2f}",
                 fontsize=8.5, color=INK_2, va="center")
    legend(fig, WEIGHT_LABELS, SERIES[:len(WEIGHT_LABELS)], y_px_from_top=125, left=0.08)
    rho = spearman(d["distance_km"], d["freight"])
    set_titles(fig, "Freight rises with distance within every weight tier",
               f"Median freight per {DIST_STEP_KM} km distance bin (bins with < "
               f"{MIN_BIN_SHIPMENTS} shipments hidden). Spearman ρ over all shipments {rho:+.2f}.\n"
               "The intercepts show a fixed part that does not scale with distance, so freight "
               "grows linearly with distance but is not strictly proportional to it")
    save(fig, "30_freight_vs_distance_by_weight")
    return fit


def chart_distance_mix(cat: pd.DataFrame, ship: pd.DataFrame) -> None:
    d = ship.dropna(subset=["distance_km"])
    d = d.assign(band=pd.cut(d["distance_km"], DIST_BANDS, labels=DIST_BAND_LABELS, right=False))
    order = cat.sort_values("far_share", ascending=False).index.tolist()
    sub = d[d["category"].isin(order)]
    ct = pd.crosstab(sub["category"], sub["band"], normalize="index") \
        .reindex(index=order, columns=DIST_BAND_LABELS) * 100
    overall = d["band"].value_counts(normalize=True).reindex(DIST_BAND_LABELS) * 100
    diff = (ct - overall).round(1) + 0.0
    save_table(ct.reset_index(), "category_distance_mix")
    cells = {(r, c): f"{ct.iat[r, c]:.1f}%" for r in range(len(ct)) for c in range(len(DIST_BAND_LABELS))}
    height = 190 + 30 * len(ct) + 20
    fig, ax = new_figure(1600, height, left=0.2, right=0.66, top=1 - 190 / height,
                         bottom=20 / height)
    lim = np.abs(diff.values).max()
    heatmap(ax, diff.values, order, [f"{b}\n(all {overall[b]:.1f}%)" for b in DIST_BAND_LABELS],
            cells, vmin=-lim, vmax=lim, cmap=DIV_CMAP)
    ax.tick_params(axis="y", labelsize=8)
    headers = [("Median value", "median_product_value", fmt_brl),
               ("Median weight", "median_weight_g", lambda v: f"{v / 1000:.2f} kg"),
               ("Freight ratio", "median_freight_ratio", lambda v: f"{v:.0%}"),
               (f"≥ {FAR_KM:,} km", "far_share", lambda v: f"{v:.1%}")]
    xs = [0.75, 0.84, 0.92, 0.99]
    for (title, col, fmt), x in zip(headers, xs):
        fig.text(x, 1 - 172 / height, title, ha="right", va="bottom", fontsize=8.5, color=MUTED)
        for i, name in enumerate(order):
            y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
            fig.text(x, y, fmt(cat.loc[name, col]), ha="right", va="center", fontsize=8,
                     color=INK_2)
    set_titles(fig, "Distance mix by category",
               f"Categories with ≥ {MIN_SHIPMENTS} shipments, sorted by share shipped ≥ "
               f"{FAR_KM:,} km. Cell = share of the category's shipments in each distance band;"
               "\ncolor = gap vs all shipments (blue above, red below)", left=0.02)
    save(fig, "31_category_distance_mix")


def chart_far_share(cat: pd.DataFrame) -> dict:
    stats = {"rho_far_vs_value": spearman(cat["far_share"], cat["median_product_value"]),
             "rho_far_vs_weight": spearman(cat["far_share"], cat["median_weight_g"]),
             "rho_far_vs_freight_ratio": spearman(cat["far_share"], cat["median_freight_ratio"]),
             "rho_distance_vs_weight": spearman(cat["median_distance_km"], cat["median_weight_g"])}
    fig = plt.figure(figsize=(1600 / DPI, 700 / DPI), dpi=DPI)
    panels = [("median_product_value", "Median product value per shipment", fmt_brl,
               stats["rho_far_vs_value"], VALUE_TICKS),
              ("median_weight_g", "Median shipment weight", lambda v: f"{v / 1000:g} kg",
               stats["rho_far_vs_weight"], [200, 500, 1000, 2000, 5000, 10000])]
    for i, (col, title, fmt, rho, ticks) in enumerate(panels):
        ax = fig.add_axes([0.07 + i * 0.48, 0.12, 0.42, 0.6])
        style_axes(ax, "y")
        ax.set_xscale("log")
        ax.scatter(cat[col], cat["far_share"] * 100, s=(8 + 2) ** 2, color=SERIES[0],
                   edgecolor=SURFACE, linewidth=2 * 72 / DPI, zorder=3)
        label = set(cat["far_share"].nlargest(3).index) | set(cat["far_share"].nsmallest(3).index)
        for name in sorted(label):
            ax.annotate(name, (cat.loc[name, col], cat.loc[name, "far_share"] * 100),
                        textcoords="offset points", xytext=(6, 4), fontsize=7.5, color=INK_2)
        ax.set_ylim(0, cat["far_share"].max() * 100 * 1.2)
        ax.set_xticks(ticks, [fmt(t) for t in ticks])
        ax.xaxis.set_minor_formatter(lambda x, _: "")
        ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%")
        ax.set_xlabel(f"{title} (log scale)", labelpad=6)
        if i == 0:
            ax.set_ylabel(f"Share of shipments ≥ {FAR_KM:,} km", labelpad=6)
        fig.text(0.07 + i * 0.48, 0.75, f"vs {title.lower()}: Spearman ρ {rho:+.2f}",
                 fontsize=9.5, fontweight="semibold", color=INK_2)
    set_titles(fig, "Which categories reach distant customers?",
               f"{len(cat)} categories. Share shipped ≥ {FAR_KM:,} km vs price level and vs "
               f"weight; ρ with freight ratio {stats['rho_far_vs_freight_ratio']:+.2f}", left=0.07)
    save(fig, "32_far_share_vs_value_and_weight")
    return stats


def main() -> None:
    con = connect()
    ship = con.execute(SHIPMENT_SQL).df()
    con.close()
    ship = ship[ship["product_value"] > 0].copy()
    ship["freight_ratio"] = ship["freight"] / ship["product_value"]
    ship["far"] = (ship["distance_km"] >= FAR_KM).astype(float).where(ship["distance_km"].notna())

    cat = category_table(ship)
    save_table(cat.reset_index(), "category_value_freight_distance")
    chart_value_ratio(cat, ship)
    fit = chart_freight_distance(ship)
    chart_distance_mix(cat, ship)
    stats = chart_far_share(cat)
    save_table(pd.DataFrame([stats]), "far_share_correlations")
    print(fit.round(3).to_string(index=False))
    print({k: round(v, 3) for k, v in stats.items()})


if __name__ == "__main__":
    main()
