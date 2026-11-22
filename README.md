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
| `trend_radar_sample_data.xlsx` | Seven tables Power BI loads by name (Tags, Trends, Products, Stores, Sales, Weeks, Geos), plus a README sheet. **All of it is made up**, including the stores, brands and trend curves. |
| `make_sample_data.py` | Rebuilds the sample workbook. Seeded and timestamp-free, so it gives the identical file each time. |
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

**Several states in one run.** Give `--geo` a comma-separated list:

```
python pull_trends.py --tags tags.txt --geo US-MD,US-VA,US-DC,US-NC,US-WV
```

For manual exports, make one subfolder per state named after its code
(`exports/US-MD`, `exports/US-VA`, ...), download each state's CSVs into its
folder, and run `python pull_trends.py --from-csv exports --geo US-MD,US-VA,US-DC,US-NC,US-WV`.
If one state fails, the others are still written and the script names the
one that is missing.

Each state is scaled on its own, the way Google does it, so a 60 in
Maryland is not a 60 in West Virginia. Compare momentum across states, not
levels.

## Each store is judged against its own state

The `Geos` table has one row per search region (`Geo`, `State`,
`StateName`) and links `Trends[Geo]` to `Stores[State]`. The measures
`Momentum % (Local)` and `Momentum Status (Local)` read the state of the
store in context, so Rising Gap, Store Readiness % and Rising Gaps judge a
Virginia store on Virginia search. Use `Geos[StateName]` as the state
slicer: it filters stores and search together. With no state selected, the
plain `Momentum %` averages the states with equal weight.

When you add a state, add its row to `Geos` and pull its trends. A state
that has stores but no search data shows no Rising tags for those stores.

The sample covers Maryland, DC and Virginia. Maryland matches the build
guide's figures. DC and Virginia differ on a few tags on purpose: mushroom
coffee is Rising only in DC, prebiotic soda only in Virginia, beef tallow is
not Rising in DC, and matcha is not Rising in Virginia.

Google scales each comparison to its own 0–100 range, so the anchor term
(`kombucha` by default) has to be in every batch. The script rescales each
batch until its anchor line matches the first batch's, which puts every tag
on one scale.

The script drops the newest week when it has not finished yet, because a
part week reads low and pulls momentum down. Pass `--keep-partial` to keep
it. It keeps the latest 104 weeks (`--weeks` changes that) and sets the
largest value among them to 100.

## One thing to know about the sample

Bone broth shows as Rising (+41.7%), but that is seasonality, not a trend.
Its underlying trend is flat; the data ends in November, on the way up to a
winter peak. It is in the sample on purpose, to show how a seasonal tag
fools the momentum measure. Compare a seasonal tag against the same weeks
last year before pitching it.

## What has been tested

- `make_sample_data.py` runs, prints the momentum and store distribution
  for each tag, and gives a byte-identical workbook on a second run.
- The `--from-csv` mode of `pull_trends.py` was checked against exports
  built from known data: it recovered the original values to within
  rounding. Also checked: an unfinished last week is dropped, an all-zero
  anchor stops the script with an error and writes nothing, and the kept
  weeks peak at 100.
- The retry logic of the live pull was checked with a stand-in for Google
  that always fails. A real live pull was **not** tested.
- The DAX has **not** been run inside Power BI.
