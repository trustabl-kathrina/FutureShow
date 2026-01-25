import os
import json

from agent_tools import tool_polymarket_data as pdata


def test_list_markets_basic():
    raw = pdata._get_markets_raw(limit=50)
    assert isinstance(raw, dict)
    assert 'data' in raw
    data = raw['data']
    assert isinstance(data, list)
    assert len(data) > 0

    # Flatten and check fields on first item
    m = data[0]
    assert 'market_slug' in m or 'question' in m
    # ensure tokens field present
    assert 'tokens' in m


def test_filter_and_prices_snapshot():
    raw = pdata._get_markets_raw(limit=200)
    data = raw['data']
    filtered = pdata._filter_markets(data, query=None, closed=None, active=None, tag=None)
    assert isinstance(filtered, list)

    # Build simplified list using the tool logic
    out = []
    for m in filtered[:10]:
        tokens = m.get('tokens') or []
        out.append({
            'market_slug': m.get('market_slug'),
            'question': m.get('question'),
            'tokens': [{'outcome': t.get('outcome'), 'price': t.get('price')} for t in tokens],
        })
    assert len(out) > 0
    # at least one token record present
    assert any(len(x['tokens']) > 0 for x in out)

