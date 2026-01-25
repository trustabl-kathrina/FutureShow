import requests
from typing import List, Optional, Dict

BASE = "https://gamma-api.polymarket.com"


def _event_category(e: dict) -> str:
    """提取事件类别：优先用 event.category；否则从 tags 推断。
    仅用于均衡分配，类别集合可按需扩展。
    """
    c = (e.get("category") or "").strip()
    if c:
        return c
    raw_tags = e.get("tags") or []
    tag_texts: List[str] = []
    for t in raw_tags:
        if isinstance(t, dict):
            tag_texts.append(str(t.get("label") or t.get("slug") or "").lower())
        else:
            tag_texts.append(str(t).lower())

    # 同时纳入标题/问题/slug，帮助在缺少 tag 时识别
    title_blob = " ".join([
        str(e.get("title") or ""),
        str(e.get("question") or ""),
        str(e.get("slug") or ""),
    ]).lower()
    haystack = tag_texts + [title_blob]

    def any_in(keys: List[str]) -> bool:
        return any(any(k in tt for k in keys) for tt in haystack)

    # 细分并尽量覆盖 Polymarket 常见领域
    if any_in(["parlay", "parlays", "games"]):
        return "Games"

    # ——— 体育细分（先匹配细分，最后再兜底到 Sports） ———
    if any_in(["premier league", "epl", "la liga", "bundesliga", "serie a", "ligue 1", "ucl",
               "champions league", "liga mx", "eredivisie", "k-league", "süper lig", "saudi professional league",
               "j league", "japan j league", "soccer"]):
        return "Soccer"
    if any_in(["nba", "basketball"]):
        return "Basketball"
    if any_in(["nfl"]):
        return "American Football"
    if any_in(["mlb", "baseball"]):
        return "Baseball"
    if any_in(["nhl", "hockey"]):
        return "Hockey"
    if any_in(["tennis"]):
        return "Tennis"
    if any_in(["golf"]):
        return "Golf"
    if any_in(["ufc", "mma"]):
        return "MMA"
    if any_in(["f1", "formula 1", "motorsport", "motogp"]):
        return "Motorsport"
    if any_in(["esports", "counter strike", "counter strike 2", "cs2", "dota 2", "league of legends", "valorant", "overwatch"]):
        return "Esports"
    if any_in(["sports", "sport", "cricket", "rugby", "chess"]):
        return "Sports"

    # 选举单列
    if any_in(["election", "elections", "vote", "ballot", "primary", "runoff", "referendum"]):
        return "Elections"

    # 政治（细分 + 兜底）
    if any_in(["u.s. politics", "us politics", "president", "presidency", "congress", "senate", "house", "governor", "cabinet", "maga"]):
        return "US Politics"
    if any_in(["politics", "global elections", "world politics"]):
        return "Politics"

    # 加密
    if any_in([
        "crypto", "crypto prices", "bitcoin", "btc", "ethereum", "eth",
        "solana", "sol", "xrp", "ripple", "doge"
    ]):
        return "Crypto"

    # 司法/法律
    if any_in([
        "courts", "court", "lawsuit", "trial", "indictment", "plea",
        "conviction", "scotus", "supreme court", "january 6", "jan 6"
    ]):
        return "Legal"

    # 国际与地缘政治
    if any_in([
        "geopolitics", "world", "foreign policy", "middle east", "ukraine", "russia",
        "israel", "iran", "nato", "eu", "yemen", "war", "conflict", "sanctions",
        "security guarantee"
    ]):
        return "Geopolitics"

    # 金融市场（公司/资产/ETF 等）
    if any_in([
        "finance", "business", "stocks", "stock", "equities", "etf",
        "treasury", "bond", "valuation", "ipo", "market cap"
    ]):
        return "Finance"

    # 宏观经济
    if any_in([
        "economy", "economics", "inflation", "interest rate", "fed", "federal reserve",
        "unemployment", "jobs", "gdp", "cpi", "pce"
    ]):
        return "Economics"

    # 科技/AI/互联网
    if any_in(["ai", "artificial intelligence", "gpt", "openai", "model", "llm"]):
        return "AI"
    if any_in([
        "tech", "technology", "startup", "internet"
    ]):
        return "Tech"

    # 文化/娱乐细分
    if any_in(["celebrities", "celebrity", "gossip", "mrbeast", "diddy", "roy lee", "elon musk"]):
        return "Celebrities"
    if any_in(["music", "album", "song", "billboard", "spotify"]):
        return "Music"
    if any_in(["film", "movie", "box office", "tv", "series", "netflix", "disney", "hbo", "prime video"]):
        return "Film & TV"
    if any_in(["awards", "oscars", "grammy", "emmys", "eurovision"]):
        return "Awards"
    if any_in(["culture", "entertainment", "creators", "barstool", "startup culture"]):
        return "Culture"

    # 社媒热度/提及数
    if any_in([
        "mentions", "social media", "twitter", "x", "youtube", "tiktok", "instagram",
        "followers", "subscribers", "views"
    ]):
        return "Mentions"

    # 天气/自然事件
    if any_in([
        "weather", "hurricane", "storm", "tornado", "rain", "snow", "snowfall",
        "heatwave", "temperature", "el nino", "wildfire", "fire", "flood"
    ]):
        return "Weather"

    # 健康/医疗
    if any_in(["health", "medicine", "medical", "disease", "virus", "covid", "flu", "vaccine"]):
        return "Health"

    # 科学/航天
    if any_in(["science", "space", "nasa", "spacex", "rocket", "satellite", "launch", "mars", "moon", "asteroid", "comet"]):
        return "Science"

    return "Other"


def _event_volume(e: dict) -> float:
    """尽量取 24h 成交量；缺失则回退到总成交额/订单簿成交额。"""
    for k in [
        "volume24hr", "volume24h", "volume24H",
        "dayVolumeUSD", "dailyVolumeUSD",
        "volumeClob", "volume"
    ]:
        v = e.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return 0.0


def get_trending_events(limit: int = 1000,
                        per_category: int = 10,
                        categories: Optional[List[str]] = None) -> List[dict]:
    """
    一次拉取全量 events（active=true, closed=false），然后：
    1) 为每个事件识别类别；
    2) 各类别均等抽样 per_category 条（按成交量降序挑选）；
    3) 合并后整体按成交量降序输出。
    """
    params = {
        "active": "true",
        "closed": "false",
        # 让后端尽量按 24h 成交量靠前返回，减少我们二次排序压力
        "order": "volume24hr,openInterest,commentCount",
        "ascending": "false",
        "limit": str(limit),
    }

    # 一些环境对默认 UA 会返回 403，这里加上浏览器风格 headers
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
        "Accept": "application/json",
    }
    r = requests.get(f"{BASE}/events", params=params, headers=headers, timeout=25)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        events = payload.get("data") or payload.get("events") or []
    else:
        events = payload or []

    # 注入辅助字段
    for e in events:
        e["_category"] = _event_category(e)
        e["_vol"] = _event_volume(e)

    # 确定需要的类别集合
    wanted: List[str]
    if categories:
        wanted = list(dict.fromkeys(categories))  # 去重保序
    else:
        wanted = sorted({str(e.get("_category") or "Other") for e in events})

    # 分组并按成交量排序
    grouped: Dict[str, List[dict]] = {c: [] for c in wanted}
    for e in events:
        c = str(e.get("_category") or "Other")
        if c in grouped:
            grouped[c].append(e)
    for c in grouped:
        grouped[c].sort(key=lambda x: x.get("_vol", 0.0), reverse=True)

    # 各类别均等抽样
    picked: List[dict] = []
    for c in wanted:
        picked.extend(grouped.get(c, [])[:max(0, int(per_category))])

    # 最终按成交量降序
    picked.sort(key=lambda x: x.get("_vol", 0.0), reverse=True)
    return picked


if __name__ == "__main__":
    events = get_trending_events(limit=3000, per_category=10)
    for i, ev in enumerate(events, 1):
        print(f"{i:02d}. {ev.get('slug')} | vol={ev.get('_vol')} | OI={ev.get('openInterest')} | cat={ev.get('_category')} | {ev.get('title')}")
