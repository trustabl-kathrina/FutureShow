import argparse
import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from run_agents_once import main as run_agents_once_main

load_dotenv()

if not os.environ.get("RUNTIME_ENV_PATH"):
    os.environ["RUNTIME_ENV_PATH"] = str((Path(__file__).parent / ".runtime_env.json").resolve())


async def _loop_run(
    config_path: Optional[str],
    limit: int,
    base_interval: int,
    overrun_pause: int,
) -> None:
    base_interval = max(60, base_interval)
    overrun_pause = max(60, overrun_pause)

    while True:
        start_monotonic = time.monotonic()
        started_at = datetime.utcnow()
        print(f"▶ {started_at.isoformat()}Z 开始执行 run_agents_once")

        try:
            await run_agents_once_main(config_path, limit)
        except Exception as exc:
            print(f"❌ run_agents_once 执行异常: {exc}")

        finished_at = datetime.utcnow()
        elapsed = time.monotonic() - start_monotonic
        print(
            f"✅ {finished_at.isoformat()}Z 本轮耗时 {elapsed:.1f}s"
        )

        if elapsed < base_interval:
            sleep_seconds = base_interval - elapsed
            next_run_at = finished_at + timedelta(seconds=sleep_seconds)
            print(
                f"⏸️ 休眠 {sleep_seconds:.1f}s，下一次预计 {next_run_at.isoformat()}Z"
            )
        else:
            sleep_seconds = overrun_pause
            next_run_at = finished_at + timedelta(seconds=sleep_seconds)
            print(
                f"⏸️ 运行超出 {base_interval}s，休息 {sleep_seconds:.1f}s，下一次预计 {next_run_at.isoformat()}Z"
            )

        await asyncio.sleep(max(0.0, sleep_seconds))


async def main(
    config_path: Optional[str],
    limit: int,
    base_interval: int,
    overrun_pause: int,
) -> None:
    await _loop_run(config_path, limit, base_interval, overrun_pause)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="循环执行 run_agents_once，带运行时长判断的休眠策略"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="配置文件路径，默认使用 configs/default_config.json",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=4,
        help="启用的 Agent 数量上限",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=2400,
        help="目标间隔秒数（默认 2400s，即 40 分钟）",
    )
    parser.add_argument(
        "--overrun-pause",
        type=int,
        default=900,
        help="当运行时长超过 interval 后的额外休眠秒数（默认 900s，即 15 分钟）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            main(
                args.config,
                args.limit,
                args.interval,
                args.overrun_pause,
            )
        )
    except KeyboardInterrupt:
        print("⏹️ 手动停止 run_agents_loop")

