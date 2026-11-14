"""The link-preview image (Open Graph, 1200x630): the page title beside every US generating unit running in 2050.

    python scripts/make_og.py          # writes web/og.png from web/data/ux2050/plants.json

Plants are EIA's AEO2026 plant file as the page maps them: colored by fuel, sized by capacity, on an Albers
projection of the lower 48. Rerun when the plant data or the page's title changes.
"""

import json
from math import cos, log, radians, sin, sqrt, tan, pi
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COLOR = {"coal": "#9b8f84", "gas": "#E8A33D", "oil": "#D0583F", "nuclear": "#B48AE0", "hydro": "#4C9BE8",
         "wind": "#5DCAA5", "solar": "#F2D04B", "other": "#86B35E", "storage": "#E07AAE"}
BG, INK, INK2, ACCENT = "#0d1015", "#e8e6df", "#a9a79f", "#5DCAA5"


def albers(lon, lat, lon0=-96.0, lat0=37.5, p1=29.5, p2=45.5):
    """US Albers equal-area conic, unit sphere."""
    p1, p2, lat0r = radians(p1), radians(p2), radians(lat0)
    n = (sin(p1) + sin(p2)) / 2
    c = cos(p1) ** 2 + 2 * n * sin(p1)
    rho0 = sqrt(c - 2 * n * sin(lat0r)) / n
    rho = sqrt(c - 2 * n * sin(radians(lat))) / n
    th = n * radians(lon - lon0)
    return rho * sin(th), rho0 - rho * cos(th)


def main(year: int = 2050) -> Path:
    p = json.loads((ROOT / "web" / "data" / "ux2050" / "plants.json").read_text())
    groups = p["groups"]
    pts = [r for r in p["rows"] if -125 < r[0] < -66 and 24 < r[1] < 50 and r[5] <= year < r[6]]
    pts.sort(key=lambda r: -r[2])                       # big plants first, so small ones stay visible on top
    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.50, 0.06, 0.48, 0.88], facecolor=BG)
    xs, ys = zip(*(albers(r[0], r[1]) for r in pts))
    ax.scatter(xs, ys, s=[max(1.5, sqrt(r[2]) * 0.55) for r in pts], c=[COLOR[groups[r[3]]] for r in pts],
               alpha=0.8, linewidths=0)
    ax.set_aspect("equal")
    ax.axis("off")
    t = fig.text
    t(0.05, 0.80, "Your America", color=INK, fontsize=44, fontweight="bold", va="top")
    t(0.05, 0.665, "in 2050", color=ACCENT, fontsize=44, fontweight="bold", va="top")
    t(0.05, 0.50, "EIA's energy forecast, rebuilt as open\nPython. Pull a lever and watch home bills,\n"
                  "gas at the pump and CO2 move.", color=INK2, fontsize=17, va="top", linespacing=1.45)
    t(0.05, 0.12, "NEMS Open", color=INK, fontsize=15, fontweight="bold")
    t(0.05, 0.07, f"{len(pts):,} generating units in {year}, from EIA's plant file", color=INK2, fontsize=12)
    out = ROOT / "web" / "og.png"
    fig.savefig(out, facecolor=BG, dpi=100)
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(main())
