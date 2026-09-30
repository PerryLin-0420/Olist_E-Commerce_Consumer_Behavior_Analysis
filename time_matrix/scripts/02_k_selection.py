"""Step 02: choose k for the time segments from silhouette and stability.

Starting from START_K and stepping k down (and up to the end of K_RANGE for
context), every k is scored on a week-block bootstrap:
1. Resample the weeks with replacement (a whole week is one block, so the
   weekday x hour structure inside a week is kept) and rebuild the 168 cell
   features from the resampled weeks.
2. Refit KMeans on the resample and record
   - silhouette: how well separated the segments are
   - ARI vs the full-data segments: how stable the segments are when the data
     changes (1 = same partition, 0 = no better than chance)
3. Balance = geometric mean of silhouette and ARI; it is high only when the
   segments are both separated and stable.

Curves show the bootstrap mean (dots), a smoothing spline through the means
and the 2.5-97.5 percentile band. Best k = the k with the highest mean
balance. k values whose balance band overlaps the best k's band are reported
as the plateau.

Outputs: outputs/k_selection.csv, k_choice.csv; charts/04_k_selection_curves.png
"""
import numpy as np
import pandas as pd
from scipy.interpolate import make_smoothing_spline
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from tm_common import (K_CHOICE_FILE, K_RANGE, N_BOOT, RANDOM_STATE, START_K, cell_features,
                       load_orders, standardize, weekly_cell_sums)
from eda_utils import (DPI, INK, INK_2, MUTED, SERIES, SURFACE, legend,  # noqa: E402
                       new_figure, save, save_table, set_titles, style_axes)

N_INIT = 10
METRICS = [("silhouette", "Silhouette (separation)", SERIES[0]),
           ("ari", "Bootstrap ARI vs full data (stability)", SERIES[1]),
           ("balance", "Balance = √(silhouette × ARI)", INK)]


def bootstrap_scores(orders, value, inst, n_weeks: int) -> pd.DataFrame:
    Z_full = standardize(cell_features(orders.sum(0), value.sum(0), inst.sum(0), n_weeks))
    full = {k: KMeans(k, n_init=50, random_state=RANDOM_STATE).fit(Z_full).labels_
            for k in K_RANGE}
    rng = np.random.default_rng(RANDOM_STATE)
    rows = []
    for b in range(N_BOOT):
        w = np.bincount(rng.integers(0, n_weeks, n_weeks), minlength=n_weeks)
        Z = standardize(cell_features(w @ orders, w @ value, w @ inst, n_weeks))
        for k in K_RANGE:
            labels = KMeans(k, n_init=N_INIT, random_state=RANDOM_STATE + b).fit(Z).labels_
            sil = silhouette_score(Z, labels)
            ari = adjusted_rand_score(full[k], labels)
            rows.append({"boot": b, "k": k, "silhouette": sil, "ari": ari,
                         "balance": float(np.sqrt(max(sil, 0) * max(ari, 0)))})
    return pd.DataFrame(rows)


def summarize(scores: pd.DataFrame) -> pd.DataFrame:
    g = scores.groupby("k")
    out = pd.DataFrame(index=list(K_RANGE))
    for m, *_ in METRICS:
        out[f"{m}_mean"] = g[m].mean()
        out[f"{m}_lo"] = g[m].quantile(0.025)
        out[f"{m}_hi"] = g[m].quantile(0.975)
    return out.rename_axis("k").reset_index()


def chart(summary: pd.DataFrame, best: int, plateau: list[int]) -> None:
    fig, ax = new_figure(1600, 780, left=0.07, right=0.63, top=0.76, bottom=0.11)
    style_axes(ax, "y")
    ks = summary["k"].to_numpy(dtype=float)
    fine = np.linspace(ks.min(), ks.max(), 200)
    ax.axvspan(min(plateau) - 0.4, max(plateau) + 0.4, color="#eef2f7", zorder=0)
    ax.text(min(plateau) - 0.35, 0.015, "plateau", fontsize=8, color=MUTED, va="bottom")
    for m, label, color in METRICS:
        mean = summary[f"{m}_mean"].to_numpy()
        ax.fill_between(ks, summary[f"{m}_lo"], summary[f"{m}_hi"], color=color, alpha=0.1,
                        linewidth=0, zorder=1)
        spline = make_smoothing_spline(ks, mean)
        ax.plot(fine, np.clip(spline(fine), 0, 1), color=color,
                linewidth=(2.6 if m == "balance" else 2) * 72 / DPI, zorder=3)
        ax.plot(ks, mean, "o", color=color, markersize=6 * 72 / DPI + 2, markeredgecolor=SURFACE,
                markeredgewidth=1.5 * 72 / DPI, zorder=4)
    ax.axvline(START_K, color=MUTED, linewidth=1 * 72 / DPI, zorder=2)
    ax.axvline(best, color=INK, linewidth=1.2 * 72 / DPI, zorder=2)
    ax.annotate("", xy=(best + 0.3, 0.06), xytext=(START_K - 0.2, 0.06),
                arrowprops={"arrowstyle": "->", "color": MUTED, "linewidth": 1})
    ax.text((best + START_K) / 2, 0.08, "stepping k down from the start", ha="center",
            fontsize=8, color=MUTED)
    ax.text(START_K + 0.1, 1.01, f"start k = {START_K}", fontsize=8, color=MUTED, va="bottom")
    ax.text(best + 0.1, 1.01, f"best k = {best}", fontsize=8, color=INK, va="bottom")
    ax.set_xticks(list(K_RANGE))
    ax.set_ylim(0, 1.06)
    ax.set_xlim(ks.min() - 0.5, ks.max() + 0.5)
    ax.set_xlabel("k (number of time segments)", labelpad=6)
    ax.set_ylabel("Score (0 to 1)", labelpad=6)
    legend(fig, [label for _, label, _ in METRICS], [c for *_, c in METRICS],
           y_px_from_top=125, left=0.07)

    # Side table
    t = summary.set_index("k")
    fig.text(0.66, 0.76, "Bootstrap mean [95% band]", fontsize=9, fontweight="semibold",
             color=INK_2, va="top")
    fig.text(0.66, 0.725, "k    silhouette   ARI                balance", fontsize=8, color=MUTED,
             va="top", family="monospace")
    for i, k in enumerate(K_RANGE):
        r = t.loc[k]
        mark = " ◀ best" if k == best else (" · plateau" if k in plateau else "")
        fig.text(0.66, 0.69 - i * 0.04,
                 f"{k:<4} {r['silhouette_mean']:.2f}         {r['ari_mean']:.2f} "
                 f"[{r['ari_lo']:.2f}–{r['ari_hi']:.2f}]   {r['balance_mean']:.2f}{mark}",
                 fontsize=8, color=INK if k == best else INK_2, va="top", family="monospace",
                 fontweight="semibold" if k == best else "normal")
    b = t.loc[best]
    s = t.loc[START_K]
    set_titles(fig, "How many time segments? Silhouette and stability vs k",
               f"{N_BOOT} week-block bootstrap samples; dots = mean, line = smoothing spline, band "
               f"= 95%. From k = {START_K} (silhouette {s['silhouette_mean']:.2f}, ARI "
               f"{s['ari_mean']:.2f}) both rise as k falls;\nthe balance peaks at k = {best} "
               f"(silhouette {b['silhouette_mean']:.2f}, ARI {b['ari_mean']:.2f}, balance "
               f"{b['balance_mean']:.2f}). Plateau (bands overlap the best): k = "
               f"{', '.join(map(str, plateau))}")
    save(fig, "04_k_selection_curves")


def main() -> None:
    df = load_orders()
    weeks, orders, value, inst = weekly_cell_sums(df)
    n_weeks = len(weeks)
    scores = bootstrap_scores(orders, value, inst, n_weeks)
    summary = summarize(scores)
    save_table(summary, "k_selection")
    save_table(scores, "k_selection_bootstrap")

    t = summary.set_index("k")
    best = int(t["balance_mean"].idxmax())
    plateau = [int(k) for k in t.index if t.loc[k, "balance_hi"] >= t.loc[best, "balance_lo"]]
    save_table(pd.DataFrame([{"k": best, "start_k": START_K, "plateau": " ".join(map(str, plateau)),
                              **t.loc[best].to_dict()}]), K_CHOICE_FILE.removesuffix(".csv"))
    chart(summary, best, plateau)
    print(summary.round(3).to_string(index=False))
    print(f"best k = {best}; plateau = {plateau}")


if __name__ == "__main__":
    main()
