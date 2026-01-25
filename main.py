import os
import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
from dotenv import load_dotenv
import litellm
# litellm._turn_on_debug()
load_dotenv()

from futureshow.utils.general_tools import get_config_value, write_config_value

# Ensure runtime env file path is set for tool coordination
import os as _os
from pathlib import Path as _Path
if not _os.environ.get("RUNTIME_ENV_PATH"):
    _os.environ["RUNTIME_ENV_PATH"] = str((_Path(__file__).parent / ".runtime_env.json").resolve())


# Agent class mapping table - for dynamic import and instantiation
AGENT_REGISTRY = {
    "PolymarketAgent": {
        "module": "futureshow.agent.polymarket.polymarket_agent",
        "class": "PolymarketAgent"
    },
    "PolymarketForecastAgent": {
        "module": "futureshow.agent.polymarket.polymarket_forecast_agent",
        "class": "PolymarketForecastAgent"
    },
}


def get_agent_class(agent_type):
    """
    Dynamically import and return the corresponding class based on agent type name
    
    Args:
        agent_type: Agent type name (e.g., "BaseAgent")
        
    Returns:
        Agent class
        
    Raises:
        ValueError: If agent type is not supported
        ImportError: If unable to import agent module
    """
    if agent_type not in AGENT_REGISTRY:
        supported_types = ", ".join(AGENT_REGISTRY.keys())
        raise ValueError(
            f"❌ Unsupported agent type: {agent_type}\n"
            f"   Supported types: {supported_types}"
        )
    
    agent_info = AGENT_REGISTRY[agent_type]
    module_path = agent_info["module"]
    class_name = agent_info["class"]
    
    try:
        # Dynamic import module
        import importlib
        module = importlib.import_module(module_path)
        agent_class = getattr(module, class_name)
        print(f"✅ Successfully loaded Agent class: {agent_type} (from {module_path})")
        return agent_class
    except ImportError as e:
        raise ImportError(f"❌ Unable to import agent module {module_path}: {e}")
    except AttributeError as e:
        raise AttributeError(f"❌ Class {class_name} not found in module {module_path}: {e}")


def load_config(config_path=None):
    """
    Load configuration file from configs directory
    
    Args:
        config_path: Configuration file path, if None use default config
        
    Returns:
        dict: Configuration dictionary
    """
    if config_path is None:
        # Default configuration file path
        config_path = Path(__file__).parent / "configs" / "default_config.json"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        print(f"❌ Configuration file does not exist: {config_path}")
        exit(1)
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"✅ Successfully loaded configuration file: {config_path}")
        return config
    except json.JSONDecodeError as e:
        print(f"❌ Configuration file JSON format error: {e}")
        exit(1)
    except Exception as e:
        print(f"❌ Failed to load configuration file: {e}")
        exit(1)


async def _graceful_shutdown():
    try:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        loop = asyncio.get_running_loop()
        if hasattr(loop, "shutdown_asyncgens"):
            await loop.shutdown_asyncgens()
    except Exception:
        pass

def get_provider_config(provider):
    match provider:
        case "openai":
            return {
                "base_url": os.getenv("OPENAI_API_BASE"),
                "api_key": os.getenv("OPENAI_API_KEY")
            }
        case "deepseek":
            return {
                "base_url": os.getenv("DEEPSEEK_API_BASE"),
                "api_key": os.getenv("DEEPSEEK_API_KEY")
            }
        case "openrouter":
            return {
                "base_url": os.getenv("OPENROUTER_API_BASE"),
                "api_key": os.getenv("OPENROUTER_API_KEY")
            }
        case "private":
            return {
                "base_url": os.getenv("PRIVATE_API_BASE"),
                "api_key": os.getenv("PRIVATE_API_KEY")
            }
        case _:
            return {
                "base_url": None,
                "api_key": None
            }


async def main(config_path=None):
    """Run trading experiment using BaseAgent class
    
    Args:
        config_path: Configuration file path, if None use default config
    """
    # Load configuration file
    config = load_config(config_path)
    
    # Get Agent type
    agent_type = config.get("agent_type", "PolymarketAgent")
    try:
        AgentClass = get_agent_class(agent_type)
    except (ValueError, ImportError, AttributeError) as e:
        print(str(e))
        exit(1)
    
    # Get init datetime from configuration (support both new and legacy keys)
    init_datetime = None
    # New preferred: time_config.init_datetime
    try:
        init_datetime = config.get("time_config", {}).get("init_datetime")
    except Exception:
        init_datetime = None
    # Legacy fallback: date_range.init_date -> convert to start-of-day UTC
    if not init_datetime:
        try:
            legacy_date = config.get("date_range", {}).get("init_date")
            if legacy_date:
                init_datetime = f"{legacy_date}T00:00:00Z"
        except Exception:
            init_datetime = None
    # Final fallback: now UTC
    if not init_datetime:
        init_datetime = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Environment variables can override init datetime (optional)
    if os.getenv("INIT_DATETIME"):
        init_datetime = os.getenv("INIT_DATETIME")
        print(f"⚠️  Using environment variable to override INIT_DATETIME: {init_datetime}")
 
    # Get model list from configuration file (only select enabled models)
    enabled_models = [
        model for model in config["models"] 
        if model.get("enabled", True)
    ]
    
    # Get agent configuration
    agent_config = config.get("agent_config", {})
    log_config = config.get("log_config", {})
    max_steps = agent_config.get("max_steps", 10)
    max_retries = agent_config.get("max_retries", 3)
    base_delay = agent_config.get("base_delay", 0.5)
    initial_cash = agent_config.get("initial_cash", 10000.0)
    
    # Display enabled model information
    model_names = [m.get("name", m.get("signature")) for m in enabled_models]
    
    print("🚀 启动实时交易模拟（按小时推进，PNL 每 10 分钟统计）")
    print(f"🤖 Agent 类型: {agent_type}")
    print(f"⏱️ 初始化时间: {init_datetime}")
    print(f"🤖 模型列表: {model_names}")
    print(f"⚙️ 运行参数: max_steps={max_steps}, max_retries={max_retries}, base_delay={base_delay}, initial_cash={initial_cash}")

    # 准备所有模型的 Agent 实例，并启动各自的 PnL 10 分钟跟踪任务
    agents_info = []
    log_path = log_config.get("log_path", "./data/agent_data")
    # 将 INIT_DATETIME 写入运行态，供交易工具兜底使用
    write_config_value("INIT_DATETIME", init_datetime)
    for model_config in enabled_models:
        model_name = model_config.get("name", "unknown")
        basemodel = model_config.get("basemodel")
        signature = model_config.get("signature")

        provider = model_config.get("provider", "openai")
        provider_config = get_provider_config(provider)
        openai_base_url = provider_config.get("base_url", None)
        openai_api_key = provider_config.get("api_key", None)

        if not basemodel:
            print(f"❌ 模型 {model_name} 缺少 basemodel 字段，跳过")
            continue
        if not signature:
            print(f"❌ 模型 {model_name} 缺少 signature 字段，跳过")
            continue

        try:
            agent = AgentClass(
                signature=signature,
                basemodel=basemodel,
                stock_symbols=None,
                log_path=log_path,
                openai_base_url=openai_base_url,
                openai_api_key=openai_api_key,
                max_steps=max_steps,
                max_retries=max_retries,
                base_delay=base_delay,
                initial_cash=initial_cash,
                init_datetime=init_datetime,
            )
            await agent.initialize()
            agent.register_agent()
            print(f"✅ 已初始化 {agent_type} 实例: {agent}")
            agents_info.append({
                "name": model_name,
                "signature": signature,
                "agent": agent,
            })
        except Exception as e:
            print(f"❌ 初始化模型 {model_name} ({signature}) 失败: {e}")
            continue

    if not agents_info:
        print("❌ 没有可用的模型，退出")
        return

    # 启动 PnL 跟踪后台任务（每 10 分钟记录一次）
    pnl_tasks = []
    for info in agents_info:
        a = info["agent"]
        pnl_tasks.append(asyncio.create_task(a.run_intraday_pnl_tracker(interval_seconds=10)))

    # 每 2 小时对每个模型运行一次当下交易回合（按小时推进思路，单次调用为“本时段”决策）
    try:
        while True:
            cycle_start = datetime.utcnow()
            print("=" * 60)
            print(f"⏱️ 周期开始: {cycle_start.isoformat()}Z，逐个模型运行交易回合…")

            for info in agents_info:
                agent = info["agent"]
                signature = info["signature"]
                model_name = info["name"]

                # 将运行态环境绑定到该模型（用于交易工具写入持仓账本）
                now_dt_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                write_config_value("SIGNATURE", signature)
                write_config_value("CURRENT_DATETIME", now_dt_iso)
                write_config_value("IF_TRADE", False)

                print(f"▶ 运行模型: {model_name}（{signature}） 当前时间: {now_dt_iso}")
                try:
                    await agent.run_with_retry(now_dt_iso)
                except Exception as e:
                    print(f"❌ 模型 {model_name}（{signature}）本周期运行失败: {e}")
                else:
                    print(f"✅ 模型 {model_name}（{signature}）本周期运行完成")

            # 计算与休眠以维持 2 小时节奏
            elapsed = (datetime.utcnow() - cycle_start).total_seconds()
            sleep_s = max(5 * 60, int(60 * 60 - elapsed))
            wake_at = datetime.utcnow() + timedelta(seconds=sleep_s)
            print(f"🕒 本轮用时 {int(elapsed)}s，将休眠 {sleep_s}s，下次预计: {wake_at.isoformat()}Z")
            await asyncio.sleep(sleep_s)
    finally:
        for t in pnl_tasks:
            try:
                t.cancel()
            except Exception:
                pass
        await _graceful_shutdown()
    
if __name__ == "__main__":
    import sys
    
    # Support specifying configuration file through command line arguments
    # Usage: python livebaseagent_config.py [config_path]
    # Example: python livebaseagent_config.py configs/my_config.json
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    
    if config_path:
        print(f"📄 Using specified configuration file: {config_path}")
    else:
        print(f"📄 Using default configuration file: configs/default_config.json")
    
    asyncio.run(main(config_path))
