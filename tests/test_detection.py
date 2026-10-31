"""Unit tests for the detection logic in poller.run_cycle.

No network: fetch_items, page_is_live and the three senders are all stubbed,
and state lives in memory.
"""

import asyncio
import types

import pytest

import poller


class Item:
    def __init__(self, i, title="Havok Tee", price=20.0):
        self.id = i
        self.title = title
        self.brand_title = "Havok"
        self.size_title = "M"
        self.condition = "Good"
        self.currency = "EUR"
        self.price = price
        self.total_item_price = price + 1.7
        self.photo = "x"
        self.url = f"u{i}"


@pytest.fixture()
def world(monkeypatch):
    state = {}
    cur = []
    page_live = {}
    sent = []

    monkeypatch.setattr(poller, "SOLD_AFTER_MISSING", 2)
    monkeypatch.setattr(poller, "load_state", lambda: dict(state))
    monkeypatch.setattr(poller, "save_state", lambda st: (state.clear(), state.update(st)))

    async def fake_fetch():
        return cur

    monkeypatch.setattr(poller, "fetch_items", fake_fetch)
    monkeypatch.setattr(poller, "page_is_live", lambda url: page_live.get(url))
    monkeypatch.setattr(poller, "_send_new", lambda it: sent.append(("NEW", it.title)))
    monkeypatch.setattr(poller, "_send_price_change", lambda *a: sent.append(("PRICE", a)))
    monkeypatch.setattr(poller, "_send_sold", lambda r: sent.append(("SOLD", r["title"])))

    w = types.SimpleNamespace(state=state, page_live=page_live, sent=sent)

    def cycle(items):
        cur[:] = items
        asyncio.run(poller.run_cycle())

    w.cycle = cycle
    return w


def test_first_run_primes_silently(world):
    world.cycle([Item(1)])
    assert world.sent == []
    assert "1" in world.state and world.state["__primed__"] is True


def test_new_item_alerts(world):
    world.cycle([Item(1, "A")])  # prime
    world.cycle([Item(1, "A"), Item(2, "B")])  # B is new
    assert world.sent == [("NEW", "B")]


def test_price_change_alerts(world):
    world.cycle([Item(1, "A", price=20.0)])  # prime
    world.cycle([Item(1, "A", price=15.0)])  # price dropped
    price_alerts = [v for k, v in world.sent if k == "PRICE"]
    assert len(price_alerts) == 1
    old, new = price_alerts[0][1], price_alerts[0][2]
    assert (old, new) == (20.0, 15.0)


def test_sold_once_and_latched(world):
    world.cycle([Item(1, "A"), Item(999, "D")])  # prime both
    world.page_live["u1"] = False  # A's page says gone
    world.cycle([Item(999, "D")])  # A missing 1
    world.cycle([Item(999, "D")])  # A missing 2 -> SOLD
    sold = [s for s in world.sent if s[0] == "SOLD" and s[1] == "A"]
    assert len(sold) == 1
    assert world.state["1"]["sold"] is True
    assert world.state["1"]["sold_alerted"] is True

    # Reappear, then sell again -> the latch must suppress the second alert.
    world.cycle([Item(1, "A"), Item(999, "D")])  # A back (un-sold)
    world.page_live["u1"] = False
    world.cycle([Item(999, "D")])
    world.cycle([Item(999, "D")])
    sold2 = [s for s in world.sent if s[0] == "SOLD" and s[1] == "A"]
    assert len(sold2) == 1


def test_live_item_not_marked_sold(world):
    world.cycle([Item(1, "A"), Item(999, "D")])  # prime both
    world.page_live["u1"] = True  # A's page still live
    for _ in range(4):
        world.cycle([Item(999, "D")])  # A absent from search
    assert world.state["1"]["sold"] is False
    assert world.state["1"]["missing"] == 0
    assert not any(s[0] == "SOLD" for s in world.sent)
