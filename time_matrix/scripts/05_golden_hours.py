"""Step 05: golden time slots inside segment T1 (the active hours of step 03).

For every T1 weekday x hour cell:
- orders per week (volume), mean order value (spend per order) and
  revenue per week = total payment value / weeks (= volume x spend)
A week-block bootstrap (N_GOLDEN_BOOT resamples of whole weeks) gives each
cell's probability of ranking in the top quarter of T1 cells by revenue per
week. Golden = probability >= GOLDEN_P; candidate = CANDIDATE_P to GOLDEN_P.

Checks
- Split-half: golden sets found on odd weeks vs even weeks (Jaccard overlap).
- Periods: in how many of the tm_common.PERIODS a cell is in the top quarter.
- What drives the ranking: Spearman correlation of revenue per week with
  orders per week and with mean order value across T1 cells.

Outputs: outputs/golden_cells.csv, golden_summary.csv; charts/11_t1_price_volume.png,
12_t1_revenue_matrix.png
"""
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from tm_common import (HOURS, OUTPUT_DIR, PERIODS, RANDOM_STATE, WEEKDAYS, load_orders,
                       weekly_cell_sums)
from eda_utils import (DPI, GRID, INK, INK_2, MUTED, SEQ_CMAP, SERIES, SURFACE,  # noqa: E402
                       fmt_brl, legend, new_figure, save, save_table, set_titles, style_axes)

N_GOLDEN_BOOT = 1000
TOP_SHARE = 0.25
GOLDEN_P = 0.9
CANDIDATE_P = 0.5
SEGMENT = "T1"


def top_quarter(revenue: np.ndarray, t1: np.ndarray) -> np.ndarray:
    """Boolean per T1 cell: revenue at or above the T1 top-quarter threshold."""
    r = revenue[t1]
    return r >= np.quantile(r, 1 - TOP_SHARE)


def blocks(cells: list[int]) -> str:
    """Group golden cells into contiguous hour blocks per weekday."""
    by_day: dict[int, list[int]] = {}
    for c in cells:
        by_day.setdefault(c // 24, []).append(c % 24)
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


def main() -> None:
    df = load_orders()
    weeks, orders, value, _ = weekly_cell_sums(df)
    n_weeks = len(weeks)
    seg = pd.read_csv(OUTPUT_DIR / "cell_clusters.csv")
    seg["cell"] = seg["weekday"] * 24 + seg["hour"]
    t1 = np.zeros(168, dtype=bool)
    t1[seg.loc[seg["segment"] == SEGMENT, "cell"].to_numpy()] = True
    t1_idx = np.flatnonzero(t1)

    tot_orders, tot_value = orders.sum(0), value.sum(0)
    table = pd.DataFrame({
        "cell": t1_idx, "weekday": [WEEKDAYS[c // 24] for c in t1_idx], "hour": t1_idx % 24,
        "orders_per_week": tot_orders[t1] / n_weeks,
        "mean_order_value": tot_value[t1] / tot_orders[t1],
        "revenue_per_week": tot_value[t1] / n_weeks,
    })

    # Week-block bootstrap: probability of being in the T1 top quarter by revenue
    rng = np.random.default_rng(RANDOM_STATE)
    hits = np.zeros(t1.sum())
    aov_boot = np.zeros((N_GOLDEN_BOOT, t1.sum()))
    for b in range(N_GOLDEN_BOOT):
        w = np.bincount(rng.integers(0, n_weeks, n_weeks), minlength=n_weeks)
        rev = w @ value / n_weeks
        hits += top_quarter(rev, t1)
        aov_boot[b] = (w @ value)[t1] / np.maximum((w @ orders)[t1], 1)
    table["p_top_quarter"] = hits / N_GOLDEN_BOOT
    table["aov_lo"], table["aov_hi"] = np.percentile(aov_boot, [2.5, 97.5], axis=0)
    table["status"] = np.select([table["p_top_quarter"] >= GOLDEN_P,
                                 table["p_top_quarter"] >= CANDIDATE_P],
                                ["golden", "candidate"], "other")

    # Split-half and period checks
    week_no = np.arange(n_weeks)
    odd, even = week_no % 2 == 1, week_no % 2 == 0
    sets = {}
    for name, mask in [("odd", odd), ("even", even)]:
        sets[name] = set(t1_idx[top_quarter(value[mask].sum(0), t1)])
    jaccard = len(sets["odd"] & sets["even"]) / len(sets["odd"] | sets["even"])
    week_start = pd.to_datetime(pd.Series(weeks))
    in_period = np.zeros(t1.sum(), dtype=int)
    for _, a, b_ in PERIODS:
        mask = ((week_start >= a) & (week_start < b_)).to_numpy()
        in_period += top_quarter(value[mask].sum(0), t1)
    table["periods_in_top_quarter"] = in_period
    table["odd_weeks_top"] = table["cell"].isin(sets["odd"])
    table["even_weeks_top"] = table["cell"].isin(sets["even"])
    table = table.sort_values("revenue_per_week", ascending=False).reset_index(drop=True)
    save_table(table, "golden_cells")

    golden = table[table["status"] == "golden"]
    rho_vol = table["revenue_per_week"].corr(table["orders_per_week"], method="spearman")
    rho_aov = table["revenue_per_week"].corr(table["mean_order_value"], method="spearman")
    summary = {
        "t1_cells": int(t1.sum()), "golden_cells": len(golden),
        "candidate_cells": int((table["status"] == "candidate").sum()),
        "golden_share_of_t1_revenue": golden["revenue_per_week"].sum() / table["revenue_per_week"].sum(),
        "golden_share_of_t1_cells": len(golden) / t1.sum(),
        "golden_orders_per_week_median": golden["orders_per_week"].median(),
        "other_orders_per_week_median": table.loc[table["status"] != "golden", "orders_per_week"].median(),
        "golden_aov_mean": golden["revenue_per_week"].sum() / golden["orders_per_week"].sum(),
        "other_aov_mean": table.loc[table["status"] != "golden", "revenue_per_week"].sum()
        / table.loc[table["status"] != "golden", "orders_per_week"].sum(),
        "rho_revenue_vs_volume": rho_vol, "rho_revenue_vs_aov": rho_aov,
        "split_half_jaccard": jaccard,
        "golden_in_all_4_periods": int((golden["periods_in_top_quarter"] == len(PERIODS)).sum()),
        "golden_blocks": blocks(golden["cell"].tolist()),
    }
    save_table(pd.DataFrame([summary]), "golden_summary")
    chart_quadrant(table, summary)
    chart_matrix(table, t1, summary)
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()})
    print(golden[["weekday", "hour", "orders_per_week", "mean_order_value", "revenue_per_week",
                  "p_top_quarter", "periods_in_top_quarter"]].round(2).to_string(index=False))


def chart_quadrant(table: pd.DataFrame, summary: dict) -> None:
    fig, ax = new_figure(1500, 820, left=0.08, right=0.97, top=0.79, bottom=0.1)
    style_axes(ax, "y")
    x_med, y_med = table["orders_per_week"].median(), table["mean_order_value"].median()
    ax.axvline(x_med, color=GRID, linewidth=1 * 72 / DPI)
    ax.axhline(y_med, color=GRID, linewidth=1 * 72 / DPI)
    xs = np.linspace(table["orders_per_week"].min() * 0.9, table["orders_per_week"].max() * 1.05, 100)
    y_top = table["aov_hi"].max() * 1.02
    curve_note = []
    for q, label in [(0.5, "T1 median"), (1 - TOP_SHARE, "top-quarter threshold")]:
        r = table["revenue_per_week"].quantile(q)
        ax.plot(xs, r / xs, color=MUTED, linewidth=1 * 72 / DPI, zorder=1)
        curve_note.append(f"{label} {fmt_brl(r)}/week")
    styles = {"other": (GRID, 6), "candidate": (SERIES[0], 7), "golden": (SERIES[1], 8)}
    for status in ["other", "candidate", "golden"]:
        d = table[table["status"] == status]
        color, size = styles[status]
        ax.errorbar(d["orders_per_week"], d["mean_order_value"],
                    yerr=[d["mean_order_value"] - d["aov_lo"], d["aov_hi"] - d["mean_order_value"]],
                    fmt="none", ecolor=color, elinewidth=0.6, alpha=0.5, zorder=2)
        ax.plot(d["orders_per_week"], d["mean_order_value"], "o", color=color,
                markersize=size * 72 / DPI + 2, markeredgecolor=SURFACE,
                markeredgewidth=1.5 * 72 / DPI, linestyle="none", zorder=3)
    # Golden slots sit in a tight cluster: stack their labels in a column to the right
    gold = table[table["status"] == "golden"].sort_values("mean_order_value", ascending=False)
    x_lab = xs[-1] * 1.04
    y_lo, y_hi = table["mean_order_value"].quantile(0.35), table["aov_hi"].max() * 0.93
    for i, (_, r) in enumerate(gold.iterrows()):
        y_lab = y_hi - i * (y_hi - y_lo) / max(len(gold) - 1, 1)
        ax.annotate(f"{r['weekday']} {int(r['hour']):02d}h  {fmt_brl(r['mean_order_value'])}",
                    (r["orders_per_week"], r["mean_order_value"]), xytext=(x_lab, y_lab),
                    fontsize=7.5, color=INK_2, va="center",
                    arrowprops={"arrowstyle": "-", "color": GRID, "linewidth": 0.6})
    ax.set_ylim(table["aov_lo"].min() * 0.95, y_top)
    ax.set_xlim(xs[0], xs[-1] * 1.22)
    ax.yaxis.set_major_formatter(lambda y, _: fmt_brl(y))
    ax.set_xlabel("Orders per week in the slot (volume)", labelpad=6)
    ax.set_ylabel("Mean order value (bar = 95% bootstrap)", labelpad=6)
    legend(fig, [f"Golden (P(top quarter) ≥ {GOLDEN_P:.0%})",
                 f"Candidate ({CANDIDATE_P:.0%}–{GOLDEN_P:.0%})", "Other T1 slot"],
           [SERIES[1], SERIES[0], GRID], y_px_from_top=122, left=0.08)
    set_titles(fig, "Price and volume of the T1 time slots",
               f"{summary['t1_cells']} weekday × hour slots in T1; curves = equal revenue per week "
               f"({', '.join(curve_note)}).\n"
               f"Revenue ranks follow volume (Spearman ρ {summary['rho_revenue_vs_volume']:+.2f}) "
               f"far more than order value (ρ {summary['rho_revenue_vs_aov']:+.2f}); "
               f"order value bars overlap across slots, so no slot is reliably pricier")
    save(fig, "11_t1_price_volume")


def chart_matrix(table: pd.DataFrame, t1: np.ndarray, summary: dict) -> None:
    rev = np.full(168, np.nan)
    rev[table["cell"].to_numpy()] = table["revenue_per_week"].to_numpy()
    grid = rev.reshape(7, 24)
    fig, ax = new_figure(1800, 640, left=0.05, right=0.97, top=0.66, bottom=0.12)
    im = ax.imshow(np.ma.masked_invalid(grid), cmap=SEQ_CMAP, aspect="auto",
                   interpolation="nearest")
    ax.set_facecolor(GRID)
    status = dict(zip(table["cell"], table["status"]))
    for c in range(168):
        r_, h = divmod(c, 24)
        if not t1[c]:
            ax.text(h, r_, "–", ha="center", va="center", fontsize=7, color=MUTED)
            continue
        v = rev[c]
        rgba = im.cmap(im.norm(v))
        lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
        ax.text(h, r_, f"{v / 1000:.1f}K", ha="center", va="center", fontsize=6.8,
                color="white" if lum < 0.5 else INK)
        if status[c] in ("golden", "candidate"):
            ax.add_patch(Rectangle((h - 0.46, r_ - 0.44), 0.92, 0.88, fill=False,
                                   edgecolor=SERIES[1] if status[c] == "golden" else SERIES[0],
                                   linewidth=(2.2 if status[c] == "golden" else 1.2) * 72 / DPI * 2,
                                   zorder=4))
    ax.set_xticks(range(24), [f"{h:02d}" for h in HOURS])
    ax.set_yticks(range(7), WEEKDAYS)
    ax.xaxis.tick_top()
    ax.tick_params(length=0, labelsize=8)
    for side in ax.spines.values():
        side.set_visible(False)
    legend(fig, ["Golden slot (outline)", "Candidate slot (outline)", "Not in T1"],
           [SERIES[1], SERIES[0], GRID], y_px_from_top=122, left=0.05)
    fig.text(0.05, 0.06, f"Golden blocks: {summary['golden_blocks']}", fontsize=8, color=INK_2,
             wrap=True)
    set_titles(fig, "Golden time slots: payment value per week in each T1 slot",
               f"R$ per week (K = thousand). {summary['golden_cells']} golden slots "
               f"({summary['golden_share_of_t1_cells']:.0%} of T1 slots) take "
               f"{summary['golden_share_of_t1_revenue']:.0%} of T1 revenue; odd vs even weeks "
               f"top-quarter overlap (Jaccard) {summary['split_half_jaccard']:.2f}; "
               f"{summary['golden_in_all_4_periods']} golden slots are top-quarter in all "
               f"{len(PERIODS)} periods", left=0.05)
    save(fig, "12_t1_revenue_matrix")


if __name__ == "__main__":
    main()
