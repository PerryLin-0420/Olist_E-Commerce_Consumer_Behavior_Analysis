"""Step 01: weekday x hour (7 x 24) matrices of order count, order value and installments.

Unit: valid orders, placed at order_purchase_timestamp (local time as stored).
- orders: number of orders in the cell (all weeks pooled) and orders per week
- mean order value: total payment value per order
- mean installments: credit-card installments when > 1, else 0 (paid in full)

Outputs: outputs/cell_metrics.csv; charts/01_orders_matrix.png,
02_order_value_matrix.png, 03_installments_matrix.png
"""
from tm_common import HOURS, WEEKDAYS, cell_table, load_orders, matrix
from eda_utils import (DPI, INK, INK_2, SEQ_CMAP, fmt_brl, new_figure, save,  # noqa: E402
                       save_table, set_titles)


def chart_matrix(m, title: str, subtitle: str, fmt, filename: str, row_totals=None,
                 scale_label: str = "") -> None:
    fig, ax = new_figure(1800, 560, left=0.06, right=0.87, top=0.72, bottom=0.08)
    vals = m.values.astype(float)
    im = ax.imshow(vals, cmap=SEQ_CMAP, aspect="auto", interpolation="nearest")
    for r in range(vals.shape[0]):
        for c in range(vals.shape[1]):
            rgba = im.cmap(im.norm(vals[r, c]))
            lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            ax.text(c, r, fmt(vals[r, c]), ha="center", va="center", fontsize=6.8,
                    color="white" if lum < 0.5 else INK)
    ax.set_xticks(range(24), [f"{h:02d}" for h in HOURS])
    ax.set_yticks(range(7), WEEKDAYS)
    ax.xaxis.tick_top()
    ax.tick_params(length=0, labelsize=8)
    ax.set_xticks([x - 0.5 for x in range(1, 24)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, 7)], minor=True)
    ax.grid(which="minor", color="#fcfcfb", linewidth=2 * 72 / DPI)
    ax.tick_params(which="minor", length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("Hour of day", labelpad=6)
    if row_totals is not None:
        for r, v in enumerate(row_totals):
            y = fig.transFigure.inverted().transform(ax.transData.transform((0, r)))[1]
            fig.text(0.985, y, v, ha="right", va="center", fontsize=8, color=INK_2)
    cax = fig.add_axes([0.06, 0.035, 0.22, 0.02])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7, length=0)
    if scale_label:
        fig.text(0.29, 0.045, scale_label, fontsize=7.5, color=INK_2, va="center")
    set_titles(fig, title, subtitle)
    save(fig, filename)


def main() -> None:
    df = load_orders()
    n_weeks = df["week"].nunique()
    cells = cell_table(df)
    save_table(cells.reset_index(), "cell_metrics")

    orders = matrix(df)
    day_totals = orders.sum(axis=1)
    peak = cells["orders"].idxmax()
    low = cells["orders"].idxmin()
    chart_matrix(orders, "Orders by weekday and hour",
                 f"{len(df):,} valid orders over {n_weeks} weeks; each cell pools every week. "
                 f"Busiest cell {WEEKDAYS[peak[0]]} {peak[1]:02d}:00 ({int(cells['orders'].max()):,}), "
                 f"quietest {WEEKDAYS[low[0]]} {low[1]:02d}:00 ({int(cells['orders'].min()):,})",
                 lambda v: f"{v:,.0f}", "01_orders_matrix",
                 row_totals=[f"{int(v):,} ({v / day_totals.sum():.1%})" for v in day_totals],
                 scale_label="orders")

    value = matrix(df, "order_value")
    day_value = df.groupby("weekday")["order_value"].mean()
    hi, lo = cells["mean_order_value"].idxmax(), cells["mean_order_value"].idxmin()
    chart_matrix(value, "Mean order value by weekday and hour",
                 f"Payment value per order. Highest {WEEKDAYS[hi[0]]} {hi[1]:02d}:00 "
                 f"({fmt_brl(cells['mean_order_value'].max())}), lowest {WEEKDAYS[lo[0]]} "
                 f"{lo[1]:02d}:00 ({fmt_brl(cells['mean_order_value'].min())}); night cells hold "
                 "few orders, so a handful of large orders moves them",
                 lambda v: f"{v:.0f}", "02_order_value_matrix",
                 row_totals=[f"day mean {fmt_brl(v)}" for v in day_value],
                 scale_label="R$ per order")

    inst = matrix(df, "installments")
    day_inst = df.groupby("weekday")["installments"].mean()
    chart_matrix(inst, "Mean installments by weekday and hour",
                 "Credit-card installments when > 1, otherwise 0 (paid in full, boleto, voucher, "
                 f"debit card). Overall mean {df['installments'].mean():.2f}; "
                 f"{df['in_installments'].mean():.1%} of orders use installments",
                 lambda v: f"{v:.1f}", "03_installments_matrix",
                 row_totals=[f"day mean {v:.2f}" for v in day_inst],
                 scale_label="installments (0 = paid in full)")
    print(cells[["orders", "mean_order_value", "mean_installments"]].describe().round(2).to_string())


if __name__ == "__main__":
    main()
