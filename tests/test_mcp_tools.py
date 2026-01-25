#!/usr/bin/env python3
"""
MCP Tools 测试脚本
通过 HTTP 请求测试运行中的 MCP 服务
"""

import os
import sys
import json
import time
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional

# MCP 服务端口配置
POLYMARKET_DATA_PORT = int(os.getenv('POLYMARKET_DATA_HTTP_PORT', '8052'))
BASE_URL = f"http://localhost:{POLYMARKET_DATA_PORT}/mcp"


def print_section(title: str):
    """打印分节标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(test_name: str, success: bool, details: str = ""):
    """打印测试结果"""
    status = "✅ 通过" if success else "❌ 失败"
    print(f"{status} - {test_name}")
    if details:
        print(f"    {details}")


class MCPSession:
    """MCP 会话管理器"""
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_id = None
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
    
    def initialize(self) -> bool:
        """初始化 MCP 会话"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"}
            }
        }
        
        try:
            response = requests.post(self.base_url, json=payload, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # 从响应头获取 session ID
            self.session_id = response.headers.get("mcp-session-id")
            if not self.session_id:
                return False

            # 解析初始化的 SSE 响应，确保初始化完成
            init_result = self.parse_sse_response(response.text)
            if not init_result:
                time.sleep(0.1)

            # 主动探测一次 tools/list 以确保会话已就绪
            probe_headers = self.headers.copy()
            probe_headers["mcp-session-id"] = self.session_id
            probe_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            }

            for _ in range(50):
                try:
                    probe_resp = requests.post(self.base_url, json=probe_payload, headers=probe_headers, timeout=5)
                    probe_resp.raise_for_status()
                    data = self.parse_sse_response(probe_resp.text)
                    if data and "error" not in data:
                        return True
                except Exception:
                    pass
                time.sleep(0.1)

            return False
        except Exception as e:
            print(f"初始化会话失败: {e}")
            return False
    
    def parse_sse_response(self, text: str) -> Optional[Dict[str, Any]]:
        """解析 SSE 格式的响应"""
        lines = text.strip().split('\n')
        for i, line in enumerate(lines):
            if line.startswith('data: '):
                try:
                    return json.loads(line[6:])  # 跳过 "data: " 前缀
                except json.JSONDecodeError:
                    continue
        return None
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """调用 MCP 工具"""
        if not self.session_id:
            if not self.initialize():
                return {"error": "无法初始化 MCP 会话"}
        
        if arguments is None:
            arguments = {}
        
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        headers = self.headers.copy()
        headers["mcp-session-id"] = self.session_id
        
        try:
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 解析 SSE 响应
            result = self.parse_sse_response(response.text)
            if not result:
                # 等待后重试一次（避免初始化竞争或网络抖动）
                time.sleep(0.2)
                response = requests.post(self.base_url, json=payload, headers=headers, timeout=30)
                response.raise_for_status()
                result = self.parse_sse_response(response.text)
                if not result:
                    return {"error": "无法解析响应"}
            
            if "error" in result:
                return {"error": result["error"]}
            
            if "result" in result:
                # FastMCP 返回格式: {"result": {"content": [{"type": "text", "text": "..."}]}}
                content = result["result"].get("content", [])
                if content and len(content) > 0:
                    text = content[0].get("text", "{}")
                    return json.loads(text)
            
            return result
        except requests.exceptions.ConnectionError:
            return {"error": f"无法连接到 MCP 服务"}
        except Exception as e:
            return {"error": str(e)}


# 全局会话实例
_mcp_session = None

def call_mcp_tool(tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
    """调用 MCP 工具（使用全局会话）"""
    global _mcp_session
    if _mcp_session is None:
        _mcp_session = MCPSession(BASE_URL)
    return _mcp_session.call_tool(tool_name, arguments)


def check_service_health() -> bool:
    """检查服务健康状态"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def test_service_connection():
    """测试服务连接"""
    print_section("测试 0: 服务连接检查")
    
    try:
        # 尝试连接服务
        response = requests.get(BASE_URL, timeout=5)
        print_result("服务连接", True, f"成功连接到端口 {POLYMARKET_DATA_PORT}")
        return True
    except Exception as e:
        print_result("服务连接", False, f"无法连接: {str(e)}")
        print(f"\n  请确保 MCP 服务已启动:")
        print(f"  python agent_tools/start_mcp_services.py")
        return False


def test_list_markets():
    """测试 list_markets 工具"""
    print_section("测试 1: list_markets 工具")
    
    try:
        # 测试基本列表
        result = call_mcp_tool("list_markets", {"limit": 10})
        
        if "error" in result:
            print_result("list_markets 工具", False, f"错误: {result['error']}")
            return False
        
        markets = result
        assert isinstance(markets, list), "返回结果应该是列表"
        assert len(markets) > 0, "应该返回至少一个市场"
        
        print_result("基本市场列表", True, f"成功获取 {len(markets)} 个市场")
        
        # 检查市场结构
        m = markets[0]
        required_fields = ['market_slug', 'question', 'tokens']
        for field in required_fields:
            assert field in m, f"市场应包含 {field} 字段"
        
        print_result("市场数据结构验证", True)
        
        # 打印前3个市场
        print(f"\n  前 3 个市场:")
        for i, market in enumerate(markets[:3], 1):
            print(f"\n  {i}. {market['question'][:60]}...")
            print(f"     Slug: {market['market_slug']}")
            print(f"     结束时间: {market.get('end_date_iso', 'N/A')}")
            if market.get('tokens'):
                print(f"     结果选项:")
                for token in market['tokens']:
                    price = token.get('price', 'N/A')
                    if price != 'N/A':
                        price = f"{float(price)*100:.1f}%"
                    print(f"       - {token.get('outcome')}: {price}")
        
        return True
    except Exception as e:
        print_result("list_markets 工具", False, f"错误: {str(e)}")
        return False


def test_list_markets_with_filters():
    """测试带过滤器的 list_markets"""
    print_section("测试 2: list_markets 过滤功能")
    
    results = []
    
    # 测试查询过滤
    try:
        result = call_mcp_tool("list_markets", {"query": "Trump", "limit": 5})
        if "error" in result:
            print_result("查询过滤 (Trump)", False, f"错误: {result['error']}")
            results.append(False)
        else:
            markets = result
            print_result("查询过滤 (Trump)", True, f"找到 {len(markets)} 个相关市场")
            if markets:
                print(f"    示例: {markets[0]['question'][:60]}...")
            results.append(True)
    except Exception as e:
        print_result("查询过滤", False, f"错误: {str(e)}")
        results.append(False)
    
    # 测试标签过滤
    try:
        result = call_mcp_tool("list_markets", {"tag": "politics", "limit": 5})
        if "error" in result:
            print_result("标签过滤 (politics)", False, f"错误: {result['error']}")
            results.append(False)
        else:
            markets = result
            print_result("标签过滤 (politics)", True, f"找到 {len(markets)} 个市场")
            results.append(True)
    except Exception as e:
        print_result("标签过滤", False, f"错误: {str(e)}")
        results.append(False)
    
    # 测试仅活跃市场
    try:
        result = call_mcp_tool("list_markets", {"only_active": True, "limit": 5})
        if "error" in result:
            print_result("仅活跃市场", False, f"错误: {result['error']}")
            results.append(False)
        else:
            markets = result
            print_result("仅活跃市场", True, f"找到 {len(markets)} 个活跃市场")
            results.append(True)
    except Exception as e:
        print_result("仅活跃市场", False, f"错误: {str(e)}")
        results.append(False)
    
    # 测试即将到期的市场
    try:
        result = call_mcp_tool("list_markets", {"expiring_within_days": 3, "limit": 5})
        if "error" in result:
            print_result("即将到期市场 (3天内)", False, f"错误: {result['error']}")
            results.append(False)
        else:
            markets = result
            print_result("即将到期市场 (3天内)", True, f"找到 {len(markets)} 个市场")
            if markets:
                print(f"    最近到期: {markets[0].get('end_date_iso', 'N/A')}")
            results.append(True)
    except Exception as e:
        print_result("即将到期市场", False, f"错误: {str(e)}")
        results.append(False)
    
    return all(results)


def test_get_market_info():
    """测试 get_market_info 工具"""
    print_section("测试 3: get_market_info 工具")
    
    try:
        # 首先获取一个市场 slug
        result = call_mcp_tool("list_markets", {"limit": 1})
        if "error" in result or not result:
            print_result("get_market_info", False, "无法获取测试市场")
            return False
        
        markets = result
        market_slug = markets[0]['market_slug']
        print(f"  测试市场 slug: {market_slug}")
        
        # 获取市场详细信息
        info = call_mcp_tool("get_market_info", {"market_slug": market_slug})
        
        if 'error' in info:
            print_result("get_market_info", False, f"错误: {info['error']}")
            return False
        
        assert 'market_slug' in info or 'question' in info, "应返回市场信息"
        
        print_result("get_market_info", True, "成功获取市场详细信息")
        
        # 打印详细信息
        print(f"\n  市场详细信息:")
        print(f"    问题: {info.get('question', 'N/A')}")
        print(f"    描述: {info.get('description', 'N/A')[:100]}...")
        print(f"    结束时间: {info.get('end_date_iso', 'N/A')}")
        print(f"    是否关闭: {info.get('closed', 'N/A')}")
        print(f"    是否活跃: {info.get('active', 'N/A')}")
        print(f"    标签: {info.get('tags', [])}")
        
        return True
    except Exception as e:
        print_result("get_market_info", False, f"错误: {str(e)}")
        return False


def test_get_market_prices():
    """测试 get_market_prices 工具"""
    print_section("测试 4: get_market_prices 工具")
    
    try:
        # 获取一个市场 slug
        result = call_mcp_tool("list_markets", {"limit": 1, "only_liquid": True})
        if "error" in result or not result:
            print_result("get_market_prices", False, "无法获取测试市场")
            return False
        
        markets = result
        market_slug = markets[0]['market_slug']
        print(f"  测试市场: {markets[0]['question'][:60]}...")
        
        # 获取价格
        prices = call_mcp_tool("get_market_prices", {"market_slug": market_slug})
        
        if 'error' in prices:
            print_result("get_market_prices", False, f"错误: {prices['error']}")
            return False
        
        assert 'prices' in prices, "应返回价格信息"
        
        print_result("get_market_prices", True, "成功获取市场价格")
        
        # 打印价格信息
        print(f"\n  当前价格:")
        for p in prices['prices']:
            price = p.get('price')
            if price is not None:
                price_pct = float(price) * 100
                print(f"    {p.get('outcome')}: {price_pct:.2f}%")
            else:
                print(f"    {p.get('outcome')}: N/A")
        
        return True
    except Exception as e:
        print_result("get_market_prices", False, f"错误: {str(e)}")
        return False


def test_get_market_history():
    """测试 get_market_history 工具"""
    print_section("测试 5: get_market_history 工具")
    
    # 检查是否设置了 API key
    api_key = os.getenv("POLYMARKET_API_KEY")
    if not api_key:
        print_result("get_market_history", False, 
                    "跳过: 需要设置 POLYMARKET_API_KEY 环境变量")
        return None  # None 表示跳过
    
    try:
        # 获取一个市场 slug
        result = call_mcp_tool("list_markets", {"limit": 1})
        if "error" in result or not result:
            print_result("get_market_history", False, "无法获取测试市场")
            return False
        
        markets = result
        market_slug = markets[0]['market_slug']
        print(f"  测试市场: {markets[0]['question'][:60]}...")
        
        # 获取交易历史
        history = call_mcp_tool("get_market_history", {"market_slug": market_slug, "limit": 10})
        
        if 'error' in history:
            print_result("get_market_history", False, f"错误: {history['error']}")
            return False
        
        assert 'trades' in history, "应返回交易历史"
        
        trades = history['trades']
        print_result("get_market_history", True, f"成功获取 {len(trades)} 条交易记录")
        
        # 打印交易信息
        if trades:
            print(f"\n  最近交易:")
            for i, trade in enumerate(trades[:3], 1):
                print(f"    {i}. 结果: {trade.get('outcome', 'N/A')}")
                print(f"       价格: {trade.get('price', 'N/A')}")
                print(f"       数量: {trade.get('size', 'N/A')}")
                print(f"       时间: {trade.get('timestamp', 'N/A')}")
        
        return True
    except Exception as e:
        print_result("get_market_history", False, f"错误: {str(e)}")
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "🚀" * 30)
    print("  MCP Tools 测试套件 (HTTP 模式)")
    print("🚀" * 30)
    print(f"\n  目标服务: {BASE_URL}")
    
    start_time = time.time()
    
    # 首先检查服务连接
    if not test_service_connection():
        print("\n❌ 服务未运行，无法继续测试")
        return False
    
    tests = [
        ("list_markets 工具", test_list_markets),
        ("list_markets 过滤功能", test_list_markets_with_filters),
        ("get_market_info 工具", test_get_market_info),
        ("get_market_prices 工具", test_get_market_prices),
        ("get_market_history 工具", test_get_market_history),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ 测试 '{test_name}' 发生未捕获异常: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # 打印总结
    print_section("测试总结")
    
    passed = sum(1 for _, r in results if r is True)
    failed = sum(1 for _, r in results if r is False)
    skipped = sum(1 for _, r in results if r is None)
    total = len(results)
    
    print(f"\n  总计: {total} 个测试")
    print(f"  ✅ 通过: {passed}")
    print(f"  ❌ 失败: {failed}")
    print(f"  ⏭️  跳过: {skipped}")
    
    elapsed = time.time() - start_time
    print(f"\n  耗时: {elapsed:.2f} 秒")
    
    # 打印详细结果
    print("\n  详细结果:")
    for test_name, result in results:
        if result is True:
            status = "✅ 通过"
        elif result is False:
            status = "❌ 失败"
        else:
            status = "⏭️  跳过"
        print(f"    {status} - {test_name}")
    
    print("\n" + "=" * 60)
    
    if failed == 0 and skipped < total:
        print("  🎉 所有测试通过!")
    elif failed == 0:
        print("  ⚠️  所有测试被跳过")
    else:
        print(f"  ⚠️  有 {failed} 个测试失败")
    
    print("=" * 60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

