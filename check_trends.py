"""Check a trends.csv from pull_trends.py and show which tags are rising.

    python check_trends.py trends.csv

It checks the file's shape, then prints momentum for every tag in every
state, two ways, with the same rules as the Power BI measures:

  YoY   last 12 weeks vs. the same 12 weeks a year earlier. This is what the
        status is based on. Above +15% is Rising, below -15% is Cooling.
  12w   last 12 weeks vs. the 12 weeks just before. This moves with the
        seasons, so read it as "what changed lately", not as the trend.

With less than 64 weeks of data there is no year-ago period, and the status
falls back to the 12-week figure.
"""

from __future__ import annotations

import sys
from datetime import date

import pandas as pd

COLUMNS = ["Week", "Tag", "Interest", "Geo"]
RISING, COOLING = 0.15, -0.15
LOW_INTEREST = 10  # below this, week-to-week noise swamps the trend


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        sys.exit(f"{path} is missing the column(s): {', '.join(missing)}")
    df["Week"] = pd.to_datetime(df["Week"])
    df["Interest"] = pd.to_numeric(df["Interest"], errors="coerce")
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
        rows.append({"Geo": geo, "Tag": tag, "Momentum": mom, "YoY": yoy, "Status": status,
                     "Level": l12, "Noisy": bool(pd.isna(l12) or l12 < LOW_INTEREST)})
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
        print(f"\n* average interest under {LOW_INTEREST} in the last 12 weeks: too little search "
              "volume to trust. Pull again with --solo, try a broader term, or a larger region.")
    if table["YoY"].isna().all():
        print("\nNo year-ago period in this file (it needs 64 weeks), so the status uses the "
              "12-week figure, which moves with the seasons.")


if __name__ == "__main__":
    main()
