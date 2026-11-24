"""Checks for pull_trends.py and check_trends.py on exports with a known answer.

    python tests/test_kit.py        (or: pytest tests)

Nothing here touches Google. The exports are built the way Google builds
them: each file on its own 0 to 100 scale, rounded to whole numbers.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import check_trends  # noqa: E402
import pull_trends  # noqa: E402

WEEKS = pd.date_range("2024-11-24", periods=104, freq="7D")
OLD = (date.today() - timedelta(days=30)).toordinal()  # exports "downloaded" long ago


def truth() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    t = np.arange(104)
    return pd.DataFrame({
        "kombucha": 12 + rng.normal(0, .6, 104),
        "matcha": 60 + 8 * np.sin(t / 9) + rng.normal(0, 2, 104),
        "colostrum": 4 * np.exp(0.006 * t) + rng.normal(0, .2, 104),
        "tiny": 0.5 * np.exp(0.007 * t) + rng.normal(0, .03, 104),
        "sea moss": 9 + rng.normal(0, .5, 104),
    }, index=WEEKS).clip(lower=0.05)


def export(path: Path, df: pd.DataFrame, place: str = "Maryland") -> None:
    scaled = (df * 100 / df.max().max()).round(0).astype(int)
    scaled.columns = [f"{c}: ({place})" for c in scaled.columns]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("Category: All categories\n\n")
        scaled.to_csv(f, index_label="Week")


def write_set(folder: Path, solo_weeks: int | None = 104, place: str = "Maryland") -> None:
    tr = truth()
    export(folder / "batch.csv", tr, place)
    if solo_weeks:
        for c in tr.columns:
            export(folder / f"solo_{c.replace(' ', '_')}.csv", tr[[c]].tail(solo_weeks), place)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "pull_trends.py"), *args],
                          capture_output=True, text=True)


def yoy(series: pd.Series) -> float:
    return series.iloc[-12:].mean() / series.iloc[-64:-52].mean() - 1


def wide(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["Week"]).pivot(index="Week", columns="Tag", values="Interest")


def test_solo_recovers_a_tiny_tag():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_set(d / "x")
        r = run("--from-csv", str(d / "x"), "--anchor", "kombucha", "--out", str(d / "o.csv"))
        assert r.returncode == 0, r.stdout + r.stderr
        out = wide(d / "o.csv")
        assert len(out) == 104
        assert abs(yoy(out["tiny"]) - yoy(truth()["tiny"])) < 0.05
        assert out["tiny"].round(4).nunique() > 20      # not squeezed back into a few values
        assert abs(out.max().max() - 100) < 1e-6


def test_short_solo_is_ignored_not_truncating():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_set(d / "x", solo_weeks=52)
        r = run("--from-csv", str(d / "x"), "--anchor", "kombucha", "--out", str(d / "o.csv"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "solo shape NOT used" in r.stdout
        assert wide(d / "o.csv").notna().all().all() and len(wide(d / "o.csv")) == 104


def test_wrong_region_file_stops_the_region():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_set(d / "x", solo_weeks=None)
        export(d / "x" / "other.csv", truth()[["kombucha", "sea moss"]], "Virginia")
        r = run("--from-csv", str(d / "x"), "--anchor", "kombucha", "--out", str(d / "o.csv"))
        assert r.returncode != 0 and "more than one place" in r.stderr
        assert not (d / "o.csv").exists()


def test_one_bad_region_keeps_the_good_one():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_set(d / "x" / "US-MD", solo_weeks=None)
        write_set(d / "x" / "US-VA", solo_weeks=None, place="Virginia")
        bad = d / "x" / "US-VA" / "batch.csv"
        lines = bad.read_text().splitlines()
        bad.write_text("\n".join(lines + [lines[-1]]) + "\n")       # a repeated date row
        r = run("--from-csv", str(d / "x"), "--geo", "US-MD,US-VA", "--anchor", "kombucha",
                "--out", str(d / "o.csv"))
        assert r.returncode != 0 and "US-VA" in r.stderr
        assert set(pd.read_csv(d / "o.csv")["Geo"]) == {"US-MD"}


def test_blocked_solo_keeps_the_comparison(monkeypatch=None):
    tr = truth()

    class Client:
        def __init__(self, *a, **k): self.group = None
        def build_payload(self, group, **k): self.group = group
        def interest_over_time(self):
            if len(self.group) == 1 and self.group[0] != "kombucha":
                raise RuntimeError("429")
            df = (tr[self.group] * 100 / tr[self.group].max().max()).round(0)
            df["isPartial"] = False
            return df

    mod, req = types.ModuleType("pytrends"), types.ModuleType("pytrends.request")
    req.TrendReq = Client
    saved = {k: sys.modules.get(k) for k in ("pytrends", "pytrends.request")}
    sys.modules.update({"pytrends": mod, "pytrends.request": req})
    sleep, pull_trends.time.sleep = pull_trends.time.sleep, lambda s: None
    try:
        frames = pull_trends.pull_live(list(tr.columns), "kombucha", "US-MD", "today 5-y", 0, solo=True)
    finally:
        pull_trends.time.sleep = sleep
        for k, v in saved.items():
            sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)
    batches, solos = pull_trends.split_solos(frames, "kombucha")
    assert len(batches) == 1 and set(solos) == {"kombucha"}
    assert set(pull_trends.stitch(batches, "kombucha", 104, solos).columns) == set(tr.columns)


def test_single_tag_file_still_works():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        export(d / "x" / "only.csv", truth()[["kombucha"]])
        r = run("--from-csv", str(d / "x"), "--anchor", "kombucha", "--out", str(d / "o.csv"))
        assert r.returncode == 0, r.stdout + r.stderr


def test_checker_fallback_rule():
    idx = pd.date_range("2025-01-05", periods=104, freq="7D")
    base = pd.DataFrame({"Week": idx, "Tag": "a", "Geo": "US-MD",
                         "Interest": np.r_[np.full(92, 10.0), np.full(12, 20.0)] + np.arange(104) * 0.01})
    full = check_trends.momentum_table(base).iloc[0]
    assert full["Status"] == "Rising" and pd.notna(full["YoY"])
    short = check_trends.momentum_table(base.tail(60)).iloc[0]       # under 64 weeks: momentum
    assert pd.isna(short["YoY"]) and pd.notna(short["Momentum"])
    zero = base.copy()
    zero.loc[zero.index[40:52], "Interest"] = 0.0                    # year-ago average of zero
    z = check_trends.momentum_table(zero).iloc[0]
    assert pd.isna(z["YoY"]) and z["Status"] == "Rising"


def test_checker_flags_coarse_not_small():
    idx = pd.date_range("2025-01-05", periods=104, freq="7D")
    rng = np.random.default_rng(3)
    small = pd.DataFrame({"Week": idx, "Tag": "small", "Geo": "US-MD", "Interest": 0.5 + rng.random(104) * 0.1})
    coarse = pd.DataFrame({"Week": idx, "Tag": "coarse", "Geo": "US-MD", "Interest": rng.integers(0, 2, 104) * 1.0})
    t = check_trends.momentum_table(pd.concat([small, coarse])).set_index("Tag")
    assert not t.loc["small", "Noisy"] and t.loc["coarse", "Noisy"]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as err:  # report every test, then fail at the end
                failed += 1
                print(f"FAIL  {name}: {type(err).__name__}: {err}")
    sys.exit(1 if failed else 0)
