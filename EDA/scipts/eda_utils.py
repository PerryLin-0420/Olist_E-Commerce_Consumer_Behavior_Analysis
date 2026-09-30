"""Shared helpers for EDA scripts: DB access, chart style and output paths."""
import os
import time
from pathlib import Path

import duckdb
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402

EDA_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = EDA_DIR.parent
DB_PATH = PROJECT_DIR / "DB" / "olist.duckdb"
CHART_DIR = EDA_DIR / "charts"
OUTPUT_DIR = EDA_DIR / "outputs"

DPI = 150  # figure pixels == saved pixels, so pixel-based mark specs hold

# Reference palette (light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
# Categorical slots in fixed order: blue, orange, aqua, yellow, magenta, green, violet, red.
# All 8 pass adjacent-pair CVD checks (stacks, bars); maps/scatter cap at the first 3.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER = "#b4b2a9"  # neutral gray for the folded "Other" bucket, never a 9th hue
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
# Ordinal steps (lightest still clears 2:1 on the light surface)
ORDINAL_BLUE = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
SEQ_CMAP = LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)
# Diverging: red (below) <-> neutral gray midpoint <-> blue (above)
DIV_CMAP = LinearSegmentedColormap.from_list("red_gray_blue", ["#e34948", "#f0efec", "#2a78d6"])

BAR_PX = 18     # bar thickness (spec: <= 24px)
RADIUS_PX = 4   # rounded data-end radius

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
    "text.parse_math": False,  # "R$ 67 → R$ 100" must not be read as mathtext
    "text.color": INK,
    "axes.labelcolor": INK_2,
    "xtick.color": MUTED,
    "ytick.color": INK_2,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


def connect() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found; run ETL_scripts/Auto_ETL.bat first")
    return duckdb.connect(str(DB_PATH), read_only=True)


def new_figure(width_px: int, height_px: int, left=0.25, right=0.9, top=0.84, bottom=0.1):
    """Create a fixed-layout figure (no tight_layout, so pixel math stays valid)."""
    fig, ax = plt.subplots(figsize=(width_px / DPI, height_px / DPI), dpi=DPI)
    fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom)
    return fig, ax


def set_titles(fig, title: str, subtitle: str | None = None, left: float | None = None) -> None:
    left = fig.subplotpars.left if left is None else left
    fig.text(left, 0.965, title, fontsize=12, fontweight="semibold", color=INK, va="top")
    if subtitle:
        fig.text(left, 0.965 - 36 / fig.get_figheight() / DPI, subtitle,
                 fontsize=9, color=INK_2, va="top")


def style_axes(ax, value_axis: str = "x") -> None:
    """Recessive chrome: hairline solid grid on the value axis only, no box."""
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    base = ax.spines["left" if value_axis == "x" else "bottom"]
    base.set_visible(True)
    base.set_color(BASELINE)
    base.set_linewidth(1 * 72 / DPI)
    ax.grid(axis=value_axis, color=GRID, linewidth=1 * 72 / DPI, linestyle="-")
    ax.set_axisbelow(True)
    ax.tick_params(length=0, pad=6)


def _rounded_bar_path(x0, y0, x1, y1, rx, ry, horizontal):
    """Bar with rounded corners only at the data end (x1 for horizontal, y1 for vertical)."""
    if horizontal:
        rx = min(rx, (x1 - x0) / 2)
        verts = [(x0, y0), (x1 - rx, y0), (x1, y0), (x1, y0 + ry), (x1, y1 - ry),
                 (x1, y1), (x1 - rx, y1), (x0, y1), (x0, y0)]
    else:
        ry = min(ry, (y1 - y0) / 2)
        verts = [(x0, y0), (x1, y0), (x1, y1 - ry), (x1, y1), (x1 - rx, y1),
                 (x0 + rx, y1), (x0, y1), (x0, y1 - ry), (x0, y0)]
    c, l = MplPath.CURVE3, MplPath.LINETO
    codes = [MplPath.MOVETO, l, c, c, l, c, c, l, MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def _px_to_data(ax):
    """Return (data units per pixel) for x and y of an axes with fixed limits."""
    bbox = ax.get_window_extent()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    return abs(x1 - x0) / bbox.width, abs(y1 - y0) / bbox.height


def barh(ax, labels, values, value_labels, color=SERIES[0], xmax=None):
    """Horizontal bars, first label on top, value label at each tip."""
    n = len(values)
    xmax = xmax or max(values) * 1.18
    ax.set_xlim(0, xmax)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), labels)
    sx, sy = _px_to_data(ax)
    half = BAR_PX * sy / 2
    for i, v in enumerate(values):
        if v > 0:
            path = _rounded_bar_path(0, i - half, v, i + half, RADIUS_PX * sx, RADIUS_PX * sy, True)
            ax.add_patch(PathPatch(path, facecolor=color, edgecolor="none"))
        ax.text(v + 6 * sx, i, value_labels[i], va="center", ha="left", color=INK_2, fontsize=8.5)


def bar(ax, labels, values, value_labels, color=SERIES[0], ymax=None):
    """Vertical columns with value label on each cap."""
    n = len(values)
    ymax = ymax or max(values) * 1.18
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(0, ymax)
    ax.set_xticks(range(n), labels)
    sx, sy = _px_to_data(ax)
    half = min(BAR_PX * 1.5, 24) * sx / 2
    for i, v in enumerate(values):
        if v > 0:
            path = _rounded_bar_path(i - half, 0, i + half, v, RADIUS_PX * sx, RADIUS_PX * sy, False)
            ax.add_patch(PathPatch(path, facecolor=color, edgecolor="none"))
        ax.text(i, v + 5 * sy, value_labels[i], va="bottom", ha="center", color=INK_2, fontsize=8.5)


GAP_PX = 2  # surface gap between touching marks


def grouped_bar(ax, group_labels, series, colors, value_labels=None, ymax=None):
    """Grouped columns; series = {name: [value per group]}, NaN/None = no bar."""
    names = list(series)
    n_groups, n_series = len(group_labels), len(names)
    ymax = ymax or max(v for vals in series.values() for v in vals if v == v and v) * 1.25
    ax.set_xlim(-0.6, n_groups - 0.4)
    ax.set_ylim(0, ymax)
    ax.set_xticks(range(n_groups), group_labels)
    sx, sy = _px_to_data(ax)
    width, gap = 20 * sx, GAP_PX * sx
    span = n_series * width + (n_series - 1) * gap
    for s, name in enumerate(names):
        for g, v in enumerate(series[name]):
            if v is None or v != v or v <= 0:
                continue
            x0 = g - span / 2 + s * (width + gap)
            path = _rounded_bar_path(x0, 0, x0 + width, v, RADIUS_PX * sx, RADIUS_PX * sy, False)
            ax.add_patch(PathPatch(path, facecolor=colors[s], edgecolor="none"))
            if value_labels and value_labels[s][g]:
                # Vertical text: adjacent bars are narrower than a horizontal label
                ax.text(x0 + width / 2, v + 5 * sy, value_labels[s][g], ha="center", va="bottom",
                        color=INK_2, fontsize=7.5, rotation=90)


def stacked_bar(ax, labels, stacks, colors, horizontal=False, total_labels=None, vmax=None):
    """Stacked bars; stacks = list of per-series value lists (bottom/left first).

    A 2px surface gap separates segments; only the outermost segment gets the
    rounded data-end.
    """
    n = len(labels)
    totals = [sum(s[i] for s in stacks) for i in range(n)]
    vmax = vmax or max(totals) * 1.15
    if horizontal:
        ax.set_xlim(0, vmax)
        ax.set_ylim(n - 0.5, -0.5)
        ax.set_yticks(range(n), labels)
    else:
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(0, vmax)
        ax.set_xticks(range(n), labels)
    sx, sy = _px_to_data(ax)
    thick = (BAR_PX * sy if horizontal else 24 * sx) / 2
    gap = GAP_PX * (sx if horizontal else sy)
    for i in range(n):
        start = 0.0
        nonzero = [k for k, s in enumerate(stacks) if s[i] > 0]
        for k in nonzero:
            v = stacks[k][i]
            end = start + v
            is_last = k == nonzero[-1]
            seg_end = end if is_last else max(start, end - gap)
            if horizontal:
                verts = _rounded_bar_path(start, i - thick, seg_end, i + thick,
                                          RADIUS_PX * sx if is_last else 0, RADIUS_PX * sy, True)
            else:
                verts = _rounded_bar_path(i - thick, start, i + thick, seg_end,
                                          RADIUS_PX * sx, RADIUS_PX * sy if is_last else 0, False)
            ax.add_patch(PathPatch(verts, facecolor=colors[k], edgecolor="none"))
            start = end
        if total_labels:
            if horizontal:
                ax.text(totals[i] + 6 * sx, i, total_labels[i], va="center", ha="left",
                        color=INK_2, fontsize=8.5)
            else:
                ax.text(i, totals[i] + 5 * sy, total_labels[i], va="bottom", ha="center",
                        color=INK_2, fontsize=8.5)


def legend(fig, names, colors, y_px_from_top=None, ncol=None, left=None):
    """Swatch legend placed under the subtitle, left-aligned with the plot."""
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=c, edgecolor="none", label=n) for n, c in zip(names, colors)]
    y = 1 - (y_px_from_top or 70) / (fig.get_figheight() * DPI)
    left = fig.subplotpars.left if left is None else left
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(left, y),
               ncol=ncol or len(names), frameon=False, fontsize=8.5, handlelength=1.0,
               handleheight=1.0, columnspacing=1.4, borderaxespad=0, labelcolor=INK_2)


BOX_FILL = BLUE_RAMP[0]
MEDIAN_DASH = (0, (4, 2))
BOX_PX = 16  # box thickness per row
WHISKER_NOTE = "whiskers = 1.5 × IQR, outliers not drawn"


def box_rows(ax, labels, datasets, show_mean=True, xmax=None) -> list[dict]:
    """Horizontal box plots, one row per label (first on top).

    Box = Q1-Q3, dashed line = median, whiskers = most extreme data within
    1.5 x IQR (Tukey), diamond = mean. Outliers are not drawn: each row holds
    thousands of points and the fliers would merge into a solid band.
    Returns the matplotlib boxplot stats (q1, med, q3, whislo, whishi, mean).
    """
    from matplotlib import cbook
    stats = [cbook.boxplot_stats(np.asarray(d, dtype=float), whis=1.5)[0] for d in datasets]
    n = len(labels)
    xmax = xmax or max(max(s["whishi"] for s in stats),
                       max(s["mean"] for s in stats) if show_mean else 0) * 1.05
    ax.set_xlim(0, xmax)
    ax.set_ylim(n - 0.5, -0.5)
    _, sy = _px_to_data(ax)
    hair = 1 * 72 / DPI
    ax.bxp(stats, positions=range(n), widths=BOX_PX * sy, orientation="horizontal",
           patch_artist=True, showfliers=False, showmeans=show_mean, manage_ticks=False,
           boxprops={"facecolor": BOX_FILL, "edgecolor": SERIES[0], "linewidth": hair},
           medianprops={"color": INK, "linewidth": 2 * 72 / DPI, "linestyle": MEDIAN_DASH},
           whiskerprops={"color": SERIES[0], "linewidth": hair},
           capprops={"color": SERIES[0], "linewidth": hair},
           capwidths=BOX_PX * sy * 0.5,
           meanprops={"marker": "D", "markersize": 7 * 72 / DPI + 2,
                      "markerfacecolor": SERIES[1], "markeredgecolor": SURFACE,
                      "markeredgewidth": 2 * 72 / DPI, "zorder": 4})
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n), labels)
    return stats


def box_legend(fig, left, y_px_from_top, with_mean=True):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=BOX_FILL, edgecolor=SERIES[0], label="Q1–Q3 box"),
               Line2D([], [], color=INK, linestyle=MEDIAN_DASH, linewidth=1.5, label="Median"),
               Line2D([], [], color=SERIES[0], linewidth=1, label="Whiskers 1.5×IQR")]
    if with_mean:
        handles.append(Line2D([], [], marker="D", color=SERIES[1], linestyle="none",
                              markersize=5, label="Mean"))
    y = 1 - y_px_from_top / (fig.get_figheight() * DPI)
    fig.legend(handles=handles, loc="upper left", frameon=False, ncol=len(handles), fontsize=8.5,
               labelcolor=INK_2, bbox_to_anchor=(left, y), borderaxespad=0, handlelength=2.2,
               columnspacing=1.2)


def side_table(fig, ax, df, columns, x_positions, header_px_from_top, bold_last=False):
    """Right-aligned numeric columns aligned to the axes rows; columns = [(title, col, fmt)]."""
    height_px = fig.get_figheight() * DPI
    header_y = 1 - header_px_from_top / height_px
    n = len(df)
    for (title, col, fmt), x in zip(columns, x_positions):
        fig.text(x, header_y, title, ha="right", va="bottom", fontsize=8.5, color=MUTED)
        for i, value in enumerate(df[col]):
            y_disp = ax.transData.transform((0, i))[1]
            y_fig = fig.transFigure.inverted().transform((0, y_disp))[1]
            last = bold_last and i == n - 1
            text = fmt(value) if callable(fmt) else fmt.format(value)
            fig.text(x, y_fig, text, ha="right", va="center", fontsize=8.5,
                     color=INK if last else INK_2, fontweight="semibold" if last else "normal")


def fmt_brl(value: float) -> str:
    """Compact currency: R$ 950, R$ 12.9K, R$ 4.2M."""
    if abs(value) >= 1e6:
        return f"R$ {value / 1e6:.1f}M"
    if abs(value) >= 1e3:
        return f"R$ {value / 1e3:.1f}K"
    return f"R$ {value:,.0f}"


def heatmap(ax, matrix, row_labels, col_labels, cell_labels, vmin=0, vmax=None, cmap=SEQ_CMAP):
    """Heatmap (sequential by default) with a 2px surface gap between cells."""
    im = ax.imshow(matrix, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(col_labels)), col_labels)
    ax.set_yticks(range(len(row_labels)), row_labels)
    ax.xaxis.tick_top()
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0, pad=6)
    ax.set_xticks([x - 0.5 for x in range(1, len(col_labels))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(row_labels))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2 * 72 / DPI)
    ax.tick_params(which="minor", length=0)
    for (r, c), text in cell_labels.items():
        rgba = im.cmap(im.norm(matrix[r][c]))
        lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
        ax.text(c, r, text, ha="center", va="center", fontsize=8.5,
                color="white" if lum < 0.5 else INK)
    return im


def fmt_pct(rate_pct: float) -> str:
    """Format a percentage without rounding small non-zero values down to 0."""
    if rate_pct == 0:
        return "0%"
    if rate_pct < 0.01:
        return "<0.01%"
    if rate_pct < 1:
        return f"{rate_pct:.2f}%"
    return f"{rate_pct:.1f}%"


def _replace_with_retry(tmp: Path, path: Path, attempts: int = 5) -> None:
    """Swap tmp into path; retry while another process (viewer, AV scan) holds the file."""
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def save(fig, name: str) -> Path:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / f"{name}.png"
    tmp = path.with_suffix(".tmp.png")
    fig.savefig(tmp, dpi=DPI)
    plt.close(fig)
    _replace_with_retry(tmp, path)
    print(f"saved {path.relative_to(PROJECT_DIR)}")
    return path


def save_table(df, name: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    print(f"saved {path.relative_to(PROJECT_DIR)}")
    return path
