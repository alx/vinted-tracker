#!/usr/bin/env python3
"""Vinted item tracker -> Discord webhook.

Polls a Vinted market/brand and tracks items across cycles, alerting on new
listings, price changes, and sold/removed items. Built on `vinted-api-kit`;
state is a JSON file of item records. Fully configured via environment
variables (see .env.example) so it can track any brand/search on any market.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path

from curl_cffi import requests as crl
from vinted import VintedClient, VintedError, VintedRateLimitError

BASE = Path(__file__).resolve().parent


def load_dotenv(path):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv(BASE / ".env")

MARKET = os.environ.get("MARKET", "fr")
SEARCH_QUERY = os.environ.get("SEARCH_QUERY", "")
BRAND_FILTER = os.environ.get("BRAND_FILTER", "").strip().lower()
TRACKER_NAME = os.environ.get("TRACKER_NAME", "Vinted Tracker")
PER_PAGE = int(os.environ.get("PER_PAGE", "96"))
PAGES = int(os.environ.get("PAGES", "2"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
PROXY = os.environ.get("PROXY", "").strip() or None
SOLD_AFTER_MISSING = int(os.environ.get("SOLD_AFTER_MISSING", "2"))
STATE_FILE = Path(os.environ.get("STATE_FILE", str(BASE / "state" / "seen.json")))
COOKIES_DIR = Path(os.environ.get("COOKIES_DIR", str(BASE / "state" / "cookies")))
CATALOG_URL = f"https://www.vinted.{MARKET}/catalog?search_text={SEARCH_QUERY}"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("vinted-tracker")
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- state -----------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            log.warning("could not read state, starting fresh")
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)


def migrate_record(val):
    """Normalize a state entry to the full record schema."""
    if isinstance(val, dict):
        r = dict(val)
    else:  # legacy: iso string
        r = {
            "title": "",
            "price": None,
            "total_price": None,
            "currency": "",
            "size": "",
            "condition": "",
            "photo": "",
            "url": "",
            "first_seen": val,
            "updated": val,
        }
    r.setdefault("missing", 0)
    r.setdefault("sold", False)
    r.setdefault("sold_alerted", bool(r.get("sold", False)))
    r.setdefault("first_seen", now_iso())
    return r


def rec(it):
    photo = it.photo or ""
    if photo and not photo.startswith("http"):
        photo = "https://" + photo.lstrip("/")
    return {
        "title": it.title,
        "price": it.price,
        "total_price": it.total_item_price,
        "currency": it.currency,
        "size": it.size_title,
        "condition": it.condition,
        "photo": photo,
        "url": it.url,
        "first_seen": now_iso(),
        "updated": now_iso(),
        "missing": 0,
        "sold": False,
    }


# --- discord ---------------------------------------------------------------
def is_match(item):
    """Return True if a catalog item matches the configured brand filter.

    Set BRAND_FILTER to a brand (case-insensitive) to ignore look-alike free
    text (e.g. a search that also returns unrelated 'Havok' comics). Leave it
    empty to track every item returned by the search query.
    """
    if not BRAND_FILTER:
        return True
    return (item.brand_title or "").strip().lower() == BRAND_FILTER


def page_is_live(url):
    """Check an item's own page for a live listing (buy button present).
    Returns True (still for sale), False (removed/sold), or None (unknown -> do not sell)."""
    if not url:
        return None
    try:
        resp = crl.get(url, timeout=20)
    except Exception as e:
        log.warning("page check failed for %s: %s", url, e)
        return None
    if resp.status_code == 404:
        return False
    if resp.status_code != 200:
        return None
    return 'data-testid="item-buy-button"' in resp.text


def _clean(embed):
    return {k: v for k, v in embed.items() if v is not None}


def _post(payload):
    if DRY_RUN:
        log.info("[dry-run] %s", json.dumps(payload, ensure_ascii=False)[:300])
        return
    if not WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL not set; skipping send")
        return
    for attempt in range(3):
        try:
            r = crl.post(WEBHOOK_URL, json=payload, timeout=20)
            if r.status_code in (200, 204):
                return
            if r.status_code == 429:
                ra = int(r.headers.get("Retry-After", "5") or 5)
                log.warning("discord 429, waiting %ss", ra)
                time.sleep(ra + 1)
                continue
            log.error("discord HTTP %s: %s", r.status_code, r.text[:300])
            return
        except Exception as e:  # noqa: BLE001
            log.error("discord send error (attempt %s): %s", attempt + 1, e)
            time.sleep(3 * (attempt + 1))
    log.error("giving up on discord send")


def _fields(price, size, condition):
    return [
        {"name": "Price", "value": price or "?", "inline": True},
        {"name": "Size", "value": size or "?", "inline": True},
        {"name": "Condition", "value": condition or "?", "inline": True},
    ]


def _send_new(it):
    photo = it.photo or ""
    if photo and not photo.startswith("http"):
        photo = "https://" + photo.lstrip("/")
    _post(
        {
            "username": TRACKER_NAME,
            "embeds": [
                _clean(
                    {
                        "title": "🆕 " + (it.title or "item")[:200],
                        "url": it.url,
                        "color": 0x5865F2,
                        "thumbnail": {"url": photo} if photo else None,
                        "fields": _fields(
                            f"{it.price:g} {it.currency}", it.size_title, it.condition
                        ),
                        "footer": {"text": f"vinted.{MARKET}"},
                    }
                )
            ],
        }
    )


def _send_price_change(it, old, new):
    down = new < old
    photo = it.photo or ""
    if photo and not photo.startswith("http"):
        photo = "https://" + photo.lstrip("/")
    _post(
        {
            "username": TRACKER_NAME,
            "embeds": [
                _clean(
                    {
                        "title": f"🏷️ Price {'↓' if down else '↑'}: " + (it.title or "")[:140],
                        "url": it.url,
                        "color": 0x57F29C if down else 0xED4245,
                        "description": f"{old:g} → {new:g} {it.currency}".strip(),
                        "thumbnail": {"url": photo} if photo else None,
                        "fields": _fields(f"{new:g} {it.currency}", it.size_title, it.condition),
                        "footer": {"text": f"vinted.{MARKET}"},
                    }
                )
            ],
        }
    )


def _send_sold(r):
    price = r.get("price")
    desc = f"was {price:g} {r.get('currency', '')}".strip() if price is not None else ""
    title = r.get("title") or "item"
    _post(
        {
            "username": TRACKER_NAME,
            "embeds": [
                _clean(
                    {
                        "title": "✅ SOLD (no longer listed)",
                        "description": f"{title}\n{desc}",
                        "url": r.get("url") or None,
                        "color": 0x99AAB5,
                        "thumbnail": {"url": r["photo"]} if r.get("photo") else None,
                        "fields": _fields(
                            (
                                f"{price:g} {r.get('currency', '')}".strip()
                                if price is not None
                                else None
                            ),
                            r.get("size"),
                            r.get("condition"),
                        ),
                        "footer": {"text": f"vinted.{MARKET}"},
                    }
                )
            ],
        }
    )


def send_test():
    _post(
        {
            "username": TRACKER_NAME,
            "embeds": [
                {
                    "title": TRACKER_NAME + " online",
                    "description": "Alerts: new, price change, sold.",
                    "color": 0x57F29C,
                    "timestamp": now_iso(),
                }
            ],
        }
    )


# --- polling ---------------------------------------------------------------
async def fetch_items():
    out: list = []
    async with VintedClient(persist_cookies=True, cookies_dir=COOKIES_DIR, proxy=PROXY) as c:
        for page in range(1, PAGES + 1):
            items = await c.search_items(
                url=CATALOG_URL, per_page=PER_PAGE, page=page, order="newest_first"
            )
            out.extend(it for it in items if is_match(it))
    return out


async def run_cycle():
    items = await fetch_items()
    state = load_state()
    primed = state.get("__primed__", False)
    present = {str(it.id): it for it in items}

    if not primed:
        for it in items:
            state[str(it.id)] = rec(it)
        state["__primed__"] = True
        save_state(state)
        log.info("PRIMED %d items (no alerts)", len(items))
        return

    alerts = 0
    for it in items:
        sid = str(it.id)
        if sid not in state:
            _send_new(it)
            alerts += 1
            state[sid] = rec(it)
        else:
            r = migrate_record(state[sid])
            if (
                not r.get("sold")
                and r.get("price") is not None
                and abs(r["price"] - it.price) > 1e-6
            ):
                _send_price_change(it, r["price"], it.price)
                alerts += 1
            nr = rec(it)
            nr["first_seen"] = r.get("first_seen", nr["first_seen"])
            nr["sold_alerted"] = r.get("sold_alerted", False)  # never re-alert sold
            state[sid] = nr

    if present:
        for sid in [k for k in state if k != "__primed__"]:
            if sid in present:
                continue
            r = migrate_record(state[sid])
            if r.get("sold"):
                continue
            r["missing"] = r.get("missing", 0) + 1
            if r["missing"] >= SOLD_AFTER_MISSING:
                live = page_is_live(r.get("url"))
                if live is False:
                    r["sold"] = True
                    r["sold_at"] = now_iso()
                    if not r.get("sold_alerted"):
                        _send_sold(r)
                        r["sold_alerted"] = True
                        alerts += 1
                elif live is True:
                    r["missing"] = 0  # still listed; just out of the search window
                # live is None (unknown): keep missing, re-check next cycle
            state[sid] = r

    save_state(state)
    active = sum(1 for k in state if k != "__primed__" and not state[k].get("sold"))
    if alerts:
        log.info("alerts sent: %d (active=%d)", alerts, active)
    else:
        log.info("no changes (active=%d)", active)


async def main_loop(once=False):
    delay = POLL_INTERVAL
    while True:
        try:
            await run_cycle()
        except VintedRateLimitError as e:
            log.warning("rate limited (%s); backing off", e)
            delay = max(POLL_INTERVAL * 2, 600)
        except VintedError as e:
            log.error("Vinted error: %s", e)
            delay = min(POLL_INTERVAL * 2, 900)
        except Exception as e:  # noqa: BLE001
            log.exception("unexpected error: %s", e)
            delay = min(POLL_INTERVAL, 60)
        if once:
            break
        await asyncio.sleep(delay)
        delay = POLL_INTERVAL


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser(description="Vinted item tracker -> Discord")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test-discord", action="store_true")
    ap.add_argument("--reset-state", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="log Discord alerts instead of POSTing")
    args = ap.parse_args()
    DRY_RUN = DRY_RUN or args.dry_run

    if args.reset_state and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("state cleared")
        return
    if args.test_discord:
        send_test()
        print("test embed sent")
        return
    asyncio.run(main_loop(once=args.once))


if __name__ == "__main__":
    main()
