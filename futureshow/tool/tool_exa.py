from typing import Dict, Any
import os
import requests
from dotenv import load_dotenv
from agents import function_tool

load_dotenv()

EXA_BASE = os.environ.get("EXA_API_BASE", "https://api.exa.ai")


def _exa_headers() -> Dict[str, str]:
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise ValueError("EXA_API_KEY not set in environment (.env)")
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@function_tool
def google_url2text(url: str) -> str:
    """
    Fetch main text content for a single URL using Exa contents API.

    Args:
        url: Target URL to extract content from

    Returns:
        Extracted plain text (may be empty if not available)
    """
    try:
        endpoint = f"{EXA_BASE}/contents"
        payload: Dict[str, Any] = {"urls": [url], "text": True}
        r = requests.post(endpoint, headers=_exa_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data: Dict[str, Any] = r.json() or {}

        # Handle status errors reported by Exa
        statuses = data.get("statuses") or []
        if statuses:
            first_status = statuses[0] or {}
            if first_status.get("status") == "error":
                message = first_status.get("message") or "error"
                return f"❌ Error fetching {url}: {message}"

        # Preferred: top-level context
        if data.get("context"):
            return data["context"] or ""

        # Fallback: first result -> text or extract
        results = data.get("results") or []
        if results:
            item = results[0] or {}
            page_text = item.get("text") or item.get("extract") or ""
            return page_text

        return ""
    except Exception as e:
        return f"❌ Exa contents request failed: {e}"


if __name__ == "__main__":
    import asyncio
    from agents.tool_context import ToolContext

    test_url = "https://www.reddit.com/gallery/1mki70f"
    ctx = ToolContext(
        context=None,
        tool_name="url2text",
        tool_call_id="exa-url2text-test",
        tool_arguments=f'{{"url": "{test_url}"}}'
    )
    out = asyncio.run(
        google_url2text.on_invoke_tool(
            ctx,
            f'{{"url": "{test_url}"}}'
        )
    )
    print(out)
