from typing import Dict, Any, Optional, List, Iterable
import os
import logging
import requests
from fastmcp import FastMCP
from dotenv import load_dotenv
import sys
import os as _os
from datetime import datetime, timezone, timedelta
import json
from agents import function_tool
try:
    from futureshow.utils.private_filter import filter_events as apply_private_filters
except ImportError:
    apply_private_filters = lambda x: x

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"

mcp = FastMCP("PolymarketData")


# Optional: py_clob_client for richer market metadata/status
try:
    from py_clob_client.client import ClobClient  # type: ignore
    from py_clob_client.constants import POLYGON  # type: ignore
    HAS_CLOB = True
except Exception:  # pragma: no cover - optional dependency
    ClobClient = None  # type: ignore
    POLYGON = None  # type: ignore
    HAS_CLOB = False


def get_clob_client() -> Optional["ClobClient"]:
    if not HAS_CLOB:
        return None
    host = os.getenv("CLOB_HOST", BASE_URL)
    key = os.getenv("KEY")
    funder = os.getenv("FUNDER")
    if not key:
        return None
    try:
        client = ClobClient(
            host,
            key=key,
            chain_id=POLYGON,
            funder=funder,
            signature_type=1,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        return client
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to init ClobClient: %s", e)
        return None


def _fetch_latest_active_markets_from_gamma(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Fetch active markets via Gamma Events API ordered by id desc and flatten markets.

    Gamma 推荐通过 /events 获取活跃市场：order=id, ascending=false, closed=false
    """
    params: Dict[str, Any] = {
        "order": "id",
        "ascending": "false",
        "closed": "false",
        "limit": str(limit),
        "offset": str(offset),
    }
    r = requests.get(f"{GAMMA}/events", params=params, timeout=15)
    r.raise_for_status()
    events = r.json()
    markets: List[Dict[str, Any]] = []
    if isinstance(events, dict):
        events_iter = events.get("data") or events.get("events") or []
    else:
        events_iter = events or []
    for ev in events_iter:
        ev_id = ev.get("id")
        ev_tags = ev.get("tags")
        for m in ev.get("markets", []) or []:
            mm = dict(m)
            mm["event_id"] = ev_id
            # 传播 tags 方便后续本地筛选
            if ev_tags is not None and not mm.get("tags"):
                mm["tags"] = ev_tags
            markets.append(mm)
    return markets

def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None

    try:
        # 2023-03-15T00:00:00Z format
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        lv = v.strip().lower()
        if lv in ("true", "yes", "1", "y"): return True
        if lv in ("false", "no", "0", "n", ""): return False
    return bool(v)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_dir(path: str) -> None:
    try:
        _os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _default_cache_dir() -> str:
    # data/cache/polymarket_markets 相对仓库根目录
    base = _os.getenv("POLYMARKET_CACHE_DIR")
    if base:
        return base
    here = _os.path.abspath(_os.path.dirname(__file__))
    root = _os.path.normpath(_os.path.join(here, "..", ".."))
    return _os.path.join(root, "data", "cache", "polymarket_markets")


def _safe_slug_filename(slug: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(slug))
    if len(safe) > 200:
        safe = safe[:200]
    return f"{safe}.json"


def _cache_read(slug: str, cache_dir: str, ttl_minutes: int) -> Optional[Dict[str, Any]]:
    try:
        path = _os.path.join(cache_dir, _safe_slug_filename(slug))
        if not _os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts_str = data.get("_cachedAt")
        if not ts_str:
            return data
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            return data
        age = (_now_utc() - ts).total_seconds() / 60.0
        if age <= max(0, int(ttl_minutes or 0)):
            return data
        return None
    except Exception:
        return None


def _cache_write(slug: str, cache_dir: str, payload: Dict[str, Any]) -> None:
    try:
        _ensure_dir(cache_dir)
        path = _os.path.join(cache_dir, _safe_slug_filename(slug))
        data = dict(payload)
        data["_cachedAt"] = _now_utc().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _extract_volume_field(m: Dict[str, Any]) -> Optional[float]:
    """从多种可能字段中提取成交量（美元）。"""
    def to_float(x: Any) -> Optional[float]:
        try:
            if x is None:
                return None
            return float(x)
        except Exception:
            return None

    candidates = [
        m.get("volume"),
        m.get("vol"),
        m.get("totalVolumeUSD"),
        m.get("totalVolumeUsd"),
        m.get("total_volume_usd"),
        m.get("total_volume"),
        m.get("volume24h"),
        m.get("volume24H"),
        m.get("volume24Hr"),
        m.get("dailyVolumeUSD"),
        m.get("dayVolumeUSD"),
    ]
    for v in candidates:
        fv = to_float(v)
        if fv is not None:
            return fv
    return None


def _fetch_market_by_slug_cached(slug: str, cache_dir: str, ttl_minutes: int) -> Optional[Dict[str, Any]]:
    # 先读缓存
    cached = _cache_read(slug, cache_dir, ttl_minutes=ttl_minutes)
    if isinstance(cached, dict) and cached:
        return cached
    # 请求 Gamma（重用函数工具实现）
    m = get_market_info_fn(slug)
    if isinstance(m, dict) and m and "error" not in m:
        _cache_write(slug, cache_dir, m)
        return m
    return None


def _filter_markets(
    data: List[Dict[str, Any]],
    *,
    query: Optional[str],
    closed: Optional[bool],
    active: Optional[bool],
    tag: Optional[str],
    tags_any: Optional[List[str]] = None,
    tags_all: Optional[List[str]] = None,
    exclude_tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    def match(m: Dict[str, Any]) -> bool:
        if query:
            q = (
                (m.get("question") or m.get("title") or m.get("name") or "")
                + " "
                + (m.get("description") or "")
            )
            if query.lower() not in q.lower():
                return False
        if closed is not None and bool(m.get("closed")) != closed:
            return False
        if active is not None and bool(m.get("active")) != active:
            return False
        tags = m.get("tags") or []
        tags_lc = [str(t).lower() for t in tags]
        if tag:
            if not any(tag.lower() in t for t in tags_lc):
                return False
        if tags_any:
            if not any(any(tk.lower() in t for t in tags_lc) for tk in tags_any):
                return False
        if tags_all:
            if not all(any(tk.lower() in t for t in tags_lc) for tk in tags_all):
                return False
        if exclude_tags:
            if any(any(x.lower() in t for t in tags_lc) for x in exclude_tags):
                return False
        return True

    return [m for m in data if match(m)]

@function_tool
def list_markets(
    query: Optional[str] = None,
    tags_any: Optional[List[str]] = None,
    tags_all: Optional[List[str]] = None,
    exclude_tags: Optional[List[str]] = None,
    limit: int = 100,
    page: int = 0,
    page_size: int = 100,
    fetch_pages: int = 1,
    only_open: bool = True,
    only_active: bool = True,
    only_accepting: bool = False,
    only_liquid: bool = False,
    sort: str = "volume_desc",
    trending_only: bool = False,
    trending_window_hours: Optional[int] = 24,
    min_liquidity: Optional[float] = None,
    exact_volume: bool = True,
    volume_cache_ttl_minutes: int = 60,
    cache_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List Polymarket markets (via Gamma Events API) with client-side filters.

    Parameters
    - query: Substring match over question/title/description.
    - tags_any: Keep if ANY of these substrings appear in market tags.
    - tags_all: Keep only if ALL of these substrings appear in market tags.
    - exclude_tags: Exclude if ANY of these substrings appear in market tags.
    - limit: Max items returned after all filters, dedupe and sorting.
    - page: Page index for manual pagination over Gamma events (0-based).
    - page_size: Page size for manual pagination.
    - fetch_pages: Number of pages to fetch starting from "page".
    - only_open: Exclude markets marked closed.
    - only_active: Prefer markets with status "active" (fallback to active flag).
    - only_accepting: Keep markets accepting orders.
    - only_liquid: Keep markets with basic liquidity signal (bb/ba/liquidity present).
    - sort: 支持以下取值（默认 volume_desc）：
        - "gamma"（保持 Gamma 原始返回顺序）
        - "end_date_asc" / "end_date_desc"
        - "updatedAt_desc" / "createdAt_desc"
        - "volume_desc" / "volume_asc"（优先使用 volume/totalVolumeUSD/volume24h；缺失时回退 liquidityClob/liquidity）
        - "liquidity_desc" / "liquidity_asc"
        - "mid_desc" / "mid_asc"（中间价）
        - "bestBid_desc" / "bestBid_asc"
        - "bestAsk_desc" / "bestAsk_asc"
    - trending_only: Keep markets updated recently or with high liquidity.
    - trending_window_hours: Recency window for trending (default 24h).
    - min_liquidity: Treat markets with liquidity/liquidityClob >= this as trending.
    - exact_volume: 若 True，按 volume 排序会逐个拉取 /markets/slug/{slug} 精准补齐成交量并落盘缓存。
    - volume_cache_ttl_minutes: 本地缓存有效期（分钟），默认 60。
    - cache_dir: 缓存目录（默认 data/cache/polymarket_markets，也可用 POLYMARKET_CACHE_DIR 指定）。

    Returns
    - List of market objects as returned by Gamma (with minimal local reshaping).
    """
    # 通过 Gamma Events 拉取在营市场（按 id 倒序），支持手动分页
    # 基础抓取规模：优先使用 page_size，否则按 limit*2 回退
    base_size = int(page_size) if int(page_size or 0) > 0 else max(limit * 2, 100)
    base_offset = max(0, int(page or 0) * base_size)
    items: List[Dict[str, Any]] = []
    pages = max(1, int(fetch_pages or 1))
    for i in range(pages):
        off = base_offset + i * base_size
        chunk = _fetch_latest_active_markets_from_gamma(limit=base_size, offset=off)
        if not chunk:
            break
        items.extend(chunk)

    filtered = _filter_markets(
        items,
        query=query,
        closed=None,
        active=None,
        tag=None,
        tags_any=tags_any,
        tags_all=tags_all,
        exclude_tags=exclude_tags,
    )
    # Filters
    if only_open:
        # Note: 'closed' 字段在 CLOB 数据中不稳定，仅在显式要求时使用
        filtered = [m for m in filtered if not _as_bool(m.get("closed"))]
    if only_active:
        # Prefer explicit status if present
        def is_active(m: Dict[str, Any]) -> bool:
            ms = str(m.get("status", "")).strip().lower()
            if ms:
                return ms == "active"
            return _as_bool(m.get("active"))
        filtered = [m for m in filtered if is_active(m)]
    if only_accepting:
        def is_accepting(m: Dict[str, Any]) -> bool:
            v = m.get("accepting_orders")
            if v is None:
                v = m.get("acceptingOrders", True)
            return _as_bool(v)
        filtered = [m for m in filtered if is_accepting(m)]
    # Exclude archived by default
    filtered = [m for m in filtered if not _as_bool(m.get("archived"))]

    # Trending heuristic (optional)
    if trending_only:
        now = datetime.now(timezone.utc)
        cutoff = None
        try:
            if trending_window_hours is not None:
                cutoff = now - timedelta(hours=int(trending_window_hours))
        except Exception:
            cutoff = None

        def is_trending(m: Dict[str, Any]) -> bool:
            # recent update or high liquidity
            updated = _parse_date(m.get("updatedAt")) or _parse_date(m.get("createdAt"))
            if updated and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            liq = m.get("liquidityClob") or m.get("liquidity")
            try:
                liqf = float(liq) if liq is not None else None
            except Exception:
                liqf = None
            cond_recent = (cutoff is not None and updated is not None and updated >= cutoff)
            cond_liq = (min_liquidity is not None and liqf is not None and liqf >= float(min_liquidity))
            return bool(cond_recent or cond_liq)

        filtered = [m for m in filtered if is_trending(m)]

    # Keep only liquid outcomes if requested (0<p<1)
    if only_liquid:
        def to_float(x: Any) -> Optional[float]:
            try:
                if x is None:
                    return None
                return float(x)
            except Exception:
                return None
        tmp: List[Dict[str, Any]] = []
        for m in filtered:
            bb = to_float(m.get("bestBid"))
            ba = to_float(m.get("bestAsk"))
            liq = to_float(m.get("liquidityClob")) or to_float(m.get("liquidity"))
            liquid = False
            if bb is not None and 0.0 < bb < 1.0:
                liquid = True
            if ba is not None and 0.0 < ba < 1.0:
                liquid = True
            if liq is not None and liq > 0:
                liquid = True
            if liquid:
                tmp.append(m)
        filtered = tmp

    # Secondary offset removed in simplified API (kept upstream pagination instead)

    # Deduplicate by key if requested
    # Deduplicate on slug/market_slug/id
    seen = set()
    uniq = []
    for m in filtered:
        key = m.get("market_slug") or m.get("slug") or m.get("id")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(m)
    filtered = uniq

    # 在按成交量排序时，若需要精准 volume，则先补齐 volume（读缓存-请求-落盘）
    need_exact_volume = (sort in ("volume_desc", "volume_asc")) and bool(exact_volume)
    if need_exact_volume and filtered:
        cdir = cache_dir or _default_cache_dir()
        for m in filtered:
            slug = m.get("market_slug") or m.get("slug")
            if not slug:
                continue
            info = _fetch_market_by_slug_cached(slug, cdir, ttl_minutes=int(volume_cache_ttl_minutes or 0))
            if not isinstance(info, dict) or not info:
                continue
            vol = _extract_volume_field(info)
            if vol is not None:
                try:
                    m["volume"] = float(vol)
                except Exception:
                    pass
            # 也把一些常见 volume 相关字段补齐，便于前端展示
            for k in ("totalVolumeUSD", "totalVolumeUsd", "volume24h", "volume24H"):
                if info.get(k) is not None and m.get(k) is None:
                    m[k] = info.get(k)

    # 排序：默认按成交量降序（volume_desc）；其他选项见参数说明
    if sort and sort != "gamma":
        def _to_float(x: Any) -> Optional[float]:
            try:
                if x is None:
                    return None
                return float(x)
            except Exception:
                return None

        def _volume_like(m: Dict[str, Any]) -> float:
            """尽量从多种可能的字段提取成交量；否则回退到流动性。

            说明：Gamma 的不同接口在 volume 字段名上可能不一致，这里做宽松兜底。
            """
            candidates = [
                m.get("volume"),
                m.get("vol"),
                m.get("totalVolumeUSD"),
                m.get("totalVolumeUsd"),
                m.get("volume24h"),
                m.get("volume24H"),
                m.get("volume24Hr"),
                m.get("dailyVolumeUSD"),
                m.get("dayVolumeUSD"),
            ]
            for v in candidates:
                fv = _to_float(v)
                if fv is not None:
                    return fv
            # 回退到流动性作为“人气近似”
            liq = _to_float(m.get("liquidityClob")) or _to_float(m.get("liquidity"))
            return liq if liq is not None else -1.0

        def _liquidity(m: Dict[str, Any]) -> float:
            liq = _to_float(m.get("liquidityClob"))
            if liq is None:
                liq = _to_float(m.get("liquidity"))
            return liq if liq is not None else -1.0

        def _mid(m: Dict[str, Any]) -> float:
            v = _to_float(m.get("mid"))
            if v is not None:
                return v
            bb = _to_float(m.get("bestBid"))
            ba = _to_float(m.get("bestAsk"))
            if bb is not None and ba is not None:
                try:
                    return (bb + ba) / 2.0
                except Exception:
                    pass
            return -1.0

        if sort.startswith("end_date"):
            rev = sort.endswith("desc")
            def sort_key(m: Dict[str, Any]):
                dt = _parse_date(
                    m.get("end_date_iso")
                    or m.get("endDate")
                    or m.get("closeDate")
                )
                if dt is None:
                    return datetime.max.replace(tzinfo=timezone.utc)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
            filtered.sort(key=sort_key, reverse=rev)
        elif sort == "updatedAt_desc":
            def parse_updated(m: Dict[str, Any]) -> datetime:
                dt = _parse_date(m.get("updatedAt"))
                if dt is None:
                    return datetime.min.replace(tzinfo=timezone.utc)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            filtered.sort(key=parse_updated, reverse=True)
        elif sort == "createdAt_desc":
            def parse_created(m: Dict[str, Any]) -> datetime:
                dt = _parse_date(m.get("createdAt"))
                if dt is None:
                    return datetime.min.replace(tzinfo=timezone.utc)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            filtered.sort(key=parse_created, reverse=True)
        elif sort in ("volume_desc", "volume_asc"):
            rev = sort.endswith("desc")
            filtered.sort(key=_volume_like, reverse=rev)
        elif sort in ("liquidity_desc", "liquidity_asc"):
            rev = sort.endswith("desc")
            filtered.sort(key=_liquidity, reverse=rev)
        elif sort in ("mid_desc", "mid_asc"):
            rev = sort.endswith("desc")
            filtered.sort(key=_mid, reverse=rev)
        elif sort in ("bestBid_desc", "bestBid_asc"):
            rev = sort.endswith("desc")
            filtered.sort(key=lambda m: _to_float(m.get("bestBid")) or -1.0, reverse=rev)
        elif sort in ("bestAsk_desc", "bestAsk_asc"):
            # 注意：ask 越小越“便宜”，按数值排序只是展示需要
            rev = sort.endswith("desc")
            filtered.sort(key=lambda m: _to_float(m.get("bestAsk")) or -1.0, reverse=rev)

    # 返回保留原始 Gamma 市场对象（含 event_id），仅做切片
    return filtered[: max(1, min(limit, len(filtered)) )]

# -------------------- Events listing (balanced by categories) --------------------

def _event_tag_texts(ev: Dict[str, Any]) -> List[str]:
    tags = ev.get("tags") or []
    out: List[str] = []
    for t in tags:
        if isinstance(t, dict):
            out.append(str(t.get("label") or t.get("slug") or "").strip().lower())
        else:
            out.append(str(t).strip().lower())
    return [s for s in out if s]

def _event_category(ev: Dict[str, Any]) -> str:
    """尽量和 tests/test_gamma_2.py 的规则保持一致，并做小幅补充。
    优先使用 event.category；否则结合 tags/title/question/slug 推断。
    """
    c = (ev.get("category") or "").strip()
    if c:
        return c
    tag_texts = _event_tag_texts(ev)
    title_blob = " ".join([
        str(ev.get("title") or ""),
        str(ev.get("question") or ""),
        str(ev.get("slug") or ""),
    ]).lower()
    haystack = tag_texts + [title_blob]

    def any_in(keys: List[str]) -> bool:
        return any(any(k in tt for k in keys) for tt in haystack)

    # Games / Parlays
    if any_in(["parlay", "parlays", "games"]):
        return "Games"

    # 体育细分
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

    # 政治
    if any_in(["u.s. politics", "us politics", "president", "presidency", "congress", "senate", "house", "governor", "cabinet", "maga"]):
        return "US Politics"
    if any_in(["politics", "global elections", "world politics"]):
        return "Politics"

    # 加密
    if any_in(["crypto", "crypto prices", "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "ripple", "doge"]):
        return "Crypto"

    # 法律
    if any_in(["courts", "court", "lawsuit", "trial", "indictment", "plea", "conviction", "scotus", "supreme court", "january 6", "jan 6"]):
        return "Legal"

    # 地缘政治
    if any_in(["geopolitics", "world", "foreign policy", "middle east", "ukraine", "russia", "israel", "iran", "nato", "eu", "yemen", "war", "conflict", "sanctions", "security guarantee"]):
        return "Geopolitics"

    # 金融
    if any_in(["finance", "business", "stocks", "stock", "equities", "etf", "treasury", "bond", "valuation", "ipo", "market cap"]):
        return "Finance"

    # 宏观经济
    if any_in(["economy", "economics", "inflation", "interest rate", "fed", "federal reserve", "unemployment", "jobs", "gdp", "cpi", "pce"]):
        return "Economics"

    # AI / Tech
    if any_in(["ai", "artificial intelligence", "gpt", "openai", "model", "llm"]):
        return "AI"
    if any_in(["tech", "technology", "startup", "internet"]):
        return "Tech"

    # 文化娱乐细分（含名人关系关键词优先）
    if any_in(["divorce", "marriage", "married", "engaged", "engagement", "break up", "breakup", "rehab"]):
        return "Celebrities"
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

    # 社媒
    if any_in(["mentions", "social media", "twitter", "x", "youtube", "tiktok", "instagram", "followers", "subscribers", "views"]):
        return "Mentions"

    # 天气
    if any_in(["weather", "hurricane", "storm", "tornado", "rain", "snow", "snowfall", "heatwave", "temperature", "el nino", "wildfire", "fire", "flood"]):
        return "Weather"

    # 健康
    if any_in(["health", "medicine", "medical", "disease", "virus", "covid", "flu", "vaccine"]):
        return "Health"

    # 科学/航天
    if any_in(["science", "space", "nasa", "spacex", "rocket", "satellite", "launch", "mars", "moon", "asteroid", "comet"]):
        return "Science"

    return "Other"

def _event_volume(ev: Dict[str, Any]) -> float:
    for k in [
        "volume24hr", "volume24h", "volume24H",
        "dayVolumeUSD", "dailyVolumeUSD",
        "volumeClob", "volume"
    ]:
        v = ev.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return 0.0

def _to_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return [v]
    if isinstance(v, (tuple, set)):
        return list(v)
    return [v]

def _event_current_prob(ev: Dict[str, Any]) -> Optional[float]:
    """从事件的第一个二元市场估计当前概率（优先取 Yes/Up 价格，其次取最高价/中间价）。"""
    markets = ev.get("markets") or []
    for m in markets:
        outcomes = _to_list(m.get("outcomes"))
        prices = _to_list(m.get("outcomePrices"))
        try:
            prices_f = [float(x) for x in prices if x is not None]
        except Exception:
            prices_f = []
        if outcomes and prices_f and len(outcomes) == len(prices_f) and 2 <= len(outcomes) <= 3:
            prob = None
            for name, p in zip(outcomes, prices_f):
                nm = str(name).strip().lower()
                if nm in ("yes", "y", "true", "1", "up"):
                    prob = p
                    break
            if prob is None:
                prob = max(prices_f) if prices_f else None
            if prob is not None:
                try:
                    return max(0.0, min(1.0, float(prob)))
                except Exception:
                    pass
        try:
            mid = m.get("mid")
            if mid is not None:
                return max(0.0, min(1.0, float(mid)))
        except Exception:
            pass
        try:
            bb = m.get("bestBid")
            if bb is not None:
                return max(0.0, min(1.0, float(bb)))
        except Exception:
            pass
        try:
            ba = m.get("bestAsk")
            if ba is not None:
                return max(0.0, min(1.0, 1.0 - float(ba)))
        except Exception:
            pass
    return None

def _filter_events(
    data: List[Dict[str, Any]],
    *,
    query: Optional[str],
    tags_any: Optional[List[str]] = None,
    tags_all: Optional[List[str]] = None,
    exclude_tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    def match(ev: Dict[str, Any]) -> bool:
        if query:
            q = (str(ev.get("title") or ev.get("question") or ev.get("slug") or "")).lower()
            if query.lower() not in q:
                return False
        tag_texts = _event_tag_texts(ev)
        if tags_any:
            if not any(any(tk.lower() in t for t in tag_texts) for tk in tags_any):
                return False
        if tags_all:
            if not all(any(tk.lower() in t for t in tag_texts) for tk in tags_all):
                return False
        if exclude_tags:
            if any(any(x.lower() in t for t in tag_texts) for x in exclude_tags):
                return False
        return True

    return [ev for ev in data if match(ev)]

@function_tool
def list_events(
    query: Optional[str] = None,
    tags_any: Optional[List[str]] = None,
    tags_all: Optional[List[str]] = None,
    exclude_tags: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    limit: int = 3000,
    per_category: int = 10,
    detailed: bool = True,
) -> List[str]:
    """List active Polymarket events with category-balanced sampling and return
    readable lines.

    Description:
    - Fetch active and open events from Gamma `/events`, ordered primarily by
      24h volume and related signals.
    - Apply keyword and tag-based filtering.
    - Perform balanced sampling across categories (up to `per_category` items
      per category). The final list is then sorted by 24h volume (desc).
    - When `detailed=True`, append multi-line details after each summary line
      (tags, end/updated timestamps, liquidity/comments, first market snapshot).

    Args:
        query: Case-insensitive substring filter over title/question/slug.
        tags_any: Keep event if ANY of these substrings appear in tag labels/slugs.
        tags_all: Keep event only if ALL of these substrings appear in tag labels/slugs.
        exclude_tags: Exclude event if ANY of these substrings appear in tag labels/slugs.
        categories: Explicit category list to balance over; if None, auto-detected
            from the fetched events.
        limit: Maximum number of events to request from Gamma (size of the base pool).
        per_category: Maximum number of items to take from each category during
            balanced sampling.
        detailed: If True, include additional multi-line details for each event.

    Returns:
        str: Human-readable text block, one summary line per event; when
            `detailed=True`, each event is followed by extra detail lines.
    """
    params = {
        "active": "true",
        "closed": "false",
        "order": "volume24hr,openInterest,commentCount",
        "ascending": "false",
        "limit": str(max(1, int(limit or 0))),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
        "Accept": "application/json",
    }
    r = requests.get(f"{GAMMA}/events", params=params, headers=headers, timeout=25)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        events = payload.get("data") or payload.get("events") or []
    else:
        events = payload or []

    # 先做检索/过滤
    base: List[Dict[str, Any]] = _filter_events(
        events,
        query=query,
        tags_any=tags_any,
        tags_all=tags_all,
        exclude_tags=exclude_tags,
    )

    base = apply_private_filters(base)

    # 注入辅助字段
    for ev in base:
        ev["_category"] = _event_category(ev)
        ev["_vol"] = _event_volume(ev)

    # 类别集合
    if categories and isinstance(categories, list) and categories:
        wanted = list(dict.fromkeys([str(c) for c in categories]))
    else:
        wanted = sorted({str(ev.get("_category") or "Other") for ev in base})

    # 分组、排序、均衡抽样
    grouped: Dict[str, List[Dict[str, Any]]] = {c: [] for c in wanted}
    for ev in base:
        c = str(ev.get("_category") or "Other")
        if c in grouped:
            grouped[c].append(ev)
    for c in grouped:
        grouped[c].sort(key=lambda x: x.get("_vol", 0.0), reverse=True)

    picked: List[Dict[str, Any]] = []
    cap = max(0, int(per_category or 0))
    for c in wanted:
        picked.extend(grouped.get(c, [])[:cap])

    # 最终按成交量降序
    picked.sort(key=lambda x: x.get("_vol", 0.0), reverse=True)

    
    page_items = picked

    # 构建可读行
    lines: List[str] = []
    for i, ev in enumerate(page_items, 1):
        try:
            volf = float(ev.get("_vol") or 0)
        except Exception:
            volf = 0.0
        # 使用紧凑格式，尽量贴近 tests/test_gamma_2.py 的展示
        vtxt = f"{volf}"  # 直接字符串化，保留小数
        # 概率（价格）
        try:
            prob = _event_current_prob(ev)
        except Exception:
            prob = None
        ptxt = f"{float(prob):.3f}" if prob is not None else "NA"
        slug = ev.get("slug") or ""
        title = ev.get("title") or ev.get("question") or ""
        cat = ev.get("_category") or "Other"
        oi = ev.get("openInterest")
        line = f"{i:02d}. {slug} | p={ptxt} | vol={vtxt} | OI={oi} | cat={cat} | {title}"
        lines.append(line)
        if detailed:
            # tags
            tags_raw = ev.get("tags") or []
            tag_labels: List[str] = []
            for t in tags_raw:
                if isinstance(t, dict):
                    lab = t.get("label") or t.get("slug")
                    if lab:
                        tag_labels.append(str(lab))
                else:
                    tag_labels.append(str(t))
            # 时间/流动性等
            end_iso = ev.get("endDateIso") or ev.get("end_date_iso") or ev.get("endDate") or ev.get("closeDate")
            updated = ev.get("updatedAt") or ev.get("createdAt")
            liq = ev.get("liquidityClob") or ev.get("liquidity")
            cmt = ev.get("commentCount")
            lines.append(f"    tags: {', '.join(tag_labels)}\n")
            lines.append(f"    time: end={end_iso} | updated={updated}\n")
            lines.append(f"    liq: {liq} | comments={cmt}\n")
            # 市场详情（首个市场）
            mks = ev.get("markets") or []
            if mks:
                m0 = mks[0]
                mslug = m0.get("slug")
                outcomes = _to_list(m0.get("outcomes"))
                prices = _to_list(m0.get("outcomePrices"))
                mid = m0.get("mid")
                bb = m0.get("bestBid")
                ba = m0.get("bestAsk")
                lines.append(
                    f"    market0: slug={mslug} | outcomes={outcomes} | prices={prices} | mid={mid} | bb/ba={bb}/{ba}\n"
                )

    return "\n".join(lines)

def get_market_info_fn(market_slug: str) -> Dict[str, Any]:
    """Use Gamma to get a full market object by slug.

    Endpoint: GET /markets/slug/{slug}
    Returns the complete market (includes clobTokenIds, outcomes, etc.).
    """
    try:
        r = requests.get(f"{GAMMA}/markets/slug/{market_slug}", timeout=15)
        if r.status_code == 404:
            return {"error": f"slug {market_slug} not found"}
        r.raise_for_status()
        data = r.json()
        # Some deployments may wrap the object in a top-level container
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], (dict, list)):
                inner = data["data"]
                if isinstance(inner, list):
                    return inner[0] if inner else {"error": f"slug {market_slug} not found"}
                return inner
            return data
        return {"error": "unexpected response format"}
    except Exception as e:  # pragma: no cover
        return {"error": f"failed to fetch from gamma: {e}"}


def get_event_info_fn(event_slug: str) -> Dict[str, Any]:
    """Use Gamma to get a full event object by slug, including its markets.

    Endpoint: GET /events/slug/{slug}
    Returns the complete event object (with markets list).
    """
    try:
        r = requests.get(f"{GAMMA}/events/slug/{event_slug}", timeout=15)
        if r.status_code == 404:
            return {"error": f"event slug {event_slug} not found"}
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], (dict, list)):
                inner = data["data"]
                if isinstance(inner, list):
                    return inner[0] if inner else {"error": f"event slug {event_slug} not found"}
                return inner
            return data
        return {"error": "unexpected response format"}
    except Exception as e:  # pragma: no cover
        return {"error": f"failed to fetch event from gamma: {e}"}

@function_tool
def get_polymarket_info_by_slug(slug: str) -> Dict[str, Any]:
    """
    Get the info of a specific market or event by slug.

    Args:
        slug: the slug of the market or event

    Returns: {"type": "market", "market": {...}} or {"type": "event", "event": {...}, "markets": [...]} or {"error": ...}
    If the slug is a market slug, return {"type": "market", "market": {...}}.
    If the slug is an event slug, return {"type": "event", "event": {...}, "markets": [...]}
    """
    # Try market first
    try:
        r = requests.get(f"{GAMMA}/markets/slug/{slug}", timeout=15)
        if r.status_code == 200:
            market = r.json()
            if isinstance(market, dict) and market:
                # unwrap if nested under data
                if "data" in market and isinstance(market["data"], (dict, list)):
                    inner = market["data"]
                    if isinstance(inner, list):
                        market_obj = inner[0] if inner else None
                    else:
                        market_obj = inner
                else:
                    market_obj = market
                if market_obj:
                    return {"type": "market", "market": market_obj}
        elif r.status_code != 404:
            r.raise_for_status()
    except Exception:
        # fall through to event attempt
        pass

    # Try event next
    event = get_event_info_fn(slug)
    if event and "error" not in event:
        markets = event.get("markets") or []
        return {"type": "event", "event": event, "markets": markets}
    return {"error": f"slug {slug} not found as market or event"}


@function_tool
def get_market_prices(market_slug: str) -> Dict[str, Any]:
    """
    Get the prices of a specific market by market_slug.

    Args:
        market_slug: the slug of the market

    Returns: {"market_slug": slug, "prices": {outcome: price_or_none}}
    """
    m = get_market_info_fn(market_slug)
    if "error" in m:
        return m

    def to_list(v: Any) -> List[Any]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
            return [v]
        if isinstance(v, (tuple, set)):
            return list(v)
        return [v]

    token_ids = to_list(m.get("clobTokenIds"))
    outcomes = to_list(m.get("outcomes"))
    clob_host = os.getenv("CLOB_HOST", BASE_URL)

    prices: Dict[str, Optional[float]] = {}
    for name, tid in zip(outcomes, token_ids):
        try:
            r = requests.get(f"{clob_host}/midpoint", params={"token_id": tid}, timeout=10)
            r.raise_for_status()
            mid = r.json().get("mid")
        except Exception:
            mid = None

        if mid is None or str(mid) == "NaN":
            p = q = None
            try:
                rp = requests.get(f"{clob_host}/price", params={"token_id": tid, "side": "BUY"}, timeout=10)
                rp.raise_for_status()
                p = rp.json().get("price")
            except Exception:
                pass
            try:
                rq = requests.get(f"{clob_host}/price", params={"token_id": tid, "side": "SELL"}, timeout=10)
                rq.raise_for_status()
                q = rq.json().get("price")
            except Exception:
                pass
            try:
                mid = (float(p) + float(q)) / 2 if p is not None and q is not None else None
            except Exception:
                mid = None

        try:
            prices[str(name)] = float(mid) if mid is not None else None
        except Exception:
            prices[str(name)] = None

    return {"market_slug": market_slug, "prices": prices}

@function_tool
def get_market_history(market_slug: str, interval: str = "1d") -> Dict[str, Any]:
    """
    Get the history of prices for each outcome of a specific market by market_slug.

    Args:
        market_slug: the slug of the market
        interval: the interval of the history

    Returns: {"market_slug": slug, "interval": interval, "history": {outcome: [{t, p}, ...]}}
    """
    m = get_market_info_fn(market_slug)
    if "error" in m:
        return m

    def to_list(v: Any) -> List[Any]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
            return [v]
        if isinstance(v, (tuple, set)):
            return list(v)
        return [v]

    token_ids = to_list(m.get("clobTokenIds"))
    outcomes = to_list(m.get("outcomes"))
    clob_host = os.getenv("CLOB_HOST", BASE_URL)

    hist: Dict[str, Any] = {}
    for name, tid in zip(outcomes, token_ids):
        try:
            r = requests.get(f"{clob_host}/prices-history", params={"market": tid, "interval": interval}, timeout=15)
            r.raise_for_status()
            payload = r.json()
            hist[str(name)] = payload.get("history", [])
        except Exception as e:
            hist[str(name)] = {"error": str(e)}

    return {"market_slug": market_slug, "interval": interval, "history": hist}

if __name__ == "__main__":
    from agents.tool_context import ToolContext
    import asyncio
    args = dict(market_slug = "will-the-supreme-court-overturn-gay-marriage-in2025")
    ctx = ToolContext(
        context=None,
        tool_name="get_market_prices",
        tool_call_id="get-market-prices-test",
        tool_arguments=json.dumps(args)
    )
    result = asyncio.run(
        get_market_prices.on_invoke_tool(
            ctx,
            json.dumps(args)
        )
    )
    print(result)