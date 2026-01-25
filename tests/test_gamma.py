import httpx

GAMMA = "https://gamma-api.polymarket.com"

def fetch_latest_active_markets(limit=100, offset=0):
    # “通过 Events 获取所有活跃市场”是官方推荐做法
    # 关键参数：order=id, ascending=false, closed=false
    params = {
        "order": "id",
        "ascending": "false",
        "closed": "false",
        "limit": str(limit),
        "offset": str(offset),
    }
    r = httpx.get(f"{GAMMA}/events", params=params, timeout=15.0)
    r.raise_for_status()
    events = r.json()
    # 将事件里的所有 markets 摊平成列表
    markets = []
    for ev in events:
        for m in ev.get("markets", []):
            m["event_id"] = ev.get("id")
            markets.append(m)
    return markets

if __name__ == "__main__":
    markets = fetch_latest_active_markets(limit=100, offset=0)
    print(markets[-1])