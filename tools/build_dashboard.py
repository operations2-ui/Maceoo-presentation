#!/usr/bin/env python3
"""Assemble data/dashboard.json from the raw Shopify + NetSuite pulls in data/raw/.

Run after refreshing data/raw/ (see REFRESH.md):

    python3 tools/build_dashboard.py

Everything the dashboard renders is derived here, so the HTML stays a pure view.
"""
import csv
import json
import os
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "dashboard.json")

# The windows the raw pulls were taken over. tools/periods.py writes this file and
# prints the matching queries, so the data and the labels can never drift apart.
_PERIOD_FILE = os.path.join(ROOT, "data", "periods.json")
with open(_PERIOD_FILE, encoding="utf-8") as _fh:
    PERIODS = json.load(_fh)

# Locations that are warehouses / wholesale entities rather than sellable retail doors.
NON_RETAIL = {"WEB - Quiet LLC"}


def read_csv(name):
    with open(os.path.join(RAW, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_json(name):
    with open(os.path.join(RAW, name), encoding="utf-8") as fh:
        return json.load(fh)


def num(v):
    if v in (None, "", "null"):
        return 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0


def pct(ty, ly):
    """Percent change, or None when last year has no base to grow from."""
    if not ly:
        return None
    return (ty - ly) / abs(ly) * 100


def safe_div(a, b):
    return a / b if b else 0


# --------------------------------------------------------------------------
# 1. Store-level sales, UPT, AOV
# --------------------------------------------------------------------------
def build_stores():
    sales = read_json("sales_by_store.json")
    custs = read_json("customers_by_store.json")

    stores = defaultdict(lambda: {k: None for k in PERIODS})
    for period, rows in ((p, sales[p]) for p in PERIODS):
        for name, net, gross, disc, rev, orders, units in rows:
            stores[name][period] = {
                "net_sales": net,
                "gross_sales": gross,
                "discounts": abs(disc),
                "returns": abs(rev),
                "orders": orders,
                "units": units,
                "upt": round(safe_div(units, orders), 2),
                "aov": round(safe_div(net, orders), 2),
                "new_customers": 0,
                "returning_customers": 0,
                "customers": 0,
            }

    for period in PERIODS:
        for name, new, ret, total in custs[period]:
            if stores[name][period] is None:
                continue
            stores[name][period].update(
                new_customers=new, returning_customers=ret, customers=total
            )

    empty = {
        "net_sales": 0, "gross_sales": 0, "discounts": 0, "returns": 0,
        "orders": 0, "units": 0, "upt": 0, "aov": 0,
        "new_customers": 0, "returning_customers": 0, "customers": 0,
    }
    for name in stores:
        for period in PERIODS:
            if stores[name][period] is None:
                stores[name][period] = dict(empty)
    return stores


def totals_for(stores, names, period):
    agg = defaultdict(float)
    for name in names:
        for key, value in stores[name][period].items():
            if key in ("upt", "aov"):
                continue
            agg[key] += value
    agg["upt"] = round(safe_div(agg["units"], agg["orders"]), 2)
    agg["aov"] = round(safe_div(agg["net_sales"], agg["orders"]), 2)
    return dict(agg)


# --------------------------------------------------------------------------
# 2. Salespeople
# --------------------------------------------------------------------------
def build_staff():
    def load(name):
        out = {}
        for r in read_csv(name):
            out[(r["staff"], r["store"])] = {
                "net_sales": num(r["net_sales"]),
                "orders": int(num(r["orders"])),
                "units": int(num(r["units"])),
            }
        return out

    periods = {
        "ytd_ty": load("staff_ytd_ty.csv"),
        "ytd_ly": load("staff_ytd_ly.csv"),
        "mtd_ty": load("staff_mtd_ty.csv"),
        "mtd_ly": load("staff_mtd_ly.csv"),
    }

    keys = set()
    for table in periods.values():
        keys |= set(table)

    rows = []
    for staff, store in sorted(keys):
        entry = {"staff": staff, "store": store}
        for period, table in periods.items():
            rec = table.get((staff, store), {"net_sales": 0, "orders": 0, "units": 0})
            entry[period] = {
                **rec,
                "upt": round(safe_div(rec["units"], rec["orders"]), 2),
                "aov": round(safe_div(rec["net_sales"], rec["orders"]), 2),
            }
        rows.append(entry)
    return rows


def roll_up_staff(rows):
    """Company view keys on the person, not the person-and-door.

    Salespeople move between locations, and keying on the pair makes a transfer
    look like a new hire with no last-year figure. Per-store views keep the pair.
    """
    merged = {}
    for r in rows:
        entry = merged.setdefault(r["staff"], {"staff": r["staff"], "stores": []})
        entry["stores"].append(r["store"])
        for period in PERIODS:
            acc = entry.setdefault(period, {"net_sales": 0, "orders": 0, "units": 0})
            for key in ("net_sales", "orders", "units"):
                acc[key] += r[period][key]

    out = []
    for entry in merged.values():
        # Label the person by the door they sold the most from this year.
        primary = max(
            set(entry["stores"]),
            key=lambda s: sum(
                r["ytd_ty"]["net_sales"]
                for r in rows
                if r["staff"] == entry["staff"] and r["store"] == s
            ),
        )
        doors = len(set(entry["stores"]))
        row = {
            "staff": entry["staff"],
            "store": primary,
            "doors": doors,
        }
        for period in PERIODS:
            acc = entry[period]
            row[period] = {
                **acc,
                "upt": round(safe_div(acc["units"], acc["orders"]), 2),
                "aov": round(safe_div(acc["net_sales"], acc["orders"]), 2),
            }
        out.append(row)
    out.sort(key=lambda r: -r["ytd_ty"]["net_sales"])
    return out


# --------------------------------------------------------------------------
# 3. Inventory, categories, refill signals
# --------------------------------------------------------------------------
def build_inventory():
    by_store = {"ty": {}, "ly": {}}
    for r in read_csv("inventory_by_store.csv"):
        by_store[r["period"]][r["store"]] = {
            "units": int(num(r["units"])),
            "retail_value": num(r["retail_value"]),
            "cost_value": num(r["cost_value"]),
        }

    by_cat = defaultdict(list)
    for r in read_csv("inventory_by_category.csv"):
        by_cat[r["store"]].append({
            "category": r["category"],
            "units": int(num(r["units"])),
            "retail_value": num(r["retail_value"]),
        })

    cat_sales = defaultdict(dict)
    for r in read_csv("category_sales_ytd.csv"):
        cat_sales[r["store"]][r["category"]] = {
            "net_sales": num(r["net_sales"]),
            "units": int(num(r["units"])),
        }

    # Refill matrix: inventory on hand next to YTD sell-through for the same category.
    # "Uncategorized" is a bookkeeping bucket, not a merchandising category, so it is
    # excluded from every signal rather than dominating the top of the table.
    def matrix_rows(cats, sold_lookup):
        rows = []
        for cat, on_hand, retail in cats:
            if cat in ("", "Uncategorized"):
                continue
            sold = sold_lookup.get(cat, {})
            sold_units = sold.get("units", 0)
            sell_through = safe_div(sold_units, sold_units + max(on_hand, 0)) * 100
            rows.append({
                "category": cat,
                "on_hand_units": on_hand,
                "on_hand_retail": retail,
                "sold_units": sold_units,
                "sold_value": sold.get("net_sales", 0),
                "sell_through": round(sell_through, 1),
                "signal": refill_signal(on_hand, sold_units, sell_through),
            })
        rows.sort(key=lambda r: -r["on_hand_retail"])
        return rows

    matrix = {}
    for store, cats in by_cat.items():
        matrix[store] = matrix_rows(
            [(c["category"], c["units"], c["retail_value"]) for c in cats],
            cat_sales.get(store, {}),
        )

    # Company roll-up: the same matrix with every location summed per category.
    comp_inv = defaultdict(lambda: [0, 0.0])
    for cats in by_cat.values():
        for c in cats:
            comp_inv[c["category"]][0] += c["units"]
            comp_inv[c["category"]][1] += c["retail_value"]
    comp_sales = defaultdict(lambda: {"net_sales": 0.0, "units": 0})
    for store_cats in cat_sales.values():
        for cat, v in store_cats.items():
            comp_sales[cat]["net_sales"] += v["net_sales"]
            comp_sales[cat]["units"] += v["units"]
    company_matrix = matrix_rows(
        [(cat, v[0], v[1]) for cat, v in comp_inv.items()], dict(comp_sales)
    )
    return {"by_store": by_store, "matrix": matrix, "company_matrix": company_matrix}


def refill_signal(on_hand, sold_units, sell_through):
    """Classify a category into a buy-plan action."""
    if on_hand < 0:
        # POS sold past zero: the count is wrong before any buy decision is worth making.
        return "check_count"
    if sold_units == 0 and on_hand > 0:
        return "no_movement"
    if sell_through >= 60:
        return "refill"
    if on_hand > 0 and sell_through < 15:
        return "overstocked"
    return "healthy"


# --------------------------------------------------------------------------
# 4. Monthly trend
# --------------------------------------------------------------------------
def build_trend():
    trend = defaultdict(dict)
    for r in read_csv("monthly_by_store.csv"):
        trend[r["store"]][r["month"]] = {
            "net_sales": num(r["net_sales"]),
            "orders": int(num(r["orders"])),
            "units": int(num(r["units"])),
        }
    return trend


def trend_for(trend, names):
    months = sorted({m for n in names for m in trend.get(n, {})})
    out = []
    for m in months:
        agg = defaultdict(float)
        for n in names:
            rec = trend.get(n, {}).get(m)
            if rec:
                for k, v in rec.items():
                    agg[k] += v
        out.append({"month": m, **{k: round(v, 2) for k, v in agg.items()}})
    return out


# --------------------------------------------------------------------------
# Assemble
# --------------------------------------------------------------------------
def main():
    stores = build_stores()
    trend = build_trend()

    retail = sorted(
        n for n in stores
        if n not in NON_RETAIL and any(stores[n][p]["net_sales"] for p in PERIODS)
    )
    all_names = sorted(stores)

    staff = build_staff()
    inventory = build_inventory()
    netsuite = read_json("netsuite.json")

    store_blocks = {}
    for name in all_names:
        store_blocks[name] = {
            "periods": {p: stores[name][p] for p in PERIODS},
            "trend": trend_for(trend, [name]),
            "staff": [s for s in staff if s["store"] == name],
            "inventory": {
                "ty": inventory["by_store"]["ty"].get(name),
                "ly": inventory["by_store"]["ly"].get(name),
                "matrix": inventory["matrix"].get(name, []),
            },
        }

    company = {
        "periods": {p: totals_for(stores, all_names, p) for p in PERIODS},
        "trend": trend_for(trend, all_names),
        "staff": roll_up_staff(staff),
        "inventory": {
            "ty": {
                "units": sum(v["units"] for v in inventory["by_store"]["ty"].values()),
                "retail_value": sum(v["retail_value"] for v in inventory["by_store"]["ty"].values()),
                "cost_value": sum(v["cost_value"] for v in inventory["by_store"]["ty"].values()),
            },
            "ly": {
                "units": sum(v["units"] for v in inventory["by_store"]["ly"].values()),
                "retail_value": sum(v["retail_value"] for v in inventory["by_store"]["ly"].values()),
                "cost_value": sum(v["cost_value"] for v in inventory["by_store"]["ly"].values()),
            },
            "matrix": inventory["company_matrix"],
        },
    }

    payload = {
        "meta": {
            "shop": "Maceoo",
            "domain": "maceoo.com",
            "currency": "USD",
            "generated_at": date.today().isoformat(),
            "periods": PERIODS,
            "sources": {
                "sales": "Shopify (ShopifyQL, sales schema)",
                "customers": "Shopify (ShopifyQL, sales schema)",
                "staff": "Shopify POS (staff_member_name)",
                "inventory": "Shopify (ShopifyQL, inventory_by_location)",
                "purchasing": "NetSuite (SuiteQL, transaction / PurchOrd)",
            },
            "manual_sources": ["Endear", "V-Count", "Homebase", "Drive calendar"],
        },
        "stores": {"all": all_names, "retail": retail},
        "company": company,
        "by_store": store_blocks,
        "store_table": {
            p: sorted(
                ({"store": n, **stores[n][p]} for n in all_names),
                key=lambda r: -r["net_sales"],
            )
            for p in PERIODS
        },
        "top_products": [
            {
                "product": r["product"],
                "net_sales": num(r["net_sales"]),
                "units": int(num(r["units"])),
                "orders": int(num(r["orders"])),
            }
            for r in read_csv("top_products.csv")
        ],
        "netsuite": netsuite,
        "manual": load_manual(),
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    size = os.path.getsize(OUT) / 1024
    print(f"wrote {OUT} ({size:.0f} KB)")
    print(f"  {len(all_names)} locations, {len(staff)} salesperson rows")

    render_html(payload)


def render_html(payload):
    """Inline the data into the template so the page opens anywhere, offline.

    dashboard.html is the deliverable and the filename the published Artifact
    tracks. index.html is the same bytes, written for static hosts that serve
    index.html at the root; vercel.json covers that case with a rewrite instead,
    so index.html is generated rather than committed.
    """
    template = os.path.join(ROOT, "dashboard.template.html")
    with open(template, encoding="utf-8") as fh:
        html = fh.read()
    if "__DASHBOARD_DATA__" not in html:
        raise SystemExit("template is missing the __DASHBOARD_DATA__ placeholder")
    # </script> inside a JSON island would close the block early.
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("__DASHBOARD_DATA__", blob)

    for name in ("dashboard.html", "index.html"):
        target = os.path.join(ROOT, name)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"wrote {target} ({os.path.getsize(target)/1024:.0f} KB)")


def load_manual():
    """Sections with no live connector are fed from data/manual.json when present."""
    path = os.path.join(ROOT, "data", "manual.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


if __name__ == "__main__":
    main()
