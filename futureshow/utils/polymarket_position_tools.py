import os
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, Optional


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _position_path(signature: str) -> Path:
    return _base_dir() / "data" / "agent_data" / signature / "position" / "position.jsonl"


def ensure_position_store(signature: str, init_cash: float = 10000.0, init_datetime: str = "1970-01-01T00:00:00Z") -> None:
    """Ensure ledger file exists with an initial timestamp-based record.

    Fields:
      - timestamp: ISO8601 string (UTC recommended)
      - id: monotonically increasing integer starting at 0
      - positions: mapping with at least {"CASH": float}
    """
    p = _position_path(signature)
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    init = {"timestamp": init_datetime, "id": 0, "positions": {"CASH": float(init_cash)}}
    p.write_text(json.dumps(init) + "\n", encoding="utf-8")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # Support trailing Z
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def _date_to_eod_iso(d: Optional[str]) -> Optional[datetime]:
    if not d:
        return None
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # Treat legacy date-only entries as end-of-day for ordering
        return dt + timedelta(hours=23, minutes=59, seconds=59)
    except Exception:
        return None


def get_latest_position_by_time(as_of_datetime: str, signature: str) -> Tuple[Dict[str, float], int]:
    """Return the latest positions as of the given timestamp.

    Supports legacy rows containing only "date" by mapping them to end-of-day.
    """
    p = _position_path(signature)
    if not p.exists():
        return {}, -1

    cutoff = _parse_iso(as_of_datetime)
    if cutoff is None:
        cutoff = datetime.utcnow().replace(tzinfo=timezone.utc)

    best_doc: Dict[str, any] = {}
    best_id = -1
    best_at: Optional[datetime] = None

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except Exception:
                continue

            at = _parse_iso(doc.get("timestamp"))
            if at is None and doc.get("date"):
                at = _date_to_eod_iso(doc.get("date"))
            if at is None:
                continue

            if at <= cutoff:
                did = int(doc.get("id", -1))
                # Prefer latest time; break ties by id
                if best_at is None or at > best_at or (at == best_at and did > best_id):
                    best_at = at
                    best_id = did
                    best_doc = doc

    return best_doc.get("positions", {}), best_id


def add_no_trade_record(current_datetime: str, signature: str) -> None:
    positions, last_id = get_latest_position_by_time(current_datetime, signature)
    p = _position_path(signature)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": current_datetime,
            "id": last_id + 1,
            "this_action": {"action": "no_trade"},
            "positions": positions,
        }) + "\n")

