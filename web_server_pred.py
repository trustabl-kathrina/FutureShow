#!/usr/bin/env python3
import json
import math
import os
import sys
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add repo root to sys.path to allow importing futureshow
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from futureshow.tool.tool_polymarket_data import get_event_info_fn, _event_current_prob

FORECAST_ROOT = REPO_ROOT / "data" / "forecasts"
FRONTEND_DIR = REPO_ROOT / "frontend"
WATCHLIST_PATH = REPO_ROOT / "futureshow" / "utils" / "polymarket_watchlist.json"

# Global cache
CACHE_LOCK = threading.Lock()
CACHE_EVENTS: List[Dict[str, Any]] = []
MARKET_INFO_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_MODEL_SUMMARY: Dict[str, Dict[str, Any]] = {}
CACHE_HUMAN_SUMMARY: Dict[str, Any] = {}
SHARED_RESULT_CACHE: Dict[str, Dict[str, Any]] = {}

MAX_PREVIEW_CHARS = 240
MAX_HISTORY_CHARS = 6000


def extract_result_winners(result_data: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Parse result.json to figure out winning outcomes per market."""
    winners: Dict[str, Dict[str, Any]] = {}
    if not result_data or not isinstance(result_data, dict):
        return winners

    for market in result_data.get("markets", []):
        if not isinstance(market, dict):
            continue
        slug = market.get("market_slug") or market.get("slug")
        if not slug:
            continue
        outcomes = market.get("outcomes") or []
        prices = market.get("prices") or []
        if not isinstance(outcomes, list) or not isinstance(prices, list):
            continue
        if len(outcomes) != len(prices):
            continue

        parsed: List[tuple[str, float]] = []
        for outcome, price in zip(outcomes, prices):
            try:
                price_val = float(price)
            except Exception:
                continue
            parsed.append((str(outcome), price_val))

        if not parsed:
            continue

        max_price = max(p[1] for p in parsed)
        winning_outcomes = [name for name, val in parsed if val == max_price]
        winners[slug] = {"winning_outcomes": winning_outcomes, "max_price": max_price}

    return winners


def build_options_from_markets(markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build options list from markets data (tracking.jsonl or result.json).
    
    Unified logic: every market_slug + every outcome = one option
    Format: {market_slug}_{outcome} (preserving original case like Yes, No, Sliwa, Adams)
    
    Returns:
        options_list: [{"id": "slug_outcome", "show_name": "slug_outcome"}, ...]
    """
    if not markets or not isinstance(markets, list):
        return []
    
    options = []
    
    for market in markets:
        market_slug = market.get("market_slug") or market.get("slug") or ""
        if not market_slug:
            continue
        outcomes = market.get("outcomes") or []
        for outcome in outcomes:
            outcome_str = str(outcome)
            # ID format: {market_slug}_{outcome} (preserve original case)
            option_id = f"{market_slug}_{outcome_str}"
            options.append({
                "id": option_id,
                "show_name": option_id,
                "market_slug": market_slug,
                "outcome": outcome_str
            })
    
    return options


def compute_gt_id(result_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Compute the ground truth option ID from result.json.
    
    Logic: find the outcome with price=1 for each market
    - For binary (1 market): return {market_slug}_{winning_outcome} (Yes/No/Sliwa/Adams)
    - For multi-choice: find the market where "Yes" has price=1, return {market_slug}_Yes
    
    Returns format: {market_slug}_{outcome} (preserving original case)
    """
    if not result_data or not isinstance(result_data, dict):
        return None
    
    markets = result_data.get("markets") or []
    if not markets:
        return None
    
    # Filter to active markets to determine binary/multi
    active_markets = [m for m in markets if not m.get("closed", False)]
    if not active_markets:
        active_markets = markets
    
    is_binary = len(active_markets) == 1
    
    if is_binary:
        # Binary: find the outcome with price=1
        market = active_markets[0]
        market_slug = market.get("market_slug") or market.get("slug") or ""
        outcomes = market.get("outcomes") or []
        prices = market.get("prices") or []
        
        for i, price in enumerate(prices):
            try:
                if float(price) == 1 and i < len(outcomes):
                    winning_outcome = str(outcomes[i])  # Preserve original case
                    return f"{market_slug}_{winning_outcome}"
            except:
                continue
    else:
        # Multi-choice: find the market where "Yes" has price=1
        for market in markets:
            market_slug = market.get("market_slug") or market.get("slug") or ""
            outcomes = market.get("outcomes") or []
            prices = market.get("prices") or []
            
            for i, outcome in enumerate(outcomes):
                # Check if this is "Yes" (case-insensitive check, but preserve original)
                if str(outcome).lower() == "yes" and i < len(prices):
                    try:
                        if float(prices[i]) == 1:
                            return f"{market_slug}_{outcome}"  # Preserve original case
                    except:
                        continue
    
    return None


def compute_prediction_option_id(
    pred_slug: Optional[str], 
    outcome: Optional[str],
    markets: Optional[List[Dict[str, Any]]] = None
) -> Optional[str]:
    """
    Compute the option ID for a model's prediction.
    
    Model outputs YES/NO, which maps to:
        - YES = first outcome (index 0)
        - NO = second outcome (index 1)
    
    The actual outcome is found from the market's outcomes list.
    Returns format: {market_slug}_{outcome} (preserving original case like Yes, No, Sliwa)
    """
    if not pred_slug or not outcome:
        return None
    
    outcome_upper = str(outcome).upper()
    
    # Find the market that matches pred_slug
    target_market = None
    if markets:
        for m in markets:
            if m.get("market_slug") == pred_slug or m.get("slug") == pred_slug:
                target_market = m
                break
    
    if target_market:
        outcomes = target_market.get("outcomes") or []
        if len(outcomes) >= 2:
            if outcome_upper == "YES":
                actual_outcome = str(outcomes[0])  # First outcome, preserve case
            elif outcome_upper == "NO":
                actual_outcome = str(outcomes[1])  # Second outcome, preserve case
            else:
                actual_outcome = outcome  # Keep as-is for ABSTAIN etc
            return f"{pred_slug}_{actual_outcome}"
        elif len(outcomes) == 1:
            return f"{pred_slug}_{outcomes[0]}"
    
    # Fallback: convert YES->Yes, NO->No for consistency
    if outcome_upper == "YES":
        return f"{pred_slug}_Yes"
    elif outcome_upper == "NO":
        return f"{pred_slug}_No"
    
    return f"{pred_slug}_{outcome}"


def evaluate_prediction_success(
    pred_slug: Optional[str],
    call: Optional[str],
    winners: Dict[str, Dict[str, Any]],
) -> tuple[Optional[bool], Optional[str]]:
    """Return (success flag, resolved outcome text) for a prediction."""
    if not pred_slug or not winners:
        return None, None

    market = winners.get(pred_slug)
    if not market:
        return None, None

    winning_outcomes: List[str] = market.get("winning_outcomes") or []
    resolved_outcome = winning_outcomes[0] if winning_outcomes else None
    if not winning_outcomes:
        return None, resolved_outcome

    call_norm = (call or "").strip().upper()
    if not call_norm or call_norm == "ABSTAIN":
        return None, resolved_outcome

    winning_norm = [str(o).strip().upper() for o in winning_outcomes]
    success = call_norm in winning_norm

    # Gracefully handle YES/NO casing mismatches
    if not success and call_norm in ("YES", "NO"):
        success = call_norm in winning_norm

    return success, resolved_outcome


def compute_single_prediction_value(
    call: str,
    market_prob: Optional[Dict[str, Any]],
    is_correct: bool,
    market_slug: Optional[str] = None,
) -> Optional[float]:
    """
    Compute the prediction value for a single prediction using log return method.

    Logic:
    - If model predicts YES and is correct: value = -log(market_yes_prob)
    - If model predicts YES and is wrong: value = log(market_yes_prob)
    - If model predicts NO and is correct: value = -log(market_no_prob)
    - If model predicts NO and is wrong: value = log(market_no_prob)

    Higher positive values = more valuable predictions (beating the market)
    """
    if not market_prob or not call:
        return None

    call_upper = call.upper()
    if call_upper == "ABSTAIN":
        return None

    # Get market probability for the predicted outcome
    yes_prob = market_prob.get("yes_prob")
    no_prob = market_prob.get("no_prob")

    # Fallback: calculate from bestBid/bestAsk if yes_prob/no_prob not available
    if yes_prob is None and no_prob is None:
        best_bid = market_prob.get("bestBid")
        best_ask = market_prob.get("bestAsk")
        if best_bid is not None and best_ask is not None:
            try:
                bid_val = float(best_bid)
                ask_val = float(best_ask)
                if bid_val > 0 or ask_val < 1:  # Has meaningful price data
                    yes_prob = (bid_val + ask_val) / 2
                    no_prob = 1 - yes_prob
            except (ValueError, TypeError):
                pass

    # Handle case where market_prob has different structure
    if yes_prob is None and no_prob is None:
        return None

    # Determine the market probability for the model's prediction
    if call_upper == "YES":
        p = yes_prob if yes_prob is not None else (1 - no_prob if no_prob is not None else None)
    else:  # NO
        p = no_prob if no_prob is not None else (1 - yes_prob if yes_prob is not None else None)

    if p is None:
        return None

    # Clamp probability to avoid log(0) or log(1) edge cases
    p = max(0.001, min(0.999, float(p)))

    if is_correct:
        # Correct prediction: reward inversely proportional to market probability
        # Lower market prob for our choice = higher reward
        value = -math.log(p)
    else:
        # Wrong prediction: penalty proportional to market probability
        # Higher market prob for our choice = higher penalty
        value = math.log(p)

    return value


def compute_model_accuracy_from_history(
    forecasts: List[Dict[str, Any]],
    result_winners: Dict[str, Dict[str, Any]],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Compute per-model correct/total counts, prediction value, and human baseline across all forecasts.

    Returns:
        tuple: (model_stats, human_stats_per_model)
            - model_stats: {model_name: {correct, total, value_sum, value_count}}
            - human_stats_per_model: {model_name: {correct, total}} for market consensus predictions per model
    """
    model_stats: Dict[str, Dict[str, Any]] = {}
    human_stats_per_model: Dict[str, Dict[str, Any]] = {}

    if not forecasts or not result_winners:
        return model_stats, human_stats_per_model

    for f in forecasts:
        model_name = f.get("model") or f.get("signature") or "unknown"
        preds = f.get("predictions") or []
        market_prob = f.get("market_prob")
        call_val: Optional[str] = None
        market_slug: Optional[str] = None
        if preds and isinstance(preds, list):
            p0 = preds[0]
            if isinstance(p0, dict):
                call_val = p0.get("outcome") or p0.get("call")
                market_slug = p0.get("slug")
            else:
                call_val = str(p0)

        success, _ = evaluate_prediction_success(market_slug, call_val, result_winners)
        if success is None:
            continue

        entry = model_stats.setdefault(model_name, {
            "correct": 0,
            "total": 0,
            "value_sum": 0.0,
            "value_count": 0
        })
        entry["total"] += 1
        if success:
            entry["correct"] += 1

        # Compute prediction value
        pred_value = compute_single_prediction_value(call_val, market_prob, success, market_slug)
        if pred_value is not None:
            entry["value_sum"] += pred_value
            entry["value_count"] += 1

        # Compute human (market) accuracy per model - only when market_prob is available
        if market_prob:
            yes_prob = market_prob.get("yes_prob")
            # Fallback: calculate yes_prob from bestBid/bestAsk if not directly available
            if yes_prob is None:
                best_bid = market_prob.get("bestBid")
                best_ask = market_prob.get("bestAsk")
                if best_bid is not None and best_ask is not None:
                    try:
                        bid_val = float(best_bid)
                        ask_val = float(best_ask)
                        if bid_val > 0 or ask_val < 1:  # Has meaningful price data
                            yes_prob = (bid_val + ask_val) / 2
                    except (ValueError, TypeError):
                        pass

            if yes_prob is not None:
                # Track human stats per model
                human_entry = human_stats_per_model.setdefault(model_name, {"correct": 0, "total": 0})
                human_entry["total"] += 1
                # Market predicts YES if yes_prob > 0.5, otherwise NO
                human_prediction = "YES" if yes_prob > 0.5 else "NO"
                # Get the actual winner for this market
                market_winner = result_winners.get(market_slug, {})
                winning_outcomes = market_winner.get("winning_outcomes", [])
                if winning_outcomes:
                    actual_outcome = str(winning_outcomes[0]).upper()
                    if human_prediction == actual_outcome:
                        human_entry["correct"] += 1

    return model_stats, human_stats_per_model


def get_shared_result(slug: str, cache: Dict[str, Dict[str, Any]]) -> tuple[Optional[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Find a single result.json for the slug across all model folders."""
    if slug in cache:
        res = cache[slug]
        winners = extract_result_winners(res) if res else {}
        return res, winners

    if not FORECAST_ROOT.exists():
        return None, {}

    for model_dir in FORECAST_ROOT.iterdir():
        if not model_dir.is_dir():
            continue
        res_path = model_dir / slug / "result.json"
        if res_path.exists():
            try:
                with res_path.open("r", encoding="utf-8") as rf:
                    res_data = json.load(rf)
                    cache[slug] = res_data
                    winners = extract_result_winners(res_data)
                    return res_data, winners
            except Exception:
                continue
    cache[slug] = None  # sentinel to avoid repeated scans
    return None, {}


def parse_outcomes(raw: Any) -> Optional[List[str]]:
    """Parse outcomes field that may be JSON encoded."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return None
    return None


def build_market_lookup(meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Construct slug -> market metadata mapping from watchlist meta."""
    lookup: Dict[str, Dict[str, Any]] = {}
    markets = meta.get("markets")
    if not isinstance(markets, list):
        return lookup
    for market in markets:
        if not isinstance(market, dict):
            continue
        market_copy = dict(market)
        market_slug = market_copy.get("slug")
        if not market_slug:
            continue
        outcomes = parse_outcomes(market_copy.get("outcomes"))
        if outcomes is not None:
            market_copy["outcomes"] = outcomes
        lookup[market_slug] = market_copy
    return lookup


def merge_market_lookup(base: Dict[str, Dict[str, Any]], extra: Any) -> Dict[str, Dict[str, Any]]:
    """Merge additional markets into existing lookup."""
    if not isinstance(extra, list):
        return base
    for market in extra:
        if not isinstance(market, dict):
            continue
        market_slug = market.get("slug")
        if not market_slug:
            continue
        target = base.setdefault(market_slug, {})
        for key, value in market.items():
            if value not in (None, ""):
                target[key] = value
    return base


def derive_market_selection(event_slug: str, market_slug: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    """Generate a short label for the selected market range."""
    if not market_slug:
        return fallback
    if event_slug and market_slug.startswith(event_slug):
        remainder = market_slug[len(event_slug) :].lstrip("-_ ")
        return remainder or fallback or market_slug
    return fallback or market_slug


def simplify_event_info(info: Dict[str, Any], slug: str) -> Dict[str, Any]:
    """Reduce the raw Polymarket payload to the fields needed by the UI."""
    simplified: Dict[str, Any] = {
        "title": info.get("title") or info.get("question") or slug,
        "description": info.get("description"),
        "category": info.get("category"),
        "endDate": info.get("endDate"),
        "closed": bool(info.get("closed")),
    }

    volume_fields = ("volume", "volumeClob", "volumeNum")
    for key in volume_fields:
        volume_val = info.get(key)
        if volume_val is not None:
            try:
                simplified["volume"] = float(volume_val)
            except Exception:
                simplified["volume"] = volume_val
            break

    markets: List[Dict[str, Any]] = []
    for market in info.get("markets", []):
        if not isinstance(market, dict):
            continue
        market_entry: Dict[str, Any] = {
            "slug": market.get("slug"),
            "question": market.get("question"),
            "closed": market.get("closed"),
            "bestBid": market.get("bestBid"),
            "bestAsk": market.get("bestAsk"),
            "liquidity": market.get("liquidity") or market.get("liquidityNum"),
            "groupItemTitle": market.get("groupItemTitle"),
        }
        outcomes = parse_outcomes(market.get("outcomes"))
        if outcomes is not None:
            market_entry["outcomes"] = outcomes
        markets.append({k: v for k, v in market_entry.items() if v not in (None, "")})
    if markets:
        simplified["markets"] = markets

    return simplified


def truncate_text(text: Optional[str], limit: int) -> tuple[str, bool]:
    """Trim long text for UI responses."""
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    trimmed = text[:limit].rstrip()
    remaining = max(len(text) - len(trimmed), 0)
    notice = f"\n\n[... truncated {remaining} chars for display ...]"
    return trimmed + notice, True


def read_jsonl(path: Path, limit: int | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    try:
        if limit is None:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            out.append(json.loads(line))
                        except Exception:
                            continue
        else:
            dq: deque[str] = deque(maxlen=limit)
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        dq.append(line)
            for line in dq:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def load_watchlist() -> Dict[str, Dict[str, Any]]:
    if not WATCHLIST_PATH.exists():
        return {}
    try:
        with WATCHLIST_PATH.open("r", encoding="utf-8") as f:
            arr = json.load(f)
        res: Dict[str, Dict[str, Any]] = {}
        for ev in arr:
            slug = ev.get("slug")
            if not slug:
                continue
            res[slug] = ev
        return res
    except Exception:
        return {}


def fetch_market_data(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch live market data for a slug."""
    try:
        info = get_event_info_fn(slug)
        if not info or "error" in info:
            return None
        
        prob = _event_current_prob(info)
        return {
            "probability": prob,
            "info": simplify_event_info(info, slug),
            "fetched_at": time.time()
        }
    except Exception as e:
        print(f"[Error] fetching market data for {slug}: {e}")
        return None

def build_local_events(watch: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Rebuild Event Summaries from local forecast files only."""
    new_events = {}
    global_model_stats: Dict[str, Dict[str, Any]] = {}
    global_human_stats_per_model: Dict[str, Dict[str, Any]] = {}  # Human stats per model
    per_event_stats: Dict[str, Dict[str, Any]] = {}
    shared_result_cache: Dict[str, Dict[str, Any]] = {}

    # Cache for tracking data (to get markets/options)
    tracking_cache: Dict[str, Dict[str, Any]] = {}
    
    if FORECAST_ROOT.exists():
        for model_dir in FORECAST_ROOT.iterdir():
            if not model_dir.is_dir():
                continue
            model_name = model_dir.name
            for event_dir in model_dir.iterdir():
                if not event_dir.is_dir():
                    continue
                slug = event_dir.name
                meta = watch.get(slug, {})
                market_lookup = build_market_lookup(meta)
                event_result_data, event_winners = get_shared_result(slug, shared_result_cache)
                event_model_stats = per_event_stats.get(slug, {})
                
                # For accuracy, read full history once per model if event resolved
                if event_result_data:
                    full_forecasts = read_jsonl(event_dir / "forecasts.jsonl")
                    stats, human_stats_per_model = compute_model_accuracy_from_history(full_forecasts, event_winners)

                    # Aggregate human stats per model
                    # Each model's prediction points have corresponding human (market) predictions
                    for m, h_stats in human_stats_per_model.items():
                        h_agg = global_human_stats_per_model.setdefault(m, {"correct": 0, "total": 0})
                        h_agg["correct"] += h_stats.get("correct", 0)
                        h_agg["total"] += h_stats.get("total", 0)

                    if stats:
                        for m, stat in stats.items():
                            ev_agg = event_model_stats.setdefault(m, {
                                "correct": 0, "total": 0,
                                "value_sum": 0.0, "value_count": 0
                            })
                            ev_agg["correct"] += stat.get("correct", 0)
                            ev_agg["total"] += stat.get("total", 0)
                            ev_agg["value_sum"] += stat.get("value_sum", 0.0)
                            ev_agg["value_count"] += stat.get("value_count", 0)

                            g_agg = global_model_stats.setdefault(m, {
                                "correct": 0, "total": 0,
                                "value_sum": 0.0, "value_count": 0
                            })
                            g_agg["correct"] += stat.get("correct", 0)
                            g_agg["total"] += stat.get("total", 0)
                            g_agg["value_sum"] += stat.get("value_sum", 0.0)
                            g_agg["value_count"] += stat.get("value_count", 0)
                        per_event_stats[slug] = event_model_stats
                
                with CACHE_LOCK:
                    cached_markets = MARKET_INFO_CACHE.get(slug, {}).get("info", {}).get("markets") if slug in MARKET_INFO_CACHE else None
                market_lookup = merge_market_lookup(market_lookup, cached_markets)
                
                # Read latest forecast
                forecasts = read_jsonl(event_dir / "forecasts.jsonl", limit=1)
                if not forecasts:
                    continue
                latest = forecasts[-1]
                
                # Extract prediction call (YES/NO) and slug
                preds = latest.get("predictions") or []
                call: Optional[str] = None
                pred_slug: Optional[str] = None
                if isinstance(preds, list) and preds:
                    p0 = preds[0]
                    if isinstance(p0, dict):
                        call = p0.get("outcome") or p0.get("call")
                        pred_slug = p0.get("slug")
                    else:
                        call = str(p0)
                
                # Initialize event entry if needed
                if slug not in new_events:
                    # Read tracking.jsonl to get markets for options
                    tracking_data = None
                    if slug not in tracking_cache:
                        tracking_records = read_jsonl(event_dir / "tracking.jsonl", limit=1)
                        if tracking_records:
                            tracking_cache[slug] = tracking_records[-1]
                    tracking_data = tracking_cache.get(slug, {})
                    
                    # Get markets from tracking, result, or meta
                    markets_data = (
                        tracking_data.get("markets") or 
                        (event_result_data.get("markets") if event_result_data else None) or 
                        meta.get("markets") or 
                        []
                    )
                    
                    # Build options list (all market_slug + outcome combinations)
                    options = build_options_from_markets(markets_data)
                    
                    # Compute ground truth ID if closed
                    gt_id = compute_gt_id(event_result_data) if event_result_data else None
                    
                    new_events[slug] = {
                        "slug": slug,
                        "title": latest.get("event_title") or meta.get("title") or slug,
                        "description": meta.get("description"),
                        "category": meta.get("category"),
                        "endDate": meta.get("endDate"),
                        "markets": markets_data,
                        "options": options,
                        "gt_id": gt_id,
                        "predictions": [],
                        "result": event_result_data,
                        "market_probability": None
                    }
                elif event_result_data and new_events[slug].get("result") is None:
                    new_events[slug]["result"] = event_result_data
                    # Also update gt_id when result becomes available
                    new_events[slug]["gt_id"] = compute_gt_id(event_result_data)
                
                if not event_winners and new_events[slug].get("result"):
                    event_winners = extract_result_winners(new_events[slug]["result"])
                if event_model_stats:
                    new_events[slug]["model_stats"] = event_model_stats

                # Add prediction
                preview_text, preview_truncated = truncate_text(latest.get("forecast"), MAX_PREVIEW_CHARS)
                
                # Compute option_id for this prediction
                # Model outputs YES/NO, convert to actual outcome from market
                markets_data = new_events[slug].get("markets", [])
                option_id = compute_prediction_option_id(pred_slug, call, markets_data)
                
                pred_entry = {
                    "model": model_name,
                    "timestamp": latest.get("timestamp"),
                    "call": (call or "ABSTAIN").upper(),
                    "option_id": option_id,
                }
                if preview_text:
                    pred_entry["preview"] = preview_text
                    pred_entry["preview_truncated"] = preview_truncated
                if pred_slug:
                    pred_entry["market_slug"] = pred_slug
                    market_meta = market_lookup.get(pred_slug)
                    if market_meta:
                        pred_entry["market_question"] = market_meta.get("question")
                        selection = market_meta.get("groupItemTitle") or derive_market_selection(slug, pred_slug)
                        if selection:
                            pred_entry["market_selection"] = selection
                    else:
                        selection = derive_market_selection(slug, pred_slug)
                        if selection:
                            pred_entry["market_selection"] = selection

                # Check if prediction is correct using option_id matching
                gt_id = new_events[slug].get("gt_id")
                if gt_id and option_id:
                    pred_entry["success"] = (option_id == gt_id)
                else:
                    # Fallback to old method
                    success_flag, resolved_outcome = evaluate_prediction_success(pred_slug, call, event_winners)
                    if resolved_outcome:
                        pred_entry["resolved_outcome"] = resolved_outcome
                    if success_flag is not None:
                        pred_entry["success"] = success_flag

                new_events[slug]["predictions"].append(pred_entry)
    return {"events": new_events, "model_summary": global_model_stats, "human_summary": global_human_stats_per_model}

def update_global_cache_from_dict(
    events_dict: Dict[str, Any],
    model_summary: Dict[str, Dict[str, int]],
    human_summary: Optional[Dict[str, Any]] = None
):
    """Enrich events with market info and update global cache."""
    with CACHE_LOCK:
        for slug, entry in events_dict.items():
            if slug in MARKET_INFO_CACHE:
                entry["market_probability"] = MARKET_INFO_CACHE[slug].get("probability")
                # Update title/markets if missing
                info = MARKET_INFO_CACHE[slug].get("info", {})
                if not entry["title"] or entry["title"] == slug:
                    entry["title"] = info.get("title")
                if not entry["endDate"]:
                    entry["endDate"] = info.get("endDate")

        final_list = sorted(events_dict.values(), key=lambda x: x.get("title") or x.get("slug") or "")
        global CACHE_EVENTS
        CACHE_EVENTS = final_list
        global CACHE_MODEL_SUMMARY
        CACHE_MODEL_SUMMARY = model_summary or {}
        global CACHE_HUMAN_SUMMARY
        CACHE_HUMAN_SUMMARY = human_summary or {}

def update_loop(interval: int = 60):
    """Background loop to update forecasts and market data."""
    print(f"Background update loop started. Interval: {interval}s")
    while True:
        try:
            start_time = time.time()
            watch = load_watchlist()

            # 1. Quick local build
            local_result = build_local_events(watch)
            local_events = local_result["events"]
            model_summary = local_result["model_summary"]
            human_summary = local_result["human_summary"]
            update_global_cache_from_dict(local_events, model_summary, human_summary)
            print(f"[Update] Loaded {len(local_events)} events from local disk.")

            # 2. Slow network fetch
            slugs = set(local_events.keys())
            if not slugs and FORECAST_ROOT.exists():
                 # Fallback to find slugs even if no forecasts yet? (Maybe not needed for this UI)
                 pass

            for i, slug in enumerate(slugs):
                # Fetch market data
                market_data = fetch_market_data(slug)
                if market_data:
                    with CACHE_LOCK:
                        MARKET_INFO_CACHE[slug] = market_data

                # Optional: Progressive update every few items
                if (i + 1) % 3 == 0:
                     update_global_cache_from_dict(local_events, model_summary, human_summary)

                time.sleep(0.2)

            # 3. Final update for this cycle
            update_global_cache_from_dict(local_events, model_summary, human_summary)
            print(f"[Update] Cycle complete. Updated market info for {len(slugs)} events.")

            elapsed = time.time() - start_time
            sleep_time = max(5, interval - elapsed)
            time.sleep(sleep_time)

        except Exception as e:
            print(f"[Update Loop Error] {e}")
            time.sleep(10)


def get_event_details(slug: str) -> Dict[str, Any]:
    """Get full history for an event with enriched metadata."""
    watch = load_watchlist()
    meta = watch.get(slug, {})
    market_lookup = build_market_lookup(meta)
    shared_result_cache: Dict[str, Dict[str, Any]] = {}
    result_data, result_winners = get_shared_result(slug, shared_result_cache)
    per_event_model_stats: Dict[str, Dict[str, int]] = {}

    details: Dict[str, Any] = {"slug": slug, "history": []}

    with CACHE_LOCK:
        cached_market_entry = MARKET_INFO_CACHE.get(slug)
    if cached_market_entry:
        details["market_info"] = cached_market_entry
        cached_markets = (cached_market_entry.get("info") or {}).get("markets")
        market_lookup = merge_market_lookup(market_lookup, cached_markets)
    else:
        cached_markets = None
    
    # Find all models that have this event
    if FORECAST_ROOT.exists():
        for model_dir in FORECAST_ROOT.iterdir():
            if not model_dir.is_dir():
                continue
            model_name = model_dir.name
            event_dir = model_dir / slug
            if event_dir.exists() and event_dir.is_dir():
                if result_data:
                    try:
                        full_forecasts = read_jsonl(event_dir / "forecasts.jsonl")
                        stats = compute_model_accuracy_from_history(full_forecasts, result_winners)
                        if stats:
                            for m, s in stats.items():
                                agg = per_event_model_stats.setdefault(m, {"correct": 0, "total": 0})
                                agg["correct"] += s.get("correct", 0)
                                agg["total"] += s.get("total", 0)
                    except Exception:
                        pass

                # Read full history
                forecasts = read_jsonl(event_dir / "forecasts.jsonl")
                for f in forecasts:
                    f["model"] = model_name
                    
                    # Normalize prediction for chart
                    preds = f.get("predictions") or []
                    call = "ABSTAIN"
                    prediction_details: List[Dict[str, Any]] = []
                    success_flag: Optional[bool] = None
                    resolved_outcome: Optional[str] = None
                    if preds and isinstance(preds, list):
                        p0 = preds[0]
                        if isinstance(p0, dict):
                            call = (p0.get("outcome") or p0.get("call") or "ABSTAIN").upper()
                        else:
                            call = str(p0).upper()
                        for pred in preds:
                            pred_info: Dict[str, Any] = {}
                            market_slug = None
                            if isinstance(pred, dict):
                                market_slug = pred.get("slug")
                                pred_info["market_slug"] = market_slug
                                outcome_val = pred.get("outcome") or pred.get("call")
                                if outcome_val:
                                    pred_info["outcome"] = str(outcome_val).upper()
                            else:
                                pred_info["outcome"] = str(pred).upper()
                            market_meta = market_lookup.get(market_slug) if market_slug else None
                            if market_meta:
                                pred_info["market_question"] = market_meta.get("question")
                                selection = market_meta.get("groupItemTitle") or derive_market_selection(slug, market_slug)
                                if selection:
                                    pred_info["market_selection"] = selection
                                if "outcomes" in market_meta:
                                    pred_info["outcomes"] = market_meta["outcomes"]
                            else:
                                selection = derive_market_selection(slug, market_slug)
                                if selection:
                                    pred_info["market_selection"] = selection

                            success_val, resolved_val = evaluate_prediction_success(
                                market_slug, outcome_val, result_winners
                            )
                            if resolved_val and not resolved_outcome:
                                resolved_outcome = resolved_val
                            if success_val is not None and success_flag is None:
                                success_flag = success_val
                            if resolved_val:
                                pred_info["resolved_outcome"] = resolved_val
                            if success_val is not None:
                                pred_info["success"] = success_val
                            prediction_details.append({k: v for k, v in pred_info.items() if v not in (None, "", [])})
                    else:
                        call = str(call).upper()
                    
                    f["parsed_call"] = call
                    original_forecast = f.get("forecast") or f.get("raw_forecast")
                    forecast_text, forecast_truncated = truncate_text(
                        original_forecast, MAX_HISTORY_CHARS
                    )
                    f["forecast"] = forecast_text
                    if forecast_truncated and original_forecast:
                        f["forecast_truncated"] = True
                        f["forecast_original_length"] = len(original_forecast)
                        f["forecast_full"] = original_forecast
                    # Drop raw_forecast if present to avoid huge payloads
                    f.pop("raw_forecast", None)
                    if prediction_details:
                        f["prediction_details"] = prediction_details
                    if success_flag is not None:
                        f["success"] = success_flag
                    if resolved_outcome:
                        f["resolved_outcome"] = resolved_outcome
                    details["history"].append(f)

    # Sort history by timestamp
    details["history"].sort(key=lambda x: x.get("timestamp", ""))
    
    # Build price history for closed events (from tracking.jsonl)
    if result_data is not None:
        price_history: Dict[str, List[Dict[str, Any]]] = {}
        # Find tracking.jsonl from any model folder
        if FORECAST_ROOT.exists():
            for model_dir in FORECAST_ROOT.iterdir():
                if not model_dir.is_dir():
                    continue
                tracking_path = model_dir / slug / "tracking.jsonl"
                if tracking_path.exists():
                    tracking_records = read_jsonl(tracking_path)
                    for record in tracking_records:
                        timestamp = record.get("timestamp")
                        if not timestamp:
                            continue
                        markets = record.get("markets") or []
                        for market in markets:
                            market_slug = market.get("market_slug") or market.get("slug")
                            if not market_slug:
                                continue
                            # Skip if market is already closed at this point
                            if market.get("closed"):
                                continue
                            prices = market.get("prices") or []
                            outcomes = market.get("outcomes") or []
                            if prices and len(prices) > 0:
                                try:
                                    # Get first outcome's price
                                    first_price = float(prices[0])
                                    first_outcome = outcomes[0] if outcomes else "Yes"
                                    if market_slug not in price_history:
                                        price_history[market_slug] = {
                                            "outcome": first_outcome,
                                            "data": []
                                        }
                                    price_history[market_slug]["data"].append({
                                        "timestamp": timestamp,
                                        "price": first_price
                                    })
                                except (ValueError, IndexError):
                                    continue
                    break  # Only need tracking from one model folder
        
        # Sort each market's data by timestamp
        for market_slug in price_history:
            price_history[market_slug]["data"].sort(key=lambda x: x.get("timestamp", ""))
        
        if price_history:
            details["price_history"] = price_history
        
        # Build prediction distribution for closed events
        prediction_distribution: Dict[str, Dict[str, Any]] = {}
        if FORECAST_ROOT.exists():
            for model_dir in FORECAST_ROOT.iterdir():
                if not model_dir.is_dir():
                    continue
                model_name = model_dir.name
                forecasts_path = model_dir / slug / "forecasts.jsonl"
                if not forecasts_path.exists():
                    continue
                
                model_forecasts = read_jsonl(forecasts_path)
                if not model_forecasts:
                    continue
                
                option_counts: Dict[str, int] = {}
                total_predictions = 0
                
                for f in model_forecasts:
                    preds = f.get("predictions") or []
                    if not preds:
                        continue
                    p0 = preds[0]
                    if isinstance(p0, dict):
                        pred_slug = p0.get("slug")
                        outcome = p0.get("outcome") or p0.get("call")
                    else:
                        continue
                    
                    if not pred_slug or not outcome:
                        continue
                    
                    outcome_upper = str(outcome).upper()
                    if outcome_upper == "ABSTAIN":
                        continue
                    
                    # Build option_id similar to compute_prediction_option_id
                    # Map YES->first outcome, NO->second outcome
                    option_id = f"{pred_slug}_{outcome_upper}"
                    
                    option_counts[option_id] = option_counts.get(option_id, 0) + 1
                    total_predictions += 1
                
                if total_predictions > 0:
                    prediction_distribution[model_name] = {
                        "total": total_predictions,
                        "options": option_counts
                    }
        
        if prediction_distribution:
            details["prediction_distribution"] = prediction_distribution
    
    if result_data is not None:
        details["result"] = result_data
        details["gt_id"] = compute_gt_id(result_data)
    if per_event_model_stats:
        details["model_stats"] = per_event_model_stats

    # Event level metadata for detail page
    last_history = details["history"][-1] if details["history"] else {}
    simplified_info = (cached_market_entry or {}).get("info") if cached_market_entry else {}

    details["title"] = meta.get("title") or last_history.get("event_title") or simplified_info.get("title") or slug
    details["description"] = meta.get("description") or simplified_info.get("description")
    details["category"] = meta.get("category") or simplified_info.get("category")
    details["endDate"] = meta.get("endDate") or simplified_info.get("endDate")

    market_summaries: List[Dict[str, Any]] = []
    for market_slug, market_meta in market_lookup.items():
        market_summaries.append(
            {
                "slug": market_slug,
                "question": market_meta.get("question"),
                "groupItemTitle": market_meta.get("groupItemTitle"),
            }
        )
    if market_summaries:
        market_summaries.sort(key=lambda m: m.get("question") or m.get("slug") or "")
        details["markets"] = market_summaries

    return details


class PredServer(SimpleHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            self._set_cors()
            self.end_headers()
        else:
            super().do_OPTIONS()

    def translate_path(self, path: str) -> str:
        if path.startswith("/api/"):
            return super().translate_path(path)
        rel = path.lstrip("/")
        if "?" in rel:
            rel = rel.split("?", 1)[0]
        if not rel or rel == "/":
            rel = "predictions.html"
        if rel == "details" or rel == "details/":
            rel = "details.html"
        # simple security check
        if ".." in rel:
            rel = "predictions.html"
        return str(FRONTEND_DIR / rel)

    def _send_json(self, data: Dict[str, Any], code: int = 200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._set_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/api/predictions":
            with CACHE_LOCK:
                data = list(CACHE_EVENTS)
                model_summary = dict(CACHE_MODEL_SUMMARY)
                human_summary = dict(CACHE_HUMAN_SUMMARY)
            self._send_json({
                "ok": True,
                "events": data,
                "model_summary": model_summary,
                "human_summary": human_summary
            })
            return
        
        if self.path.startswith("/api/predictions/"):
            slug = self.path.split("/")[-1]
            details = get_event_details(slug)
            self._send_json({"ok": True, "event": details})
            return
            
        return super().do_GET()


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PRED_PORT", "10032"))
    
    # Start background thread
    t = threading.Thread(target=update_loop, args=(60,), daemon=True)
    t.start()
    
    print(f"Serving prediction dashboard on http://{host}:{port}")
    with ThreadingHTTPServer((host, port), PredServer) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
