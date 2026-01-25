import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from agents import Agent, Runner, function_tool, SQLiteSession, ModelSettings  # type: ignore

from futureshow.utils.general_tools import get_config_value, write_config_value
from futureshow.utils.polymarket_position_tools import (
    ensure_position_store,
    add_no_trade_record,
)
from futureshow.prompt.polymarket_agent_prompt import get_agent_system_prompt
from futureshow.tool.tool_polymarket_data import (
    list_markets,
    get_polymarket_info_by_slug,
    get_market_prices,
    get_market_history,
    list_events,
    get_market_info_fn,
)
from futureshow.tool.tool_polymarket_trade import (
    settle,
    buy,
    sell,
    _resolve_market_and_token,
    _get_order_book,
    _simulate_sell_shares,
)
from futureshow.tool.tool_exa import google_url2text
from futureshow.tool.tool_google import google_web_search, google_news_search
from futureshow.tool.tool_twitter import search_tweets
from futureshow.tool.tool_reddit import reddit_search, reddit_post_details
from futureshow.tool.tool_math import add, multiply
from agents.tool_context import ToolContext
from futureshow.agent.polymarket.market_preview import summarize_snap
from agents.lifecycle import RunHooks
from agents.extensions.models.litellm_model import LitellmModel
from agents.run import RunConfig
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box
from futureshow.utils.agent_logs import Logs

class StepReminder(RunHooks):
    def __init__(self, max_turns: int, threshold: int = 2, session: Optional[SQLiteSession] = None, debug: bool = False):
        super().__init__()
        self.max_turns = int(max_turns)
        self.threshold = max(1, int(threshold))
        self.session = session
        self.debug = debug
        self.llm_calls = 0
        self._reminded = False
        self.console = Console(highlight=True)

    async def on_agent_start(self, ctx, agent):
        self.llm_calls = 0
        self._reminded = False

    async def on_llm_start(self, ctx, agent, system_prompt, input_items):
        # 估算当前第几次 LLM 调用（在调用前触发，所以 +1）
        try:
            requests = getattr(getattr(ctx, "usage", None), "requests", None)
            if isinstance(requests, int) and requests >= 0:
                current_index = requests + 1
            else:
                self.llm_calls += 1
                current_index = self.llm_calls
        except Exception:
            self.llm_calls += 1
            current_index = self.llm_calls

        remaining = self.max_turns - current_index
        if (remaining <= self.threshold) and (remaining >= 0) and (not self._reminded):
            reminder = (
                f"[REMINDER] 还剩 {remaining} 步达到最大步数 {self.max_turns}。"
                "请在本轮尽快收敛并给出最终交易决策："
                "输出包含 Exploration summary / Shortlist / Portfolio plan / Trades / Risk notes / PnL / Next steps，"
                "并以 FINAL TRADES 或 ABSTAIN 结束。"
            )
            # 尝试直接注入到当次提示（若 SDK 在 hook 后复用该列表）
            try:
                if isinstance(input_items, list):
                    input_items.append({"role": "system", "content": reminder})
            except Exception:
                pass
            # 同步写入会话，保证后续轮次也能看到
            try:
                if self.session is not None:
                    await self.session.add_items([{"role": "system", "content": reminder}])
            except Exception:
                pass
            # 可选控制台提醒
            if self.debug:
                self.console.print(Panel(Text(reminder, style="bold red"), box=box.ROUNDED, border_style="red"))
            self._reminded = True

class MultiHooks(RunHooks):
    def __init__(self, hooks: List[RunHooks]):
        super().__init__()
        self._hooks = [h for h in (hooks or []) if h is not None]

    def __getattr__(self, name):
        async def _call_all(*args, **kwargs):
            for h in self._hooks:
                fn = getattr(h, name, None)
                if callable(fn):
                    res = fn(*args, **kwargs)
                    if hasattr(res, "__await__"):
                        await res
        return _call_all

class PolymarketAgent:
    """
    Polymarket trading/backtesting agent.

    Capabilities:
    - Connects to MCP servers: search, polymarket_data, polymarket_trade, math (optional)
    - Runs daily decision loop with tool-driven reasoning
    - Records trades/positions to JSONL ledger
    - Marks no-trade days and supports settlement via trade tool
    """

    def __init__(
        self,
        signature: str,
        basemodel: str,
        stock_symbols: Optional[List[str]] = None,  # kept for compatibility, unused
        log_path: Optional[str] = None,
        max_steps: int = 10,
        max_retries: int = 3,
        base_delay: float = 0.5,
        openai_base_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        initial_cash: float = 10000.0,
        init_datetime: str = "1970-01-01T00:00:00Z",
    ):
        self.signature = signature
        self.basemodel = basemodel
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.initial_cash = initial_cash
        self.init_datetime = init_datetime
        self.base_log_path = log_path or "./data/agent_data"

        # Model config
        self.openai_base_url = openai_base_url or os.getenv("OPENAI_API_BASE")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        # Derived paths
        self.data_path = os.path.join(self.base_log_path, self.signature)
        self.position_file = os.path.join(self.data_path, "position", "position.jsonl")
        self.pnl_dir = os.path.join(self.base_log_path, self.signature, "pnl")

        # Runtime
        self.tools: Optional[List] = None
        self.debug = str(os.getenv("DEBUG", "0")).lower() in ("1", "true", "yes")

    async def initialize(self) -> None:

        self.tools = [list_events, get_polymarket_info_by_slug, get_market_prices, get_market_history, buy, sell, google_url2text, google_web_search, google_news_search, search_tweets, reddit_search, reddit_post_details, add, multiply]
        if self.debug:
            try:
                tool_names = [t.name for t in self.tools]
            except Exception:
                raise
            print(f"[DEBUG] Loaded Agents SDK tools: {tool_names}")

    def _setup_logging(self, current_datetime: str) -> str:
        # Derive day folder from current_datetime
        try:
            d = current_datetime
            if d.endswith("Z"):
                d = d[:-1] + "+00:00"
            dt = datetime.fromisoformat(d)
            day = dt.strftime("%Y-%m-%d")
        except Exception:
            day = (current_datetime or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
        log_path = os.path.join(self.base_log_path, self.signature, 'log', day)
        os.makedirs(log_path, exist_ok=True)
        return os.path.join(log_path, "log.jsonl")

    def _log_message(self, log_file: str, new_messages: List[Dict[str, str]]) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "signature": self.signature,
            "new_messages": new_messages,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if self.debug:
            try:
                for m in new_messages if isinstance(new_messages, list) else [new_messages]:
                    role = m.get("role")
                    content = (m.get("content") or "").strip()
                    clip = (content[:200] + ("..." if len(content) > 200 else "")) if isinstance(content, str) else str(content)
                    print(f"[DEBUG][LOG] {role}: {clip}")
            except Exception:
                pass

    async def run_trading_session(self, current_datetime: str) -> None:
        log_file = self._setup_logging(current_datetime)

        # Prepare system prompt for polymarket
        market_preview = "(empty)"
        try:

            args = dict(limit = 3000, per_category = 10, detailed = True)
            ctx = ToolContext(
                context=None,
                tool_name="list_events",
                tool_call_id="list-events-test",
                tool_arguments=json.dumps(args)
            )
            market_preview =  await list_events.on_invoke_tool(
                    ctx,
                    json.dumps(args)
                )
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to build market preview: {e}")

        # 基于当前时间上下文构造 Agent（使用 Agents SDK）
        instructions = get_agent_system_prompt(current_datetime, self.signature, market_preview=market_preview)
        agent = Agent(
            name="PolymarketAgent",
            instructions=instructions,
            tools=self.tools or [],
            model=LitellmModel(model=self.basemodel, api_key=self.openai_api_key, base_url=self.openai_base_url),
            model_settings=ModelSettings(parallel_tool_calls=True, include_usage=True),
        )

        # 用会话维持对话历史（与 SDK 文档一致）
        # Group conversation per day to keep context bounded
        try:
            d = current_datetime
            if d.endswith("Z"):
                d = d[:-1] + "+00:00"
            dt = datetime.fromisoformat(d)
            session_key_day = dt.strftime("%Y-%m-%d")
        except Exception:
            session_key_day = (current_datetime or "")[:10]
        session = SQLiteSession(f"{self.signature}:{session_key_day}")

        # 首次用户输入：不指定具体工具调用，强调广泛信息收集与收益最大化
        user_input = (
            f"For {current_datetime}, broadly scan Polymarket and manage the portfolio for evaluation. "
            "Explore multiple open, liquid markets across different topics using several list_events queries; do not rely on initial ordering. "
            "Compare candidates and build a small shortlist; choose opportunities with clear, positive expected value and adequate liquidity. "
            "Allocate capital reasonably (avoid excessive concentration, consider spread/time-to-resolution/fees/correlation); keep some cash if uncertain. "
            "When context is needed, use web/news search, Twitter, and Reddit tools to gather concise evidence (cite URLs in notes). "
            "If no edge is found, abstain. "
            "Output: Exploration summary, Shortlist with brief rationale, Portfolio plan, Trades (side/size/avg price), Risk notes, PnL snapshot, Next steps. "
            "End with a FINAL TRADES block (or ABSTAIN)."
        )
        self._log_message(log_file, [{"role": "user", "content": user_input}])

        # 运行（让 SDK 内部控制工具循环）；限制 max_turns 防止失控
        result = await Runner.run(
            agent,
            input=user_input,
            session=session,
            max_turns=self.max_steps,
            hooks=Logs(self.debug),
            run_config = RunConfig(tracing_disabled=True)
        )
        final_text = getattr(result, "final_output", None) or ""
        self._log_message(log_file, [{"role": "assistant", "content": final_text}])

        await self._handle_trading_result(current_datetime)

    async def _handle_trading_result(self, current_datetime: str) -> None:
        if_trade = get_config_value("IF_TRADE")
        if if_trade:
            write_config_value("IF_TRADE", False)
        else:
            # No actions -> append a no-trade record
            add_no_trade_record(current_datetime, self.signature)
            write_config_value("IF_TRADE", False)

    def register_agent(self) -> None:
        # Ensure directory and initial ledger exists
        ensure_position_store(self.signature, init_cash=self.initial_cash, init_datetime=self.init_datetime)

    def get_trading_dates(self, init_date: str, end_date: str) -> List[str]:
        dates: List[str] = []
        max_date: Optional[str] = None

        # Create if missing
        if not os.path.exists(self.position_file):
            self.register_agent()
            max_date = init_date
        else:
            with open(self.position_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    doc = json.loads(line)
                    current_date = doc.get("date")
                    if not max_date or current_date > max_date:
                        max_date = current_date

        max_date_obj = datetime.strptime(max_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        if end_date_obj <= max_date_obj:
            return []
        trading_dates: List[str] = []
        current_date = max_date_obj + timedelta(days=1)
        while current_date <= end_date_obj:
            if current_date.weekday() < 6:  # include Saturday updates if desired; adjust to <5 for weekdays only
                trading_dates.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)
        return trading_dates

    async def run_with_retry(self, current_datetime: str) -> None:
        for attempt in range(1, self.max_retries + 1):
            try:
                await self.run_trading_session(current_datetime)
                return
            except Exception:
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.base_delay * attempt)

    async def run_date_range(self, init_date: str, end_date: str) -> None:
        trading_dates = self.get_trading_dates(init_date, end_date)
        if not trading_dates:
            return
        for date in trading_dates:
            write_config_value("TODAY_DATE", date)
            write_config_value("SIGNATURE", self.signature)
            await self.run_with_retry(date)

    def get_position_summary(self) -> Dict[str, Any]:
        if not os.path.exists(self.position_file):
            return {"error": "Position file does not exist"}
        items: List[Dict[str, Any]] = []
        with open(self.position_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        if not items:
            return {"error": "No position records"}
        latest = items[-1]
        return {
            "signature": self.signature,
            "latest_timestamp": latest.get("timestamp") or latest.get("date"),
            "positions": latest.get("positions", {}),
            "total_records": len(items),
        }

    def __str__(self) -> str:
        return f"PolymarketAgent(signature='{self.signature}', basemodel='{self.basemodel}')"

    def __repr__(self) -> str:
        return self.__str__()

    # ===== Intraday PnL tracking (10-min interval) =====
    async def _auto_settle_closed_markets(self, current_datetime: str) -> None:
        from futureshow.utils.polymarket_position_tools import get_latest_position_by_time

        positions, _ = get_latest_position_by_time(current_datetime, self.signature)
        if not positions:
            return

        # Identify markets with open quantities
        active_slugs: Dict[str, bool] = {}
        for key, qty in positions.items():
            if key == "CASH":
                continue
            try:
                qty_val = float(qty)
            except Exception:
                qty_val = 0.0
            if qty_val <= 0:
                continue
            try:
                slug, _ = key.split(":", 1)
            except ValueError:
                continue
            active_slugs[slug] = True

        if not active_slugs:
            return

        closed_slugs: List[str] = []
        for slug in active_slugs.keys():
            market = get_market_info_fn(slug)
            if not isinstance(market, dict) or ("error" in market):
                continue
            status = str(market.get("status", "")).strip().lower()
            closed_flag = bool(market.get("closed")) or status in {"closed", "settled", "resolved"}

            if not closed_flag:
                # Additional heuristics for resolved markets
                resolved = market.get("resolved") or market.get("resolvedOutcome") or market.get("result")
                if resolved:
                    closed_flag = True

            if closed_flag:
                closed_slugs.append(slug)

        if not closed_slugs:
            return

        for slug in closed_slugs:
            settle(market_slug = slug, signature = self.signature)

    def _estimate_liquidation_value(self, slug: str, outcome: str, qty: float) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "value": 0.0,
            "price": None,
            "filled": 0.0,
            "unfilled": max(0.0, qty),
            "avg_price": None,
            "levels": None,
            "error": None,
        }

        if qty <= 0:
            return result

        try:
            _, token_id = _resolve_market_and_token(slug, outcome)
        except Exception as exc:
            result["error"] = f"resolve_token: {exc}"
            return result

        try:
            book = _get_order_book(token_id, self.signature)
        except Exception as exc:
            result["error"] = f"order_book: {exc}"
            return result

        simulation = _simulate_sell_shares(book, float(qty))
        filled = float(simulation.get("filled") or 0.0)
        proceeds = float(simulation.get("proceeds") or 0.0)
        unfilled = float(simulation.get("unfilled_shares") or max(0.0, qty - filled))
        avg_price = simulation.get("avg_price")

        per_share = None
        if qty > 0:
            try:
                per_share = proceeds / float(qty)
            except Exception:
                per_share = None

        result.update({
            "value": proceeds,
            "price": per_share,
            "filled": filled,
            "unfilled": unfilled,
            "avg_price": avg_price,
            "levels": simulation.get("levels"),
        })

        return result

    async def _compute_intraday_snapshot(
        self,
        current_datetime: str,
        snapshot_timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute current NAV and return based on latest positions and live prices.

        Returns:
            {
              "timestamp": iso8601,
              "date": today_date,
              "signature": str,
              "nav": float,
              "return": float | None,
              "cash": float,
              "positions": [ { key, qty, price, value }, ... ]
            }
        """
        from futureshow.utils.polymarket_position_tools import get_latest_position_by_time

        await self._auto_settle_closed_markets(current_datetime)

        positions, _ = get_latest_position_by_time(current_datetime, self.signature)
        try:
            cash_balance = float(positions.get("CASH", 0.0))
        except Exception:
            cash_balance = 0.0


        # Collect holdings requiring pricing
        holdings: Dict[str, float] = {}
        for k, v in (positions or {}).items():
            if k == "CASH":
                continue
            try:
                qty = float(v)
            except Exception:
                qty = 0.0
            if qty > 0:
                holdings[k] = qty

        # Aggregate NAV using simulated immediate liquidation on current (overlay-adjusted) book
        total_value = cash_balance
        detailed: List[Dict[str, Any]] = []
        for key, qty in holdings.items():
            try:
                slug, outcome = key.split(":", 1)
            except ValueError:
                continue
            liquidation = self._estimate_liquidation_value(slug, outcome, qty)
            total_value += float(liquidation.get("value", 0.0))
            detailed.append({
                "key": key,
                "qty": qty,
                "price": liquidation.get("price"),
                "value": liquidation.get("value"),
                "filled": liquidation.get("filled"),
                "unfilled": liquidation.get("unfilled"),
                "avg_price": liquidation.get("avg_price"),
                "levels": liquidation.get("levels"),
                "error": liquidation.get("error"),
                "mark_method": "orderbook_liquidation",
            })

        nav = total_value
        ret = None
        try:
            if float(self.initial_cash) > 0:
                ret = (nav / float(self.initial_cash)) - 1.0
        except Exception:
            ret = None

        return {
            "timestamp": (snapshot_timestamp or datetime.utcnow().isoformat() + "Z"),
            "as_of": current_datetime,
            "signature": self.signature,
            "nav": nav,
            "return": ret,
            "cash": cash_balance,
            "positions": detailed,
        }

        
    def _pnl_file_path(self, today_date: str) -> str:
        os.makedirs(self.pnl_dir, exist_ok=True)
        return os.path.join(self.pnl_dir, f"intraday_{today_date}.jsonl")

    async def record_intraday_pnl(self, today_date: str, snapshot_iso: Optional[str] = None) -> None:
        # Use end-user readable filename by day; snapshot still carries exact as_of time
        current_iso = snapshot_iso or (datetime.utcnow().isoformat() + "Z")
        snap = await self._compute_intraday_snapshot(current_iso, snapshot_timestamp=current_iso)
        fpath = self._pnl_file_path(today_date)
        try:
            with open(fpath, "a", encoding="utf-8") as f:
                f.write(json.dumps(snap, ensure_ascii=False) + "\n")
        except Exception:
            # best-effort; do not crash trading loop
            pass

    async def run_intraday_pnl_tracker(self, interval_seconds: int = 10) -> None:
        """Background task to record PnL snapshot every `interval_seconds`."""
        interval_seconds = max(10, interval_seconds)
        while True:
            try:
                today_date = datetime.utcnow().strftime("%Y-%m-%d")
                await self.record_intraday_pnl(today_date)
            except Exception:
                # Never raise; continue ticking
                pass
            await asyncio.sleep(interval_seconds)
