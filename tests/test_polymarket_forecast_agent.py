import json
from pathlib import Path

import pytest

from futureshow.agent.polymarket.polymarket_forecast_agent import PolymarketForecastAgent


class DummyResult:
    def __init__(self, text: str):
        self.final_output = text


class DummySession:
    def __init__(self, key: str):
        self.key = key


@pytest.mark.asyncio
async def test_forecast_agent_records_predictions(monkeypatch, tmp_path: Path):
    # Prepare watchlist
    watchlist_path = tmp_path / "watch.json"
    watchlist_path.write_text(
        json.dumps(
            [
                {
                    "slug": "test-slug",
                    "title": "Test Event",
                    "endDate": "2024-11-15T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    # Stub Runner.run to avoid LLM calls
    async def fake_run(*args, **kwargs):
        return DummyResult("Rationale...\n<PREDICTION> test-slug|YES </PREDICTION>")

    monkeypatch.setattr(
        "futureshow.agent.polymarket.polymarket_forecast_agent.Runner.run",
        fake_run,
    )
    monkeypatch.setattr(
        "futureshow.agent.polymarket.polymarket_forecast_agent.SQLiteSession",
        DummySession,
    )

    agent = PolymarketForecastAgent(
        signature="sig",
        basemodel="mock-model",
        watchlist_path=watchlist_path,
        forecast_dir=tmp_path / "forecasts",
    )

    results = await agent.run_forecasts("2024-10-01T00:00:00Z", refresh_watchlist=False)
    assert results and results[0]["event_slug"] == "test-slug"
    assert results[0]["predictions"] == [{"slug": "test-slug", "outcome": "YES"}]

    out_file = tmp_path / "forecasts" / "sig" / "test-slug" / "forecasts.jsonl"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8").strip()
    assert "<PREDICTION>" in content
