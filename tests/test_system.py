from futureshow.prompt.polymarket_forecast_prompt import get_forecast_system_prompt
import json
from typing import List
from datetime import datetime

def main():
    with open("futureshow/utils/polymarket_watchlist.json", "r") as f:
        events = json.load(f)
    event = events[2]
    slug = event.get("slug")
    title = event.get("title") or event.get("question") or "unknown"
    close_time = event.get("endDate") or ""
    event_description = event.get("description") or ""
    outcomes_text = "unknown"
    markets_text_lines: List[str] = []
    try:
        markets = event.get("markets") or []
        if markets and isinstance(markets, list):
            m0 = markets[0]
            outcomes = m0.get("outcomes")
            if isinstance(outcomes, list) and outcomes:
                outcomes_text = ", ".join(str(o) for o in outcomes)
            for m in markets:
                if not isinstance(m, dict):
                    continue
                mslug = m.get("slug") or "unknown"
                q = m.get("question") or m.get("title") or ""
                desc = m.get("description") or m.get("shortDescription") or ""
                
                mout = m.get("outcomes")
                if isinstance(mout, list):
                    mout_txt = ", ".join(str(o) for o in mout)
                else:
                    mout_txt = str(mout) if mout is not None else ""
                markets_text_lines.append(f"- {mslug}: {q} | outcomes: {mout_txt} | desc: {desc}")
    except Exception:
        outcomes_text = "unknown"

    markets_text = "\n".join(markets_text_lines) if markets_text_lines else "none provided"

    current_datetime = datetime.now().isoformat()

    system_prompt = get_forecast_system_prompt(
        current_datetime=current_datetime,
        signature="claude",
        event_title=title,
        close_time=close_time,
        outcomes_text=outcomes_text,
        event_description=event_description,
        markets_text=markets_text,
    )
    print(system_prompt)

if __name__ == "__main__":
    main()