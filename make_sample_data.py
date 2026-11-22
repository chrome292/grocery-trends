"""Build trend_radar_sample_data.xlsx, the made-up dataset for the trend radar.

Everything here is invented: the stores, brands, sales and trend curves.
The numbers are seeded, so running this again rebuilds the same workbook.

    pip install pandas numpy openpyxl
    python make_sample_data.py
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

SEED = 29
OUT = "trend_radar_sample_data.xlsx"
LAST_WEEK = date(2026, 11, 15)  # a Sunday; Google Trends weeks start on Sunday
N_WEEKS = 104                   # weeks of search data
N_SALES_WEEKS = 52              # weeks of sales data
LAG = 3                         # sales follow search by this many weeks
N_STORES = 24

# tag: (category, typical interest, target momentum, stores carrying, seasonal swing)
# Momentum is search interest over the last 12 weeks vs. the 12 before.
TAGS = {
    "kombucha":            ("Grocery",   55,  0.00, 23, 0.00),
    "mushroom coffee":     ("Grocery",   30,  0.08, 14, 0.00),
    "colostrum":           ("Nutrition", 22,  0.23,  6, 0.00),
    "beef tallow":         ("Body Care", 26,  0.34, 11, 0.00),
    "matcha":              ("Grocery",   48,  0.18, 13, 0.00),
    "oat milk":            ("Grocery",   50, -0.19, 22, 0.00),
    "ashwagandha":         ("Nutrition", 38, -0.21, 19, 0.00),
    "bone broth":          ("Grocery",   28,  0.00, 16, 0.28),
    "sea moss":            ("Nutrition", 18, -0.06,  9, 0.00),
    "electrolyte powder":  ("Nutrition", 34,  0.05, 17, 0.00),
    "magnesium glycinate": ("Nutrition", 36,  0.10, 15, 0.00),
    "collagen peptides":   ("Nutrition", 32, -0.04, 18, 0.00),
    "prebiotic soda":      ("Grocery",   24,  0.11, 16, 0.00),
}

# SKU, product, brand, tag, unit price, popularity (typical weekly units)
PRODUCTS = [
    ("KB-01", "Ginger Lemon Kombucha 16oz", "Tidewater Ferments", "kombucha", 3.99, 9),
    ("KB-02", "Hibiscus Kombucha 16oz", "Tidewater Ferments", "kombucha", 3.99, 7),
    ("KB-03", "Original Kombucha 48oz", "Bay Culture", "kombucha", 8.49, 4),
    ("MC-01", "Lion's Mane Mushroom Coffee 12ct", "Morning Mycelium", "mushroom coffee", 16.99, 4),
    ("MC-02", "Chaga Mushroom Coffee Ground 10oz", "Morning Mycelium", "mushroom coffee", 14.99, 3),
    ("MC-03", "Mushroom Coffee Instant Sticks 20ct", "Forager's Cup", "mushroom coffee", 21.99, 3),
    ("CO-01", "Colostrum Powder 30 Servings", "First Pasture", "colostrum", 39.99, 5),
    ("CO-02", "Colostrum Capsules 120ct", "First Pasture", "colostrum", 34.99, 3),
    ("BT-01", "Whipped Beef Tallow Balm 2oz", "Hearth & Hide", "beef tallow", 18.99, 5),
    ("BT-02", "Beef Tallow Face Cream 1.7oz", "Hearth & Hide", "beef tallow", 24.99, 3),
    ("BT-03", "Grass-Fed Beef Tallow Cooking Fat 14oz", "Old Line Provisions", "beef tallow", 12.99, 4),
    ("MA-01", "Ceremonial Matcha Tin 30g", "Green Ridge Tea", "matcha", 24.99, 5),
    ("MA-02", "Matcha Latte Mix 8oz", "Green Ridge Tea", "matcha", 13.99, 6),
    ("MA-03", "Sparkling Matcha 12oz", "Still Pond", "matcha", 3.49, 7),
    ("OM-01", "Barista Oat Milk 32oz", "Oat & Anchor", "oat milk", 4.99, 9),
    ("OM-02", "Unsweetened Oat Milk 64oz", "Oat & Anchor", "oat milk", 5.49, 8),
    ("OM-03", "Chocolate Oat Milk 32oz", "Plain Grain", "oat milk", 4.79, 5),
    ("AS-01", "Ashwagandha Capsules 60ct", "Root & Rest", "ashwagandha", 19.99, 5),
    ("AS-02", "Ashwagandha Gummies 60ct", "Root & Rest", "ashwagandha", 17.99, 4),
    ("BB-01", "Chicken Bone Broth 32oz", "Simmer House", "bone broth", 7.99, 6),
    ("BB-02", "Beef Bone Broth 32oz", "Simmer House", "bone broth", 8.49, 5),
    ("BB-03", "Bone Broth Powder 20 Servings", "Stockpot Naturals", "bone broth", 29.99, 3),
    ("SM-01", "Sea Moss Gel 16oz", "Atlantic Bloom", "sea moss", 22.99, 3),
    ("SM-02", "Sea Moss Capsules 90ct", "Atlantic Bloom", "sea moss", 18.99, 3),
    ("EL-01", "Electrolyte Powder Citrus 30ct", "Salt Line", "electrolyte powder", 23.99, 6),
    ("EL-02", "Electrolyte Powder Berry 30ct", "Salt Line", "electrolyte powder", 23.99, 5),
    ("MG-01", "Magnesium Glycinate 120ct", "Calm Harbor", "magnesium glycinate", 21.99, 6),
    ("MG-02", "Magnesium Glycinate Powder 8oz", "Calm Harbor", "magnesium glycinate", 26.99, 3),
    ("CP-01", "Collagen Peptides Unflavored 10oz", "Kindred Wellness", "collagen peptides", 27.99, 5),
    ("CP-02", "Collagen Peptides Vanilla 10oz", "Kindred Wellness", "collagen peptides", 29.99, 4),
    ("PS-01", "Prebiotic Soda Cherry Cola 12oz", "Fizz & Fiber", "prebiotic soda", 2.49, 9),
    ("PS-02", "Prebiotic Soda Lemon Lime 12oz", "Fizz & Fiber", "prebiotic soda", 2.49, 8),
    ("PS-03", "Prebiotic Soda Variety 8pk", "Fizz & Fiber", "prebiotic soda", 15.99, 4),
]

# store, type, size tier, city, state
STORES = [
    ("Chesapeake Community Co-op", "Co-op", "Large", "Annapolis", "MD"),
    ("Patapsco Natural Market", "Independent Natural", "Medium", "Ellicott City", "MD"),
    ("Federal Hill Greens", "Independent Natural", "Small", "Baltimore", "MD"),
    ("Hampden Whole Pantry", "Independent Natural", "Medium", "Baltimore", "MD"),
    ("Towson Vitamin Cottage", "Vitamin Shop", "Small", "Towson", "MD"),
    ("Frederick Farmstead Market", "Independent Natural", "Large", "Frederick", "MD"),
    ("Columbia Harvest Co-op", "Co-op", "Large", "Columbia", "MD"),
    ("Silver Spring Roots Market", "Regional Chain", "Large", "Silver Spring", "MD"),
    ("Bethesda Roots Market", "Regional Chain", "Large", "Bethesda", "MD"),
    ("Rockville Roots Market", "Regional Chain", "Medium", "Rockville", "MD"),
    ("Salisbury Shore Naturals", "Independent Natural", "Small", "Salisbury", "MD"),
    ("Bel Air Wellness Corner", "Vitamin Shop", "Small", "Bel Air", "MD"),
    ("Hagerstown Good Earth", "Independent Natural", "Medium", "Hagerstown", "MD"),
    ("Takoma Commons Co-op", "Co-op", "Medium", "Takoma Park", "MD"),
    ("Capitol Hill Provisions", "Independent Natural", "Medium", "Washington", "DC"),
    ("Petworth Pantry", "Independent Natural", "Small", "Washington", "DC"),
    ("Dupont Vitamin Bar", "Vitamin Shop", "Small", "Washington", "DC"),
    ("Georgetown Roots Market", "Regional Chain", "Large", "Washington", "DC"),
    ("Arlington Roots Market", "Regional Chain", "Large", "Arlington", "VA"),
    ("Old Town Natural Grocer", "Independent Natural", "Medium", "Alexandria", "VA"),
    ("Fairfax Family Co-op", "Co-op", "Medium", "Fairfax", "VA"),
    ("Reston Wellness Market", "Independent Natural", "Medium", "Reston", "VA"),
    ("Leesburg Vitamin Depot", "Vitamin Shop", "Small", "Leesburg", "VA"),
    ("Falls Church Green Basket", "Independent Natural", "Small", "Falls Church", "VA"),
]

SIZE_SCALE = {"Small": 0.6, "Medium": 1.0, "Large": 1.6}

README = [
    "Natural Food Trend Radar: sample data",
    "",
    "ALL OF THIS DATA IS MADE UP. The stores, brands, products, sales and",
    "trend curves are invented so you can build and test the report before",
    "you have real data. Do not quote any number here as a real figure.",
    "",
    "Six tables, one per sheet. In Power BI, load the tables (not the sheets):",
    "  Tags      1 row per tag             Tag, Category",
    "  Trends    tag x week                Week, Tag, Interest, Geo",
    "  Products  1 row per SKU             SKU, Product, Brand, Category, Tag, UnitPrice",
    "  Stores    1 row per store           StoreID, Store, StoreType, SizeTier, City, State",
    "  Sales     store x SKU x week        Week, StoreID, SKU, Units, Dollars",
    "  Weeks     1 row per week            Week, WeekIndex, Year, WeekLabel",
    "",
    "How the sample was built:",
    "  - 104 weeks of search interest and 52 weeks of sales, ending 2026-11-15.",
    "  - Weeks start on Sunday, the same as Google Trends.",
    "  - Sales follow search interest with a 3-week lag.",
    "  - A store carries a SKU if it has sales rows for it.",
    "  - Tag text is the exact Google search term. It links search to products.",
    "",
    "Rebuild this file any time with: python make_sample_data.py",
]


def week_list() -> list[date]:
    return [LAST_WEEK - timedelta(weeks=N_WEEKS - 1 - i) for i in range(N_WEEKS)]


def trend_curve(rng, bump_rng, level, momentum, seasonal, weeks) -> np.ndarray:
    """Weekly interest that lands near the target momentum over the last 24 weeks."""
    n = len(weeks)
    t = np.arange(n)
    growth = math.log(1 + momentum) / 12            # per-week log growth
    ramp_start = n - 30                             # the move starts 30 weeks back
    log_shape = np.where(t > ramp_start, (t - ramp_start) * growth, 0.0)
    log_shape -= log_shape[-12:].mean()             # level describes the latest weeks
    doy = np.array([w.timetuple().tm_yday for w in weeks])
    season = 1 + seasonal * np.cos(2 * math.pi * (doy - 350) / 365.25)  # peaks in December
    noise = rng.normal(1.0, 0.035, n)
    # Two short spikes (think: a viral video) earlier in the sales year. They sit
    # before the last 24 weeks, so they don't move momentum, and they give the
    # lag page something to line up.
    bumps = np.ones(n)
    for center in bump_rng.choice(np.arange(n - 48, n - 28), size=2, replace=False):
        bumps += bump_rng.uniform(0.25, 0.40) * np.exp(-((t - center) ** 2) / (2 * 1.5 ** 2))
    return np.clip(level * np.exp(log_shape) * season * noise * bumps, 1, 100).round(1)


def build():
    rng = np.random.default_rng(SEED)
    bump_rng = np.random.default_rng(SEED + 1)
    weeks = week_list()

    tags = pd.DataFrame([{"Tag": t, "Category": v[0]} for t, v in TAGS.items()])

    curves = {t: trend_curve(rng, bump_rng, v[1], v[2], v[4], weeks) for t, v in TAGS.items()}
    trends = pd.DataFrame(
        [
            {"Week": w, "Tag": t, "Interest": float(curves[t][i]), "Geo": "US-MD"}
            for t in TAGS
            for i, w in enumerate(weeks)
        ]
    )

    products = pd.DataFrame(
        [
            {"SKU": sku, "Product": name, "Brand": brand, "Category": TAGS[tag][0],
             "Tag": tag, "UnitPrice": price}
            for sku, name, brand, tag, price, _ in PRODUCTS
        ]
    )
    stores = pd.DataFrame(
        [
            {"StoreID": f"S{i + 1:02d}", "Store": s, "StoreType": typ, "SizeTier": size,
             "City": city, "State": st}
            for i, (s, typ, size, city, st) in enumerate(STORES)
        ]
    )

    # Which stores carry which SKUs. Bigger stores are more likely to carry a tag.
    scale = np.array([SIZE_SCALE[s[2]] for s in STORES])
    rows = []
    for tag, (_, _, _, n_carry, _) in TAGS.items():
        carriers = rng.choice(N_STORES, size=n_carry, replace=False, p=scale / scale.sum())
        tag_skus = [p for p in PRODUCTS if p[3] == tag]
        for s in carriers:
            picked = [p for p in tag_skus if rng.random() < 0.62]
            if not picked:
                picked = [tag_skus[int(rng.integers(len(tag_skus)))]]
            rel = curves[tag] / curves[tag][-N_SALES_WEEKS:].mean()
            for sku, _, _, _, price, pop in picked:
                for i in range(N_WEEKS - N_SALES_WEEKS, N_WEEKS):
                    lam = scale[s] * pop * rel[i - LAG]
                    units = int(rng.poisson(lam))
                    if units > 0:
                        rows.append({"Week": weeks[i], "StoreID": f"S{s + 1:02d}", "SKU": sku,
                                     "Units": units, "Dollars": round(units * price, 2)})
    sales = pd.DataFrame(rows).sort_values(["Week", "StoreID", "SKU"]).reset_index(drop=True)

    weeks_df = pd.DataFrame(
        [
            {"Week": w, "WeekIndex": i + 1, "Year": w.year, "WeekLabel": w.strftime("%b %d, %Y")}
            for i, w in enumerate(weeks)
        ]
    )
    return {"Tags": tags, "Trends": trends, "Products": products, "Stores": stores,
            "Sales": sales, "Weeks": weeks_df}


def write_workbook(tables: dict[str, pd.DataFrame], path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    for line in README:
        ws.append([line])
    ws["A1"].font = Font(bold=True, size=14)
    ws["A3"].font = Font(bold=True)
    ws.column_dimensions["A"].width = 90

    for name, df in tables.items():
        ws = wb.create_sheet(name)
        ws.append(list(df.columns))
        for row in df.itertuples(index=False):
            ws.append(list(row))
        ref = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"
        table = Table(displayName=name, ref=ref)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)
        for i, col in enumerate(df.columns, start=1):
            width = max(len(str(col)), int(df[col].astype(str).str.len().max())) + 2
            ws.column_dimensions[get_column_letter(i)].width = min(width, 45)
            if col == "Week":
                for cell in ws[get_column_letter(i)][1:]:
                    cell.number_format = "yyyy-mm-dd"
    wb.save(path)


def summarize(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The same numbers the DAX measures produce, for checking the sample."""
    trends, sales, products = tables["Trends"], tables["Sales"], tables["Products"]
    wk = sorted(trends["Week"].unique())
    last12, prior12 = set(wk[-12:]), set(wk[-24:-12])
    out = []
    recent = sales[sales["Week"].isin(last12)].merge(products[["SKU", "Tag"]], on="SKU")
    for tag in TAGS:
        t = trends[trends["Tag"] == tag]
        l12 = t[t["Week"].isin(last12)]["Interest"].mean()
        p12 = t[t["Week"].isin(prior12)]["Interest"].mean()
        mom = l12 / p12 - 1
        dist = recent[recent["Tag"] == tag]["StoreID"].nunique() / N_STORES
        status = "Rising" if mom > 0.15 else "Cooling" if mom < -0.15 else "Steady"
        out.append({"Tag": tag, "Momentum %": round(mom * 100, 1), "Status": status,
                    "Store Distribution %": round(dist * 100, 1)})
    return pd.DataFrame(out)


if __name__ == "__main__":
    data = build()
    write_workbook(data, OUT)
    print(f"Wrote {OUT}")
    for name, df in data.items():
        print(f"  {name:<9}{len(df):>7,} rows")
    print()
    print(summarize(data).to_string(index=False))
