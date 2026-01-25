import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_SOURCE = Path(__file__).resolve().parent / "polymarket_watchlist_2026_01.json"
DEFAULT_TARGET = Path(__file__).resolve().parent / "polymarket_watchlist.json"


def _event_slug(event: Dict[str, Any]) -> Optional[str]:
    slug = event.get("slug")
    if isinstance(slug, str) and slug.strip():
        return slug.strip()
    return None


def _load_watchlist(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected a list in {path}, got {type(data).__name__}.")
    events: List[Dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Expected object at index {idx} in {path}.")
        events.append(item)
    return events


def _merge_dict(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if value is None:
            continue
        merged[key] = value
    return merged


def _merge_markets(
    base_markets: List[Any], incoming_markets: List[Any]
) -> Tuple[List[Any], int]:
    merged: List[Any] = list(base_markets)
    index_by_slug: Dict[str, int] = {}
    for idx, market in enumerate(merged):
        if isinstance(market, dict):
            slug = market.get("slug")
            if isinstance(slug, str) and slug.strip():
                index_by_slug[slug.strip()] = idx
    added = 0
    for market in incoming_markets:
        if not isinstance(market, dict):
            merged.append(market)
            added += 1
            continue
        slug = market.get("slug")
        if isinstance(slug, str) and slug.strip() and slug.strip() in index_by_slug:
            target_idx = index_by_slug[slug.strip()]
            existing = merged[target_idx]
            if isinstance(existing, dict):
                merged[target_idx] = _merge_dict(existing, market)
            else:
                merged[target_idx] = market
        else:
            merged.append(market)
            added += 1
            if isinstance(slug, str) and slug.strip():
                index_by_slug[slug.strip()] = len(merged) - 1
    return merged, added


def _merge_event(base: Dict[str, Any], incoming: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    merged = _merge_dict(base, {k: v for k, v in incoming.items() if k != "markets"})
    added_markets = 0
    if "markets" in incoming:
        base_markets = base.get("markets") if isinstance(base.get("markets"), list) else []
        incoming_markets = (
            incoming.get("markets") if isinstance(incoming.get("markets"), list) else []
        )
        merged_markets, added_markets = _merge_markets(base_markets, incoming_markets)
        merged["markets"] = merged_markets
    return merged, added_markets


def merge_watchlists(
    target_events: List[Dict[str, Any]],
    source_events: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, int, int]:
    merged: List[Dict[str, Any]] = list(target_events)
    index_by_slug: Dict[str, int] = {}
    for idx, event in enumerate(merged):
        slug = _event_slug(event)
        if slug:
            index_by_slug[slug] = idx

    added_events = 0
    updated_events = 0
    added_markets_total = 0
    for incoming in source_events:
        slug = _event_slug(incoming)
        if slug and slug in index_by_slug:
            target_idx = index_by_slug[slug]
            merged_event, added_markets = _merge_event(merged[target_idx], incoming)
            merged[target_idx] = merged_event
            updated_events += 1
            added_markets_total += added_markets
        else:
            merged.append(incoming)
            added_events += 1
            if slug:
                index_by_slug[slug] = len(merged) - 1
            markets = incoming.get("markets")
            if isinstance(markets, list):
                added_markets_total += len(markets)
    return merged, added_events, updated_events, added_markets_total


def _write_watchlist(path: Path, events: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge a Polymarket watchlist JSON into the main watchlist.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Path to the source watchlist JSON.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Path to the target watchlist JSON to update in place.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show merge stats without writing changes.",
    )
    args = parser.parse_args(argv)

    source_events = _load_watchlist(args.source)
    target_events = _load_watchlist(args.target)
    merged, added_events, updated_events, added_markets = merge_watchlists(
        target_events, source_events
    )

    if not args.dry_run:
        _write_watchlist(args.target, merged)

    action = "Would update" if args.dry_run else "Updated"
    print(
        f"{action} {args.target}: +{added_events} events, "
        f"~{updated_events} events merged, +{added_markets} markets."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
