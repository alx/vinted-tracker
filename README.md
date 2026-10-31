# vinted-tracker

Track listings on **any Vinted market** and get **Discord alerts** + a **web
dashboard**. Built for following a brand (or any search) for new drops, price
changes, and when items sell out.

- Polls a Vinted catalog search and tracks items across cycles by id.
- Alerts (Discord webhook — no bot token):
  - 🆕 **new** listings
  - 🏷️ **price changes** (↑/↓, old → new)
  - ✅ **sold / removed** — confirmed against the item's own page, so an item
    that merely ages out of the search ranking is *not* falsely reported sold.
- A per-item latch guarantees **one sold alert per item, ever**.
- Read-only **web dashboard** (Python stdlib, auto-refresh) with active + sold
  sections, search, and price sorting.
- One **Docker** image, two roles (poller / dashboard), running **non-root**.
- Fully driven by **environment variables** — point it at any brand/search on
  any market with a single `.env`.

## How detection works

State is a JSON file mapping item id → record (title, price, size, condition,
photo, url, first_seen, updated, missing, sold, sold_alerted).

Each poll (`POLL_INTERVAL` seconds):
1. Fetch `PER_PAGE × PAGES` results from the catalog search (newest first).
2. **New** items (id not in state) → alert.
3. **Price changes** on tracked items → alert.
4. **Sold** candidates: items absent for `SOLD_AFTER_MISSING` consecutive
   *non-empty* polls. Before alerting, the item's own page is fetched — if the
   buy button is gone (404 / no live listing) it's marked sold; if it's still
   live it stays active. This is what prevents false "sold" alerts from
   ranking drift.

## Configuration

Copy `.env.example` → `.env`. Key variables (all optional except the webhook
and what to track):

| Var | Default | Meaning |
| --- | --- | --- |
| `MARKET` | `fr` | Vinted market TLD (`fr`, `de`, `es`, `us`, …) |
| `SEARCH_QUERY` | — | Free-text catalog search (usually the brand) |
| `BRAND_FILTER` | — | Keep only items whose `brand_title` equals this (case-insensitive). Prevents look-alikes (e.g. `havok` → Marvel's X-Men Havok comics). Empty = track everything the search returns. |
| `TRACKER_NAME` | `Vinted Tracker` | Discord username + dashboard title |
| `DISCORD_WEBHOOK_URL` | — | Discord channel webhook (success = HTTP 204) |
| `POLL_INTERVAL` | `300` | Seconds between polls |
| `PER_PAGE` | `96` | Results per page (Vinted caps ~96) |
| `PAGES` | `2` | Pages to scan (`PER_PAGE × PAGES` items) |
| `SOLD_AFTER_MISSING` | `2` | Missing non-empty polls before a sold check |
| `PROXY` | — | Optional proxy URL; empty = direct |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING` |

> **Never commit `.env`** (it holds the webhook). It is git-ignored.

## Quickstart (Docker)

```bash
cp .env.example .env        # then edit: SEARCH_QUERY, BRAND_FILTER, webhook…
mkdir -p state && chmod 775 state

docker build -t vinted-tracker:latest .

# Poller (default role)
docker run -d --name vinted-tracker \
  --restart unless-stopped \
  -v "$PWD/state":/app/state \
  --env-file .env \
  vinted-tracker:latest

# Dashboard (second container, read-only state)
docker run -d --name vinted-tracker-ui \
  --restart unless-stopped \
  -p 127.0.0.1:3110:3110 \
  -v "$PWD/state":/app/state:ro \
  --env-file .env \
  vinted-tracker:latest python ui.py
```

Open `http://127.0.0.1:3110/` (or expose it on your tailnet — see
`docs/DEPLOYMENT.md`).

> **First run primes silently** (records the current items, no alerts). Alerts
> start on the cycle after.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

ruff format --check .   # formatting
ruff check .            # lint
pytest                  # unit tests (no network)
mypy poller.py ui.py    # types
```

## Project layout

```
poller.py              poller: fetch → detect (new/price/sold) → Discord
ui.py                  stdlib HTTP dashboard (serves index.html + /api/items)
index.html             single-page dashboard UI
Dockerfile             non-root image serving both roles
tests/                 pytest suite (detection logic + dashboard HTTP)
docs/DEPLOYMENT.md     step-by-step deployment runbook (any brand/market)
.env.example           configuration template
.github/workflows/ci   CI: ruff, pytest, mypy, docker build
```

## Notes & limits

- Uses the public catalog search via [`vinted-api-kit`](https://pypi.org/project/vinted-api-kit/).
  If you see repeated HTTP 403s, set `PROXY` to a residential proxy.
- Vinted's `newest_first` ranking moves; `PAGES` bounds how deep we look for
  *new* items. Sold detection is page-confirmed, so ranking drift does not
  cause false sold alerts.

## License

MIT — see [LICENSE](LICENSE).
