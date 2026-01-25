import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from agent_tools.tool_polymarket_data import list_markets_fn, get_market_info_fn, resolve_slug_fn, get_market_history_fn, get_market_prices_fn
def test_polymarket_data():
    result = list_markets_fn()
    latest = result[0]
    # del latest['tags']
    # print(f"result: {latest}")
    result = get_market_prices_fn("over-1pt8b-committed-to-the-megaeth-public-sale-982-115-476")
    print(f"result: {result}")

if __name__ == "__main__":
    test_polymarket_data()