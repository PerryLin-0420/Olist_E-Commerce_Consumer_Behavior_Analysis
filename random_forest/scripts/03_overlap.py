"""Step 03: enumerate every seller segment x customer segment pairing.

Each shipment (order_id x seller_id, valid orders) links one seller segment to
one customer segment. For every pair of segments:
- shipments, distinct customers, distinct sellers
- row share: share of the seller segment's shipments going to the customer segment
- lift = observed / expected under independence (row total x column total / N)
- standardized residual = (observed - expected) / sqrt(expected)

Overall association: chi-square test and Cramér's V (0 = customer mix is the
same for every seller segment, 1 = each seller segment maps to one customer
segment). A seller segment counts as having a fixed customer segment when one
customer segment takes >= FIXED_SHARE of its shipments AND that pair's lift is
>= FIXED_LIFT; share alone is not enough, because a large customer segment
takes a big share of every seller segment by base rate.

Outputs: outputs/overlap_pairs.csv, overlap_by_seller_segment.csv,
overlap_summary.csv; charts/overlap_seller_customer_segments.png
"""
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from rf_common import OUTPUT_DIR
from eda_utils import (DIV_CMAP, connect, fmt_pct, heatmap, new_figure,  # noqa: E402
                       save, save_table, set_titles)

FIXED_SHARE = 0.5
FIXED_LIFT = 1.5

SHIPMENT_SQL = """
SELECT DISTINCT o.order_id, i.seller_id, c.customer_unique_id
FROM orders o
JOIN customers c USING (customer_id)
JOIN order_items i USING (order_id)
WHERE o.order_status NOT IN ('canceled', 'unavailable')
ORDER BY 1, 2
"""


def seg_order(labels) -> list[str]:
    return sorted(set(labels), key=lambda s: int(s[1:]))


def main() -> None:
    con = connect()
    ship = con.execute(SHIPMENT_SQL).df()
    con.close()
    sellers = pd.read_csv(OUTPUT_DIR / "seller_clusters.csv").rename(
        columns={"cluster": "seller_segment"})
    customers = pd.read_csv(OUTPUT_DIR / "customer_clusters.csv").rename(
        columns={"cluster": "customer_segment"})
    ship = ship.merge(sellers, on="seller_id").merge(customers, on="customer_unique_id")
    s_order, c_order = seg_order(ship["seller_segment"]), seg_order(ship["customer_segment"])

    obs = pd.crosstab(ship["seller_segment"], ship["customer_segment"]) \
        .reindex(index=s_order, columns=c_order, fill_value=0)
    n = obs.values.sum()
    expected = np.outer(obs.sum(axis=1), obs.sum(axis=0)) / n
    lift = obs / expected
    resid = (obs - expected) / np.sqrt(expected)
    row_share = obs.div(obs.sum(axis=1), axis=0)
    col_share = obs.div(obs.sum(axis=0), axis=1)
    chi2, p, dof, _ = chi2_contingency(obs.values)
    cramers_v = np.sqrt(chi2 / (n * (min(obs.shape) - 1)))

    # Every pair, enumerated
    counts = ship.groupby(["seller_segment", "customer_segment"]).agg(
        shipments=("order_id", "size"), customers=("customer_unique_id", "nunique"),
        sellers=("seller_id", "nunique"))
    pairs = []
    for s in s_order:
        for c in c_order:
            k = counts.loc[(s, c)] if (s, c) in counts.index else None
            pairs.append({
                "seller_segment": s, "customer_segment": c,
                "shipments": int(obs.loc[s, c]),
                "customers": int(k["customers"]) if k is not None else 0,
                "sellers": int(k["sellers"]) if k is not None else 0,
                "share_of_seller_segment": row_share.loc[s, c],
                "share_of_customer_segment": col_share.loc[s, c],
                "expected": expected[s_order.index(s), c_order.index(c)],
                "lift": lift.loc[s, c], "std_residual": resid.loc[s, c],
            })
    pairs = pd.DataFrame(pairs)
    save_table(pairs.sort_values("lift", ascending=False), "overlap_pairs")

    # Concentration per seller segment
    p_row = row_share.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        ent = -(np.where(p_row > 0, p_row * np.log(p_row), 0)).sum(axis=1) / np.log(len(c_order))
    by_seller = pd.DataFrame({
        "seller_segment": s_order,
        "shipments": obs.sum(axis=1).to_numpy(),
        "top_customer_segment": row_share.idxmax(axis=1).to_numpy(),
        "top_share": row_share.max(axis=1).to_numpy(),
        "top_lift": [lift.loc[s, row_share.loc[s].idxmax()] for s in s_order],
        "highest_lift_segment": lift.idxmax(axis=1).to_numpy(),
        "highest_lift": lift.max(axis=1).to_numpy(),
        "normalized_entropy": ent,
    })
    by_seller["fixed_pairing"] = (by_seller["top_share"] >= FIXED_SHARE) &         (by_seller["top_lift"] >= FIXED_LIFT)
    save_table(by_seller, "overlap_by_seller_segment")
    save_table(pd.DataFrame([{"shipments": n, "chi2": chi2, "dof": dof, "p_value": p,
                              "cramers_v": cramers_v, "fixed_share_rule": FIXED_SHARE,
                              "fixed_lift_rule": FIXED_LIFT, "max_pair_lift": lift.values.max(),
                              "seller_segments_with_fixed_pairing":
                                  int(by_seller["fixed_pairing"].sum())}]), "overlap_summary")

    # Heatmap: row share annotated, colored by log2 lift
    log_lift = np.log2(lift.clip(lower=1e-9))
    lim = max(0.5, min(1.5, np.abs(log_lift.values).max()))
    cells = {(r, c): f"{row_share.iat[r, c] * 100:.1f}%\n×{lift.iat[r, c]:.2f}"
             for r in range(len(s_order)) for c in range(len(c_order))}
    col_totals = obs.sum(axis=0) / n * 100
    width = max(1300, 320 + 120 * len(c_order))
    height = 200 + 70 * len(s_order)
    fig, ax = new_figure(width, height, left=250 / width, right=0.98, top=1 - 200 / height,
                         bottom=10 / height)
    heatmap(ax, np.clip(log_lift.values, -lim, lim),
            [f"{s}  ({fmt_pct(v / n * 100)} of shipments)" for s, v in obs.sum(axis=1).items()],
            [f"{c}\n(all: {v:.1f}%)" for c, v in col_totals.items()], cells,
            vmin=-lim, vmax=lim, cmap=DIV_CMAP)
    fixed = by_seller["fixed_pairing"].sum()
    set_titles(fig, "Seller segment × customer segment: every pairing",
               f"{n:,} shipments. Cell = share of the seller segment's shipments to each customer "
               "segment, and lift vs independence;\ncolor = log2 lift (blue: more than expected, "
               f"red: fewer). Cramér's V = {cramers_v:.3f}; highest lift ×{lift.values.max():.2f}. "
               f"Fixed pairings (share ≥ {FIXED_SHARE:.0%} and lift ≥ {FIXED_LIFT}): "
               f"{fixed} of {len(s_order)} seller segments", left=0.02)
    save(fig, "overlap_seller_customer_segments")

    print(f"shipments linked: {n:,}; chi2={chi2:,.0f} dof={dof} p={p:.3g} "
          f"Cramer's V={cramers_v:.3f}")
    print(by_seller.round(3).to_string(index=False))
    print(pairs.sort_values("lift", ascending=False).head(8).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
