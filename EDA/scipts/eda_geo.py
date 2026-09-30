"""Brazil geography helpers: regions, IBGE state mesh and choropleth drawing."""
import json

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.patches import Patch, Polygon

from eda_utils import DPI, INK, INK_2, PROJECT_DIR, SURFACE

REGIONS = {
    "North": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Northeast": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Center-West": ["DF", "GO", "MT", "MS"],
    "Southeast": ["ES", "MG", "RJ", "SP"],
    "South": ["PR", "RS", "SC"],
}
STATE_TO_REGION = {s: r for r, states in REGIONS.items() for s in states}

# IBGE state codes (codarea in the IBGE mesh API) -> UF abbreviation
IBGE_CODE_TO_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}
GEOJSON_PATH = PROJECT_DIR / "Raw_data" / "brazil_states_ibge.geojson"
# Region name positions (lon, lat), placed outside Brazil so they never cover state labels
REGION_LABEL_POS = {"North": (-70.5, 3.2), "Northeast": (-30.8, -9.0),
                    "Center-West": (-63.5, -18.5), "Southeast": (-38.0, -24.0),
                    "South": (-45.5, -31.0)}
# States too small for an inside label: (dx, dy) offset in degrees, drawn with a leader line
STATE_LABEL_OFFSET = {"DF": (-0.4, 1.6)}


def load_state_rings() -> dict[str, list[np.ndarray]]:
    """Return {UF: [outer ring coordinates, ...]} from the IBGE GeoJSON."""
    geo = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    rings = {}
    for feature in geo["features"]:
        uf = IBGE_CODE_TO_UF[feature["properties"]["codarea"]]
        geom = feature["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        rings[uf] = [np.asarray(poly[0]) for poly in polys]
    return rings


def ring_centroid(ring: np.ndarray) -> tuple[float, float]:
    x, y = ring[:, 0], ring[:, 1]
    cross = x[:-1] * y[1:] - x[1:] * y[:-1]
    area = cross.sum() / 2
    return ((x[:-1] + x[1:]) * cross).sum() / (6 * area), ((y[:-1] + y[1:]) * cross).sum() / (6 * area)


def region_border_segments(rings: dict[str, list[np.ndarray]]) -> list:
    """Edges shared by two states of different regions (the mesh shares vertices)."""
    owners: dict[tuple, set] = {}
    for uf, polys in rings.items():
        for ring in polys:
            pts = [tuple(np.round(p, 6)) for p in ring]
            for a, b in zip(pts[:-1], pts[1:]):
                owners.setdefault(tuple(sorted((a, b))), set()).add(uf)
    return [list(seg) for seg, ufs in owners.items()
            if len({STATE_TO_REGION[u] for u in ufs}) > 1]


def draw_state_map(ax, state_class: dict[str, int], colors: list[str], class_labels: list[str],
                   legend_title: str, region_labels: dict[str, str] | None = None,
                   rings: dict | None = None, show_legend: bool = True) -> None:
    """Choropleth of the 27 states with thick region borders.

    state_class maps UF -> index into colors (an ordinal ramp).
    region_labels maps region -> extra text shown under the region name.
    """
    rings = rings or load_state_rings()
    for uf, polys in rings.items():
        cls = state_class[uf]
        for ring in polys:
            ax.add_patch(Polygon(ring, closed=True, facecolor=colors[cls], edgecolor=SURFACE,
                                 linewidth=1 * 72 / DPI))
        cx, cy = ring_centroid(max(polys, key=len))
        text_color = "white" if cls >= 2 else INK
        tx, ty = cx, cy
        if uf in STATE_LABEL_OFFSET:
            tx, ty = cx + STATE_LABEL_OFFSET[uf][0], cy + STATE_LABEL_OFFSET[uf][1]
            ax.plot([cx, tx], [cy, ty - 0.45], color=text_color, linewidth=1 * 72 / DPI, zorder=5)
        ax.text(tx, ty, uf, ha="center", va="center", fontsize=6.5, color=text_color, zorder=6)
    ax.add_collection(LineCollection(region_border_segments(rings), colors=INK,
                                     linewidths=1.6 * 72 / DPI, zorder=4))
    for region, (x, y) in REGION_LABEL_POS.items():
        text = region if not region_labels else f"{region}\n{region_labels[region]}"
        ax.text(x, y, text, ha="center", va="center", fontsize=8, color=INK_2,
                fontweight="semibold")
    ax.set_xlim(-75, -27)
    ax.set_ylim(-34.5, 6.5)
    ax.set_aspect("equal")
    ax.axis("off")
    if not show_legend:
        return
    handles = [Patch(facecolor=c, edgecolor="none", label=l) for c, l in zip(colors, class_labels)]
    ax.legend(handles=handles, title=legend_title, loc="lower left", frameon=False, fontsize=8,
              title_fontsize=8.5, labelcolor=INK_2, handlelength=1.0, handleheight=1.0,
              bbox_to_anchor=(0.0, 0.02))
