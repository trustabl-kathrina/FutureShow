import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from futureshow.tool.tool_polymarket_data import get_event_info_fn
import requests
from zoneinfo import ZoneInfo

GAMMA = "https://gamma-api.polymarket.com"
DEFAULT_WATCHLIST_PATH = Path(__file__).resolve().parent / "polymarket_watchlist_2026_01.json"


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-like datetime string to aware datetime (UTC) if possible."""
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _close_time(ev: Dict[str, Any]) -> Optional[datetime]:
    for key in (
        "endDateIso",
        "end_date_iso",
        "endDate",
        "closeDate",
        "closedDate",
        "expiry",
        "expiresAt",
    ):
        dt = _parse_datetime(ev.get(key))
        if dt:
            return dt
    return None


def _has_month_hint(ev: Dict[str, Any], month: int) -> bool:
    month_names = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    month_idx = max(1, min(12, int(month))) - 1
    month_token = month_names[month_idx]
    texts: List[str] = []
    for key in ("title", "question", "description", "slug"):
        val = ev.get(key)
        if isinstance(val, str):
            texts.append(val.lower())
    # include tag labels if present
    for tag in ev.get("tags") or []:
        if isinstance(tag, dict):
            lab = tag.get("label") or tag.get("slug")
            if isinstance(lab, str):
                texts.append(lab.lower())
        elif isinstance(tag, str):
            texts.append(tag.lower())
    return any(month_token in t for t in texts)


def _is_closed(ev: Dict[str, Any]) -> bool:
    """Detect already-closed/resolved events."""
    closed_flag = ev.get("closed")
    if isinstance(closed_flag, bool) and closed_flag:
        return True
    status = str(ev.get("status") or ev.get("resolution") or "").lower()
    if status in {"closed", "resolved", "settled"}:
        return True
    if ev.get("resolved") or ev.get("resolvedAt"):
        return True
    return False


def _volume_score(ev: Dict[str, Any]) -> float:
    """Approximate event popularity using volume/open interest."""
    candidates: Sequence[str] = (
        "volume24hr",
        "volume24h",
        "volume24H",
        "totalVolumeUSD",
        "totalVolumeUsd",
        "dayVolumeUSD",
        "openInterest",
        "liquidityClob",
        "liquidity",
    )
    for key in candidates:
        try:
            val = ev.get(key)
            if val is None:
                continue
            return float(val)
        except Exception:
            continue
    return 0.0


def _category(ev: Dict[str, Any]) -> str:
    if ev.get("category"):
        return str(ev["category"])
    cats = ev.get("categories") or ev.get("categorySlug")
    if isinstance(cats, list) and cats:
        return str(cats[0])
    if isinstance(cats, str) and cats:
        return cats
    tags = ev.get("tags") or []
    for t in tags:
        if isinstance(t, dict):
            lab = t.get("label") or t.get("slug")
            if lab:
                return str(lab)
        elif t:
            return str(t)
    return "Other"


def _is_excluded_category(ev: Dict[str, Any], exclude_keywords: Sequence[str]) -> bool:
    """Return True if event belongs to an excluded category/tag/slug match."""
    if not exclude_keywords:
        return False
    target = [s.lower() for s in exclude_keywords]

    # core category text
    cat = (_category(ev) or "").lower()
    if any(k in cat for k in target):
        return True

    # slug/title/description
    for key in ("slug", "title", "question", "description"):
        val = ev.get(key)
        if isinstance(val, str):
            txt = val.lower()
            if any(k in txt for k in target):
                return True

    # tags
    for tag in ev.get("tags") or []:
        if isinstance(tag, dict):
            for field in ("label", "slug"):
                lab = tag.get(field)
                if isinstance(lab, str) and any(k in lab.lower() for k in target):
                    return True
        elif isinstance(tag, str):
            if any(k in tag.lower() for k in target):
                return True
    return False


def _summarize_markets(ev: Dict[str, Any]) -> List[Dict[str, Any]]:
    markets = ev.get("markets") or []
    summary: List[Dict[str, Any]] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        closed_flag = False
        status = str(m.get("status") or m.get("resolution") or "").lower()
        if status in {"closed", "resolved", "settled"}:
            closed_flag = True
        if isinstance(m.get("closed"), bool) and m.get("closed"):
            closed_flag = True
        if closed_flag:
            continue
        summary.append(
            {
                "slug": m.get("slug"),
                "question": m.get("question") or m.get("title"),
                "description": m.get("description") or m.get("shortDescription") or m.get("longDescription"),
                "outcomes": m.get("outcomes"),
                "prices": m.get("outcomePrices"),
                "mid": m.get("mid"),
                "bestBid": m.get("bestBid"),
                "bestAsk": m.get("bestAsk"),
                "liquidity": m.get("liquidityClob") or m.get("liquidity"),
                "volume24h": m.get("volume24h") or m.get("volume24H"),
                "closed": closed_flag,
            }
        )
    return summary


def fetch_trending_events(
    limit: int = 500,
    per_category: int = 5,
    exclude_categories: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetch active Polymarket events ordered by recent activity and sample per category."""
    params = {
        "active": "true",
        "closed": "false",
        "order": "volume24hr,openInterest,commentCount",
        "ascending": "false",
        "limit": str(max(1, limit)),
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    r = requests.get(f"{GAMMA}/events", params=params, headers=headers, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        events = payload.get("data") or payload.get("events") or []
    else:
        events = payload or []

    enriched: List[Dict[str, Any]] = []
    exclude_categories = exclude_categories or []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev = dict(ev)
        ev["_category"] = _category(ev)
        ev["_volume_score"] = _volume_score(ev)
        ev["_close_time"] = _close_time(ev)
        if _is_excluded_category(ev, exclude_categories):
            continue
        enriched.append(ev)

    # group by category and sample top items per category
    categories = sorted({ev["_category"] for ev in enriched})
    grouped: Dict[str, List[Dict[str, Any]]] = {c: [] for c in categories}
    for ev in enriched:
        grouped[ev["_category"]].append(ev)
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x.get("_volume_score", 0.0), reverse=True)

    picked: List[Dict[str, Any]] = []
    cap = max(0, int(per_category))
    for cat in categories:
        picked.extend(grouped.get(cat, [])[:cap])

    # final sort: by volume desc then close time asc
    picked.sort(
        key=lambda x: (
            -(x.get("_volume_score", 0.0) or 0.0),
            _close_time(x) or datetime.max.replace(tzinfo=timezone.utc),
        )
    )
    return picked


def fetch_specific_events(slugs: Sequence[str]) -> List[Dict[str, Any]]:
    """Fetch explicit event slugs (skip missing/closed)."""
    items: List[Dict[str, Any]] = []
    for slug in slugs:
        if not slug:
            continue
        data = get_event_info_fn(str(slug))
        if not data or "error" in data:
            continue
        event = data.get("event") if isinstance(data, dict) else None
        if not isinstance(event, dict):
            event = data if isinstance(data, dict) else None
        if not event:
            continue
        if _is_closed(event):
            continue
        ev = dict(event)
        ev["_category"] = _category(ev)
        ev["_volume_score"] = _volume_score(ev)
        ev["_close_time"] = _close_time(ev)
        items.append(ev)
    return items


def filter_events_likely_in_month(
    events: Iterable[Dict[str, Any]],
    year: int,
    month: int,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Keep events that either (a) have a future close time in the target month,
    or (b) mention the month in title/question/description/tags."""
    now = now or datetime.now(timezone.utc)
    filtered: List[Dict[str, Any]] = []
    for ev in events:
        if _is_closed(ev):
            continue
        dt = ev.get("_close_time") or _close_time(ev)
        has_hint = _has_month_hint(ev, month)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.year == year and dt.month == month and dt > now:
                filtered.append(ev)
                continue
        if has_hint and (not dt or dt > now):
            filtered.append(ev)
    return filtered


def save_watchlist(events: List[Dict[str, Any]], path: Path = DEFAULT_WATCHLIST_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "slug": ev.get("slug"),
                    "title": ev.get("title") or ev.get("question"),
                    "description": ev.get("description") or ev.get("shortDescription") or ev.get("longDescription"),
                    "category": ev.get("_category"),
                    "endDate": (dt.isoformat() if (dt := (ev.get("_close_time") or _close_time(ev))) else None),
                    "volumeScore": ev.get("_volume_score", 0.0),
                    "markets": _summarize_markets(ev),
                }
                for ev in events
                if ev.get("slug")
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )
    return path


def load_watchlist(path: Path = DEFAULT_WATCHLIST_PATH) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        title = item.get("title")
        if not slug or not title:
            continue
        out.append(item)
    return out


def remove_events_from_watchlist(
    slugs: Sequence[str],
    path: Path = DEFAULT_WATCHLIST_PATH,
) -> List[Dict[str, Any]]:
    """Remove events by slug from the watchlist and persist."""
    if not Path(path).exists():
        return []
    current = load_watchlist(path)
    keep: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    targets = {s for s in slugs if s}
    for ev in current:
        if ev.get("slug") in targets:
            removed.append(ev)
        else:
            keep.append(ev)
    if removed:
        save_watchlist(keep, path=path)
    return removed


def refresh_trending_watchlist(
    *,
    watchlist_path: Path = DEFAULT_WATCHLIST_PATH,
    year: Optional[int] = None,
    month: int = 11,
    limit: int = 50000,
    per_category: int = 5000,
    exclude_categories: Optional[Sequence[str]] = None,
    include_slugs: Optional[Sequence[str]] = None,
    max_end_iso: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch trending events (with optional exclusions) and optionally append explicit slugs."""
    target_year = year or datetime.utcnow().year
    default_excludes = ["up or down", "crypto", "sports", "games", "esports"]
    events = fetch_trending_events(
        limit=limit,
        per_category=per_category,
        exclude_categories=exclude_categories or default_excludes,
    )
    if max_end_iso:
        max_dt = _parse_datetime(max_end_iso)
        if max_dt:
            filtered_events: List[Dict[str, Any]] = []
            for ev in events:
                ct = ev.get("_close_time") or _close_time(ev)
                if ct and ct > max_dt:
                    continue
                filtered_events.append(ev)
            events = filtered_events
    
    manual_events: List[Dict[str, Any]] = []
    if include_slugs:
        manual_events = fetch_specific_events(include_slugs)

    combined: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for ev in events + manual_events:
        slug = ev.get("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        combined.append(ev)

    now = datetime.now(timezone.utc)
    filtered: List[Dict[str, Any]] = []
    for ev in combined:
        dt = ev.get("_close_time") or _close_time(ev)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= now:
                continue
        filtered.append(ev)

    filtered.sort(
        key=lambda ev: (
            _close_time(ev) or datetime.max.replace(tzinfo=timezone.utc)
        )
    )

    save_watchlist(filtered, path=watchlist_path)
    return filtered


if __name__ == "__main__":
    include_slugs = [
        "khamenei-out-as-supreme-leader-of-iran-by-january-31",
        "will-trump-acquire-greenland-before-2027", 
        "will-the-iranian-regime-fall-by-the-end-of-2026", 
        "us-strikes-iran-by", 
        "israel-strikes-iran-by-january-31-2026", 
        "jerome-powell-out-as-fed-chair-by", 
        "jerome-powell-federally-charged-by-june-30", 
        "us-strike-on-mexico-by", 
        "portugal-presidential-election", 
        "ice-shooter-charged-by-march-31", 
        "will-trump-and-machado-share-the-nobel-peace-prize", 
        "who-will-trump-nominate-as-fed-chair", 
        "will-the-supreme-court-rule-in-favor-of-trumps-tariffs"
    ]
    max_end_iso = "2026-06-01T23:00:00+00:00"
    refreshed = refresh_trending_watchlist(include_slugs=include_slugs, max_end_iso=max_end_iso)
    print(f"Saved {len(refreshed)} events to {DEFAULT_WATCHLIST_PATH}")
