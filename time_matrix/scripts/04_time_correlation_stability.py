"""Step 04: does purchase time go with other behaviour, and is the pattern stable over time?

Association
- Cell level: Spearman correlations between the behaviour metrics of the
  weekday x hour cells that hold >= MIN_CELL_ORDERS orders (sparse night cells
  are noise-dominated).
- Order level: how much of each behaviour the time slot explains:
  epsilon-squared of a Kruskal-Wallis test for numeric metrics and Cramér's V
  for categorical ones, by weekday, by hour and by weekday x hour.

Stability (is the pattern spread over the timeline, not one event?)
- Weekly fingerprint: every week's order distribution over the 168 cells,
  correlated with the pooled distribution of all other weeks (leave-one-out).
- Periods: the three step-01 matrices rebuilt per period (tm_common.PERIODS)
  and correlated between periods; also with vs without the spike weeks.
- Split-half: odd vs even weeks.
- Segments: KMeans refit per period, ARI vs the full-data segments, for the
  k chosen in step 02 and for START_K.

Outputs: outputs/cell_correlations.csv, time_effect_sizes.csv, weekly_fingerprint.csv,
period_stability.csv, segment_stability.csv; charts/07_cell_correlations.png,
08_time_effect_sizes.png, 09_weekly_fingerprint.png, 10_period_matrices.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, kruskal
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score

from tm_common import (PERIODS, RANDOM_STATE, SPIKE_WEEKS, START_K, WEEKDAYS, cell_table,
                       chosen_k, load_orders, matrix)
from eda_utils import (DIV_CMAP, DPI, GRID, INK, INK_2, MUTED, SEQ_CMAP, SERIES,  # noqa: E402
                       SURFACE, heatmap, legend, new_figure, save, save_table, set_titles,
                       style_axes)

MIN_CELL_ORDERS = 300
METRICS = {"orders_per_week": "Orders per week", "mean_order_value": "Mean order value",
           "median_order_value": "Median order value", "mean_installments": "Mean installments",
           "installment_share": "Installment share", "boleto_share": "Boleto share",
           "voucher_share": "Voucher share", "items_per_order": "Items per order",
           "median_freight_ratio": "Median freight ratio", "mean_review_score": "Mean review score"}
NUMERIC = {"order_value": "Order value", "installments": "Installments",
           "items": "Items per order", "freight_ratio": "Freight ratio",
           "review_score": "Review score"}
CATEGORICAL = {"main_payment_type": "Payment type", "in_installments": "Pays in installments",
               "category": "Category (top 20 + other)", "customer_state": "Customer state"}


def epsilon_squared(values: pd.Series, groups: pd.Series) -> float:
    d = pd.DataFrame({"v": values, "g": groups}).dropna()
    samples = [g["v"].to_numpy() for _, g in d.groupby("g") if len(g) > 1]
    h = kruskal(*samples).statistic
    return h / (len(d) - 1)


def cramers_v(a: pd.Series, b: pd.Series) -> float:
    ct = pd.crosstab(a, b)
    chi2 = chi2_contingency(ct.values)[0]
    return float(np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1))))


def cell_correlations(cells: pd.DataFrame, n_weeks: int) -> pd.DataFrame:
    c = cells[cells["orders"] >= MIN_CELL_ORDERS].copy()
    c["orders_per_week"] = c["orders"] / n_weeks
    corr = c[list(METRICS)].astype(float).corr(method="spearman")
    save_table(corr.reset_index(names="metric"), "cell_correlations")
    labels = list(METRICS.values())
    cells_txt = {(r, k): f"{corr.iat[r, k]:+.2f}" for r in range(len(labels))
                 for k in range(len(labels))}
    height = 190 + 44 * len(labels)
    fig, ax = new_figure(1500, height, left=0.19, right=0.98, top=1 - 190 / height,
                         bottom=10 / height)
    heatmap(ax, corr.values, labels, [l.replace(" ", "\n", 1) for l in labels], cells_txt,
            vmin=-1, vmax=1, cmap=DIV_CMAP)
    ax.tick_params(axis="x", labelsize=8)
    r = corr.loc["orders_per_week"]
    set_titles(fig, "Behaviour of busy vs quiet time slots",
               f"Spearman correlation across the {len(c)} weekday × hour cells with ≥ "
               f"{MIN_CELL_ORDERS} orders. Orders per week vs boleto share {r['boleto_share']:+.2f}, "
               f"vs installments {r['mean_installments']:+.2f}, vs mean order value "
               f"{r['mean_order_value']:+.2f}", left=0.02)
    save(fig, "07_cell_correlations")
    return corr


def effect_sizes(df: pd.DataFrame) -> pd.DataFrame:
    top = df["category"].value_counts().head(20).index
    d = df.assign(cell=df["weekday"] * 24 + df["hour"],
                  category=df["category"].where(df["category"].isin(top), "other"))
    rows = []
    for col, name in NUMERIC.items():
        for key, label in [("weekday", "Weekday"), ("hour", "Hour"), ("cell", "Weekday × hour")]:
            rows.append({"metric": name, "grouping": label, "measure": "epsilon²",
                         "value": epsilon_squared(d[col], d[key])})
    for col, name in CATEGORICAL.items():
        for key, label in [("weekday", "Weekday"), ("hour", "Hour"), ("cell", "Weekday × hour")]:
            sub = d.dropna(subset=[col])
            rows.append({"metric": name, "grouping": label, "measure": "Cramér's V",
                         "value": cramers_v(sub[col], sub[key])})
    table = pd.DataFrame(rows)
    save_table(table, "time_effect_sizes")

    metrics = list(NUMERIC.values()) + list(CATEGORICAL.values())
    groupings = ["Weekday", "Hour", "Weekday × hour"]
    height = 150 + 44 * len(metrics) + 60
    fig, ax = new_figure(1400, height, left=0.24, right=0.78, top=1 - 170 / height,
                         bottom=60 / height)
    style_axes(ax, "x")
    bar_h = 0.26
    for j, (grp, color) in enumerate(zip(groupings, SERIES)):
        vals = [table[(table["metric"] == m) & (table["grouping"] == grp)]["value"].iat[0]
                for m in metrics]
        ax.barh(np.arange(len(metrics)) + (j - 1) * (bar_h + 0.02), vals, height=bar_h,
                color=color, zorder=2)
    ax.set_yticks(range(len(metrics)), [f"{m} ({'ε²' if m in NUMERIC.values() else 'V'})"
                                        for m in metrics])
    ax.set_ylim(len(metrics) - 0.5, -0.5)
    ax.axvline(0.01, color=MUTED, linewidth=1 * 72 / DPI)
    ax.text(0.01, -0.45, " 0.01", fontsize=7.5, color=MUTED, va="bottom")
    for i, m in enumerate(metrics):
        v = table[(table["metric"] == m) & (table["grouping"] == "Weekday × hour")]["value"].iat[0]
        y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
        fig.text(0.98, y, f"weekday × hour {v:.4f}", ha="right", va="center", fontsize=8,
                 color=INK_2)
    legend(fig, groupings, SERIES[:3], y_px_from_top=122, left=0.24)
    top_row = table[table["grouping"] == "Weekday × hour"].sort_values("value").iloc[-1]
    set_titles(fig, "How much does the purchase time explain?",
               "epsilon² (numbers) = share of rank variance tied to the time slot, so < 0.01 is "
               "< 1%; Cramér's V (categories) = association strength, < 0.1 is very weak.\n"
               f"Largest: {top_row['metric']} by weekday × hour (V = {top_row['value']:.3f})",
               left=0.02)
    save(fig, "08_time_effect_sizes")
    return table


def weekly_fingerprint(df: pd.DataFrame) -> pd.DataFrame:
    weeks = df.groupby("week").size()
    weeks = weeks[weeks >= 200].index  # skip the sparse first and truncated last weeks
    d = df[df["week"].isin(weeks)]
    counts = d.groupby(["week", "weekday", "hour"]).size().unstack(["weekday", "hour"], fill_value=0)
    shares = counts.div(counts.sum(axis=1), axis=0)
    total = counts.sum()
    rows = []
    for wk in shares.index:
        others = (total - counts.loc[wk])
        rows.append({"week": wk, "orders": int(counts.loc[wk].sum()),
                     "corr_with_other_weeks": np.corrcoef(shares.loc[wk], others / others.sum())[0, 1],
                     "spike_week": wk in SPIKE_WEEKS})
    fp = pd.DataFrame(rows)
    save_table(fp, "weekly_fingerprint")

    fig, ax = new_figure(1600, 580, left=0.07, right=0.97, top=0.72, bottom=0.12)
    style_axes(ax, "y")
    x = np.arange(len(fp))
    ax.plot(x, fp["corr_with_other_weeks"], color=SERIES[0], linewidth=2 * 72 / DPI, zorder=2)
    spikes = fp[fp["spike_week"]]
    ax.plot(spikes.index, spikes["corr_with_other_weeks"], "o", color=SERIES[1],
            markersize=8 * 72 / DPI + 2, markeredgecolor=SURFACE, markeredgewidth=2 * 72 / DPI,
            zorder=3)
    med = fp["corr_with_other_weeks"].median()
    ax.axhline(med, color=MUTED, linewidth=1 * 72 / DPI)
    ticks = [i for i, w in enumerate(fp["week"]) if w.day <= 7 and w.month % 3 == 1]
    ax.set_xticks(ticks, [f"{fp['week'].iat[i]:%Y-%m}" for i in ticks])
    ax.set_ylim(0, 1)
    ax.set_xlim(-0.8, len(x) - 0.2)
    ax.set_ylabel("Correlation with all other weeks", labelpad=6)
    legend(fig, ["Week", "Spike week", f"Median {med:.2f}"], [SERIES[0], SERIES[1], MUTED],
           y_px_from_top=122, left=0.07)
    low = fp.nsmallest(3, "corr_with_other_weeks")
    set_titles(fig, "Is the weekday × hour pattern the same every week?",
               f"Each week's order distribution over the 168 cells vs the pooled distribution "
               f"of every other week ({len(fp)} weeks with ≥ 200 orders).\nSpike weeks: "
               + ", ".join(f"{r.week:%Y-%m-%d} {r.corr_with_other_weeks:.2f}"
                           for r in spikes.itertuples())
               + "; lowest: " + ", ".join(f"{r.week:%Y-%m-%d} {r.corr_with_other_weeks:.2f}"
                                          for r in low.itertuples()))
    save(fig, "09_weekly_fingerprint")
    return fp


def period_stability(df: pd.DataFrame) -> pd.DataFrame:
    def flat(sub, value):
        m = matrix(sub) if value is None else matrix(sub, value)
        return (m / m.values.sum()).values.ravel() if value is None else m.values.ravel()

    subsets = {name: df[(df["purchased_at"] >= a) & (df["purchased_at"] < b)]
               for name, a, b in PERIODS}
    subsets["all weeks"] = df
    subsets["without spike weeks"] = df[~df["spike_week"]]
    odd = df["week"].rank(method="dense").astype(int) % 2 == 1
    subsets["odd weeks"], subsets["even weeks"] = df[odd], df[~odd]
    pairs = [(a[0], b[0]) for i, a in enumerate(PERIODS) for b in PERIODS[i + 1:]]
    pairs += [("all weeks", "without spike weeks"), ("odd weeks", "even weeks")]
    rows = []
    for metric, value in [("order share", None), ("mean order value", "order_value"),
                          ("mean installments", "installments")]:
        vec = {k: flat(v, value) for k, v in subsets.items()}
        for a, b in pairs:
            ok = ~(np.isnan(vec[a]) | np.isnan(vec[b]))
            rows.append({"metric": metric, "a": a, "b": b,
                         "pearson": np.corrcoef(vec[a][ok], vec[b][ok])[0, 1],
                         "spearman": pd.Series(vec[a][ok]).corr(pd.Series(vec[b][ok]),
                                                                method="spearman")})
    table = pd.DataFrame(rows)
    save_table(table, "period_stability")
    return table


def segment_stability(df: pd.DataFrame) -> pd.DataFrame:
    def labels_for(sub, k):
        cells = cell_table(sub)
        n_weeks = sub["week"].nunique()
        X = pd.DataFrame({"o": np.log(cells["orders"].clip(lower=1) / n_weeks),
                          "v": cells["mean_order_value"], "i": cells["mean_installments"]})
        X = X.fillna(X.mean())
        Z = ((X - X.mean()) / X.std(ddof=0)).to_numpy()
        return KMeans(k, n_init=50, random_state=RANDOM_STATE).fit(Z).labels_

    rows = []
    for k in [chosen_k(), START_K]:
        full = labels_for(df, k)
        for name, a, b in PERIODS:
            sub = df[(df["purchased_at"] >= a) & (df["purchased_at"] < b)]
            rows.append({"k": k, "period": name, "orders": len(sub),
                         "ari_vs_full": adjusted_rand_score(full, labels_for(sub, k))})
        odd = df["week"].rank(method="dense").astype(int) % 2 == 1
        rows.append({"k": k, "period": "odd vs even weeks", "orders": len(df),
                     "ari_vs_full": adjusted_rand_score(labels_for(df[odd], k),
                                                        labels_for(df[~odd], k))})
    table = pd.DataFrame(rows)
    save_table(table, "segment_stability")
    return table


def chart_periods(df: pd.DataFrame, stab: pd.DataFrame, seg: pd.DataFrame) -> None:
    fig = plt.figure(figsize=(1800 / DPI, 820 / DPI), dpi=DPI)
    mats = []
    for name, a, b in PERIODS:
        sub = df[(df["purchased_at"] >= a) & (df["purchased_at"] < b)]
        m = matrix(sub)
        mats.append((name, len(sub), m / m.values.sum() * 100))
    vmax = max(m.values.max() for *_, m in mats)
    for i, (name, n, m) in enumerate(mats):
        ax = fig.add_axes([0.04 + i * 0.24, 0.42, 0.21, 0.3])
        ax.imshow(m.values, cmap=SEQ_CMAP, vmin=0, vmax=vmax, aspect="auto",
                  interpolation="nearest")
        ax.set_xticks([0, 6, 12, 18, 23], ["00", "06", "12", "18", "23"])
        ax.set_yticks(range(7), [d[0] for d in WEEKDAYS] if i == 0 else [""] * 7)
        ax.tick_params(length=0, labelsize=7)
        for side in ax.spines.values():
            side.set_visible(False)
        ax.set_title(f"{name}  ({n:,} orders)", fontsize=8.5, color=INK_2, loc="left")
    # Stability table under the maps
    share = stab[stab["metric"] == "order share"]
    lines = ["Order-share pattern, Pearson r between periods: "
             + "; ".join(f"{r.a} vs {r.b} {r.pearson:.2f}" for r in share.itertuples()
                         if r.a in [p[0] for p in PERIODS])]
    for metric in ["order share", "mean order value", "mean installments"]:
        s = stab[stab["metric"] == metric].set_index(["a", "b"])["pearson"]
        per = s[[(a[0], b[0]) for i, a in enumerate(PERIODS) for b in PERIODS[i + 1:]]]
        lines.append(f"{metric}: between periods r {per.min():.2f}–{per.max():.2f}; odd vs even weeks "
                     f"{s[('odd weeks', 'even weeks')]:.2f}; with vs without spike weeks "
                     f"{s[('all weeks', 'without spike weeks')]:.2f}")
    for k in [chosen_k(), START_K]:
        s = seg[seg["k"] == k]
        per = s[s["period"] != "odd vs even weeks"]["ari_vs_full"]
        oe = s[s["period"] == "odd vs even weeks"]["ari_vs_full"].iat[0]
        lines.append(f"Segments k = {k}: refit per period, ARI vs full data {per.min():.2f}–"
                     f"{per.max():.2f}; odd vs even weeks {oe:.2f}")
    for j, line in enumerate(lines[1:]):
        fig.text(0.04, 0.3 - j * 0.055, line, fontsize=9, color=INK_2)
    set_titles(fig, "The weekday × hour pattern across periods",
               "Share of each period's orders per cell, same color scale; the numbers below "
               "compare the three matrices and the segments between periods", left=0.04)
    save(fig, "10_period_matrices")


def main() -> None:
    df = load_orders()
    n_weeks = df["week"].nunique()
    cells = cell_table(df)
    corr = cell_correlations(cells, n_weeks)
    eff = effect_sizes(df)
    fp = weekly_fingerprint(df)
    stab = period_stability(df)
    seg = segment_stability(df)
    chart_periods(df, stab, seg)
    print(corr.loc["orders_per_week"].round(2).to_string())
    print(eff.pivot(index="metric", columns="grouping", values="value").round(4).to_string())
    print(fp["corr_with_other_weeks"].describe().round(3).to_string())
    print(fp[fp.spike_week].to_string(index=False))
    print(stab.round(3).to_string(index=False))
    print(seg.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
