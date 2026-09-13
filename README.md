# Maceoo retail performance dashboard

The store review deck, rebuilt as one HTML page that switches store with a click
and rebuilds from Shopify and NetSuite with one command.

Open `dashboard.html`. It is self-contained: the data is inlined, so it works from
a file, a shared drive or a static host with nothing to install and no build step.

## What it covers

The eight sections match the deck's own numbering, so a slide has one place to
live.

| | Section | Source |
|---|---|---|
| 1 | Overall performance | Shopify sales, this year against last |
| 2 | Salespeople and store performance | Shopify POS staff attribution |
| 3 | Endear clienteling | Endear, manual |
| 4 | Conversion rate | V-Count and Homebase, manual |
| 5 | Client behaviour | Shopify customer dimension |
| 6 | Inventory and refill | Shopify inventory, NetSuite purchase orders |
| 7 | Mathematical merchandising | Shopify inventory against sales by category |
| 8 | Marketing events and calendar | Drive calendar, manual |

## Choosing what you are looking at

Two controls sit under the wordmark and drive every section at once, including the
charts, the leaderboard, the category matrix and the merchandising gap.

**Location** is a dropdown listing every door by year-to-date net sales, with
`All locations` for the company roll-up. The list is built from the data, so a door
that opened since the last refresh appears on its own.

**Period** offers month to date, year to date, or a custom range. The two date
boxes always show the window actually in effect, and editing either one is itself
the request for a custom range, so the period switches to Custom on its own.
Whichever you pick, the comparison is the identical window one year earlier, so a
part-finished month is never measured against a whole one. A custom range under
about two months charts a point per day; longer ranges chart months.

One caveat the page also states on screen: a custom range is totalled from daily
figures, so a client who came in on several days counts once per day. Those tiles
say "visits" rather than "clients" while a custom range is showing. The preset
windows use Shopify's own period figures and count each client once.

## Refreshing

See [REFRESH.md](REFRESH.md). Short version:

```bash
python3 tools/periods.py          # prints today's 22 queries, already dated
python3 tools/build_dashboard.py  # rebuilds data/dashboard.json and dashboard.html
```

## Layout

```
dashboard.html              the deliverable, data inlined
index.html                  same bytes, generated for hosts that want index.html
vercel.json                 static deploy, no build step, root serves the page
dashboard.template.html     the view, with a __DASHBOARD_DATA__ placeholder
data/raw/                   untouched query output, one file per pull
data/raw/daily_by_*.csv     daily facts, what a custom range is totalled from
data/periods.json           the four reporting windows
data/manual.json            the sections with no connector
data/dashboard.json         everything the page renders, derived
tools/periods.py            windows and the query manifest
tools/build_dashboard.py    raw pulls to dashboard.json to dashboard.html
```

Every figure on the page is derived in `tools/build_dashboard.py`, never in the
browser, so the HTML stays a view and a number can be traced from the page back to
the query that produced it.

## Hosting

The page is plain static HTML, so any static host serves it with no build step.
Vercel picks up `vercel.json`, which maps `/` to `dashboard.html`; without it the
root has no `index.html` to serve and Vercel answers 404. `.vercelignore` keeps
the pipeline and the raw pulls off the host.

A host with no rewrite support wants a real `index.html` at the root. The build
writes one beside `dashboard.html` with the same bytes; it is generated rather
than committed.

The page carries the whole report inside it: company sales, every salesperson's
numbers and the vendor purchase orders. Anyone who can open the URL can read all
of it, so put the deployment behind Vercel's Deployment Protection before sharing
the link.
