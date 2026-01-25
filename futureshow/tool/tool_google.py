from typing import Dict, Any, List
import os
import requests
from dotenv import load_dotenv
from agents import function_tool

load_dotenv()

SERPER_BASE = "https://google.serper.dev"


def _serper_headers() -> Dict[str, str]:
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise ValueError("SERPER_API_KEY not set in environment (.env)")
    return {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _post_json(endpoint: str, payload: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    url = f"{SERPER_BASE}{endpoint}"
    r = requests.post(url, headers=_serper_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}


@function_tool
def google_web_search(
    query: str,
    num_results: int = 5,
    location: str = "United States",
    hl: str = "en",
    gl: str = "us",
) -> str:
    """
    Perform Google Web Search via Serper API and return structured text results.

    Args:
        query: Search keywords
        num_results: Number of results (Serper returns up to ~10 per call)
        location: Search location (e.g., United States)
        hl: Language code (e.g., en)
        gl: Country code (e.g., us)
    """
    try:
        payload = {
            "q": query,
            "num": max(1, min(num_results, 10)),
            "location": location,
            "hl": hl,
            "gl": gl,
        }
        data = _post_json("/search", payload, timeout=25)
    except Exception as e:
        return f"❌ Serper web search failed: {e}"

    formatted: List[str] = []

    knowledge_graph = data.get("knowledgeGraph")
    if knowledge_graph:
        parts: List[str] = [
            "Knowledge Graph:",
            f"Title: {knowledge_graph.get('title', 'N/A')}",
            f"Type: {knowledge_graph.get('type', 'N/A')}",
            f"Description: {knowledge_graph.get('description', 'N/A')}",
        ]
        attributes = knowledge_graph.get("attributes") or {}
        if attributes:
            parts.append("Attributes:")
            for attr_key, attr_value in attributes.items():
                parts.append(f"  {attr_key}: {attr_value}")
        formatted.append("\n".join(parts))

    answer_box = data.get("answerBox")
    if answer_box:
        parts: List[str] = [
            "Answer Box:",
            f"Answer: {answer_box.get('answer', answer_box.get('snippet', 'N/A'))}",
        ]
        if answer_box.get("link"):
            parts.append(f"Source: {answer_box.get('link')}")
        formatted.append("\n".join(parts))

    organic = data.get("organic", [])
    if organic:
        for r in organic[: max(1, min(num_results, 10))]:
            title = r.get("title", "")
            link = r.get("link", "")
            snippet = r.get("snippet", "")
            position = r.get("position")
            block = [
                f"URL: {link}",
                f"Title: {title}",
                f"Snippet: {snippet}",
            ]
            if position is not None:
                block.append(f"Position: {position}")
            formatted.append("\n".join(block))

    if not formatted:
        return f"⚠️ No results for query: {query}"

    header = f"Query: {query}\n"
    return header + "\n\n".join(formatted)


@function_tool
def google_news_search(
    query: str,
    num_results: int = 5,
    hl: str = "en",
    gl: str = "us",
) -> str:
    """
    Perform Google News Search via Serper API and return structured text results.

    Args:
        query: Search keywords
        num_results: Number of results (Serper returns up to ~10 per call)
        hl: Language code (e.g., en)
        gl: Country code (e.g., us)
    """
    try:
        payload = {
            "q": query,
            "num": max(1, min(num_results, 10)),
            "hl": hl,
            "gl": gl,
        }
        data = _post_json("/news", payload, timeout=25)
    except Exception as e:
        return f"❌ Serper news search failed: {e}"

    news_items = data.get("news") or data.get("organic") or []
    if not news_items:
        return f"⚠️ No news results for query: {query}"

    formatted: List[str] = []
    for r in news_items[: max(1, min(num_results, 10))]:
        title = r.get("title", "")
        link = r.get("link", "")
        snippet = r.get("snippet", "")
        source = r.get("source") or r.get("publisher")
        date_str = r.get("date") or r.get("publishedTime")
        block = [
            f"URL: {link}",
            f"Title: {title}",
            f"Snippet: {snippet}",
        ]
        if source:
            block.append(f"Source: {source}")
        if date_str:
            block.append(f"Date: {date_str}")
        formatted.append("\n".join(block))

    header = f"Query: {query}\n"
    return header + "\n\n".join(formatted)


if __name__ == "__main__":
    import asyncio
    from agents.tool_context import ToolContext

    # Quick local tests
    ctx_web = ToolContext(
        context=None,
        tool_name="google_web_search",
        tool_call_id="google-web-test",
        tool_arguments='{"query":"OpenAI Sora", "num_results":3}'
    )
    out_web = asyncio.run(
        google_web_search.on_invoke_tool(
            ctx_web,
            '{"query":"OpenAI Sora", "num_results":3}'
        )
    )
    print("google_web_search:")
    print(out_web)

    ctx_news = ToolContext(
        context=None,
        tool_name="google_news_search",
        tool_call_id="google-news-test",
        tool_arguments='{"query":"NVIDIA earnings", "num_results":3}'
    )
    out_news = asyncio.run(
        google_news_search.on_invoke_tool(
            ctx_news,
            '{"query":"NVIDIA earnings", "num_results":3}'
        )
    )
    print("google_news_search:")
    print(out_news)
