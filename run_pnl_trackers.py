import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from main import get_agent_class, get_provider_config, load_config

load_dotenv()

if not os.environ.get("RUNTIME_ENV_PATH"):
    os.environ["RUNTIME_ENV_PATH"] = str((Path(__file__).parent / ".runtime_env.json").resolve())


def _resolve_init_datetime(config: Dict[str, Any]) -> str:
    init_datetime = None
    try:
        init_datetime = config.get("time_config", {}).get("init_datetime")
    except Exception:
        init_datetime = None

    if not init_datetime:
        try:
            legacy_date = config.get("date_range", {}).get("init_date")
            if legacy_date:
                init_datetime = f"{legacy_date}T00:00:00Z"
        except Exception:
            init_datetime = None

    if not init_datetime:
        init_datetime = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    env_override = os.getenv("INIT_DATETIME")
    if env_override:
        init_datetime = env_override

    return init_datetime


async def _prepare_agents(
    config: Dict[str, Any],
    init_datetime: str,
    limit: int,
) -> List[Dict[str, Any]]:
    agent_type = config.get("agent_type", "PolymarketAgent")
    try:
        AgentClass = get_agent_class(agent_type)
    except Exception as exc:
        print(f"❌ 获取 Agent 类失败: {exc}")
        return []

    enabled_models = [m for m in config.get("models", []) if m.get("enabled", True)]
    if not enabled_models:
        print("❌ 配置文件中没有启用的模型")
        return []

    agent_config = config.get("agent_config", {})
    log_config = config.get("log_config", {})
    log_path = log_config.get("log_path", "./data/agent_data")

    selected_models = enabled_models[:limit] if limit else enabled_models

    agents_info: List[Dict[str, Any]] = []
    for model_config in selected_models:
        model_name = model_config.get("name", "unknown")
        basemodel = model_config.get("basemodel")
        signature = model_config.get("signature")

        if not basemodel or not signature:
            print(f"⚠️ 模型 {model_name} 参数不完整，跳过")
            continue

        provider = model_config.get("provider", "openai")
        provider_config = get_provider_config(provider)
        openai_base_url = provider_config.get("base_url")
        openai_api_key = provider_config.get("api_key")

        try:
            agent = AgentClass(
                signature=signature,
                basemodel=basemodel,
                stock_symbols=None,
                log_path=log_path,
                openai_base_url=openai_base_url,
                openai_api_key=openai_api_key,
                max_steps=agent_config.get("max_steps", 10),
                max_retries=agent_config.get("max_retries", 3),
                base_delay=agent_config.get("base_delay", 0.5),
                initial_cash=agent_config.get("initial_cash", 10000.0),
                init_datetime=init_datetime,
            )
            await agent.initialize()
            agent.register_agent()
            agents_info.append({
                "name": model_name,
                "signature": signature,
                "agent": agent,
            })
            print(f"✅ Agent 已就绪: {model_name}（{signature}）")
        except Exception as exc:
            print(f"❌ 初始化模型 {model_name}（{signature}）失败: {exc}")

    return agents_info


async def _run_coordinated_trackers(
    agents_info: List[Dict[str, Any]],
    interval_seconds: int,
) -> None:
    interval_seconds = max(10, interval_seconds)
    agent_labels = ", ".join(f"{info['name']}({info['signature']})" for info in agents_info)
    print(f"🚀 启动 PnL 追踪，间隔 {interval_seconds}s，Agents: {agent_labels}")

    while True:
        cycle_start = datetime.utcnow()
        snapshot_iso = cycle_start.replace(microsecond=0).isoformat() + "Z"
        today_date = cycle_start.strftime("%Y-%m-%d")

        tasks = [
            info["agent"].record_intraday_pnl(today_date, snapshot_iso)
            for info in agents_info
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for info, result in zip(agents_info, results):
            if isinstance(result, Exception):
                print(f"⚠️ 记录 {info['name']}（{info['signature']}）PnL 失败: {result}")

        elapsed = (datetime.utcnow() - cycle_start).total_seconds()
        sleep_s = max(0.0, interval_seconds - elapsed)
        await asyncio.sleep(sleep_s)


async def main(config_path: Optional[str], interval_seconds: int, limit: int) -> None:
    config = load_config(config_path)
    init_datetime = _resolve_init_datetime(config)

    agents_info = await _prepare_agents(config, init_datetime, limit)
    if not agents_info:
        print("❌ 没有可用的 Agent，退出")
        return

    await _run_coordinated_trackers(agents_info, interval_seconds)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 Polymarket Agents 的 PnL 追踪器")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径，默认为 configs/default_config.json")
    parser.add_argument("--interval", type=int, default=10, help="记录间隔（秒），最小 10 秒")
    parser.add_argument("--limit", type=int, default=4, help="启用的 Agent 数量上限")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(main(args.config, args.interval, args.limit))
    except KeyboardInterrupt:
        print("⏹️ 手动停止 PnL 追踪")

