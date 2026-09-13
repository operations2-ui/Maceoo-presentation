# Refreshing the dashboard

Say **"refresh the dashboard"** and Claude runs this file top to bottom. Nothing
below needs a human in the loop as long as the Shopify and NetSuite connectors
are authorised.

## The command

```bash
python3 tools/periods.py          # 1. recompute the windows, print the 22 queries
#                                   2. run each printed query through its connector
#                                      and write the result to data/raw/<name>
python3 tools/build_dashboard.py  # 3. rebuild data/dashboard.json and dashboard.html
```

Step 2 is the only step that needs a connector. `tools/periods.py` prints every
query already filled in with today's dates, grouped by the raw file it feeds, so
there is nothing to compose by hand.

## What the windows are

`tools/periods.py` writes `data/periods.json` and both the queries and the
dashboard labels read from it, so the data and its captions cannot drift apart.

| Key | Window |
|---|---|
| `ytd_ty` | 1 January to today |
| `ytd_ly` | 1 January to the same day last year |
| `mtd_ty` | 1st of this month to today |
| `mtd_ly` | 1st of the same month last year to the same day |

Month to date is always measured against a month cut off at the same day, so a
part-finished month is never compared against a whole one. Pass `--as-of
YYYY-MM-DD` to rebuild the report as it stood on an earlier date.

## Raw files and their shapes

Everything in `data/raw/` is the untouched query output, so a number in the
dashboard can always be traced back to the query that produced it.

| File | Columns | Fed by |
|---|---|---|
| `sales_by_store.json` | store, net_sales, gross_sales, discounts, sales_reversals, orders, units | `sales_by_store` x 4 periods |
| `customers_by_store.json` | store, new_customers, returning_customers, customers | `customers_by_store` x 4 periods |
| `staff_{ytd,mtd}_{ty,ly}.csv` | staff, store, net_sales, orders, units | `staff` x 4 periods |
| `daily_by_store.csv` | day, store, net_sales, gross_sales, discounts, sales_reversals, orders, units, new_customers, returning_customers, customers | `daily_by_store` |
| `daily_by_staff.csv` | day, staff, store, net_sales, orders, units | `daily_by_staff` |
| `inventory_by_store.csv` | period, store, units, retail_value, cost_value | `inventory_by_store` x 2 |
| `inventory_by_category.csv` | store, category, units, retail_value | `inventory_by_category` |
| `category_sales_ytd.csv` | store, category, net_sales, units | `category_sales_ytd` |
| `top_products.csv` | product, net_sales, units, orders | `top_products` |
| `netsuite.json` | po_by_status_2026, open_po_by_vendor, po_monthly, totals | the three SuiteQL queries |

Two conventions the build depends on: the blank POS location that Shopify returns
for web orders is written as `Online Store`, and a blank `product_type` is written
as `Uncategorized`. The category matrix drops the `Uncategorized` bucket, because
it is bookkeeping rather than a merchandising category. In the daily salesperson
file a blank staff name is written as `Unattributed`; those are web orders with no
one on the floor behind them, and the leaderboard leaves them out.

## Why both daily and period pulls

The two daily pulls come back too large to return inline, so they are saved to a
file and converted by script. They are what makes a custom date range possible.

The preset windows still use their own period queries rather than totalling days,
because the two disagree in a way that matters. Summing days counts a client once
for every day they came in, which overstates returning clients by about half; it
also re-counts an order on the day a later refund touches it, which moves money by
about a quarter of a percent. So Month to date and Year to date read Shopify's own
period figures, and only a custom range totals days. The page says so on screen
whenever a custom range is showing.

## Sections with no connector

Four parts of the deck have no live source in this session. They render as a
labelled panel naming what is missing rather than as empty space, and they fill in
from `data/manual.json` the moment the numbers are pasted there.

| Deck section | Source | Where it goes |
|---|---|---|
| 3, Endear clienteling | Endear | `manual.endear.segments` |
| 4, Conversion rate | V-Count door counters | `manual.vcount.rows` |
| 2, hours worked | Homebase | `manual.homebase.rows` |
| 8, Marketing calendar | Drive calendar | `manual.marketing.events` |

Authorising an Endear, V-Count, Homebase or Google Calendar connector lets those
join the automated pull; until then they are a paste.

## Checks worth running after a refresh

- Company net sales in the first tile should equal the sum of the location table.
- A salesperson who moved store shows one row at company level and one row per
  door when that door is selected. Their last-year figure should not read `new`.
- A location added since the last refresh appears in the chip row automatically.
  Nothing has to be registered anywhere.
