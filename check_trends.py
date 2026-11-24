"""Check a trends.csv from pull_trends.py and show which tags are rising.

    python check_trends.py trends.csv

It checks the file's shape, then prints momentum for every tag in every
state, two ways, with the same rules as the Power BI measures:

  YoY   last 12 weeks vs. the same 12 weeks a year earlier. This is what the
        status is based on. Above +15% is Rising, below -15% is Cooling.
  12w   last 12 weeks vs. the 12 weeks just before. This moves with the
        seasons, so read it as "what changed lately", not as the trend.

The status falls back to the 12-week figure when there is no usable
year-ago period: less than 64 weeks of data, or a year-ago average of zero.
The Power BI measure [Trend Change %] applies the same rule.
"""

from __future__ import annotations

import sys
from datetime import date

import pandas as pd

COLUMNS = ["Week", "Tag", "Interest", "Geo"]
RISING, COOLING = 0.15, -0.15
# A tag is flagged when its recent values are too coarse to read a trend
# from: mostly zeros, or only a few distinct values (Google's whole-number
# rounding). Size alone is not the problem, so a small tag pulled with
# --solo is not flagged.
MAX_ZERO_SHARE = 0.25
MIN_DISTINCT = 6


def load(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        sys.exit(f"Cannot find {path}. Run this from the folder that holds it, or give the full path.")
    except pd.errors.EmptyDataError:
        sys.exit(f"{path} is empty.")
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        sys.exit(f"{path} is missing the column(s): {', '.join(missing)}")
    df["Week"] = pd.to_datetime(df["Week"])
    df["Interest"] = pd.to_numeric(df["Interest"], errors="coerce")
    if df.empty:
        sys.exit(f"{path} has a header but no rows.")
    return df


def shape_problems(df: pd.DataFrame, today: date) -> list[str]:
    problems = []
    if df["Interest"].isna().any():
        problems.append(f"{int(df['Interest'].isna().sum())} rows have no Interest value")
    not_sunday = df[df["Week"].dt.dayofweek != 6]["Week"].nunique()
    if not_sunday:
        problems.append(f"{not_sunday} week(s) do not start on a Sunday; Google Trends weeks do")
    newest = df["Week"].max()
    if (pd.Timestamp(today) - newest).days < 7:
        problems.append(f"the newest week ({newest.date()}) is not complete yet and will read low")
    dupes = int(df.duplicated(["Week", "Tag", "Geo"]).sum())
    if dupes:
        problems.append(f"{dupes} duplicate Week/Tag/Geo rows")
    all_tags = set(df["Tag"])
    for geo, g in df.groupby("Geo"):
        lacking = sorted(all_tags - set(g["Tag"]))
        if lacking:
            problems.append(f"{geo} has no data for: {', '.join(lacking)}")
        weeks = g.groupby("Tag")["Week"].nunique()
        if weeks.min() < 24:
            problems.append(f"{geo} has fewer than 24 weeks for some tags; momentum needs 24")
        elif weeks.nunique() > 1:
            problems.append(f"{geo}: tags have different numbers of weeks ({weeks.min()} to {weeks.max()})")
    return problems


def change(now: float, before: float) -> float:
    return (now / before - 1) if pd.notna(before) and before > 0 and pd.notna(now) else float("nan")


def momentum_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per geo and tag, measured on that geo's own latest weeks."""
    rows = []
    for (geo, tag), g in df.groupby(["Geo", "Tag"]):
        weeks = sorted(df[df["Geo"] == geo]["Week"].unique())
        mean = lambda ws: g[g["Week"].isin(set(ws))]["Interest"].mean() if len(ws) else float("nan")
        l12, p12 = mean(weeks[-12:]), mean(weeks[-24:-12])
        ly12 = mean(weeks[-64:-52]) if len(weeks) >= 64 else float("nan")
        mom, yoy = change(l12, p12), change(l12, ly12)
        basis = yoy if pd.notna(yoy) else mom
        if pd.isna(basis):
            status = "No data"
        elif basis > RISING:
            status = "Rising"
        elif basis < COOLING:
            status = "Cooling"
        else:
            status = "Steady"
        recent = g[g["Week"].isin(set(weeks[-24:]))]["Interest"]
        coarse = bool(len(recent) == 0 or (recent == 0).mean() > MAX_ZERO_SHARE
                      or recent.round(4).nunique() < MIN_DISTINCT)
        rows.append({"Geo": geo, "Tag": tag, "Momentum": mom, "YoY": yoy, "Status": status,
                     "Level": l12, "Noisy": coarse})
    return pd.DataFrame(rows)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python check_trends.py trends.csv")
    df = load(sys.argv[1])
    geos = sorted(df["Geo"].unique())
    print(f"{len(df):,} rows: {len(geos)} region(s) ({', '.join(geos)}), "
          f"{df['Tag'].nunique()} tags, weeks {df['Week'].min().date()} to {df['Week'].max().date()}")

    problems = shape_problems(df, date.today())
    print("\nShape check: " + ("no problems" if not problems else ""))
    for p in problems:
        print(f"  - {p}")

    table = momentum_table(df)

    def pct(x: float) -> str:
        return "n/a" if pd.isna(x) else f"{round(x * 100) + 0:+d}%"

    def cell(r) -> str:
        if r["Status"] == "No data":
            return "no data"
        return f"{r['Status']}{'*' if r['Noisy'] else ''} (YoY {pct(r['YoY'])}, 12w {pct(r['Momentum'])})"

    table["Cell"] = table.apply(cell, axis=1)
    print("\nStatus by state. YoY = vs. the same 12 weeks a year earlier; "
          "12w = vs. the 12 weeks just before.")
    for geo in geos:
        g = table[table["Geo"] == geo].sort_values("YoY", ascending=False, na_position="last")
        print(f"\n{geo}")
        for _, r in g.iterrows():
            print(f"  {r['Tag']:<22}{r['Cell']}")
    if table["Noisy"].any():
        print("\n* too coarse to trust: in the last 24 weeks this tag is mostly zeros or takes only a "
              "few distinct values.\n  If you have not pulled with --solo, do that first. If it is "
              "still starred, the area has too few searches:\n  try a broader term or a larger region.")
    if table["YoY"].isna().all():
        print("\nNo year-ago period in this file (it needs 64 weeks), so the status uses the "
              "12-week figure, which moves with the seasons.")


if __name__ == "__main__":
    main()
