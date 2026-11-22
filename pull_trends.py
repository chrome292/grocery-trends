"""Get Google Trends data into the shape of the Trends table.

Writes trends.csv with the columns Week, Tag, Interest, Geo.

Route A, automatic pull (needs: pip install pytrends pandas):
    python pull_trends.py --tags tags.txt --geo US-MD

Route B, convert CSVs downloaded from trends.google.com (needs: pip install pandas):
    python pull_trends.py --from-csv exports_folder --geo US-MD

Why there is an anchor term
---------------------------
Google compares at most 5 terms at once and scales each comparison to its
own 0-100 range, so a 60 in one batch is not a 60 in another. To fix that,
one anchor term goes into every batch. Each batch is then rescaled so its
anchor line matches the first batch's anchor line. After that every tag is
on one scale and can be compared.

The newest week is dropped when it is not complete yet, because a part
week reads low and pulls momentum down. Pass --keep-partial to keep it.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

BATCH_SIZE = 4  # tags per batch, plus the anchor = Google's limit of 5
ATTEMPTS = 5    # tries per batch before giving up on the live pull


def read_tags(path: str) -> list[str]:
    tags = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.lower() not in [t.lower() for t in tags]:
            tags.append(line)
    if not tags:
        sys.exit(f"No tags found in {path}")
    return tags


def batches(tags: list[str], anchor: str) -> list[list[str]]:
    rest = [t for t in tags if t.lower() != anchor.lower()]
    return [[anchor] + rest[i:i + BATCH_SIZE] for i in range(0, max(len(rest), 1), BATCH_SIZE)]


# ---------- Route A: pytrends ----------

def drop_flagged_partial(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the rows pytrends flags as an incomplete period, then the flag column."""
    if "isPartial" in df.columns:
        partial = df["isPartial"].astype(str).str.lower() == "true"
        df = df[~partial].drop(columns="isPartial")
    return df


def pull_live(tags: list[str], anchor: str, geo: str, timeframe: str, pause: float,
              keep_partial: bool = False) -> list[pd.DataFrame]:
    try:
        from pytrends.request import TrendReq
    except ImportError:
        sys.exit("pytrends is not installed. Run: pip install pytrends   (or use --from-csv)")

    client = TrendReq(hl="en-US", tz=300)
    frames = []
    groups = batches(tags, anchor)
    for n, group in enumerate(groups, start=1):
        print(f"Batch {n} of {len(groups)}: {', '.join(group)}")
        for attempt in range(1, ATTEMPTS + 1):
            try:
                client.build_payload(group, timeframe=timeframe, geo=geo)
                df = client.interest_over_time()
                break
            except Exception as err:  # pytrends raises several types when Google blocks it
                if attempt == ATTEMPTS:
                    print(f"  attempt {attempt} failed ({err})")
                    continue  # no point waiting when there is no next try
                wait = max(pause, 2.0) * 2 ** attempt
                print(f"  attempt {attempt} failed ({err}); waiting {wait:.0f}s")
                time.sleep(wait)
        else:
            sys.exit(
                "Google keeps refusing the request (often HTTP 429).\n"
                "Use Route B: download the CSVs by hand and run with --from-csv."
            )
        if df.empty:
            sys.exit(f"Google returned no data for: {', '.join(group)}")
        if keep_partial:
            df = df.drop(columns=[c for c in df.columns if c == "isPartial"])
        else:
            df = drop_flagged_partial(df)
        df.index.name = "Week"
        frames.append(df.astype(float))
        time.sleep(pause)
    return frames


# ---------- Route B: manual exports ----------

def read_export(path: Path) -> pd.DataFrame:
    """Read one 'Interest over time' CSV downloaded from trends.google.com."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next(
        (i for i, line in enumerate(lines)
         if re.match(r"^\"?(week|day|month|time|date)\"?,", line.strip(), re.I)),
        None,
    )
    if start is None:
        raise ValueError("no header row starting with Week, Day, Month or Time")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df = df.rename(columns={df.columns[0]: "Week"})
    df["Week"] = pd.to_datetime(df["Week"])
    df = df.set_index("Week")
    # "kombucha: (Maryland)" -> "kombucha"
    df.columns = [re.sub(r":\s*\(.*\)\s*$", "", str(c)).strip() for c in df.columns]
    # Google writes "<1" for tiny values
    df = df.replace({"<1": 0.5}).apply(pd.to_numeric, errors="coerce")
    return df.dropna(how="all")


def drop_partial(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Drop the last week if it had not finished when the file was downloaded.

    A week that started less than 7 days ago holds only part of a week's
    searches, and a low last week drags momentum down.
    """
    if len(df) and (pd.Timestamp(today) - df.index[-1]).days < 7:
        return df.iloc[:-1]
    return df


def read_folder(folder: str, keep_partial: bool = False) -> list[pd.DataFrame]:
    files = sorted(Path(folder).glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files found in {folder}")
    frames = []
    for f in files:
        try:
            df = read_export(f)
        except Exception as err:
            sys.exit(f"Could not read {f.name}: {err}")
        if not keep_partial:
            trimmed = drop_partial(df, date.today())
            if len(trimmed) < len(df):
                print(f"  dropped the week of {df.index[-1].date()}: it is not complete yet")
            df = trimmed
        print(f"Read {f.name}: {', '.join(df.columns)} ({len(df)} rows)")
        frames.append(df)
    return frames


# ---------- Shared: put every batch on one scale ----------

def find_column(df: pd.DataFrame, name: str) -> str | None:
    return next((c for c in df.columns if c.lower() == name.lower()), None)


def usable(mean: float) -> bool:
    return pd.notna(mean) and mean > 0


def stitch(frames: list[pd.DataFrame], anchor: str, weeks: int = 0) -> pd.DataFrame:
    """Rescale each batch so its anchor matches the first batch's anchor.

    Keeps the latest `weeks` weeks (0 keeps all), then sets the largest
    value that is left to 100.
    """
    for i, df in enumerate(frames, start=1):
        if find_column(df, anchor) is None:
            sys.exit(
                f"Batch {i} has no '{anchor}' column (it has: {', '.join(df.columns)}).\n"
                "The anchor term must be in every batch. Add it, or pass --anchor."
            )
    base = frames[0]
    base_anchor = base[find_column(base, anchor)]
    if not usable(base_anchor.mean()):
        sys.exit(f"The anchor '{anchor}' is all zeros or empty in batch 1. Pick a more popular anchor.")
    combined = base.copy()
    for i, df in enumerate(frames[1:], start=2):
        this_anchor = df[find_column(df, anchor)]
        shared = base_anchor.index.intersection(this_anchor.index)
        if len(shared) == 0:
            sys.exit(f"Batch {i} shares no dates with batch 1. Use the same time range for every batch.")
        if not usable(this_anchor[shared].mean()) or not usable(base_anchor[shared].mean()):
            sys.exit(f"The anchor '{anchor}' is all zeros or empty in batch {i}. Pick a more popular anchor.")
        factor = base_anchor[shared].mean() / this_anchor[shared].mean()
        print(f"Batch {i}: scaled by {factor:.3f} to match the anchor")
        for col in df.columns:
            if col.lower() != anchor.lower() and find_column(combined, col) is None:
                combined[col] = df[col] * factor
    combined = combined.sort_index()
    if weeks > 0:
        combined = combined.tail(weeks)
    # Final rescale so the largest value in the weeks kept is 100, like Google's own scale.
    peak = combined.max().max()
    if pd.notna(peak) and peak > 0:
        combined = combined * (100 / peak)
    return combined


def to_long(wide: pd.DataFrame, geo: str) -> pd.DataFrame:
    long = wide.reset_index().melt(id_vars="Week", var_name="Tag", value_name="Interest")
    long = long.dropna(subset=["Interest"])
    long["Week"] = pd.to_datetime(long["Week"]).dt.strftime("%Y-%m-%d")
    long["Interest"] = long["Interest"].round(1)
    long["Geo"] = geo
    return long[["Week", "Tag", "Interest", "Geo"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build trends.csv for the trend radar.")
    ap.add_argument("--tags", default="tags.txt", help="file of search terms, one per line")
    ap.add_argument("--from-csv", metavar="FOLDER", help="convert CSVs downloaded from Google Trends")
    ap.add_argument("--geo", default="US-MD", help="region code, e.g. US-MD, US-DC, US-VA, US-NC")
    ap.add_argument("--anchor", help="term present in every batch (default: first line of the tags file)")
    ap.add_argument("--timeframe", default="today 5-y", help="live pull only; 5 years gives weekly points")
    ap.add_argument("--weeks", type=int, default=104, help="keep the latest N weeks (0 keeps all)")
    ap.add_argument("--pause", type=float, default=5.0, help="live pull only; seconds between requests")
    ap.add_argument("--keep-partial", action="store_true",
                    help="keep the newest week even if it is not complete yet")
    ap.add_argument("--out", default="trends.csv")
    args = ap.parse_args()

    if args.from_csv:
        frames = read_folder(args.from_csv, args.keep_partial)
        anchor = args.anchor
        if not anchor:
            # Use the first tag from the tags file if there is one, else the first exported term.
            anchor = read_tags(args.tags)[0] if Path(args.tags).exists() else frames[0].columns[0]
    else:
        tags = read_tags(args.tags)
        anchor = args.anchor or tags[0]
        frames = pull_live(tags, anchor, args.geo, args.timeframe, args.pause, args.keep_partial)

    print(f"Anchor term: {anchor}")
    result = to_long(stitch(frames, anchor, args.weeks), args.geo)
    result.to_csv(args.out, index=False)
    print(f"Wrote {args.out}: {result['Tag'].nunique()} tags, "
          f"{result['Week'].nunique()} weeks, {len(result):,} rows")


if __name__ == "__main__":
    main()
