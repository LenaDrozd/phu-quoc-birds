"""Phu Quoc birds by month, from the eBird Basic Dataset (EBD).

Reads the raw EBD export for Vietnam (observations + sampling events), keeps
Phu Quoc and its islets, and writes the derived tables used by the map:

    data/species_by_month.csv  one row per species: % of complete checklists and
                               number of checklists, for every month and the whole year
    data/points.json           map points with checklists and species, by month
    data/months.json           number of checklists behind every month

A "month" is the calendar month plus half a month on each side (December =
16 November - 16 January). Few people go birding on Phu Quoc, so a wider window
gives steadier numbers; neighbouring months therefore overlap.

Usage:
    python scripts/analyze.py --ebd raw/ebd_VN_..._relSep-2026.txt \
                              --sampling raw/ebd_VN_..._relSep-2026_sampling.txt

The raw EBD files are NOT part of this repository (eBird terms of use forbid
redistributing them). Request your own copy at https://ebird.org/data/download
"""
import argparse
import calendar
import json
import math
from pathlib import Path

import pandas as pd

from names import RU_NAMES, WINTER_VISITORS, SUMMER_VISITORS, EXCLUDED, POINTS, CARD_LABELS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

BBOX = dict(lat=(9.85, 10.50), lon=(103.80, 104.15))   # Phu Quoc and the An Thoi islets
HALF_WIDTH = 1.0            # months; window = [month - 0.5, month + 1.5) on a 1..13 scale
ZOO = "Vinpearl Safari"     # captive birds: species seen only here are dropped
# Locations that stand for "somewhere on the island" or the zoo: counted in the
# frequencies (zoo-only species excepted), never placed on the map.
GENERIC = {"Phu Quoc Island", "Phu Quoc", "Đảo Phú Quốc", "TOBYBIRDING.COM/PHU QUOC ISLAND", ZOO}
POINT_RADIUS_KM = 3.5
MONTHS = list(range(1, 13))

OBS_COLS = ["CATEGORY", "COMMON NAME", "SCIENTIFIC NAME", "LOCALITY", "LOCALITY ID", "LATITUDE", "LONGITUDE",
            "OBSERVATION DATE", "SAMPLING EVENT IDENTIFIER", "GROUP IDENTIFIER", "ALL SPECIES REPORTED"]
SMP_COLS = ["LOCALITY", "LOCALITY ID", "LATITUDE", "LONGITUDE", "OBSERVATION DATE",
            "SAMPLING EVENT IDENTIFIER", "GROUP IDENTIFIER", "ALL SPECIES REPORTED"]


def read_ebd(path, cols):
    df = pd.read_csv(path, sep="\t", usecols=cols, dtype=str, quoting=3)
    df["lat"] = df.LATITUDE.astype(float)
    df["lon"] = df.LONGITUDE.astype(float)
    df = df[df.lat.between(*BBOX["lat"]) & df.lon.between(*BBOX["lon"])].copy()
    # a shared checklist appears once per observer; count it once
    df["ck"] = df["GROUP IDENTIFIER"].fillna(df["SAMPLING EVENT IDENTIFIER"])
    d = pd.to_datetime(df["OBSERVATION DATE"])
    days = [calendar.monthrange(y, m)[1] for y, m in zip(d.dt.year, d.dt.month)]
    df["mpos"] = d.dt.month + (d.dt.day - 1) / pd.Series(days, index=df.index)   # 1.0 .. 12.97
    return df


def in_month(mpos, m):
    """True where a date (as month position) falls in the window around month m."""
    diff = ((mpos - (m + 0.5) + 6) % 12) - 6
    return (diff >= -HALF_WIDTH) & (diff < HALF_WIDTH)


def km(lat1, lon1, lat2, lon2):
    return math.hypot((lat1 - lat2) * 111.0, (lon1 - lon2) * 111.0 * math.cos(math.radians(10.2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ebd", required=True)
    ap.add_argument("--sampling", required=True)
    a = ap.parse_args()

    obs = read_ebd(a.ebd, OBS_COLS)
    smp = read_ebd(a.sampling, SMP_COLS).drop_duplicates("ck")

    # species level: fold subspecies groups (issf) into their species
    obs = obs[obs.CATEGORY.isin(["species", "issf"])].copy()
    obs["sp"] = obs["SCIENTIFIC NAME"].str.split().str[:2].str.join(" ")
    en = obs[obs.CATEGORY == "species"].drop_duplicates("sp").set_index("sp")["COMMON NAME"]
    zoo_only = {sp for sp, g in obs.groupby("sp") if set(g.LOCALITY) == {ZOO}}
    obs = obs[~obs.sp.isin(EXCLUDED) & ~obs.sp.isin(zoo_only)].drop_duplicates(["ck", "sp"])
    missing = sorted(set(obs.sp) - set(RU_NAMES))
    if missing:
        raise SystemExit(f"add Russian names to scripts/names.py for: {missing}")

    # map points: each specific location goes to the nearest named point
    locs = smp[~smp.LOCALITY.isin(GENERIC)].groupby("LOCALITY ID")[["lat", "lon"]].first()
    loc2pt = {}
    for lid, r in locs.iterrows():
        d, i = min((km(r.lat, r.lon, p[0], p[1]), i) for i, p in enumerate(POINTS))
        if d <= POINT_RADIUS_KM:
            loc2pt[lid] = f"p{i:02d}"
    smp["pt"] = smp["LOCALITY ID"].map(loc2pt)
    obs["pt"] = obs["LOCALITY ID"].map(loc2pt)

    windows = {0: (smp.mpos > 0, obs.mpos > 0)}          # 0 = whole year
    for m in MONTHS:
        windows[m] = (in_month(smp.mpos, m), in_month(obs.mpos, m))

    months, table = {}, {sp: {} for sp in sorted(set(obs.sp))}
    points = {f"p{i:02d}": dict(lat=p[0], lon=p[1], name_ru=p[2], short_ru=p[3], name_en=p[4], short_en=p[5],
                                tag_ru=p[3] or CARD_LABELS.get(p[2], (p[2], p[4]))[0],
                                tag_en=p[5] or CARD_LABELS.get(p[2], (p[2], p[4]))[1],
                                dx=p[6], dy=p[7], anchor=p[8], lists={}, species={})
              for i, p in enumerate(POINTS)}
    for m, (ms, mo) in windows.items():
        s, o = smp[ms], obs[mo]
        complete = set(s[s["ALL SPECIES REPORTED"] == "1"].ck)
        months[m] = dict(checklists=int(len(s)), complete=int(len(complete)))
        freq = o[o.ck.isin(complete)].groupby("sp").size() / max(len(complete), 1) * 100
        n = o.groupby("sp").size()
        for sp in table:
            table[sp][m] = (round(float(freq.get(sp, 0.0)), 1), int(n.get(sp, 0)))
        for pid, p in points.items():
            p["lists"][m] = int((s.pt == pid).sum())
            sp = o[o.pt == pid].groupby("sp").size().sort_values(ascending=False)
            p["species"][m] = {k: int(v) for k, v in sp.items()}

    rows = []
    for sp, vals in table.items():
        r = dict(latin=sp, name_en=en.get(sp, sp), name_ru=RU_NAMES[sp],
                 status="winter" if sp in WINTER_VISITORS else "summer" if sp in SUMMER_VISITORS else "resident")
        for m in [0] + MONTHS:
            key = "year" if m == 0 else calendar.month_abbr[m].lower()
            r[f"pct_{key}"], r[f"lists_{key}"] = vals[m]
        rows.append(r)
    df = pd.DataFrame(rows).sort_values(["pct_year", "lists_year"], ascending=False)
    df.to_csv(DATA / "species_by_month.csv", index=False)

    meta = dict(source="eBird Basic Dataset, EBD_relSep-2026, Cornell Lab of Ornithology",
                window="calendar month ± half a month; 0 = whole year", months=months)
    json.dump(meta, open(DATA / "months.json", "w"), ensure_ascii=False, indent=1)
    json.dump(points, open(DATA / "points.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(df)} species; checklists per month: " + ", ".join(f"{m}:{v['checklists']}" for m, v in months.items()))
    if zoo_only:
        print("dropped (zoo only):", ", ".join(sorted(zoo_only)))


if __name__ == "__main__":
    main()
