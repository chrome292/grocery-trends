"""Check a trends.csv from pull_trends.py and show which tags are rising.

    python check_trends.py trends.csv

It checks the file's shape, then prints momentum for every tag in every
state, using the same rule as the Power BI measures: average interest over
the last 12 weeks vs. the 12 weeks before. Above +15% is Rising, below -15%
is Cooling.
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


def momentum_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per geo and tag, measured on that geo's own latest 24 weeks."""
    rows = []
    for (geo, tag), g in df.groupby(["Geo", "Tag"]):
        weeks = sorted(df[df["Geo"] == geo]["Week"].unique())
        last12, prior12 = set(weeks[-12:]), set(weeks[-24:-12])
        l12 = g[g["Week"].isin(last12)]["Interest"].mean()
        p12 = g[g["Week"].isin(prior12)]["Interest"].mean()
        mom = (l12 / p12 - 1) if p12 and pd.notna(p12) and p12 > 0 else float("nan")
        if pd.isna(mom):
            status = "No data"
        elif mom > RISING:
            status = "Rising"
        elif mom < COOLING:
            status = "Cooling"
        else:
            status = "Steady"
        rows.append({"Geo": geo, "Tag": tag, "Momentum": mom, "Status": status,
                     "Level": l12, "Noisy": bool(pd.notna(l12) and l12 < LOW_INTEREST)})
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

    def cell(r) -> str:
        if r["Status"] == "No data":
            return "no data"
        return f"{r['Momentum'] * 100:+.0f}% {r['Status']}{' *' if r['Noisy'] else ''}"

    table["Cell"] = table.apply(cell, axis=1)
    wide = table.pivot(index="Tag", columns="Geo", values="Cell").fillna("missing")
    print("\nMomentum, last 12 weeks vs. the 12 before:\n")
    print(wide.to_string())
    if table["Noisy"].any():
        print(f"\n* average interest under {LOW_INTEREST} in the last 12 weeks: "
              "too little search volume to trust the momentum figure.")
    print("\nA Rising tag is not always a trend. Seasonal items (bone broth, for one) "
          "rise every fall; compare them with the same weeks last year.")


if __name__ == "__main__":
    main()
