from datetime import datetime
from zoneinfo import ZoneInfo
import json

ET = ZoneInfo("America/New_York")

def _parse_iso(s: str | None):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _et_window(start_iso: str | None, end_iso: str | None) -> str:
    s = _parse_iso(start_iso)
    e = _parse_iso(end_iso)
    if not (s and e):
        return ""
    s_et = s.astimezone(ET)
    e_et = e.astimezone(ET)
    return f"{s_et.strftime('%b %d %H:%M')}–{e_et.strftime('%H:%M')} ET"

def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def _fmt_money(x):
    f = _safe_float(x)
    return f"${f:,.2f}" if f is not None else "-"

def _to_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return []

def _format_outcomes(names_raw, prices_raw):
    names = _to_list(names_raw)
    prices = [_safe_float(p) for p in _to_list(prices_raw)]
    parts = []
    for i, name in enumerate(names):
        p = prices[i] if i < len(prices) else None
        parts.append(f"{name}:{p:.2f}" if p is not None else f"{name}:--")
    return "[" + ", ".join(parts) + "]" if parts else "[]"

def _orderbook(m):
    bb = _safe_float(m.get("bestBid"))
    ba = _safe_float(m.get("bestAsk"))
    mid = ((bb + ba) / 2) if (bb is not None and ba is not None) else None
    spr = (ba - bb) if (bb is not None and ba is not None) else None
    return bb, ba, mid, spr

def _token_prices_top3(m):
    tokens = m.get("tokens") or []
    prices = []
    for t in tokens:
        p = t.get("price")
        if p is not None:
            try:
                prices.append(float(p))
            except Exception:
                continue
        if len(prices) >= 3:
            break
    return prices

def format_market_line_original(m: dict) -> str:
    slug = m.get("slug") or m.get("ticker") or "-"
    question = m.get("question") or m.get("title") or "-"
    active = m.get("active")
    accepting = m.get("acceptingOrders", True)
    restricted = m.get("restricted")
    eventStartTime = m.get("eventStartTime") or m.get("startDate")
    endDate = m.get("endDate")
    timeWindowET = _et_window(eventStartTime, endDate)  # 衍生字段，不替代原名
    liquidity = m.get("liquidity")
    liquidityClob = m.get("liquidityClob")
    outcomes = m.get("outcomes")
    outcomePrices = m.get("outcomePrices")
    bb, ba, mid, spr = _orderbook(m)
    prices = _token_prices_top3(m)

    parts = [
        f"- slug={slug}",
        f"active={active} acceptingOrders={accepting} restricted={restricted}",
        f"eventStartTime={eventStartTime} endDate={endDate}",
    ]
    if timeWindowET:
        parts.append(f"timeWindowET={timeWindowET}")
    if liquidity is not None:
        parts.append(f"liquidity={_fmt_money(liquidity)}")
    if liquidityClob is not None:
        parts.append(f"liquidityClob={_fmt_money(liquidityClob)}")
    if bb is not None and ba is not None:
        parts.append(f"bestBid={bb:.2f} bestAsk={ba:.2f}")
    if mid is not None:
        parts.append(f"mid={mid:.2f}")
    if spr is not None:
        parts.append(f"spread={spr:.2f}")
    # 原字段名保留：outcomes / outcomePrices
    parts.append(f"outcomes={_to_list(outcomes) if isinstance(outcomes, list) else _to_list(outcomes)}")
    # 友好展示 outcomePrices（保留原名）
    pretty_prices = [_safe_float(p) for p in _to_list(outcomePrices)]
    parts.append(f"outcomePrices={[None if p is None else round(p, 4) for p in pretty_prices]}")
    # 保留你原先的 tokens->prices 汇总名
    parts.append(f"prices={prices}")
    parts.append(f"question={question}")
    return " | ".join(parts)

def format_market_card_original(m: dict) -> str:
    """多行卡片样式，左侧 label 使用原字段名；派生量单独标注，不覆盖原名。"""
    slug = m.get("slug") or m.get("ticker") or "-"
    question = m.get("question") or m.get("title") or "-"
    active = m.get("active")
    accepting = m.get("acceptingOrders", True)
    restricted = m.get("restricted")
    eventStartTime = m.get("eventStartTime") or m.get("startDate")
    endDate = m.get("endDate")
    timeWindowET = _et_window(eventStartTime, endDate)
    liquidity = m.get("liquidity")
    liquidityClob = m.get("liquidityClob")
    outcomes = m.get("outcomes")
    outcomePrices = m.get("outcomePrices")
    bb, ba, mid, spr = _orderbook(m)
    prices = _token_prices_top3(m)

    lines = [
        f"slug: {slug}",
        f"question: {question}",
        f"active: {active}",
        f"acceptingOrders: {accepting}",
        f"restricted: {restricted}",
        f"eventStartTime: {eventStartTime}",
        f"endDate: {endDate}",
    ]
    if timeWindowET:
        lines.append(f"timeWindowET: {timeWindowET}")  # 派生
    if liquidity is not None:
        lines.append(f"liquidity: {_fmt_money(liquidity)}")
    if liquidityClob is not None:
        lines.append(f"liquidityClob: {_fmt_money(liquidityClob)}")
    if bb is not None and ba is not None:
        lines.append(f"bestBid: {bb:.2f}")
        lines.append(f"bestAsk: {ba:.2f}")
    if mid is not None:
        lines.append(f"mid: {mid:.2f}")               # 派生
    if spr is not None:
        lines.append(f"spread: {spr:.2f}")            # 派生
    lines.append(f"outcomes: {_to_list(outcomes) if isinstance(outcomes, list) else _to_list(outcomes)}")
    pretty_prices = [_safe_float(p) for p in _to_list(outcomePrices)]
    lines.append(f"outcomePrices: {[None if p is None else round(p, 4) for p in pretty_prices]}")
    lines.append(f"prices: {prices}")                 # 你原先聚合的 tokens 价格 Top3
    return "\n".join(lines)

def summarize_snap(snap: list[dict], detailed: bool = False) -> str:
    lines = []
    for m in snap:
        lines.append(format_market_card_original(m) if detailed else format_market_line_original(m))
    return "\n".join(lines)

if __name__ == "__main__":
    from futureshow.tool.tool_polymarket_data import list_markets
    from agents.tool_context import ToolContext
    import asyncio
    args = dict(query=None, limit=100, only_open=True, only_active=False, only_liquid=True, only_accepting=True, trending_only = True, page = 0)
    ctx = ToolContext(
        context=None,
        tool_name="list_markets",
        tool_call_id="get-market-preview",
        tool_arguments=json.dumps(args)
    )
    snap = asyncio.run(list_markets.on_invoke_tool(
            ctx,
            json.dumps(args)
        )
    )
    snap = snap[20:25]
    print(summarize_snap(snap, detailed=True))