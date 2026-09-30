"""Unsupervised random forest segmentation, shared by the segmentation steps.

Method (Breiman's unsupervised random forest)
1. Synthetic data: every feature column is resampled independently from its
   own marginal distribution, which keeps each feature's distribution but
   destroys the joint structure.
2. A random forest (N_TREES trees) learns to tell real rows from synthetic
   ones. It can only do so by using the joint structure of the real data.
3. Proximity(a, b) = share of trees where a and b land in the same leaf.
   sqrt(1 - proximity) is a Euclidean distance in leaf one-hot space, so Ward
   linkage is valid on it.
4. k is chosen by silhouette over K_RANGE, keeping every cluster >= a minimum share.

Up to CUSTOMER_SAMPLE rows are clustered on the full proximity matrix. Larger
sets are clustered on a random sample, and every row is then assigned to the
nearest cluster centroid in leaf one-hot space (the space Ward works in),
computed exactly per tree from leaf x cluster counts.

A supervised random forest (N_TREES trees) is then trained to predict the
segment labels; its feature importances show what separates the segments.
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import adjusted_rand_score, silhouette_score

from rf_common import (CUSTOMER_SAMPLE, K_RANGE, MIN_CLUSTER_SHARE, N_TREES, RANDOM_STATE,
                       STABILITY_SEED)
from eda_utils import (DIV_CMAP, barh, fmt_pct, heatmap, new_figure,  # noqa: E402
                       save, save_table, set_titles, style_axes)

PROFILE_TOP_FEATURES = 15


def unsupervised_forest(X: pd.DataFrame, min_leaf: int, rng,
                        seed: int) -> tuple[RandomForestClassifier, float]:
    synthetic = pd.DataFrame({c: rng.choice(X[c].to_numpy(), size=len(X)) for c in X.columns})
    data = pd.concat([X, synthetic], ignore_index=True)
    y = np.r_[np.ones(len(X)), np.zeros(len(X))]
    rf = RandomForestClassifier(n_estimators=N_TREES, min_samples_leaf=min_leaf,
                                max_features="sqrt", oob_score=True, n_jobs=-1,
                                random_state=seed)
    rf.fit(data, y)
    return rf, rf.oob_score_


def proximity(leaves: np.ndarray) -> np.ndarray:
    """Share of trees in which each pair of rows shares a leaf."""
    n, trees = leaves.shape
    prox = np.zeros((n, n), dtype=np.float32)
    for t in range(trees):
        col = leaves[:, t]
        prox += col[:, None] == col[None, :]
    return prox / trees


def hierarchical(prox: np.ndarray, k: int | None = None,
                 min_cluster_share: float = MIN_CLUSTER_SHARE) -> tuple[np.ndarray, pd.DataFrame]:
    """Ward clustering on sqrt(1 - proximity); pick k by silhouette unless given."""
    dist = np.sqrt(np.clip(1 - prox, 0, None)).astype(np.float64)
    np.fill_diagonal(dist, 0)
    tree = linkage(squareform(dist, checks=False), method="ward")
    rows = []
    for cand in K_RANGE:
        labels = fcluster(tree, cand, criterion="maxclust")
        sizes = np.bincount(labels)[1:]
        rows.append({"k": cand, "silhouette": silhouette_score(dist, labels, metric="precomputed"),
                     "smallest_cluster_share": sizes.min() / len(labels)})
    table = pd.DataFrame(rows)
    valid = table[table["smallest_cluster_share"] >= min_cluster_share]
    best_k = k or int((valid if len(valid) else table).sort_values("silhouette").iloc[-1]["k"])
    table["chosen"] = table["k"] == best_k
    return fcluster(tree, best_k, criterion="maxclust"), table


def assign_to_centroid(leaves_all: np.ndarray, leaves_ref: np.ndarray,
                       ref_labels: np.ndarray) -> np.ndarray:
    """Assign rows to the nearest cluster centroid in leaf one-hot space.

    Ward works in that space, so the centroid rule keeps the same geometry.
    Per tree, the centroid of cluster c is mu[leaf, c] = share of c's members in
    that leaf, and ||phi(x) - mu_c||^2 = const - 2 * mu[leaf(x), c] + sum(mu[:, c]^2).
    """
    clusters = np.unique(ref_labels)
    idx = np.searchsorted(clusters, ref_labels)
    sizes = np.bincount(idx)
    score = np.zeros((len(leaves_all), len(clusters)))
    norm = np.zeros(len(clusters))
    for t in range(leaves_all.shape[1]):
        n_leaves = max(leaves_all[:, t].max(), leaves_ref[:, t].max()) + 1
        counts = np.zeros((n_leaves, len(clusters)))
        np.add.at(counts, (leaves_ref[:, t], idx), 1)
        mu = counts / sizes
        score += 2 * mu[leaves_all[:, t]]
        norm += (mu ** 2).sum(axis=0)
    return clusters[np.argmax(score - norm, axis=1)]


def relabel_by_size(labels: np.ndarray, prefix: str) -> np.ndarray:
    order = pd.Series(labels).value_counts().index
    mapping = {old: f"{prefix}{i + 1}" for i, old in enumerate(order)}
    return np.array([mapping[l] for l in labels])


def segment(X: pd.DataFrame, min_leaf: int, seed: int, k: int | None = None,
            min_cluster_share: float = MIN_CLUSTER_SHARE):
    """Run the unsupervised forest + Ward pipeline; k=None picks k by silhouette."""
    rng = np.random.default_rng(seed)
    rf, oob = unsupervised_forest(X, min_leaf, rng, seed)
    leaves = rf.apply(X)
    if len(X) <= CUSTOMER_SAMPLE:
        raw_labels, k_table = hierarchical(proximity(leaves), k, min_cluster_share)
        agreement = None
    else:
        sample = rng.choice(len(X), size=CUSTOMER_SAMPLE, replace=False)
        sample_labels, k_table = hierarchical(proximity(leaves[sample]), k, min_cluster_share)
        raw_labels = assign_to_centroid(leaves, leaves[sample], sample_labels)
        agreement = (raw_labels[sample] == sample_labels).mean()
    return raw_labels, k_table, oob, agreement


def profile(X: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    grouped = X.assign(cluster=labels).groupby("cluster")
    prof = grouped.median().T
    prof.columns = [f"{c}_median" for c in prof.columns]
    z = ((grouped.mean() - X.mean()) / X.std(ddof=0)).T
    z.columns = [f"{c}_z" for c in z.columns]
    return prof.join(z).rename_axis("feature").reset_index()


def chart_profile(name: str, label: str, X: pd.DataFrame, labels: np.ndarray,
                  importance: pd.Series) -> None:
    clusters = sorted(np.unique(labels), key=lambda c: int(c.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")))
    feats = importance.index[:PROFILE_TOP_FEATURES].tolist()
    grouped = X.assign(cluster=labels).groupby("cluster")
    z = ((grouped.mean() - X.mean()) / X.std(ddof=0)).loc[clusters, feats].T
    med = grouped.median().loc[clusters, feats].T
    sizes = pd.Series(labels).value_counts().reindex(clusters)

    def fmt(v):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"

    cells = {(r, c): f"{fmt(med.iat[r, c])}\n{z.iat[r, c]:+.2f}σ"
             for r in range(len(feats)) for c in range(len(clusters))}
    height = 190 + 40 * len(feats)
    width = max(1300, 360 + 140 * len(clusters))
    fig, ax = new_figure(width, height, left=320 / width, right=0.98, top=1 - 190 / height,
                         bottom=10 / height)
    lim = min(2.0, np.abs(z.values).max())
    heatmap(ax, np.clip(z.values, -lim, lim), feats,
            [f"{c}\nn={n:,}\n({fmt_pct(n / len(labels) * 100)})" for c, n in sizes.items()],
            cells, vmin=-lim, vmax=lim, cmap=DIV_CMAP)
    set_titles(fig, f"{label} segments: profile of the top {len(feats)} features",
               "Rows ranked by importance for telling segments apart. Cell = segment median and "
               "mean gap vs all rows in SD units;\ncolor = that gap (blue above average, red "
               f"below, capped at ±{lim:.1f}σ)", left=0.02)
    save(fig, f"{name}_cluster_profile")


def chart_importance(name: str, label: str, importance: pd.Series) -> None:
    top = importance.head(PROFILE_TOP_FEATURES)
    height = 115 + 34 * len(top) + 50
    fig, ax = new_figure(1300, height, left=0.26, right=0.9, top=1 - 115 / height,
                         bottom=50 / height)
    style_axes(ax, "x")
    barh(ax, top.index.tolist(), (top * 100).tolist(), [f"{v:.1%}" for v in top])
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    set_titles(fig, f"What separates {label.lower()} segments",
               f"Impurity importance of a supervised random forest ({N_TREES} trees) "
               "predicting the segment label")
    save(fig, f"{name}_feature_importance")


def run_segmentation(name: str, label: str, ids: pd.DataFrame, X: pd.DataFrame, prefix: str,
                     min_leaf: int, min_cluster_share: float = MIN_CLUSTER_SHARE) -> dict:
    """Segment X, check stability and write tables + charts under `name`.

    Returns the quality metrics (k, silhouette, OOB scores, stability ARI).
    """
    raw_labels, k_table, oob, agreement = segment(X, min_leaf, RANDOM_STATE,
                                                  min_cluster_share=min_cluster_share)
    labels = relabel_by_size(raw_labels, prefix)
    chosen = k_table.loc[k_table["chosen"]].iloc[0]
    best_k = int(chosen["k"])
    # Stability: same k, different seed for the synthetic data and the forest
    alt_labels, _, _, _ = segment(X, min_leaf, STABILITY_SEED, best_k, min_cluster_share)
    ari = adjusted_rand_score(raw_labels, alt_labels)
    k_table["oob_real_vs_synthetic"] = oob
    k_table["sample_agreement"] = agreement
    k_table["seed_stability_ari"] = ari
    save_table(k_table, f"{name}_k_selection")

    sup = RandomForestClassifier(n_estimators=N_TREES, oob_score=True, n_jobs=-1,
                                 random_state=RANDOM_STATE).fit(X, labels)
    importance = pd.Series(sup.feature_importances_, index=X.columns).sort_values(ascending=False)
    save_table(importance.rename("importance").rename_axis("feature").reset_index(),
               f"{name}_feature_importance")
    save_table(ids.assign(cluster=labels), f"{name}_clusters")
    save_table(profile(X, labels), f"{name}_profile")
    chart_profile(name, label, X, labels, importance)
    chart_importance(name, label, importance)

    metrics = {"rows": len(X), "features": X.shape[1], "k": best_k,
               "silhouette": chosen["silhouette"], "oob_real_vs_synthetic": oob,
               "sample_agreement": agreement, "seed_stability_ari": ari,
               "supervised_oob_accuracy": sup.oob_score_,
               "sizes": pd.Series(labels).value_counts().to_dict()}
    print(f"[{name}] " + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                                   for k, v in metrics.items()))
    return metrics
