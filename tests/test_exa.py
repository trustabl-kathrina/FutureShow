import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from agent_tools.tool_exa_search import get_information_fn
def test_exa_search():
    result = get_information_fn("What is the capital of France?")
    print(result)
    

if __name__ == "__main__":
    test_exa_search()