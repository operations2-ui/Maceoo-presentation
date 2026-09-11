#!/usr/bin/env python3
"""Compute the four reporting windows for today and print the exact pulls to run.

    python3 tools/periods.py            # write data/periods.json and print the query set
    python3 tools/periods.py --as-of 2026-10-01

Year-to-date runs 1 January to today. Month-to-date runs from the 1st of the
current month. Both are compared against the identical window one year earlier,
so a part-finished month is never measured against a whole one.
"""
import argparse
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "periods.json")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def windows(today):
    ly = today.replace(year=today.year - 1)
    return {
        "ytd_ty": {
            "label": f"YTD {today.year}",
            "since": f"{today.year}-01-01", "until": today.isoformat(),
        },
        "ytd_ly": {
            "label": f"YTD {ly.year}",
            "since": f"{ly.year}-01-01", "until": ly.isoformat(),
        },
        "mtd_ty": {
            "label": f"{MONTHS[today.month - 1][:3]} {today.year} MTD",
            "since": today.replace(day=1).isoformat(), "until": today.isoformat(),
        },
        "mtd_ly": {
            "label": f"{MONTHS[ly.month - 1][:3]} {ly.year} MTD",
            "since": ly.replace(day=1).isoformat(), "until": ly.isoformat(),
        },
    }


# Every pull the dashboard needs. {since}/{until} are filled per period.
SHOPIFY = [
    ("sales_by_store", ["ytd_ty", "ytd_ly", "mtd_ty", "mtd_ly"],
     "FROM sales SHOW net_sales, gross_sales, discounts, sales_reversals, orders, "
     "net_items_sold GROUP BY pos_location_name SINCE {since} UNTIL {until} "
     "ORDER BY net_sales DESC LIMIT 30"),
    ("customers_by_store", ["ytd_ty", "ytd_ly", "mtd_ty", "mtd_ly"],
     "FROM sales SHOW new_customers, returning_customers, customers "
     "GROUP BY pos_location_name SINCE {since} UNTIL {until} "
     "ORDER BY returning_customers DESC LIMIT 30"),
    ("staff", ["ytd_ty", "ytd_ly", "mtd_ty", "mtd_ly"],
     "FROM sales SHOW net_sales, orders, net_items_sold "
     "GROUP BY staff_member_name, pos_location_name SINCE {since} UNTIL {until} "
     "ORDER BY net_sales DESC LIMIT 90"),
    ("inventory_by_store", ["mtd_ty", "mtd_ly"],
     "FROM inventory_by_location SHOW ending_inventory_units_at_location, "
     "ending_inventory_retail_value_at_location, ending_inventory_value_at_location "
     "GROUP BY inventory_location_name SINCE {since} UNTIL {until} "
     "ORDER BY ending_inventory_retail_value_at_location DESC LIMIT 25"),
    ("inventory_by_category", ["mtd_ty"],
     "FROM inventory_by_location SHOW ending_inventory_units_at_location, "
     "ending_inventory_retail_value_at_location "
     "GROUP BY inventory_location_name, product_type SINCE {since} UNTIL {until} "
     "ORDER BY ending_inventory_retail_value_at_location DESC LIMIT 120"),
    ("category_sales_ytd", ["ytd_ty"],
     "FROM sales SHOW net_sales, net_items_sold GROUP BY pos_location_name, product_type "
     "SINCE {since} UNTIL {until} ORDER BY net_sales DESC LIMIT 110"),
    ("monthly_by_store", ["*"],
     "FROM sales SHOW net_sales, orders, net_items_sold GROUP BY pos_location_name "
     "TIMESERIES month SINCE {ly_start} UNTIL {until} ORDER BY month ASC LIMIT 400"),
    ("top_products", ["ytd_ty"],
     "FROM sales SHOW net_sales, net_items_sold, orders GROUP BY product_title "
     "SINCE {since} UNTIL {until} ORDER BY net_items_sold DESC LIMIT 25"),
]

NETSUITE = [
    ("po_by_status",
     "SELECT BUILTIN.DF(t.status) AS po_status, COUNT(*) AS po_count, "
     "SUM(t.foreigntotal) AS total_value FROM transaction t WHERE t.type = 'PurchOrd' "
     "AND t.trandate >= TO_DATE('{year_start}','YYYY-MM-DD') "
     "GROUP BY BUILTIN.DF(t.status) ORDER BY SUM(t.foreigntotal) DESC"),
    ("open_po_by_vendor",
     "SELECT BUILTIN.DF(t.entity) AS vendor, COUNT(*) AS po_count, "
     "SUM(ABS(t.foreigntotal)) AS open_value, MIN(t.trandate) AS oldest, "
     "MAX(t.trandate) AS newest FROM transaction t WHERE t.type = 'PurchOrd' "
     "AND t.trandate >= TO_DATE('{year_start}','YYYY-MM-DD') AND BUILTIN.DF(t.status) IN "
     "('Purchase Order : Pending Receipt','Purchase Order : Partially Received',"
     "'Purchase Order : Pending Supervisor Approval') "
     "GROUP BY BUILTIN.DF(t.entity) ORDER BY SUM(ABS(t.foreigntotal)) DESC"),
    ("po_monthly",
     "SELECT TO_CHAR(t.trandate,'YYYY-MM') AS po_month, COUNT(DISTINCT t.id) AS po_count, "
     "SUM(ABS(t.foreigntotal)) AS po_value FROM transaction t WHERE t.type = 'PurchOrd' "
     "AND t.trandate >= TO_DATE('{ly_start}','YYYY-MM-DD') "
     "GROUP BY TO_CHAR(t.trandate,'YYYY-MM') ORDER BY TO_CHAR(t.trandate,'YYYY-MM')"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", help="ISO date to report through (default: today)")
    args = ap.parse_args()
    today = date.fromisoformat(args.as_of) if args.as_of else date.today()

    per = windows(today)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(per, fh, indent=2)
    print(f"wrote {OUT}\n")
    for k, v in per.items():
        print(f"  {k:<8} {v['since']} .. {v['until']}   {v['label']}")

    extra = {
        "ly_start": per["ytd_ly"]["since"],
        "year_start": per["ytd_ty"]["since"],
    }

    print("\n--- ShopifyQL (run-analytics-query) ---")
    for name, periods, q in SHOPIFY:
        for pk in periods:
            src = per.get(pk, per["ytd_ty"])
            label = pk if pk != "*" else "full range"
            print(f"\n# {name} / {label}")
            print(q.format(since=src["since"], until=src["until"], **extra))

    print("\n--- NetSuite (ns_runCustomSuiteQL) ---")
    for name, q in NETSUITE:
        print(f"\n# {name}")
        print(q.format(until=per["ytd_ty"]["until"], **extra))


if __name__ == "__main__":
    main()
