import asyncio
import json
import os
from datetime import datetime
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.live import Live

from agents import Agent, Runner, SQLiteSession, ModelSettings  # type: ignore
from agents.exceptions import ModelBehaviorError  # type: ignore
from agents.extensions.models.litellm_model import LitellmModel  # type: ignore
from agents.run import RunConfig  # type: ignore

from futureshow.prompt.polymarket_forecast_prompt import get_forecast_system_prompt
from futureshow.tool.tool_google import google_news_search, google_web_search
from futureshow.tool.tool_exa import google_url2text
from futureshow.tool.tool_twitter import search_tweets
from futureshow.tool.tool_reddit import reddit_search, reddit_post_details
from futureshow.utils.polymarket_watchlist import (
    DEFAULT_WATCHLIST_PATH,
    load_watchlist,
    refresh_trending_watchlist,
    remove_events_from_watchlist,
)
from futureshow.tool.tool_polymarket_data import get_event_info_fn
from futureshow.utils.agent_logs import Logs
from futureshow.utils.batch_progress import BatchProgressManager
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.markdown import Markdown

class PolymarketForecastAgent:
    """Forecast-only agent that iterates over a fixed watchlist and produces probability updates."""

    def __init__(
        self,
        signature: str,
        basemodel: str,
        watchlist_path: Optional[Path] = None,
        forecast_dir: Optional[Path] = None,
        max_steps: int = 6,
        max_retries: int = 2,
        base_delay: float = 0.5,
        openai_base_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        concurrent_tasks: int = 10,
    ):
        self.signature = signature
        self.basemodel = basemodel
        self.watchlist_path = Path(watchlist_path or DEFAULT_WATCHLIST_PATH)
        self.forecast_dir = Path(forecast_dir or "./data/forecasts") / signature
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.openai_base_url = openai_base_url or os.getenv("OPENAI_API_BASE")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.concurrent_tasks = max(1, int(concurrent_tasks))
        self.tools = [
            google_url2text, google_web_search, google_news_search, search_tweets, reddit_search, reddit_post_details
        ]
        self.debug = str(os.getenv("DEBUG", "0")).lower() in ("1", "true", "yes")
        self.debug = False if self.concurrent_tasks > 1 else self.debug
        self.progress_bar_enabled = self.concurrent_tasks > 1

    def ensure_dirs(self) -> None:
        self.forecast_dir.mkdir(parents=True, exist_ok=True)

    def load_watchlist(self, refresh: bool = False, year: Optional[int] = None, month: int = 11) -> List[Dict[str, Any]]:
        if refresh or not self.watchlist_path.exists():
            refresh_trending_watchlist(
                watchlist_path=self.watchlist_path,
                year=year,
                month=month,
            )
        watchlist = load_watchlist(self.watchlist_path)
        return watchlist

    async def _forecast_event(self, event: Dict[str, Any], current_datetime: str, progress_mgr: Optional[BatchProgressManager] = None) -> Dict[str, Any]:
        slug = event.get("slug")
        title = event.get("title") or event.get("question") or "unknown"
        close_time = event.get("endDate") or ""
        event_description = event.get("description") or ""
        outcomes_text = "unknown"
        markets_text_lines: List[str] = []
        markets_count = 0
        try:
            markets = event.get("markets") or []
            if markets and isinstance(markets, list):
                markets_count = len(markets)
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
                    if isinstance(desc, str) and len(desc) > 240:
                        desc = desc[:240] + "..."
                    mout = m.get("outcomes")
                    if isinstance(mout, list):
                        mout_txt = ", ".join(str(o) for o in mout)
                    else:
                        mout_txt = str(mout) if mout is not None else ""
                    markets_text_lines.append(f"- {mslug}: {q} | outcomes: {mout_txt} | desc: {desc}")
        except Exception:
            outcomes_text = "unknown"

        markets_text = "\n".join(markets_text_lines) if markets_text_lines else "none provided"

        single_market = markets_count <= 1
        history_summary = self._recent_forecast_summary(slug, limit=3)
        system_prompt = get_forecast_system_prompt(
            current_datetime=current_datetime,
            signature=self.signature,
            event_title=title,
            close_time=close_time,
            outcomes_text=outcomes_text,
            event_description=event_description,
            markets_text=markets_text,
        )

        agent_logs = Logs(self.debug, max_steps=self.max_steps, label=slug, progress_mgr=progress_mgr)

        agent = Agent(
            name="PolymarketForecastAgent",
            instructions=system_prompt,
            tools=self.tools,
            model=LitellmModel(model=self.basemodel, api_key=self.openai_api_key, base_url=self.openai_base_url),
            model_settings=ModelSettings(parallel_tool_calls=True, include_usage=True),
        )

        if single_market:
            instruction = (
                "Single-market event: choose YES or NO. "
                "Return one <PREDICTION> block with 'slug|YES' or 'slug|NO' (or YES/NO if no slug); use ABSTAIN only if truly undecidable. "
            )
        else:
            instruction = (
                "Multiple markets: pick exactly one best market to go YES on; if none are reasonable, use ABSTAIN. "
                "Return one <PREDICTION> block with 'slug|YES' (or ABSTAIN); do not return NO for multi-market. "
            )

        user_input = (
            f"Update forecast for event '{title}' (close: {close_time}). "
            f"Recent forecasts: {history_summary}. "
            "Use web/news/social tools to gather the latest information and return concise rationale; cross-check multiple sources and avoid stopping after a single search. "
            f"{instruction}"
        )

        console = Console()
        if self.debug:
            console.print(
                Panel(
                    Text(f"User input: {user_input}", style="bold blue"),
                    box=box.ROUNDED,
                    border_style="blue",
                )
            )

        session_key = f"{self.signature}:forecast:{slug}"
        session = SQLiteSession(session_key)

        try:
            result = await Runner.run(
                agent,
                input=user_input,
                session=session,
                max_turns=self.max_steps,
                hooks=agent_logs,
                run_config=RunConfig(tracing_disabled=True),
            )
        except ModelBehaviorError as exc:
            if "Tool " in str(exc) and "not found" in str(exc):
                retry_input = self._tool_error_retry_input(user_input, str(exc))
                retry_session = SQLiteSession(f"{session_key}:tool_retry")
                result = await Runner.run(
                    agent,
                    input=retry_input,
                    session=retry_session,
                    max_turns=self.max_steps,
                    hooks=agent_logs,
                    run_config=RunConfig(tracing_disabled=True),
                )
            else:
                raise
        forecast_text = getattr(result, "final_output", None) or ""
        return self._record_prediction(event, current_datetime, forecast_text)

    def _record_prediction(self, event: Dict[str, Any], current_datetime: str, forecast_text: str) -> Dict[str, Any]:
        self.ensure_dirs()
        predictions = self._extract_predictions(forecast_text)
        market_prob = self._extract_market_prob(event, predictions)
        payload = {
            "timestamp": current_datetime,
            "signature": self.signature,
            "event_slug": event.get("slug"),
            "event_title": event.get("title") or event.get("question"),
            "forecast": forecast_text,
            "predictions": predictions,
            "market_prob": market_prob,
        }
        event_slug = event.get("slug") or "unknown_event"
        out_dir = self.forecast_dir / event_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "forecasts.jsonl"
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if self.debug:
            console = Console()
            console.print(
                Panel(
                    Text(f"Forecast: {forecast_text}", style="bold green"),
                    box=box.ROUNDED,
                    border_style="green",
                )
            )
        return payload

    def _extract_predictions(self, text: str) -> List[Dict[str, Any]]:
        """Parse <PREDICTION> blocks into binary calls."""
        try:
            import re
            blocks = re.findall(r"<PREDICTION>(.*?)</PREDICTION>", text, flags=re.IGNORECASE | re.DOTALL)
            preds: List[Dict[str, Any]] = []
            for blk in blocks:
                token = blk.strip()
                token_norm = token.replace("\n", " ").strip()
                # support "slug|YES" or "slug: YES" or "YES"
                sep = "|" if "|" in token_norm else ":"
                parts = [p.strip() for p in token_norm.split(sep) if p.strip()]
                if len(parts) == 1:
                    call = parts[0].upper()
                    if call in {"YES", "NO", "ABSTAIN"}:
                        preds.append({"outcome": call})
                elif len(parts) >= 2:
                    slug_part = parts[0]
                    call = parts[1].upper()
                    if call in {"YES", "NO", "ABSTAIN"}:
                        preds.append({"slug": slug_part, "outcome": call})
            return preds
        except Exception:
            return []

    def _tool_error_retry_input(self, user_input: str, error_message: str) -> str:
        tool_names = sorted({getattr(tool, "name", "") for tool in self.tools if getattr(tool, "name", "")})
        tool_list = ", ".join(tool_names) if tool_names else "none"
        return (
            f"{user_input}\n\n"
            f"Tool error: {error_message}\n"
            f"Available tools: {tool_list}\n"
            "Use only the tool names listed above."
        )

    def _extract_market_prob(self, event: Dict[str, Any], predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Grab the current Yes/No prices for the chosen market (if available)."""
        try:
            target_slug = None
            if predictions:
                p0 = predictions[0]
                if isinstance(p0, dict):
                    target_slug = p0.get("slug")

            markets = event.get("markets") or []
            chosen = None
            for m in markets:
                if not isinstance(m, dict):
                    continue
                if target_slug and m.get("slug") != target_slug:
                    continue
                chosen = m
                break
            if not chosen and markets:
                chosen = markets[0]

            if not chosen:
                return {}

            outcomes = chosen.get("outcomes") or []
            prices = chosen.get("prices") or chosen.get("outcomePrices") or []
            chosen_closed = bool(chosen.get("closed")) or str(chosen.get("status", "")).lower() in {"closed", "resolved", "settled"}
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except Exception:
                    pass
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    pass
            yes_prob = None
            no_prob = None
            if isinstance(outcomes, list) and isinstance(prices, list) and len(outcomes) == len(prices):
                for o, p in zip(outcomes, prices):
                    try:
                        if str(o).lower().startswith("yes"):
                            yes_prob = float(p)
                        elif str(o).lower().startswith("no"):
                            no_prob = float(p)
                    except Exception:
                        continue
            elif isinstance(prices, list) and prices:
                try:
                    yes_prob = float(prices[0])
                except Exception:
                    yes_prob = None
                if len(prices) > 1:
                    try:
                        no_prob = float(prices[1])
                    except Exception:
                        pass

            return {
                "market_slug": chosen.get("slug"),
                "closed": chosen_closed,
                "yes_prob": yes_prob,
                "no_prob": no_prob,
                "bestBid": chosen.get("bestBid"),
                "bestAsk": chosen.get("bestAsk"),
                "liquidity": chosen.get("liquidityClob") or chosen.get("liquidity"),
            }
        except Exception:
            return {}

    def _recent_forecast_summary(self, event_slug: str, limit: int = 3) -> str:
        """Load recent forecast lines for context."""
        path = self.forecast_dir / event_slug / "forecasts.jsonl"
        if not path.exists():
            return "none"
        try:
            dq: deque[str] = deque(maxlen=limit)
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        dq.append(line.strip())
            lines: List[str] = []
            for item in dq:
                try:
                    obj = json.loads(item)
                    ts = obj.get("timestamp") or ""
                    preds = obj.get("predictions") or []
                    pred_txt = ", ".join(f"{p.get('slug') or ''}:{p.get('outcome')}" if isinstance(p, dict) else str(p) for p in preds) or obj.get("forecast") or ""
                    if len(pred_txt) > 120:
                        pred_txt = pred_txt[:120] + "..."
                    lines.append(f"{ts} => {pred_txt}")
                except Exception:
                    lines.append(item[:120] + ("..." if len(item) > 120 else ""))
            return "; ".join(lines) if lines else "none"
        except Exception:
            return "none"

    def _market_snapshot(self, event_slug: str) -> Dict[str, Any]:
        """Pull latest market info for an event slug."""
        try:
            data = get_event_info_fn(event_slug)
            ev = None
            if isinstance(data, dict):
                if "event" in data and isinstance(data["event"], dict):
                    ev = data["event"]
                elif "markets" in data:  # some responses return the event directly
                    ev = data
            if not ev or (isinstance(data, dict) and "error" in data):
                return {"error": data.get("error") if isinstance(data, dict) else "unknown"}
            closed = bool(ev.get("closed")) or str(ev.get("status", "")).lower() in {"closed", "resolved", "settled"}
            resolved_at = ev.get("resolvedAt") or ev.get("resolutionTime")
            markets = []
            for m in ev.get("markets", []) or []:
                if not isinstance(m, dict):
                    continue
                m_closed = bool(m.get("closed")) or str(m.get("status", "")).lower() in {"closed", "resolved", "settled"}
                resolved_time = m.get("resolvedAt") or m.get("resolutionTime")
                outcomes = m.get("outcomes")
                prices = m.get("outcomePrices")
                try:
                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                except Exception:
                    pass
                best_bid = m.get("bestBid")
                best_ask = m.get("bestAsk")
                mid = None
                try:
                    if best_bid is not None and best_ask is not None:
                        mid = (float(best_bid) + float(best_ask)) / 2.0
                except Exception:
                    mid = None
                markets.append(
                    {
                        "market_slug": m.get("slug"),
                        "question": m.get("question") or m.get("title"),
                        "outcomes": outcomes,
                        "prices": prices,
                        "bestBid": best_bid,
                        "bestAsk": best_ask,
                        "mid": mid,
                        "liquidity": m.get("liquidityClob") or m.get("liquidity"),
                        "volume24h": m.get("volume24h") or m.get("volume24H"),
                        "closed": m_closed,
                        "resolved_at": resolved_time,
                    }
                )
            return {
                "closed": closed,
                "resolved_at": resolved_at,
                "markets": markets,
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def record_snapshot(
        self,
        snapshot_iso: str,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Record current market state (closed? current prices) for watchlist events."""
        if events is None:
            events = self.load_watchlist(refresh=False)
        for ev in events:
            slug = ev.get("slug") or "unknown_event"
            snap = self._market_snapshot(slug)
            row = {
                "timestamp": snapshot_iso,
                "event_slug": slug,
                "event_title": ev.get("title") or ev.get("question"),
                **snap,
            }
            out_dir = self.forecast_dir / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            track_file = out_dir / "tracking.jsonl"
            with open(track_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

            if snap.get("closed"):
                # persist a result file for the event
                result_file = out_dir / "result.json"
                with open(result_file, "w", encoding="utf-8") as rf:
                    json.dump(row, rf, ensure_ascii=False, indent=2)
                # remove from watchlist to keep list fresh
                try:
                    remove_events_from_watchlist([slug], path=self.watchlist_path)
                except Exception:
                    pass

    async def run_forecasts(
        self,
        current_datetime: str,
        refresh_watchlist: bool = False,
        watch_year: Optional[int] = None,
        watch_month: int = 11,
    ) -> List[Dict[str, Any]]:
        watchlist = self.load_watchlist(refresh=refresh_watchlist, year=watch_year, month=watch_month)
        if not watchlist:
            raise ValueError(f"Watchlist is empty at {self.watchlist_path}")

        sem = asyncio.Semaphore(self.concurrent_tasks)
        results: List[Optional[Dict[str, Any]]] = [None] * len(watchlist)
        progress_total = len(watchlist)
        progress_done = 0
        progress_lock = asyncio.Lock()
        progress_mgr = BatchProgressManager(progress_total) if self.progress_bar_enabled else None

        async def worker(idx: int, ev: Dict[str, Any]) -> None:
            nonlocal progress_done
            async with sem:
                if progress_mgr:
                    progress_mgr.start_event(ev.get("slug") or ev.get("title") or f"event-{idx}")
                for attempt in range(1, self.max_retries + 1):
                    try:
                        res = await self._forecast_event(ev, current_datetime, progress_mgr=progress_mgr)
                        results[idx] = res
                        break
                    except Exception as exc:
                        if attempt >= self.max_retries:
                            raise
                        await asyncio.sleep(self.base_delay * attempt)
                        if self.debug:
                            print(f"[DEBUG] retrying forecast for {ev.get('slug')} due to {exc}")
                async with progress_lock:
                    progress_done += 1
                if progress_mgr:
                    progress_mgr.end_event(ev.get("slug") or ev.get("title") or f"event-{idx}", status="done")

        tasks = [asyncio.create_task(worker(i, ev)) for i, ev in enumerate(watchlist)]
        if progress_mgr:
            with progress_mgr.live():
                await asyncio.gather(*tasks)
        else:
            await asyncio.gather(*tasks)
        return [r for r in results if r is not None]
