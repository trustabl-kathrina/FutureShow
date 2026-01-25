import argparse
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from main import get_agent_class, get_provider_config, load_config
from futureshow.agent.polymarket.polymarket_forecast_agent import PolymarketForecastAgent
from futureshow.utils.polymarket_watchlist import (
    DEFAULT_WATCHLIST_PATH,
    refresh_trending_watchlist,
)
from rich.console import Console
from rich.panel import Panel
load_dotenv()

if not os.environ.get("RUNTIME_ENV_PATH"):
    os.environ["RUNTIME_ENV_PATH"] = str((Path(__file__).parent / ".runtime_env.json").resolve())


def _prepare_agents(
    config: Dict[str, Any],
    limit: int,
    watchlist_path: Path,
    agent_type: str,
) -> List[PolymarketForecastAgent]:
    AgentClass = get_agent_class(agent_type)

    enabled_models = [m for m in config.get("models", []) if m.get("enabled", True)]
    if not enabled_models:
        raise ValueError("配置文件中没有启用的模型")

    agent_config = config.get("agent_config", {})
    log_config = config.get("log_config", {})
    forecast_path = log_config.get("forecast_path", "./data/forecasts")

    selected_models = enabled_models[:limit] if limit else enabled_models

    agents: List[PolymarketForecastAgent] = []
    for model in selected_models:
        basemodel = model.get("basemodel")
        signature = model.get("signature")
        if not basemodel or not signature:
            print(f"⚠️ 模型参数缺失，跳过: {model}")
            continue

        provider = model.get("provider", "openai")
        provider_config = get_provider_config(provider)
        openai_base_url = provider_config.get("base_url")
        openai_api_key = provider_config.get("api_key")

        agent = AgentClass(
            signature=signature,
            basemodel=basemodel,
            max_steps=agent_config.get("max_steps", 6),
            max_retries=agent_config.get("max_retries", 2),
            base_delay=agent_config.get("base_delay", 0.5),
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            watchlist_path=watchlist_path,
            forecast_dir=forecast_path,
        )
        agents.append(agent)

    return agents


async def _run_once(
    agents: List[PolymarketForecastAgent],
    refresh_watchlist: bool,
    watch_year: Optional[int],
    watch_month: int,
) -> None:
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    console = Console()
    model_names = [agent.signature for agent in agents]
    console.print(Panel(f"▶ {now_iso}Z Forecast Loop, models: {', '.join(model_names)}", style="bold green"))
    for agent in agents:
        try:
            console.print(Panel(f"Running forecast for {agent.signature}", style="bold yellow"))
            await agent.run_forecasts(
                now_iso,
                refresh_watchlist=refresh_watchlist,
                watch_year=watch_year,
                watch_month=watch_month,
            )
        except Exception as exc:
            print(f"❌ Forecast 失败 ({agent.signature}): {exc}")
    print(f"✅ {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}Z 结束本轮预测")


async def main(
    config_path: Optional[str],
    watchlist_path: Path,
    refresh_watchlist: bool,
    watch_year: Optional[int],
    watch_month: int,
    interval_seconds: int,
    once: bool,
    limit: int,
    agent_type: str,
) -> None:
    config = load_config(config_path)
    agents = _prepare_agents(config, limit, watchlist_path, agent_type)
    # Ensure watchlist exists before looping
    if refresh_watchlist or not watchlist_path.exists():
        refresh_trending_watchlist(
            watchlist_path=watchlist_path,
            year=watch_year,
            month=watch_month,
        )

    while True:
        start = datetime.utcnow()
        await _run_once(
            agents,
            refresh_watchlist=refresh_watchlist,
            watch_year=watch_year,
            watch_month=watch_month,
        )
        if once:
            break
        elapsed = (datetime.utcnow() - start).total_seconds()
        sleep_s = max(300, interval_seconds - elapsed)
        next_run = datetime.utcnow() + timedelta(seconds=sleep_s)
        print(f"⏸️ 休眠 {sleep_s:.0f}s，下一轮预计 {next_run.strftime('%Y-%m-%dT%H:%M:%SZ')}Z")
        await asyncio.sleep(sleep_s)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="循环运行 Polymarket 预测 Agent（每 4 小时默认一次）")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径，默认为 configs/default_config.json")
    parser.add_argument("--watchlist", type=str, default=str(DEFAULT_WATCHLIST_PATH), help="watchlist 文件路径")
    parser.add_argument("--refresh", action="store_true", help="每轮运行前刷新 watchlist（过滤指定月）")
    parser.add_argument("--year", type=int, default=None, help="watchlist 目标年份（默认 UTC 当前年）")
    parser.add_argument("--month", type=int, default=11, help="watchlist 目标月份（默认 11 月）")
    parser.add_argument("--interval", type=int, default=3600 * 6, help="循环间隔秒（默认 4 小时，最小 300s）")
    parser.add_argument("--once", action="store_true", help="仅运行一轮后退出")
    parser.add_argument("--limit", type=int, default=4, help="最多启用的模型数量")
    parser.add_argument("--agent-type", type=str, default="PolymarketForecastAgent", help="Agent 类型，默认 PolymarketForecastAgent")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            main(
                config_path=args.config,
                watchlist_path=Path(args.watchlist),
                refresh_watchlist=args.refresh,
                watch_year=args.year,
                watch_month=args.month,
                interval_seconds=max(300, args.interval),
                once=args.once,
                limit=args.limit,
                agent_type=args.agent_type,
            )
        )
    except KeyboardInterrupt:
        print("⏹️ 手动停止 Forecast 循环")
