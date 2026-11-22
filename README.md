# Natural Food Trend Radar: starter kit

A Power BI starter kit that answers one sales question: **which ingredients
are heating up in local search, and which of my stores aren't carrying them
yet?**

The full walkthrough is in the
[build guide](https://claude.ai/artifact/KM5MDBAtkbURzWBPStHza8). It goes
from loading the data to a four-page report: the radar chart, a page that
checks whether searches lead sales, store readiness, and a pitch list.

## Files

| File | What it is |
| --- | --- |
| `trend_radar_sample_data.xlsx` | Six tables Power BI loads by name (Tags, Trends, Products, Stores, Sales, Weeks), plus a README sheet. **All of it is made up**, including the stores, brands and trend curves. |
| `make_sample_data.py` | Rebuilds the sample workbook. Seeded, so it gives the same file each time. |
| `pull_trends.py` | Pulls real Google Trends data, or converts CSVs downloaded from the Google Trends site, into the Trends table shape. |
| `tags.txt` | The search terms the script pulls, one per line. The first one is the anchor. |
| `trend_radar_measures.dax` | Every measure, in paste order. |

## Getting real trends data

**Route A, automatic pull:**

```
pip install pytrends pandas
python pull_trends.py --tags tags.txt --geo US-MD
```

pytrends is unofficial, so Google sometimes blocks it. If it keeps failing,
use Route B.

**Route B, manual exports:** on trends.google.com, compare `kombucha` plus
up to 4 other tags, set the location and a 5-year range, and download
*Interest over time*. Repeat until every tag is covered, put the CSVs in one
folder, then:

```
pip install pandas
python pull_trends.py --from-csv <folder> --geo US-MD
```

Both routes write `trends.csv` with the columns `Week, Tag, Interest, Geo`.

Google scales each comparison to its own 0–100 range, so the anchor term
(`kombucha` by default) has to be in every batch. The script rescales each
batch until its anchor line matches the first batch's, which puts every tag
on one scale.

## What has been tested

- `make_sample_data.py` runs and prints the momentum and store distribution
  for each tag.
- The `--from-csv` mode of `pull_trends.py` was checked against exports
  built from known data: it recovered the original values to within
  rounding.
- The live pull was **not** tested, and the DAX has **not** been run inside
  Power BI.
