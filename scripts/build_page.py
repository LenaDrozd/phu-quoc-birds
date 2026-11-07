"""Build the map page from the derived data.

    python scripts/build_page.py                    -> index.html (photos loaded from photos/)
    python scripts/build_page.py --inline -o x.html -> one self-contained file with embedded photos
    python scripts/build_page.py --repo https://github.com/<user>/phu-quoc-birds

Inputs: data/species_by_month.csv, data/points.json, data/months.json,
        data/photo_credits.json, data/island_outline.json, scripts/template.html
"""
import argparse
import base64
import calendar
import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

LON0, LON1, LAT0, LAT1 = 103.79, 104.14, 10.47, 9.885   # map frame
K = 1300.0                                               # px per degree of latitude
CX = math.cos(math.radians(10.2))
W, H = (LON1 - LON0) * CX * K, (LAT0 - LAT1) * K


def xy(lon, lat):
    return (lon - LON0) * CX * K, (LAT0 - lat) * K


def ring_path(ring, tol=0.6):
    pts = [xy(*c) for c in ring]
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol:
            out.append(p)
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in out) + "Z"



    if not text:
        return ""
    dx, dy, anc = p["dx"], p["dy"], p["anchor"]
    if anc == "middle":
        dy += (r - 8) if dy > 0 else -(r - 8)
    else:
        dx += (r - 8) if dx > 0 else -(r - 8)
    return f'<text class="lbl {cls}" x="{x+dx:.1f}" y="{y+dy+4:.1f}" text-anchor="{anc}">{text}</text>'


def build_svg(points, polys):
    """Static parts of the map. The points are drawn by the page script, per month."""
    island = "".join(ring_path(p[0]) for p in polys if len(p[0]) > 4)
    for p in points.values():
        x, y = xy(p["lon"], p["lat"])
        p["x"], p["y"] = round(x, 1), round(y, 1)
    km = K / 111.0
    sx, sy = W - 20 - 5 * km, H - 26
    scale = (f'<g class="scale"><line x1="{sx:.1f}" y1="{sy}" x2="{sx+5*km:.1f}" y2="{sy}"/>'
             f'<line x1="{sx:.1f}" y1="{sy-4}" x2="{sx:.1f}" y2="{sy+4}"/><line x1="{sx+5*km:.1f}" y1="{sy-4}" x2="{sx+5*km:.1f}" y2="{sy+4}"/>'
             f'<text x="{sx+2.5*km:.1f}" y="{sy-7}" text-anchor="middle"><tspan class="ru">5 км</tspan><tspan class="en">5 km</tspan></text></g>')
    nx, ny = W - 26, 30
    north = (f'<g class="scale"><line x1="{nx:.1f}" y1="{ny+14}" x2="{nx:.1f}" y2="{ny-12}"/>'
             f'<path d="M{nx-5:.1f},{ny-6}L{nx:.1f},{ny-16}L{nx+5:.1f},{ny-6}" fill="none" style="stroke:var(--ink);stroke-width:1.3"/>'
             f'<text x="{nx:.1f}" y="{ny+28}" text-anchor="middle"><tspan class="ru">С</tspan><tspan class="en">N</tspan></text></g>')
    fx, fy = xy(103.965, 10.335)
    sx1, sy1 = xy(103.86, 10.12)
    return (f'<svg class="map" viewBox="0 0 {W:.0f} {H:.0f}" role="group" aria-label="Phu Quoc / Фукуок">'
            f'<path class="island" d="{island}"/>'
            f'<text class="forestlbl ru" x="{fx:.1f}" y="{fy:.1f}" text-anchor="middle">лесной север</text>'
            f'<text class="forestlbl en" x="{fx:.1f}" y="{fy:.1f}" text-anchor="middle">forested north</text>'
            f'<text class="sealbl ru" x="{sx1:.1f}" y="{sy1:.1f}" text-anchor="middle">Сиамский залив</text>'
            f'<text class="sealbl en" x="{sx1:.1f}" y="{sy1:.1f}" text-anchor="middle">Gulf of Thailand</text>'
            f'{scale}{north}<g id="spots"></g></svg>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(ROOT / "index.html"))
    ap.add_argument("--inline", action="store_true", help="embed photos as data URIs")
    ap.add_argument("--fragment", action="store_true", help="omit <!doctype>/<html>/<head> wrapper")
    ap.add_argument("--repo", default="", help="repository URL for the footer link")
    a = ap.parse_args()

    points = json.load(open(DATA / "points.json"))
    months = json.load(open(DATA / "months.json"))["months"]
    credits = json.load(open(DATA / "photo_credits.json"))
    polys = json.load(open(DATA / "island_outline.json"))
    keys = ["year"] + [calendar.month_abbr[m].lower() for m in range(1, 13)]
    birds = []
    with open(DATA / "species_by_month.csv", newline="") as f:
        for r in csv.DictReader(f):
            birds.append(dict(latin=r["latin"], name_ru=r["name_ru"], name_en=r["name_en"], status=r["status"],
                              pct=[float(r[f"pct_{k}"]) for k in keys], lists=[int(r[f"lists_{k}"]) for k in keys]))
    for p in points.values():          # month keys "0".."12" -> list index
        p["lists"] = [p["lists"][str(m)] for m in range(13)]
        p["species"] = [p["species"][str(m)] for m in range(13)]
    months = [months[str(m)] for m in range(13)]

    photos = {}
    for sp in [b["latin"] for b in birds]:
        c = dict(credits[sp])
        path = ROOT / c["file"]
        c["src"] = ("data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()) if a.inline else c["file"]
        photos[sp] = {k: c[k] for k in ("src", "author", "license", "license_url", "source")}

    svg = build_svg(points, polys)
    data = dict(points=points, birds=birds, months=months, photos=photos)
    html = (ROOT / "scripts" / "template.html").read_text()
    html = (html.replace("__SVG__", svg)
                .replace("__LISTS__", str(months[0]["checklists"]))
                .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    if a.repo:
        html = html.replace("__REPO__", a.repo)
    else:
        html = re.sub(r' (Код|Code): <a href="__REPO__"[^>]*>GitHub</a>\.', "", html)
    if not a.fragment:
        i = html.index('<div class="wrap"')
        head = html[:i].replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
        html = ('<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                + head + '</head>\n<body>\n' + html[i:] + '\n</body>\n</html>\n')
    Path(a.out).write_text(html)
    print(f"wrote {a.out} ({len(html)//1024} KB, {len(birds)} species, {len(points)} points)")


if __name__ == "__main__":
    main()
