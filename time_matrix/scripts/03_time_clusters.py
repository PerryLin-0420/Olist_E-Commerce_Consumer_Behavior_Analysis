"""Step 03: cluster the 168 weekday x hour cells with the k chosen in step 02.

Each cell is described by the three matrices of step 01:
- log(orders per week) - how much buying happens in the slot
- mean order value
- mean installments (0 = paid in full)
Features are standardized and clustered with KMeans (k from 02_k_selection.py).
Segments are relabelled T1..Tk by orders per cell and week, highest first.
Every order inherits the segment of its cell, so the segments are profiled at
order level. The START_K segmentation is kept to show how its segments nest
into the chosen ones.

Outputs: outputs/cell_clusters.csv, cluster_profile.csv, segments_start_k_vs_best.csv;
charts/05_cluster_map.png, 06_cluster_profile.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from sklearn.cluster import KMeans

from tm_common import (HOURS, RANDOM_STATE, START_K, WEEKDAYS, cell_features, cell_table,
                       chosen_k, load_orders, standardize)
from eda_utils import (DIV_CMAP, DPI, GRID, INK, INK_2, SERIES, SURFACE, fmt_brl,  # noqa: E402
                       heatmap, legend, new_figure, save, save_table, set_titles)

MAX_COLORED = 3  # beyond 3 hues on a map the colors stop being distinguishable


def segments(cells: pd.DataFrame, n_weeks: int, k: int) -> pd.Series:
    X = cell_features(cells["orders"].to_numpy(), (cells["orders"] * cells["mean_order_value"])
                      .to_numpy(), (cells["orders"] * cells["mean_installments"]).to_numpy(),
                      n_weeks)
    raw = KMeans(k, n_init=50, random_state=RANDOM_STATE).fit(standardize(X)).labels_
    raw = pd.Series(raw, index=cells.index)
    order = (cells["orders"] / n_weeks).groupby(raw).mean().sort_values(ascending=False).index
    return raw.map({old: f"T{i + 1}" for i, old in enumerate(order)}).rename("segment")


def profile_orders(df: pd.DataFrame, labels: pd.Series, n_weeks: int) -> pd.DataFrame:
    df = df.join(labels, on=["weekday", "hour"])
    g = df.groupby("segment")
    p = pd.DataFrame({
        "cells": labels.value_counts(),
        "orders": g.size(),
        "mean_order_value": g["order_value"].mean(),
        "median_order_value": g["order_value"].median(),
        "mean_installments": g["installments"].mean(),
        "installment_share": g["in_installments"].mean(),
        "boleto_share": g["main_payment_type"].apply(lambda s: (s == "boleto").mean()),
        "items_per_order": g["items"].mean(),
        "median_freight_ratio": g["freight_ratio"].median(),
        "mean_review_score": g["review_score"].mean(),
    }).astype(float)
    p["orders_share"] = p["orders"] / p["orders"].sum()
    p["orders_per_week"] = p["orders"] / p["cells"] / n_weeks
    return p.loc[sorted(p.index, key=lambda s: int(s[1:]))]


def describe_cells(labels: pd.Series, seg: str) -> str:
    """Short text of which weekday-hour blocks a segment covers."""
    cells = labels[labels == seg].index
    by_day = {}
    for d, h in cells:
        by_day.setdefault(d, []).append(h)
    parts = []
    for d in sorted(by_day):
        hours = sorted(by_day[d])
        runs, start = [], hours[0]
        for a, b in zip(hours, hours[1:] + [None]):
            if b != a + 1:
                runs.append(f"{start:02d}–{a:02d}h" if a > start else f"{start:02d}h")
                if b is not None:
                    start = b
        parts.append(f"{WEEKDAYS[d]} {', '.join(runs)}")
    return "; ".join(parts)


def chart_map(labels: pd.Series, profile: pd.DataFrame, k: int) -> None:
    segs = list(profile.index)
    grid = labels.map({s: i for i, s in enumerate(segs)}).unstack("hour") \
        .reindex(index=range(7), columns=HOURS)
    fig = plt.figure(figsize=(1800 / DPI, 760 / DPI), dpi=DPI)
    ax = fig.add_axes([0.05, 0.3, 0.9, 0.38])
    if k <= MAX_COLORED:
        cmap = ListedColormap(SERIES[:k])
        ax.imshow(grid.values, cmap=cmap, vmin=-0.5, vmax=k - 0.5, aspect="auto",
                  interpolation="nearest")
        for r in range(7):
            for c in range(24):
                ax.text(c, r, segs[int(grid.iat[r, c])], ha="center", va="center", fontsize=7,
                        color="white" if int(grid.iat[r, c]) != 2 else INK)
    else:  # fall back to one outlined label per cell on a neutral background
        ax.imshow(np.zeros_like(grid.values, dtype=float), cmap=ListedColormap([GRID]),
                  aspect="auto")
        for r in range(7):
            for c in range(24):
                ax.text(c, r, segs[int(grid.iat[r, c])], ha="center", va="center", fontsize=7,
                        color=INK)
    ax.set_xticks(range(24), [f"{h:02d}" for h in HOURS])
    ax.set_yticks(range(7), WEEKDAYS)
    ax.xaxis.tick_top()
    ax.tick_params(length=0, labelsize=8)
    ax.set_xticks([x - 0.5 for x in range(1, 24)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, 7)], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2 * 72 / DPI)
    ax.tick_params(which="minor", length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    names = [f"{s}: {int(p['cells'])} cells, {p['orders_share']:.1%} of orders, "
             f"{p['orders_per_week']:.1f} orders/cell/week, {fmt_brl(p['mean_order_value'])}, "
             f"{p['mean_installments']:.2f} inst." for s, p in profile.iterrows()]
    if k <= MAX_COLORED:
        legend(fig, names, SERIES[:k], y_px_from_top=100, ncol=1, left=0.05)
    for i, s in enumerate(segs):
        fig.text(0.05, 0.2 - i * 0.05, f"{s} covers: {describe_cells(labels, s)}",
                 fontsize=7.5, color=INK_2, wrap=True)
    set_titles(fig, f"The week in {k} time segments (k chosen by silhouette and stability)",
               "KMeans on each weekday × hour cell's orders per week, mean order value and mean "
               "installments; segments ordered by orders per cell and week", left=0.05)
    save(fig, "05_cluster_map")


def chart_profile(profile: pd.DataFrame) -> None:
    cols = ["orders_per_week", "mean_order_value", "median_order_value", "mean_installments",
            "installment_share", "boleto_share", "items_per_order", "median_freight_ratio",
            "mean_review_score"]
    names = ["Orders / cell / week", "Mean order value", "Median order value",
             "Mean installments", "Installment share", "Boleto share", "Items per order",
             "Median freight ratio", "Mean review score"]
    fmts = [lambda v: f"{v:.1f}", fmt_brl, fmt_brl, lambda v: f"{v:.2f}", lambda v: f"{v:.1%}",
            lambda v: f"{v:.1%}", lambda v: f"{v:.2f}", lambda v: f"{v:.1%}", lambda v: f"{v:.2f}"]
    vals = profile[cols].astype(float)
    z = (vals - vals.mean()) / vals.std(ddof=0)
    cells = {(r, c): fmts[c](vals.iat[r, c]) for r in range(len(vals)) for c in range(len(cols))}
    height = 170 + 50 * len(profile)
    fig, ax = new_figure(1700, height, left=0.2, right=0.98, top=1 - 170 / height,
                         bottom=10 / height)
    lim = np.abs(z.values).max()
    heatmap(ax, z.values, [f"{s}  ({int(profile.loc[s, 'cells'])} cells, "
                           f"{profile.loc[s, 'orders_share']:.1%} of orders)" for s in profile.index],
            names, cells, vmin=-lim, vmax=lim, cmap=DIV_CMAP)
    ax.tick_params(axis="x", labelsize=8)
    set_titles(fig, "Time segment profiles",
               "Order-level metrics of the orders placed in each segment's cells; color = gap vs "
               "the other segments (blue above, red below). Clustering used orders, mean order "
               "value and installments only", left=0.02)
    save(fig, "06_cluster_profile")


def main() -> None:
    df = load_orders()
    n_weeks = df["week"].nunique()
    cells = cell_table(df)
    k = chosen_k()
    labels = segments(cells, n_weeks, k)
    start = segments(cells, n_weeks, START_K)
    save_table(cells.join(labels).reset_index(), "cell_clusters")

    profile = profile_orders(df, labels, n_weeks)
    save_table(profile.reset_index(names="segment"), "cluster_profile")
    nest = pd.crosstab(start.rename(f"segment_k{START_K}"), labels.rename(f"segment_k{k}"))
    nest = nest.loc[sorted(nest.index, key=lambda s: int(s[1:]))]
    save_table(nest.reset_index(), "segments_start_k_vs_best")
    chart_map(labels, profile, k)
    chart_profile(profile)
    print(f"k = {k}")
    print(profile.round(3).to_string())
    print(nest.to_string())


if __name__ == "__main__":
    main()
