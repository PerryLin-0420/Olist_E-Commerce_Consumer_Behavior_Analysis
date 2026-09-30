"""Step 07: compare where active and one-time customers are.

Location = state of the customer's latest order (customer_features.csv).
Tiers come from step 04.

- Share of each tier per state and region, and the active rate
  (active / all customers) per state with Wilson 95% intervals
- Chi-square tests of state x tier and region x tier with Cramér's V, plus
  the correlation of the two tiers' state shares

Outputs: outputs/activity_geography_state.csv, activity_geography_region.csv,
activity_geography_summary.csv; charts/activity_geography_map.png,
activity_rate_by_state.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from rf_common import FEATURE_DIR, OUTPUT_DIR
from eda_geo import REGIONS, STATE_TO_REGION, draw_state_map, load_state_rings  # noqa: E402
from eda_utils import (DPI, GRID, INK_2, MUTED, ORDINAL_BLUE, SERIES, SURFACE,  # noqa: E402
                       fmt_pct, new_figure, save, save_table, set_titles, style_axes)

SHARE_BINS = [0, 0.5, 1, 3, 10, float("inf")]
SHARE_LABELS = ["< 0.5%", "0.5–1%", "1–3%", "3–10%", "≥ 10%"]


def wilson(k: np.ndarray, n: np.ndarray, z: float = 1.96) -> tuple[np.ndarray, np.ndarray]:
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def chart_map(state: pd.DataFrame, region: pd.DataFrame, summary: dict) -> None:
    rings = load_state_rings()
    fig = plt.figure(figsize=(1700 / DPI, 860 / DPI), dpi=DPI)
    panels = [("active", "Active customers"), ("one_time", "One-time customers")]
    for i, (tier, title) in enumerate(panels):
        rect = [0.0 + 0.5 * i, 0.03, 0.5, 0.78]
        share = state.set_index("state")[f"{tier}_share"] * 100
        classes = pd.cut(share, SHARE_BINS, labels=False, right=False).to_dict()
        ax = fig.add_axes(rect)
        draw_state_map(ax, classes, ORDINAL_BLUE, SHARE_LABELS, "Share of the tier",
                       {r: fmt_pct(v * 100) for r, v in
                        region.set_index("region")[f"{tier}_share"].items()},
                       rings=rings, show_legend=i == 0)
        fig.text(rect[0] + 0.02, rect[1] + rect[3] + 0.005,
                 f"{title}  (n={int(state[tier].sum()):,})", fontsize=10, fontweight="semibold",
                 color=INK_2)
    set_titles(fig, "Where active and one-time customers are",
               f"Share of each tier per state, same color scale. Correlation of state shares "
               f"{summary['share_correlation']:.4f}. State x tier: chi-square p = "
               f"{summary['chi2_p']:.3f}, Cramér's V = {summary['cramers_v']:.3f}; region x tier: "
               f"p = {summary['region_chi2_p']:.2g}, V = {summary['region_cramers_v']:.3f}",
               left=0.02)
    save(fig, "activity_geography_map")


def chart_rate(state: pd.DataFrame, summary: dict) -> None:
    d = state.sort_values("active_rate", ascending=False).reset_index(drop=True)
    n = len(d)
    height = 150 + 26 * n + 75
    fig, ax = new_figure(1400, height, left=0.2, right=0.72, top=1 - 150 / height,
                         bottom=75 / height)
    style_axes(ax, "x")
    overall = summary["overall_active_rate"] * 100
    ax.axvline(overall, color=MUTED, linewidth=1 * 72 / DPI, zorder=1)
    ax.text(overall, -0.9, f"all customers {overall:.2f}%", ha="center", va="bottom",
            fontsize=8, color=MUTED)
    for i, row in d.iterrows():
        ax.plot([row["rate_lo"] * 100, row["rate_hi"] * 100], [i, i], color=GRID,
                linewidth=4 * 72 / DPI, solid_capstyle="round", zorder=2)
        outside = row["rate_lo"] * 100 > overall or row["rate_hi"] * 100 < overall
        # Solid dot when the interval excludes the overall rate, faded otherwise
        ax.plot(row["active_rate"] * 100, i, "o", color=SERIES[0],
                markersize=8 * 72 / DPI + 2, markeredgecolor=SURFACE,
                markeredgewidth=2 * 72 / DPI, zorder=3, alpha=1 if outside else 0.45)
    ax.set_yticks(range(n), [f"{s} ({r})" for s, r in zip(d["state"], d["region"])])
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylim(n - 0.5, -1.2)
    ax.set_xlim(0, max(8, (d["rate_hi"] * 100).max() * 1.05))
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    ax.set_xlabel("Active rate (share of customers with purchases on ≥ 2 dates)", labelpad=6)
    # Side table: customers, active, rate
    for i, row in d.iterrows():
        y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
        fig.text(0.97, y, f"{int(row['customers']):,} customers   {int(row['active']):,} active"
                 f"   {row['active_rate']:.2%} [{row['rate_lo']:.1%}–{row['rate_hi']:.1%}]",
                 ha="right", va="center", fontsize=8, color=INK_2)
    differs = d.loc[(d["rate_lo"] * 100 > overall) | (d["rate_hi"] * 100 < overall), "state"]
    set_titles(fig, "Active rate by state",
               "Dot = active rate, bar = Wilson 95% interval, line = all customers. "
               f"States whose interval excludes the overall rate: "
               f"{', '.join(differs) if len(differs) else 'none'} (solid dots);\n"
               f"with {n} states tested at 95%, about {0.05 * n:.1f} would fall outside by "
               "chance alone", left=0.02)
    save(fig, "activity_rate_by_state")


def main() -> None:
    loc = pd.read_csv(FEATURE_DIR / "customer_features.csv")[["customer_unique_id",
                                                              "customer_state"]]
    tiers = pd.read_csv(OUTPUT_DIR / "customer_activity.csv")[["customer_unique_id", "tier"]]
    d = loc.merge(tiers, on="customer_unique_id")

    ct = pd.crosstab(d["customer_state"], d["tier"]).reindex(
        index=list(STATE_TO_REGION), fill_value=0)
    chi2, p, dof, _ = chi2_contingency(ct[ct.sum(axis=1) > 0].values)
    state = pd.DataFrame({"state": ct.index, "region": ct.index.map(STATE_TO_REGION),
                          "active": ct["active"].values, "one_time": ct["one_time"].values})
    state["customers"] = state["active"] + state["one_time"]
    for t in ["active", "one_time"]:
        state[f"{t}_share"] = state[t] / state[t].sum()
    state["active_rate"] = state["active"] / state["customers"]
    state["rate_lo"], state["rate_hi"] = wilson(state["active"].to_numpy(),
                                                state["customers"].to_numpy())
    save_table(state.sort_values("customers", ascending=False), "activity_geography_state")

    region = state.groupby("region")[["active", "one_time", "customers"]].sum() \
        .reindex(list(REGIONS)).reset_index()
    for t in ["active", "one_time"]:
        region[f"{t}_share"] = region[t] / region[t].sum()
    region["active_rate"] = region["active"] / region["customers"]
    region["rate_lo"], region["rate_hi"] = wilson(region["active"].to_numpy(),
                                                  region["customers"].to_numpy())
    save_table(region, "activity_geography_region")

    r_chi2, r_p, r_dof, _ = chi2_contingency(region[["active", "one_time"]].values)
    summary = {"customers": len(d), "chi2": chi2, "dof": dof, "chi2_p": p,
               "region_chi2": r_chi2, "region_dof": r_dof, "region_chi2_p": r_p,
               "region_cramers_v": np.sqrt(r_chi2 / len(d)),
               "cramers_v": np.sqrt(chi2 / len(d)),
               "share_correlation": state["active_share"].corr(state["one_time_share"]),
               "overall_active_rate": state["active"].sum() / state["customers"].sum(),
               "max_share_gap_pp": (state["active_share"] - state["one_time_share"]).abs().max()
               * 100}
    save_table(pd.DataFrame([summary]), "activity_geography_summary")
    chart_map(state, region, summary)
    chart_rate(state, summary)
    print({k: round(v, 4) if isinstance(v, float) else v for k, v in summary.items()})
    print(region.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
