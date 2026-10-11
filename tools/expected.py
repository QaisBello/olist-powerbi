"""Work out what every report visual should show, in pandas, from the same CSVs the Power BI model loads.

This is the reference implementation of the DAX measures. It follows the model's filter rules:
  - Orders and Order Items keep only rows in the analysis window (as the Power Query step does).
  - A product category filters Order Items directly and reaches Orders through the both-directions relationship,
    so an order counts in every category it has an item in.
  - Customers is not filtered by category (the relationship runs from Customers to Orders only).

Outputs
  docs/expected_values.md   the numbers to check against Power BI Desktop after the first refresh
  web/data/report.json      the same numbers, broken down by category, for the web version of the report

    python tools/expected.py [path-to-clean-csvs]
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else "https://raw.githubusercontent.com/QaisBello/olist-dbt-warehouse/main/data/clean/"
BUCKETS = [None, "15+ days early", "8-14 days early", "1-7 days early", "On the day",
           "1-3 days late", "4-7 days late", "8-14 days late", "15+ days late"]


def read(name, **kw):
    return pd.read_csv(os.path.join(SRC, name) if not SRC.startswith("http") else SRC + name, low_memory=False, **kw)


def bucket(d):
    if pd.isna(d):
        return 0
    return 1 if d <= -15 else 2 if d <= -8 else 3 if d <= -1 else 4 if d == 0 else 5 if d <= 3 else 6 if d <= 7 else 7 if d <= 14 else 8


def boolcol(s):
    return s.map({True: True, False: False, "true": True, "false": False, "True": True, "False": False})


orders = read("fct_orders.csv", parse_dates=["purchase_date", "delivered_at"])
items = read("fct_order_items.csv")
customers = read("dim_customers.csv")
for c in ("is_late", "in_analysis_window"):
    orders[c] = boolcol(orders[c])
items["in_analysis_window"] = boolcol(items["in_analysis_window"])
customers["is_repeat_customer"] = boolcol(customers["is_repeat_customer"])
orders = orders[orders.in_analysis_window == True].copy()
items = items[items.in_analysis_window == True].copy()
items["category"] = items["category"].fillna("unknown")
orders["lateness"] = orders.days_late.map(bucket)
orders["month"] = orders.purchase_date.dt.strftime("%Y-%m")


def measures(o, it):
    delivered = o[(o.order_status == "delivered") & o.delivered_at.notna()]
    late = delivered[delivered.is_late == True]
    reviewed = o[o.review_score.notna()]
    on_time = o[o.is_late == False].review_score.mean()
    late_r = o[o.is_late == True].review_score.mean()
    rev = float(it.price.sum())
    n = len(o)
    return {
        "Order Count": n,
        "Revenue": round(rev, 2),
        "Avg Order Value": round(rev / n, 2) if n else None,
        "% Late": round(len(late) / len(delivered), 4) if len(delivered) else None,
        "Avg Review": round(o.review_score.mean(), 4),
        "Avg Review (On Time)": round(on_time, 4),
        "Avg Review (Late)": round(late_r, 4) if not np.isnan(late_r) else None,
        "Review Gap": round(on_time - late_r, 4) if not np.isnan(late_r) else None,
        "% One-Star": round((reviewed.review_score == 1).mean(), 4) if len(reviewed) else None,
    }


def breakdowns(o):
    d = o[(o.order_status == "delivered") & o.delivered_at.notna()]
    by_late = o[o.lateness > 0].groupby("lateness").review_score.agg(["mean", "size"])
    by_state = d.groupby("customer_state").is_late.agg(lambda s: (s == True).mean())
    by_state_n = d.groupby("customer_state").size()
    by_month = o.groupby("month").size()
    return {
        "lateness": [{"bucket": BUCKETS[i], "avg_review": round(r["mean"], 6), "orders": int(r["size"])} for i, r in by_late.iterrows()],
        "states": sorted([{"state": s, "pct_late": round(v, 4), "delivered": int(by_state_n[s])} for s, v in by_state.items()],
                         key=lambda x: -x["pct_late"]),
        "months": [{"month": m, "orders": int(v)} for m, v in by_month.items()],
    }


overall = measures(orders, items)
overall["Repeat Customer %"] = round(customers.is_repeat_customer.mean(), 4)
out = {"overall": {**overall, **breakdowns(orders)}, "categories": []}

# Why the measures use == rather than =: in DAX, BLANK() = FALSE() is true, so Orders[is_late] = FALSE () would also
# keep every order with no delivery (is_late blank) and count it as on time.
blank = orders[orders.is_late.isna()]
out["pitfall"] = {"blank_orders": len(blank), "blank_reviewed": int(blank.review_score.notna().sum()),
                  "blank_avg_review": round(blank.review_score.mean(), 2),
                  "on_time_with_equals": round(orders[(orders.is_late == False) | orders.is_late.isna()].review_score.mean(), 4),
                  "on_time_with_strict": overall["Avg Review (On Time)"]}

order_cats = items[["order_id", "category"]].drop_duplicates()
for cat, ids in order_cats.groupby("category").order_id:
    o = orders[orders.order_id.isin(ids)]
    m = measures(o, items[items.category == cat])
    out["categories"].append({"category": cat, **m, **breakdowns(o)})
out["categories"].sort(key=lambda c: -c["Revenue"])

os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
def clean(o):  # NaN (e.g. an average over no reviews) is not valid JSON
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return None if isinstance(o, float) and np.isnan(o) else o


json.dump(clean(out), open(os.path.join(ROOT, "web", "data", "report.json"), "w"), separators=(",", ":"), allow_nan=False)

fmt = {"Order Count": "{:,.0f}", "Revenue": "R${:,.0f}", "Avg Order Value": "R${:,.2f}", "% Late": "{:.1%}", "Avg Review": "{:.2f}",
       "Avg Review (On Time)": "{:.2f}", "Avg Review (Late)": "{:.2f}", "Review Gap": "{:.2f}", "% One-Star": "{:.1%}", "Repeat Customer %": "{:.1%}"}
lines = ["# Expected values", "",
         "Generated by `tools/expected.py`, which recomputes every measure in pandas from the same CSVs the model loads.",
         "After the first refresh in Power BI Desktop, the cards and visuals should show these numbers (no slicer selected).", "",
         "| Measure | Expected |", "|---|---:|"]
lines += [f"| {k} | {fmt[k].format(v)} |" for k, v in overall.items() if k in fmt]
lines += ["", "## Average review by lateness (column chart)", "", "| Lateness | Avg Review | Orders |", "|---|---:|---:|"]
lines += [f"| {r['bucket']} | {r['avg_review']:.2f} | {r['orders']:,} |" for r in out["overall"]["lateness"]]
lines += ["", "## Top 5 categories by revenue (table)", "", "| Category | Revenue | Orders | % Late | Avg Review |", "|---|---:|---:|---:|---:|"]
lines += [f"| {c['category']} | R${c['Revenue']:,.0f} | {c['Order Count']:,} | {c['% Late']:.1%} | {c['Avg Review']:.2f} |" for c in out["categories"][:5]]
open(os.path.join(ROOT, "docs", "expected_values.md"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines[6:18]))
print(len(out["categories"]), "categories;", os.path.getsize(os.path.join(ROOT, "web", "data", "report.json")) // 1024, "KB")
