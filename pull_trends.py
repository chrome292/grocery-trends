"""Get Google Trends data into the shape of the Trends table.

Writes trends.csv with the columns Week, Tag, Interest, Geo.

Route A, automatic pull (needs: pip install pytrends pandas):
    python pull_trends.py --tags tags.txt --geo US-MD

Route B, convert CSVs downloaded from trends.google.com (needs: pip install pandas):
    python pull_trends.py --from-csv exports_folder --geo US-MD

Several regions in one run (each is scaled on its own, as Google does):
    python pull_trends.py --tags tags.txt --geo US-MD,US-VA,US-DC,US-NC,US-WV
    python pull_trends.py --from-csv exports_folder --geo US-MD,US-VA,US-DC,US-NC,US-WV
For the second form, put each region's CSVs in exports_folder/US-MD, exports_folder/US-VA, ...

Why there is an anchor term
---------------------------
Google compares at most 5 terms at once and scales each comparison to its
own 0-100 range, so a 60 in one batch is not a 60 in another. To fix that,
one anchor term goes into every batch. Each batch is then rescaled so its
anchor line matches the first batch's anchor line. After that every tag is
on one scale and can be compared.

Sharper trends for small tags
-----------------------------
In a comparison, Google rounds every value to a whole number on a scale set
by the most searched term, so a small tag is squeezed into values like 0, 1
and 2 and its trend is lost. Pulled on its own, the same tag uses the full
0 to 100 range. Add --solo to the live pull to fetch each tag alone as well.
For manual exports, also download each tag by itself (one term, no
comparison) into the same folder, with the SAME location and the SAME
"Past 5 years" range as the comparison exports; single-term files are
detected automatically, and one with a shorter range is ignored. The solo pull supplies the shape, the comparison the size.

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
              keep_partial: bool = False, solo: bool = False) -> list[pd.DataFrame]:
    """Pull the comparison batches, and with solo=True each tag on its own as well."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        sys.exit("pytrends is not installed. Run: pip install pytrends   (or use --from-csv)")

    client = TrendReq(hl="en-US", tz=300)
    groups = batches(tags, anchor)
    labels = [f"Batch {n} of {len(groups)}" for n in range(1, len(groups) + 1)]
    if solo:
        groups += [[t] for t in tags]
        labels += [f"Solo {n} of {len(tags)}" for n in range(1, len(tags) + 1)]

    frames = []
    solo_blocked = []
    for label, group in zip(labels, groups):
        is_solo = solo and len(group) == 1 and label.startswith("Solo")
        if solo_blocked and is_solo:
            solo_blocked.append(group[0])  # Google is refusing; don't keep hammering it
            continue
        print(f"{label}: {', '.join(group)}")
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
            if is_solo:
                # The comparison batches are already in hand; don't throw them away.
                solo_blocked.append(group[0])
                continue
            sys.exit(
                "Google keeps refusing the request (often HTTP 429).\n"
                "Use Route B: download the CSVs by hand and run with --from-csv."
            )
        if df.empty:
            if len(group) == 1:
                # Google returns nothing at all for a term with too few searches.
                print(f"  no data for '{group[0]}' on its own; keeping its comparison values")
                time.sleep(pause)
                continue
            sys.exit(f"Google returned no data for: {', '.join(group)}")
        if keep_partial:
            df = df.drop(columns=[c for c in df.columns if c == "isPartial"])
        else:
            df = drop_flagged_partial(df)
        df.index.name = "Week"
        frames.append(df.astype(float))
        time.sleep(pause)
    if solo_blocked:
        print(f"  Google refused the solo pulls for: {', '.join(solo_blocked)}.\n"
              "  Those tags keep their comparison values. Rerun later with --solo to sharpen them.")
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
    # "kombucha: (Maryland)" -> "kombucha"; remember the place to catch misfiled exports
    places = {m.group(1).strip() for c in df.columns if (m := re.search(r":\s*\((.*)\)\s*$", str(c)))}
    df.columns = [re.sub(r":\s*\(.*\)\s*$", "", str(c)).strip() for c in df.columns]
    df.attrs["places"] = places
    if df.index.has_duplicates:
        raise ValueError("the same date appears more than once")
    # Google writes "<1" for tiny values
    df = df.replace({"<1": 0.5}).apply(pd.to_numeric, errors="coerce")
    return df.dropna(how="all")


def drop_partial(df: pd.DataFrame, today: date) -> pd.DataFrame:  # today = the download date
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
    seen_places: dict[str, str] = {}
    for f in files:
        try:
            df = read_export(f)
        except Exception as err:
            sys.exit(f"Could not read {f.name}: {err}")
        for place in df.attrs.get("places", ()):
            seen_places.setdefault(place, f.name)
        if not keep_partial:
            # Judge "complete" by when the file was downloaded, not by today.
            downloaded = date.fromtimestamp(f.stat().st_mtime)
            trimmed = drop_partial(df, downloaded)
            if len(trimmed) < len(df):
                print(f"  dropped the week of {df.index[-1].date()}: it is not complete yet")
            df = trimmed
        print(f"Read {f.name}: {', '.join(df.columns)} ({len(df)} rows)")
        frames.append(df)
    if len(seen_places) > 1:
        detail = "; ".join(f"{place} (e.g. {name})" for place, name in sorted(seen_places.items()))
        sys.exit(f"The files in {folder} are for more than one place: {detail}.\n"
                 "Each region needs its own folder. Move the files that do not belong.")
    return frames


# ---------- Shared: put every batch on one scale ----------

def find_column(df: pd.DataFrame, name: str) -> str | None:
    return next((c for c in df.columns if c.lower() == name.lower()), None)


def usable(mean: float) -> bool:
    return pd.notna(mean) and mean > 0


def split_solos(frames: list[pd.DataFrame], anchor: str) -> tuple[list[pd.DataFrame], dict[str, pd.Series]]:
    """Separate comparison batches (several terms) from solo pulls (one term)."""
    batch_frames = [f for f in frames if len(f.columns) > 1]
    singles = [f for f in frames if len(f.columns) == 1]
    if not batch_frames and len(singles) == 1 and singles[0].columns[0].lower() == anchor.lower():
        return singles, {}  # a tags file with only the anchor in it
    solos = {f.columns[0].lower(): f.iloc[:, 0] for f in singles}
    if not batch_frames:
        sys.exit("Only single-term files were found. Comparison exports "
                 "(the anchor plus up to 4 tags) are needed to size the tags against each other.")
    return batch_frames, solos


def apply_solos(combined: pd.DataFrame, solos: dict[str, pd.Series]) -> pd.DataFrame:
    """Swap in each tag's solo shape, keeping its size from the comparison.

    In a comparison, Google rounds to whole numbers on a scale set by the
    most searched term, so a small tag is squeezed into a few values like
    0, 1 and 2. Pulled on its own, the same tag uses the full 0 to 100
    range. So the solo pull gives the shape over time, and the comparison
    gives how big the tag is next to the others.
    """
    combined = combined.copy()
    for col in combined.columns:
        solo = solos.get(col.lower())
        if solo is None:
            continue
        solo = solo.dropna()
        missing = combined.index.difference(solo.index)
        if len(missing):
            # Reindexing would blank those weeks and silently delete history
            # (a solo export left on "Past 12 months" loses the year-ago weeks).
            print(f"  '{col}': solo data covers {len(solo)} weeks but the comparison has "
                  f"{len(combined)}; solo shape NOT used. Download it with the same "
                  "location and time range as the comparison exports.")
            continue
        shared = combined.index
        level, solo_mean = combined.loc[shared, col].mean(), solo[shared].mean()
        if not usable(solo_mean):
            continue
        if not usable(level):
            print(f"  '{col}' is zero in every comparison week, so its size is unknown; left at zero")
            continue
        combined[col] = solo.reindex(combined.index) * (level / solo_mean)
        print(f"  '{col}': solo shape used")
    return combined


def stitch(frames: list[pd.DataFrame], anchor: str, weeks: int = 0,
           solos: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    """Rescale each batch so its anchor matches the first batch's anchor.

    Then swaps in solo shapes where given, keeps the latest `weeks` weeks
    (0 keeps all), and sets the largest value that is left to 100.
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
    if solos:
        combined = apply_solos(combined, solos)
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
    # Four decimals: on a scale where the biggest tag is 100, one decimal
    # would squeeze a small tag back into a handful of values.
    long["Interest"] = long["Interest"].round(4)
    long["Geo"] = geo
    return long[["Week", "Tag", "Interest", "Geo"]]


def run_one(args, geo: str, folder: str | None) -> pd.DataFrame:
    """Build the long table for one region."""
    if folder:
        frames = read_folder(folder, args.keep_partial)
        anchor = args.anchor
        if not anchor:
            # Use the first tag from the tags file if there is one, else the first exported term.
            multi = [f for f in frames if len(f.columns) > 1] or frames
            anchor = read_tags(args.tags)[0] if Path(args.tags).exists() else multi[0].columns[0]
    else:
        tags = read_tags(args.tags)
        anchor = args.anchor or tags[0]
        frames = pull_live(tags, anchor, geo, args.timeframe, args.pause, args.keep_partial, args.solo)
    print(f"Anchor term: {anchor}")
    batch_frames, solos = split_solos(frames, anchor)
    return to_long(stitch(batch_frames, anchor, args.weeks, solos), geo)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build trends.csv for the trend radar.")
    ap.add_argument("--tags", default="tags.txt", help="file of search terms, one per line")
    ap.add_argument("--from-csv", metavar="FOLDER",
                    help="convert CSVs downloaded from Google Trends. With several regions, "
                         "put each region's CSVs in a subfolder named after its code (FOLDER/US-MD, ...)")
    ap.add_argument("--geo", default="US-MD",
                    help="region code, or several separated by commas: US-MD,US-VA,US-DC,US-NC,US-WV")
    ap.add_argument("--anchor", help="term present in every batch (default: first line of the tags file)")
    ap.add_argument("--timeframe", default="today 5-y", help="live pull only; 5 years gives weekly points")
    ap.add_argument("--weeks", type=int, default=104, help="keep the latest N weeks (0 keeps all)")
    ap.add_argument("--pause", type=float, default=5.0, help="live pull only; seconds between requests")
    ap.add_argument("--solo", action="store_true",
                    help="live pull only; also pull each tag on its own for a sharper trend shape "
                         "(one extra request per tag, so Google is more likely to block the run)")
    ap.add_argument("--keep-partial", action="store_true",
                    help="keep the newest week even if it is not complete yet")
    ap.add_argument("--out", default="trends.csv")
    args = ap.parse_args()

    geos = [g.strip().upper() for g in args.geo.split(",") if g.strip()]
    if not geos:
        sys.exit("--geo is empty")

    results, failed = [], []
    for geo in geos:
        folder = None
        if args.from_csv:
            folder = args.from_csv if len(geos) == 1 else str(Path(args.from_csv) / geo)
        if len(geos) > 1:
            print(f"\n=== {geo} ===")
        try:
            results.append(run_one(args, geo, folder))
        except (SystemExit, Exception) as stop:
            if len(geos) == 1:
                raise
            # One region failing should not throw away the others.
            print(f"{geo} failed: {stop}")
            failed.append(geo)

    if not results:
        sys.exit("No region produced any data.")
    result = pd.concat(results, ignore_index=True)
    result.to_csv(args.out, index=False)
    print(f"\nWrote {args.out}: {result['Geo'].nunique()} region(s), {result['Tag'].nunique()} tags, "
          f"{result['Week'].nunique()} weeks, {len(result):,} rows")
    if failed:
        sys.exit(f"These regions are missing from the file: {', '.join(failed)}")


if __name__ == "__main__":
    main()
