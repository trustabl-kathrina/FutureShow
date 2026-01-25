import os
import sys
import json
from datetime import datetime
from typing import Tuple, Dict, Any

import requests

# 确保可以导入项目包
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent_tools.tool_polymarket_trade import simulate_buy, simulate_sell


CLOB = os.getenv("CLOB_HOST", "https://clob.polymarket.com")


def _pick_liquid_market_from_clob() -> Tuple[str, str, float]:
    """从 CLOB /markets 里挑一个未关闭且有价格的市场与 outcome。

    返回: (market_slug, outcome, price)
    """
    r = requests.get(f"{CLOB}/markets", params={"limit": 1000}, timeout=15)
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else data.get("data", [])
    for m in items:
        if m.get("closed"):
            continue
        tokens = m.get("tokens") or []
        for t in tokens:
            p = t.get("price")
            if p is None:
                continue
            try:
                price = float(p)
            except Exception:
                continue
            if 0.0 < price < 1.0:
                return m.get("market_slug"), str(t.get("outcome")), price
    raise RuntimeError("未找到可用的未关闭且有价格的市场")


def test_simulate_buy_and_sell_roundtrip():
    signature = "unit-test-sim-1"
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    slug, outcome, price = _pick_liquid_market_from_clob()
    print(f"选择市场: {slug} | outcome={outcome} | 当前估价≈{price}")

    # 先买入
    buy_cost = 20.0
    buy_res: Dict[str, Any] = simulate_buy(signature, slug, outcome, buy_cost, date_str)
    assert "error" not in buy_res, f"simulate_buy 失败: {buy_res}"
    shares = float(buy_res.get("shares", 0.0))
    assert shares > 0, "买入股数应大于 0"
    print(f"买入完成: shares={shares:.4f}, price≈{buy_res.get('price')}")

    # 再卖出一半
    sell_shares = max(shares * 0.5, 0.01)
    sell_res: Dict[str, Any] = simulate_sell(signature, slug, outcome, sell_shares, date_str)
    assert "error" not in sell_res, f"simulate_sell 失败: {sell_res}"
    print(f"卖出完成: shares={sell_shares:.4f}, price≈{sell_res.get('price')}, proceeds≈{sell_res.get('proceeds')}")


def test_simulate_sell_insufficient_shares():
    signature = "unit-test-sim-2"
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    slug, outcome, _ = _pick_liquid_market_from_clob()
    # 未买入直接卖出，应该报错持仓不足
    res: Dict[str, Any] = simulate_sell(signature, slug, outcome, shares=1.0, date=date_str)
    assert "error" in res, "应返回 error 表示持仓不足"
    print(f"预期失败(持仓不足): {json.dumps(res, ensure_ascii=False)}")


if __name__ == "__main__":
    # 直接运行脚本时执行两项测试
    test_simulate_buy_and_sell_roundtrip()
    test_simulate_sell_insufficient_shares()
    print("完成: trade simulate 测试")


