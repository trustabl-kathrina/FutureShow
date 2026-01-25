import os
import time
from pathlib import Path

from agent_tools import tool_polymarket_data as pdata
from agent_tools import tool_polymarket_trade as ptrade


def _pick_liquid_market():
    raw = pdata._get_markets_raw(limit=1000)
    for m in raw.get('data', []):
        tokens = m.get('tokens') or []
        for t in tokens:
            p = t.get('price')
            # pick something tradable (strictly between 0 and 1)
            if isinstance(p, (int, float)) and p > 0.01 and p < 0.99:
                return m.get('market_slug'), str(t.get('outcome'))
    raise RuntimeError('No liquid market found in snapshot; try again later')


def test_simulate_buy_sell(tmp_path):
    # configure runtime env path for tools
    os.environ['RUNTIME_ENV_PATH'] = str(tmp_path / 'runtime_env.json')
    signature = f"test-poly-{int(time.time())}"
    today = '2025-10-28'

    # pick a market/outcome with price in (0,1)
    slug, outcome = _pick_liquid_market()

    # ensure position file path
    pos_path = Path(ptrade._position_file(signature))
    pos_path.parent.mkdir(parents=True, exist_ok=True)

    # Buy $5 worth
    res_buy = ptrade.simulate_buy(signature, slug, outcome, cost_usd=5.0, date=today)
    assert res_buy.get('ok')
    positions = res_buy['positions']
    key = f"{slug}:{outcome}"
    assert key in positions
    assert positions[key] > 0
    cash_after_buy = positions['CASH']
    shares_bought = res_buy['shares']

    # Sell half
    res_sell = ptrade.simulate_sell(signature, slug, outcome, shares=shares_bought / 2.0, date=today)
    assert res_sell.get('ok')
    positions2 = res_sell['positions']
    assert positions2[key] >= 0
    assert positions2['CASH'] > cash_after_buy  # cash increases on sell


def _pick_closed_market_with_winner():
    raw = pdata._get_markets_raw(limit=1000)
    for m in raw.get('data', []):
        if not m.get('closed'):
            continue
        tokens = m.get('tokens') or []
        if any(t.get('winner') for t in tokens):
            # use the first listed winning outcome name
            for t in tokens:
                if t.get('winner'):
                    return m.get('market_slug'), str(t.get('outcome'))
    raise RuntimeError('No closed winning market found in snapshot; try again later')


def test_simulate_settle(tmp_path):
    os.environ['RUNTIME_ENV_PATH'] = str(tmp_path / 'runtime_env.json')
    signature = f"test-poly-{int(time.time())}-settle"
    today = '2025-10-28'

    slug, win_outcome = _pick_closed_market_with_winner()

    # Buy nominal amount (may be price=1 for winners; this test focuses on settlement mechanics)
    res_buy = ptrade.simulate_buy(signature, slug, win_outcome, cost_usd=1.0, date=today)
    assert res_buy.get('ok')
    positions = res_buy['positions']
    key = f"{slug}:{win_outcome}"
    assert positions[key] > 0

    res_settle = ptrade.simulate_settle(signature, slug, date=today)
    assert res_settle.get('ok')
    positions_final = res_settle['positions']
    # After settlement, shares in this market are set to 0
    assert positions_final.get(key, 0.0) == 0.0

