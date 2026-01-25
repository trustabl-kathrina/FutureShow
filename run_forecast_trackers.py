import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from main import get_agent_class, get_provider_config, load_config
from futureshow.agent.polymarket.polymarket_forecast_agent import PolymarketForecastAgent
from futureshow.utils.polymarket_watchlist import DEFAULT_WATCHLIST_PATH
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


async def _run_once(agents: List[PolymarketForecastAgent]) -> None:
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"▶ {now_iso}Z 开始 Forecast Tracker，Agent 数量 {len(agents)}")
    for agent in agents:
        try:
            events = agent.load_watchlist(refresh=False)
            await agent.record_snapshot(now_iso, events)
        except Exception as exc:
            print(f"⚠️ 记录失败 ({agent.signature}): {exc}")
    print(f"✅ {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}Z 结束本轮")


async def main(
    config_path: Optional[str],
    watchlist_path: Path,
    interval_seconds: int,
    once: bool,
    limit: int,
    agent_type: str,
) -> None:
    config = load_config(config_path)
    agents = _prepare_agents(config, limit, watchlist_path, agent_type)

    while True:
        await _run_once(agents)
        if once:
            break
        await asyncio.sleep(max(60, interval_seconds))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="轮询记录 Forecast 状态（是否 close、当前市场价格）")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径，默认为 configs/default_config.json")
    parser.add_argument("--watchlist", type=str, default=None, help="watchlist 文件路径（默认使用 agent 内置路径）")
    parser.add_argument("--interval", type=int, default=1800, help="记录间隔（秒），默认 600")
    parser.add_argument("--once", action="store_true", help="仅运行一轮后退出")
    parser.add_argument("--limit", type=int, default=4, help="最多启用的模型数量")
    parser.add_argument("--agent-type", type=str, default="PolymarketForecastAgent", help="Agent 类型")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            main(
                config_path=args.config,
                watchlist_path=Path(args.watchlist) if args.watchlist else Path(DEFAULT_WATCHLIST_PATH),
                interval_seconds=args.interval,
                once=args.once,
                limit=args.limit,
                agent_type=args.agent_type,
            )
        )
    except KeyboardInterrupt:
        print("⏹️ 手动停止 Forecast Tracker")
