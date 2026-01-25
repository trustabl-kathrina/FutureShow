import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from futureshow.utils.polymarket_watchlist import (
    filter_events_likely_in_month,
    _is_excluded_category,
    _is_closed,
    load_watchlist,
    save_watchlist,
    refresh_trending_watchlist,
    remove_events_from_watchlist,
)


def test_filter_events_likely_in_month_prefers_future_close():
    nov_event = {"slug": "nov-ev", "title": "Nov close", "endDate": "2024-11-15T00:00:00Z"}
    dec_event = {"slug": "dec-ev", "title": "Dec close", "endDate": "2024-12-01T00:00:00Z"}
    filtered = filter_events_likely_in_month([nov_event, dec_event], 2024, 11, now=datetime(2024, 10, 1, tzinfo=timezone.utc))
    assert len(filtered) == 1
    assert filtered[0]["slug"] == "nov-ev"


def test_filter_events_likely_in_month_accepts_text_hint():
    nov_text_event = {"slug": "txt", "title": "Result expected in November", "endDate": None}
    filtered = filter_events_likely_in_month([nov_text_event], 2024, 11, now=datetime(2024, 10, 1, tzinfo=timezone.utc))
    assert filtered and filtered[0]["slug"] == "txt"


def test_is_excluded_category_matches_keywords():
    ev = {"slug": "btc-price", "title": "Crypto move", "category": "Crypto"}
    assert _is_excluded_category(ev, ["crypto"])
    assert not _is_excluded_category(ev, ["sports"])


def test_is_closed_blocks_resolved():
    ev = {"slug": "done", "status": "resolved"}
    assert _is_closed(ev)


def test_refresh_trending_watchlist_includes_manual(monkeypatch, tmp_path: Path):
    # stub fetch_trending_events to avoid network
    monkeypatch.setattr(
        "futureshow.utils.polymarket_watchlist.fetch_trending_events",
        lambda **kwargs: [
            {"slug": "trend-1", "title": "Trending 1", "_category": "Other", "_volume_score": 1.0},
        ],
    )
    # stub fetch_specific_events
    monkeypatch.setattr(
        "futureshow.utils.polymarket_watchlist.fetch_specific_events",
        lambda slugs: [
            {"slug": slugs[0], "title": "Manual", "_category": "Other", "_volume_score": 0.5},
        ],
    )
    out_path = tmp_path / "watch.json"
    res = refresh_trending_watchlist(
        watchlist_path=out_path,
        include_slugs=["manual-1"],
        per_category=5,
        limit=10,
    )
    assert {e["slug"] for e in res} == {"trend-1", "manual-1"}
    assert out_path.exists()


def test_remove_events_from_watchlist(tmp_path: Path):
    data = [
        {"slug": "a", "title": "A"},
        {"slug": "b", "title": "B"},
    ]
    path = tmp_path / "w.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    removed = remove_events_from_watchlist(["b"], path=path)
    assert removed and removed[0]["slug"] == "b"
    remaining = load_watchlist(path)
    assert [e["slug"] for e in remaining] == ["a"]


def test_refresh_trending_watchlist_filters_past_and_sorts(monkeypatch, tmp_path: Path):
    now = datetime.now(timezone.utc)
    old_dt = now.replace(year=now.year, month=now.month, day=now.day) - timedelta(days=30)
    soon_dt = now + timedelta(days=1)
    later_dt = now + timedelta(days=10)
    monkeypatch.setattr(
        "futureshow.utils.polymarket_watchlist.fetch_trending_events",
        lambda **kwargs: [
            {"slug": "old", "title": "Old", "_category": "Other", "_volume_score": 1.0, "_close_time": old_dt},
            {"slug": "soon", "title": "Soon", "_category": "Other", "_volume_score": 1.0, "_close_time": soon_dt},
            {"slug": "later", "title": "Later", "_category": "Other", "_volume_score": 1.0, "_close_time": later_dt},
        ],
    )
    monkeypatch.setattr(
        "futureshow.utils.polymarket_watchlist.fetch_specific_events",
        lambda slugs: [],
    )
    out_path = tmp_path / "watch.json"
    res = refresh_trending_watchlist(
        watchlist_path=out_path,
        include_slugs=[],
        per_category=5,
        limit=10,
        max_end_iso=(now + timedelta(days=365)).isoformat(),
    )
    assert [e["slug"] for e in res] == ["soon", "later"]


def test_refresh_trending_watchlist_max_end_filters(monkeypatch, tmp_path: Path):
    base = datetime.now(timezone.utc)
    dt1 = base + timedelta(days=30)
    dt2 = base + timedelta(days=900)
    monkeypatch.setattr(
        "futureshow.utils.polymarket_watchlist.fetch_trending_events",
        lambda **kwargs: [
            {"slug": "within", "title": "Within", "_category": "Other", "_volume_score": 1.0, "_close_time": dt1},
            {"slug": "beyond", "title": "Beyond", "_category": "Other", "_volume_score": 1.0, "_close_time": dt2},
        ],
    )
    monkeypatch.setattr(
        "futureshow.utils.polymarket_watchlist.fetch_specific_events",
        lambda slugs: [],
    )
    out_path = tmp_path / "watch2.json"
    res = refresh_trending_watchlist(
        watchlist_path=out_path,
        include_slugs=[],
        max_end_iso=(base + timedelta(days=200)).isoformat(),
    )
    assert [e["slug"] for e in res] == ["within"]


def test_save_and_load_watchlist(tmp_path: Path):
    events = [
        {
            "slug": "nov-ev",
            "title": "Nov close",
            "description": "desc here",
            "_close_time": datetime(2024, 11, 15, tzinfo=timezone.utc),
            "_category": "Politics",
            "_volume_score": 123.4,
            "markets": [
                {"slug": "m1", "description": "m desc", "question": "Q", "outcomes": ["Yes", "No"], "outcomePrices": [0.5, 0.5]},
                {"slug": "m2", "question": "Q2", "closed": True},
            ],
        }
    ]
    target = tmp_path / "watch.json"
    save_watchlist(events, path=target)
    assert target.exists()

    loaded = load_watchlist(target)
    assert loaded and loaded[0]["slug"] == "nov-ev"
    assert loaded[0]["description"] == "desc here"
    assert len(loaded[0]["markets"]) == 1  # closed market filtered out
