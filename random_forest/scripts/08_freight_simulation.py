"""Step 08: how purchases relate to the freight share, and a freight scenario simulation.

Only completed purchases are observed (no impressions or abandoned carts), so a
conversion rate cannot be measured directly. The steps below use what the
purchases reveal:

A. Tolerance: share of shipments by freight ratio (freight / product value),
   overall and per weight tier, as cumulative curves.
B. Weight x distance: distance-band mix of each weight tier vs all shipments.
C. Freight model: a random forest (N_TREES trees) predicts log1p(freight) of a
   shipment from weight, volume, item count, distance and seller / customer
   coordinates; evaluated on a 20% hold-out of orders.
D. Within-category association: for every category x customer state cell,
   lift = the category's share of the state's shipments / its national share,
   and the predicted freight ratio of the category's own shipments re-routed to
   the state's customer centroid (model C). Both are demeaned within category
   (removing how popular the category is everywhere); the weighted slope of
   log(lift) on log(freight ratio) is the association, with a bootstrap over
   categories for the 95% interval.
E. Scenario: every cell whose predicted freight ratio exceeds TARGET_RATIO is
   brought down to TARGET_RATIO, and its shipments scale by
   (TARGET_RATIO / ratio) ** slope. This treats a cross-sectional association as
   if it were causal; it is an upper-bound style what-if, not a forecast.

Outputs: outputs/sim_*.csv; charts/sim_freight_ratio_tolerance.png,
sim_weight_distance_mix.png, sim_freight_model.png, sim_category_state_association.png,
sim_scenario.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from rf_common import N_TREES, RANDOM_STATE
from eda_geo import REGIONS, STATE_TO_REGION  # noqa: E402
from eda_utils import (DIV_CMAP, DPI, GRID, INK, INK_2, MUTED, SERIES, SURFACE,  # noqa: E402
                       connect, fmt_brl, heatmap, legend, new_figure, save, save_table,
                       set_titles, style_axes)

MIN_SHIPMENTS = 300          # categories compared in D / E
MIN_EXPECTED = 5             # cells with fewer expected shipments are dropped from D
TARGET_RATIO = 0.20
SAMPLE_PER_CATEGORY = 400    # shipments re-routed per category and state in D
N_BOOT = 1000
WEIGHT_BINS = [0, 500, 2000, 10000, float("inf")]
WEIGHT_LABELS = ["< 0.5 kg", "0.5–2 kg", "2–10 kg", "≥ 10 kg"]
DIST_BANDS = [0, 100, 300, 600, 1000, 2000, float("inf")]
DIST_LABELS = ["< 100 km", "100–300", "300–600", "600–1,000", "1,000–2,000", "≥ 2,000"]
RATIO_GRID = np.linspace(0, 1.0, 101)
FEATURES = ["weight_g", "volume_cm3", "items", "distance_km", "seller_lat", "seller_lng",
            "customer_lat", "customer_lng"]

SHIPMENT_SQL = """
WITH it AS (
    SELECT i.order_id, i.seller_id, i.price, i.freight_value, p.product_weight_g AS weight_g,
           p.product_length_cm * p.product_height_cm * p.product_width_cm AS volume_cm3,
           coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
               AS category
    FROM order_items i
    JOIN products p USING (product_id)
    LEFT JOIN product_category_name_translation t USING (product_category_name)
)
SELECT it.order_id, it.seller_id, cu.customer_state,
       count(*) AS items,
       sum(it.price) AS product_value, sum(it.freight_value) AS freight,
       sum(it.weight_g) AS weight_g, sum(it.volume_cm3) AS volume_cm3,
       first(it.category ORDER BY it.price DESC, it.category) AS category,
       any_value(gs.geolocation_lat) AS seller_lat, any_value(gs.geolocation_lng) AS seller_lng,
       any_value(gc.geolocation_lat) AS customer_lat, any_value(gc.geolocation_lng) AS customer_lng
FROM it
JOIN orders o USING (order_id)
JOIN customers cu USING (customer_id)
JOIN sellers se USING (seller_id)
LEFT JOIN geolocation_zip gs ON gs.geolocation_zip_code_prefix = se.seller_zip_code_prefix
LEFT JOIN geolocation_zip gc ON gc.geolocation_zip_code_prefix = cu.customer_zip_code_prefix
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1, 2, 3
ORDER BY 1, 2
"""


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def load() -> pd.DataFrame:
    con = connect()
    ship = con.execute(SHIPMENT_SQL).df()
    con.close()
    ship = ship.dropna(subset=["seller_lat", "customer_lat", "weight_g", "volume_cm3"])
    ship = ship[ship["product_value"] > 0].copy()
    ship["distance_km"] = haversine_km(ship["seller_lat"], ship["seller_lng"],
                                       ship["customer_lat"], ship["customer_lng"])
    ship["freight_ratio"] = ship["freight"] / ship["product_value"]
    ship["weight_tier"] = pd.cut(ship["weight_g"], WEIGHT_BINS, labels=WEIGHT_LABELS, right=False)
    ship["dist_band"] = pd.cut(ship["distance_km"], DIST_BANDS, labels=DIST_LABELS, right=False)
    return ship.reset_index(drop=True)


# ---------------------------------------------------------------- A tolerance

def chart_tolerance(ship: pd.DataFrame) -> pd.DataFrame:
    rows = []
    fig, ax = new_figure(1500, 760, left=0.08, right=0.7, top=0.78, bottom=0.11)
    style_axes(ax, "y")
    ax.axvline(TARGET_RATIO * 100, color=MUTED, linewidth=1 * 72 / DPI)
    groups = [("All shipments", ship, INK)] + \
        [(t, ship[ship["weight_tier"] == t], c) for t, c in zip(WEIGHT_LABELS, SERIES)]
    for name, g, color in groups:
        cum = np.array([(g["freight_ratio"] <= r).mean() for r in RATIO_GRID])
        ax.plot(RATIO_GRID * 100, cum * 100, color=color,
                linewidth=(2.6 if name == "All shipments" else 2) * 72 / DPI, zorder=3)
        rows.append({"group": name, "shipments": len(g),
                     "median_ratio": g["freight_ratio"].median(),
                     "share_le_10": (g["freight_ratio"] <= 0.10).mean(),
                     "share_le_20": (g["freight_ratio"] <= 0.20).mean(),
                     "share_le_30": (g["freight_ratio"] <= 0.30).mean(),
                     "share_gt_50": (g["freight_ratio"] > 0.50).mean()})
    table = pd.DataFrame(rows)
    save_table(table, "sim_freight_ratio_tolerance")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%")
    ax.set_xlabel("Freight / product value", labelpad=6)
    ax.set_ylabel("Cumulative share of shipments", labelpad=6)
    ax.text(TARGET_RATIO * 100 + 1, 3, f"{TARGET_RATIO:.0%}", fontsize=8, color=MUTED)
    fig.text(0.73, 0.76, f"Share of shipments with freight ≤ {TARGET_RATIO:.0%} of value",
             fontsize=9, fontweight="semibold", color=INK_2, va="top")
    for i, row in table.iterrows():
        fig.text(0.73, 0.69 - i * 0.075,
                 f"{row['group']}: {row['share_le_20']:.1%}  (median ratio "
                 f"{row['median_ratio']:.0%}, n={row['shipments']:,})",
                 fontsize=8.5, color=INK_2, va="center")
    legend(fig, ["All shipments"] + WEIGHT_LABELS, [INK] + SERIES[:4], y_px_from_top=100,
           left=0.08)
    set_titles(fig, "How large a freight share do buyers accept?",
               "Cumulative share of completed shipments by freight ratio. Only purchases are "
               "observed, so this is the freight share buyers paid, not a conversion rate")
    save(fig, "sim_freight_ratio_tolerance")
    return table


# ---------------------------------------------------------------- B weight x distance

def chart_weight_distance(ship: pd.DataFrame) -> pd.DataFrame:
    d = ship.dropna(subset=["dist_band", "weight_tier"])
    ct = pd.crosstab(d["weight_tier"], d["dist_band"], normalize="index") \
        .reindex(index=WEIGHT_LABELS, columns=DIST_LABELS) * 100
    overall = d["dist_band"].value_counts(normalize=True).reindex(DIST_LABELS) * 100
    lift = ct / overall
    counts = pd.crosstab(d["weight_tier"], d["dist_band"]).reindex(index=WEIGHT_LABELS,
                                                                   columns=DIST_LABELS)
    ratio = d.groupby(["weight_tier", "dist_band"], observed=True)["freight_ratio"].median() \
        .unstack().reindex(index=WEIGHT_LABELS, columns=DIST_LABELS)
    out = ct.stack().rename("row_share").to_frame().join(lift.stack().rename("lift")) \
        .join(counts.stack().rename("shipments")).join(ratio.stack().rename("median_ratio"))
    save_table(out.reset_index(), "sim_weight_distance_mix")
    cells = {(r, c): f"{ct.iat[r, c]:.1f}%  ×{lift.iat[r, c]:.2f}\nfreight {ratio.iat[r, c]:.0%}"
             for r in range(len(WEIGHT_LABELS)) for c in range(len(DIST_LABELS))}
    fig, ax = new_figure(1500, 560, left=0.15, right=0.98, top=0.68, bottom=0.03)
    lim = np.abs(np.log2(lift.values)).max()
    heatmap(ax, np.log2(lift.values), [f"{t}\nn={int(counts.loc[t].sum()):,}" for t in WEIGHT_LABELS],
            [f"{b}\n(all {overall[b]:.1f}%)" for b in DIST_LABELS], cells, vmin=-lim, vmax=lim,
            cmap=DIV_CMAP)
    heavy_near = lift.loc["≥ 10 kg", "< 100 km"]
    set_titles(fig, "Distance mix by weight tier",
               "Cell = share of the tier's shipments in each distance band, lift vs all shipments, "
               "and median freight ratio;\ncolor = log2 lift (blue: over-represented). Shipments "
               f"≥ 10 kg within 100 km: ×{heavy_near:.2f} the overall share", left=0.02)
    save(fig, "sim_weight_distance_mix")
    return out


# ---------------------------------------------------------------- C freight model

def fit_freight_model(ship: pd.DataFrame):
    rng = np.random.default_rng(RANDOM_STATE)
    orders = ship["order_id"].unique()
    test_orders = set(rng.choice(orders, size=int(len(orders) * 0.2), replace=False))
    is_test = ship["order_id"].isin(test_orders).to_numpy()
    X, y = ship[FEATURES], np.log1p(ship["freight"])
    model = RandomForestRegressor(n_estimators=N_TREES, min_samples_leaf=5, n_jobs=-1,
                                  random_state=RANDOM_STATE)
    model.fit(X[~is_test], y[~is_test])
    pred = np.expm1(model.predict(X[is_test]))
    actual = ship.loc[is_test, "freight"].to_numpy()
    metrics = {"train_shipments": int((~is_test).sum()), "test_shipments": int(is_test.sum()),
               "r2_freight": r2_score(actual, pred),
               "r2_log_freight": r2_score(np.log1p(actual), np.log1p(pred)),
               "mae_brl": mean_absolute_error(actual, pred),
               "median_abs_error_brl": float(np.median(np.abs(actual - pred)))}
    importance = pd.Series(model.feature_importances_, index=FEATURES).sort_values(ascending=False)
    save_table(pd.DataFrame([metrics]), "sim_freight_model_metrics")
    save_table(importance.rename("importance").rename_axis("feature").reset_index(),
               "sim_freight_model_importance")

    fig = plt.figure(figsize=(1500 / DPI, 700 / DPI), dpi=DPI)
    ax1 = fig.add_axes([0.07, 0.12, 0.4, 0.62])
    lim = np.percentile(actual, 99)
    ax1.hexbin(actual, pred, gridsize=60, extent=(0, lim, 0, lim), bins="log",
               cmap="Blues", mincnt=1)
    ax1.plot([0, lim], [0, lim], color=MUTED, linewidth=1 * 72 / DPI)
    style_axes(ax1, "y")
    ax1.set_xlim(0, lim)
    ax1.set_ylim(0, lim)
    ax1.xaxis.set_major_formatter(lambda x, _: fmt_brl(x))
    ax1.yaxis.set_major_formatter(lambda y, _: fmt_brl(y))
    ax1.set_xlabel("Actual freight (hold-out)", labelpad=6)
    ax1.set_ylabel("Predicted freight", labelpad=6)
    fig.text(0.07, 0.77, "Predicted vs actual (color = shipment count, log)", fontsize=9.5,
             fontweight="semibold", color=INK_2)
    ax2 = fig.add_axes([0.62, 0.12, 0.34, 0.62])
    style_axes(ax2, "x")
    ax2.barh(range(len(importance)), importance.values * 100, height=0.55, color=SERIES[0])
    ax2.set_yticks(range(len(importance)), importance.index)
    ax2.set_ylim(len(importance) - 0.5, -0.5)
    ax2.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    for i, v in enumerate(importance.values):
        ax2.text(v * 100 + 0.8, i, f"{v:.1%}", va="center", fontsize=8, color=INK_2)
    fig.text(0.62, 0.77, "Feature importance", fontsize=9.5, fontweight="semibold", color=INK_2)
    set_titles(fig, "Freight model used for the simulation",
               f"Random forest ({N_TREES} trees) on {metrics['train_shipments']:,} shipments; "
               f"hold-out of {metrics['test_shipments']:,} (orders split 80/20): R² "
               f"{metrics['r2_freight']:.2f} (log scale {metrics['r2_log_freight']:.2f}), "
               f"median absolute error R$ {metrics['median_abs_error_brl']:.2f}", left=0.07)
    save(fig, "sim_freight_model")
    return model, metrics


# ---------------------------------------------------------------- D association

def state_cells(ship: pd.DataFrame, model) -> pd.DataFrame:
    """Lift and predicted freight ratio for every category x customer state."""
    rng = np.random.default_rng(RANDOM_STATE)
    cats = ship["category"].value_counts()
    cats = cats[cats >= MIN_SHIPMENTS].index
    centroid = ship.groupby("customer_state")[["customer_lat", "customer_lng"]].mean()
    counts = pd.crosstab(ship["category"], ship["customer_state"])
    national = counts.sum(axis=1) / counts.values.sum()
    state_total = counts.sum(axis=0)
    rows = []
    for cat in cats:
        g = ship[ship["category"] == cat]
        g = g.iloc[rng.choice(len(g), size=min(SAMPLE_PER_CATEGORY, len(g)), replace=False)]
        for state, (lat, lng) in centroid.iterrows():
            X = g[FEATURES].copy()
            X["customer_lat"], X["customer_lng"] = lat, lng
            X["distance_km"] = haversine_km(g["seller_lat"], g["seller_lng"], lat, lng)
            freight = np.expm1(model.predict(X))
            ratio = np.median(freight / g["product_value"].to_numpy())
            expected = national[cat] * state_total[state]
            rows.append({"category": cat, "state": state, "region": STATE_TO_REGION[state],
                         "shipments": int(counts.loc[cat, state]), "expected": expected,
                         "lift": counts.loc[cat, state] / expected,
                         "predicted_freight_ratio": ratio,
                         "median_distance_km": float(np.median(X["distance_km"]))})
    return pd.DataFrame(rows)


def within_slope(cells: pd.DataFrame) -> float:
    d = cells.copy()
    d["x"] = np.log(d["predicted_freight_ratio"])
    d["y"] = np.log(d["lift"])
    d[["x", "y"]] = d[["x", "y"]] - d.groupby("category")[["x", "y"]].transform("mean")
    w = d["expected"]
    return float((w * d["x"] * d["y"]).sum() / (w * d["x"] ** 2).sum())


def association(cells: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    d = cells[(cells["expected"] >= MIN_EXPECTED) & (cells["shipments"] > 0)].copy()
    slope = within_slope(d)
    rng = np.random.default_rng(RANDOM_STATE)
    cats = d["category"].unique()
    boot = []
    for _ in range(N_BOOT):
        pick = rng.choice(cats, size=len(cats), replace=True)
        sample = pd.concat([d[d["category"] == c].assign(category=f"{c}#{i}")
                            for i, c in enumerate(pick)])
        boot.append(within_slope(sample))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    stats = {"cells": len(d), "categories": len(cats), "slope": slope, "slope_lo": lo,
             "slope_hi": hi}
    d["x_dm"] = np.log(d["predicted_freight_ratio"]) - \
        d.groupby("category")["predicted_freight_ratio"].transform(lambda s: np.log(s).mean())
    d["y_dm"] = np.log(d["lift"]) - d.groupby("category")["lift"].transform(lambda s: np.log(s).mean())
    return d, stats


def chart_association(d: pd.DataFrame, stats: dict) -> None:
    fig, ax = new_figure(1500, 800, left=0.08, right=0.97, top=0.78, bottom=0.11)
    style_axes(ax, "y")
    sizes = np.clip(d["expected"] / d["expected"].max() * 400, 8, 400)
    colors = [SERIES[list(REGIONS).index(r) % 8] for r in d["region"]]
    ax.scatter(d["x_dm"], d["y_dm"], s=sizes, c=colors, alpha=0.55, edgecolor=SURFACE,
               linewidth=0.5, zorder=3)
    xs = np.linspace(d["x_dm"].quantile(0.01), d["x_dm"].quantile(0.99), 50)
    ax.plot(xs, stats["slope"] * xs, color=INK, linewidth=2 * 72 / DPI, zorder=4)
    ax.axhline(0, color=GRID, linewidth=1 * 72 / DPI)
    ax.axvline(0, color=GRID, linewidth=1 * 72 / DPI)
    ax.set_xlim(d["x_dm"].quantile(0.005) * 1.1, d["x_dm"].quantile(0.995) * 1.1)
    ax.set_ylim(d["y_dm"].quantile(0.005) * 1.1, d["y_dm"].quantile(0.995) * 1.1)
    ax.set_xlabel("log predicted freight ratio, relative to the category's own average", labelpad=6)
    ax.set_ylabel("log lift (state share vs national share), relative to the category", labelpad=6)
    legend(fig, list(REGIONS), SERIES[:5], y_px_from_top=122, left=0.08)
    pct = (np.exp(stats["slope"] * np.log(1.1)) - 1) * 100
    set_titles(fig, "Within a category, do states facing a higher freight share buy less of it?",
               f"{stats['cells']} category × state cells ({stats['categories']} categories); dot "
               f"size = expected shipments. Weighted slope {stats['slope']:+.2f} [95% CI "
               f"{stats['slope_lo']:+.2f} to {stats['slope_hi']:+.2f}]:\na 10% higher freight "
               f"ratio goes with {pct:+.1f}% relative purchase share. Freight ratio and region "
               "overlap almost fully, so regional taste cannot be separated from freight")
    save(fig, "sim_category_state_association")


# ---------------------------------------------------------------- E scenario

def scenario(cells: pd.DataFrame, stats: dict) -> pd.DataFrame:
    d = cells.copy()
    over = d["predicted_freight_ratio"] > TARGET_RATIO
    factor = np.where(over, TARGET_RATIO / d["predicted_freight_ratio"], 1.0)
    rows = []
    for label, slope in [("central", stats["slope"]), ("low", stats["slope_hi"]),
                         ("high", stats["slope_lo"])]:
        # slope is negative when higher freight goes with fewer purchases
        d[f"sim_{label}"] = d["shipments"] * factor ** slope
    for region in list(REGIONS) + ["All"]:
        g = d if region == "All" else d[d["region"] == region]
        base = g["shipments"].sum()
        rows.append({"region": region, "shipments": int(base),
                     "cells_over_target": float((g["predicted_freight_ratio"] > TARGET_RATIO)
                                                .mean()),
                     **{f"change_{k}": g[f"sim_{k}"].sum() / base - 1
                        for k in ["central", "low", "high"]}})
    table = pd.DataFrame(rows)
    save_table(table, "sim_scenario")
    save_table(d, "sim_category_state_cells")

    fig, ax = new_figure(1400, 520, left=0.13, right=0.62, top=0.7, bottom=0.12)
    style_axes(ax, "x")
    n = len(table)
    ax.set_ylim(n - 0.5, -0.5)  # fix the rows before placing the side labels
    for i, row in table.iterrows():
        lo, hi = sorted([row["change_low"] * 100, row["change_high"] * 100])
        ax.plot([lo, hi], [i, i], color=SERIES[0], alpha=0.35, linewidth=8 * 72 / DPI,
                solid_capstyle="butt", zorder=2)
        ax.plot(row["change_central"] * 100, i, "o", color=INK if row["region"] == "All"
                else SERIES[0], markersize=8 * 72 / DPI + 2, markeredgecolor=SURFACE,
                markeredgewidth=2 * 72 / DPI, zorder=3)
        y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
        fig.text(0.98, y, f"{row['change_central']:+.1%}  [{min(row['change_low'], row['change_high']):+.1%}"
                 f" to {max(row['change_low'], row['change_high']):+.1%}]   "
                 f"cells over {TARGET_RATIO:.0%}: {row['cells_over_target']:.0%}",
                 ha="right", va="center", fontsize=8.5, color=INK_2)
    ax.axvline(0, color=INK_2, linewidth=1 * 72 / DPI)
    ax.set_yticks(range(n), table["region"])
    ax.get_yticklabels()[-1].set_fontweight("semibold")
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:+.0f}%")
    ax.set_xlabel("Simulated change in shipments", labelpad=6)
    set_titles(fig, f"What-if: every category × state capped at {TARGET_RATIO:.0%} freight ratio",
               "Dot = central slope, bar = 95% interval of the slope. The slope is a "
               "cross-sectional association treated as causal,\nso read this as an optimistic "
               "what-if, not a forecast; an A/B test with exposure data is needed to confirm it",
               left=0.02)
    save(fig, "sim_scenario")
    return table


def main() -> None:
    ship = load()
    print(f"shipments: {len(ship):,}")
    tol = chart_tolerance(ship)
    chart_weight_distance(ship)
    model, metrics = fit_freight_model(ship)
    cells = state_cells(ship, model)
    d, stats = association(cells)
    save_table(pd.DataFrame([stats]), "sim_association")
    chart_association(d, stats)
    scen = scenario(cells, stats)
    print(tol.round(3).to_string(index=False))
    print({k: round(v, 3) if isinstance(v, float) else v for k, v in metrics.items()})
    print({k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()})
    print(scen.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
