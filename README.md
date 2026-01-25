
<div align="center">
  
# FutureShow: Can AI Predict the Future?

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Feishu](https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=wechat&logoColor=white)](./Communication.md) 
[![WeChat](https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white)](./Communication.md)
[![Live Demo](https://img.shields.io/badge/demo-futureshow.org-brightgreen.svg)](https://futureshow.org)

**⚔️ AI Battle Arena: Competing to Predict Real-World Events**

| **📊 Live Battle Rankings** | 🎯 **Real-World Forecasting** | ⚡ **Prediction Markets** |

[Live Demo](https://futureshow.org) · [中文文档](README_CN.md) · [Report Bug](https://github.com/HKUDS/FutureShow/issues)

</div>

<div align="center">

## 🏆 Current Championship Leaderboard 🏆
[*Click Here: AI Live Future Forecasting*](https://futureshow.org/)

| Rank | Model | Correct/Total | Accuracy | Human Acc | vs Human | Pred Value |
|:----:|:-----:|:-------:|:--------:|:---------:|:--------:|:----------:|
| 🥇 1 | DeepSeek | 7535/7895 | 95.4% | 97.2% | -1.8% | +0.020 |
| 🥈 2 | GPT-5 | 8010/8661 | 92.5% | 96.9% | -4.5% | -0.041 |
| 🥉 3 | Gemini | 7717/8837 | 87.3% | 97.3% | -9.9% | -0.216 |

<sub>* Each model may generate different numbers of predictions due to varying prediction intervals.</sub><br>
<sub>* Human accuracy is calculated using the same prediction points as the corresponding model for fair comparison.</sub>

<sub>📅 **Round 1 Complete** — Results above are from events resolved before end of 2024. **Round 2 is now in progress!**</sub>

</div>

<details>
<summary><b>📊 Metrics Explanation</b></summary>

| Metric | Description |
|--------|-------------|
| **Correct** | Number of correct predictions relative to total predictions made on real-world events. |
| **Accuracy** | Prediction Accuracy: (Correct Predictions / Total Predictions) × 100% |
| **Human Acc** | Market Consensus Baseline: Accuracy of crowd wisdom at identical prediction points. Human predictions are derived as YES when market probability > 50%, otherwise NO, representing the collective "Wisdom of the Crowd" benchmark |
| **vs Human** | AI forecasting performance against crowd wisdom |
| **Pred Value** | Prediction Value (log-return method): Measures the model's value generation beyond market consensus. |

### Prediction Value Formula

```
If prediction is CORRECT:  Value = -log(p)
If prediction is INCORRECT: Value = log(p)

where p = market probability for the predicted outcome at prediction time
```

**Interpretation Guide:**

| Value Range | Market Prob (p) | Meaning |
|:-----------:|:---------------:|---------|
| **+0.1 ~ +0.7** | 50% ~ 90% | Small gain. Model correctly predicted what the market also favored. |
| **+0.7 ~ +2.3** | 10% ~ 50% | Moderate gain. Model correctly made a contrarian prediction. |
| **+2.3 ~ +6.9** | 0.1% ~ 10% | Exceptional gain. Model correctly predicted a very unlikely outcome. |
| **-0.1 ~ -0.7** | 50% ~ 90% | Minor loss. Model followed market consensus but both were wrong. |
| **-0.7 ~ -2.3** | 10% ~ 50% | Moderate loss. Model made a contrarian prediction that failed. |
| **-2.3 ~ -6.9** | 0.1% ~ 10% | Severe loss. Model predicted a very unlikely outcome and was wrong. |

> **Theoretical Bounds:** Value ranges from **-6.9** to **+6.9**, based on probability clamp [0.001, 0.999]. In practice, most values fall within ±2.3 (p between 10% and 90%).

The displayed Prediction Value is the **Average** across all predictions. Positive values indicate the model outperforms market consensus; negative values indicate underperformance.
</details>

---

## 📋 Table of Contents

- [🚀 Our Mission](#-our-mission)
- [🎯 What is FutureShow?](#-what-is-futureshow)
- [✨ Key Features](#-key-features)
- [🖼️ Screenshots](#️-screenshots)
- [🏗️ System Architecture](#️-system-architecture)
- [🏃 Quick Start](#-quick-start)
- [🔧 MCP Tools Reference](#-mcp-tools-reference)
- [📊 Forecasting Pipeline](#-forecasting-pipeline)
- [🌐 Dashboard & API](#-dashboard--api)
- [⚙️ Advanced Configuration](#️-advanced-configuration)
- [📁 Data Formats & Output](#-data-formats--output)
- [🛠️ Development](#️-development)
- [🤝 Contributing](#-contributing)

---

<img src="assets/cover.png" alt="FutureShow - AI Forecasting Benchmark" width="100%">

## 🚀 Our Mission

**Can AI Agents Outthink the Wisdom of the Crowd?**

### 🧠 The Foundation: Human Collective Intelligence

Prediction markets represent humanity's most sophisticated mechanism for aggregating collective intelligence. When thousands of participants stake real money on future outcomes, their combined judgment distills into remarkably accurate probability estimates. This "wisdom of the crowd" has consistently outperformed individual experts across virtually every domain.

### 🔬 Our Approach: Real-World Testing
FutureShow conducts a transparent, ongoing experiment:
- ⚔️ Direct Competition: Frontier AI models vs. market consensus
- 📊 Rigorous Methodology: Every prediction timestamped, every outcome independently verified
- ⚖️ Fair Comparison: Identical decision points, identical timeframes
- 🚫 Zero Bias: No cherry-picking, no hindsight adjustments

### 🔍 Beyond the Leaderboard
This study investigates AI boundaries beyond performance tracking:
- ✅ Where AI excels in prediction accuracy
- ❌ Where AI systematically fails against human crowds
- 💰 Whether machines can generate alpha against aggregated human wisdom

---

## 🎯 What is FutureShow?

### Can AI agents predict the future better than human crowds betting real money? 
FutureShow is an **Open-Source AI Benchmarking** platform that puts this question to the ultimate test. We evaluate frontier **AI Models** against prediction markets — where thousands of participants stake real money on future outcomes, creating some of the most accurate probability estimates available.

### How It Works
Our system operates as a continuous, real-world experiment:

**📊 Market Intelligence**
- Monitors live prediction markets on Polymarket
- Tracks events spanning politics, economics, tech, sports, and culture

**🤖 AI Agent Deployment**
- Deploys multiple frontier models (GPT-5, Claude, Gemini, DeepSeek)
- Each agent analyzes identical market conditions independently

**🔍 Real-Time Research**
- Agents gather intelligence via web search, news, Reddit, and Twitter
- No human intervention — pure AI reasoning and research

**📈 Transparent Tracking**
- Records each model's YES/NO predictions with full reasoning
- Tracks accuracy as real events unfold
- Maintains live performance leaderboard

### Why This Matters
- 🎲 Prediction markets aren't just betting — they're humanity's most sophisticated mechanism for aggregating collective intelligence. When people risk real money, their combined judgment creates remarkably accurate forecasts that consistently outperform individual experts.

- 🧠 This makes them perfect AI benchmarks — objective, real-time, and impossible to game. No synthetic datasets, no contrived scenarios. Just AI versus the wisdom of crowds, measured transparently.

---

## ✨ Key Features

### 🤖 Multi-Model Agent Arena

FutureShow supports any LLM accessible via [LiteLLM](https://github.com/BerriAI/litellm), including:

| Provider | Models | Configuration |
|----------|--------|---------------|
| **OpenAI** | GPT-4o, GPT-5 | `openai/gpt-5` |
| **Anthropic** | Claude 4.5 Sonnet, Claude Opus | `anthropic/claude-sonnet-4.5` |
| **Google** | Gemini 2.5 Pro, Gemini Ultra | `google/gemini-2.5-pro` |
| **DeepSeek** | DeepSeek-V3, DeepSeek-R1 | `deepseek/deepseek-chat-v3.1` |
| **OpenRouter** | 100+ models | `openrouter/provider/model` |

Each model runs as an independent agent with:
- Dedicated tool access (search, market data, reasoning)
- Isolated position/PnL tracking
- Persistent session state via SQLite
- Configurable max steps, retries, and delays

### 📈 Real-Time Market Intelligence

Agents have access to comprehensive MCP (Model Context Protocol) tools:

```
┌─────────────────────────────────────────────────────────────────┐
│                    🔧 MCP Tool Suite                            │
├─────────────────────────────────────────────────────────────────┤
│  📊 Market Data        │  🔍 Web Search      │  💬 Social       │
│  ├─ list_events        │  ├─ google_web      │  ├─ reddit       │
│  ├─ list_markets       │  ├─ google_news     │  └─ twitter      │
│  ├─ get_market_info    │  └─ exa_semantic    │                  │
│  ├─ get_market_prices  │                     │  💹 Trading      │
│  └─ get_market_history │  🔢 Utilities       │  ├─ buy          │
│                        │  └─ math_tool       │  └─ sell         │
└─────────────────────────────────────────────────────────────────┘
```

### 🏆 Live Leaderboard & Dashboard

- **Real-time accuracy tracking** across all resolved markets
- **Per-model breakdowns** with correct/total/abstain counts
- **Category-wise performance** (Politics, Crypto, Sports, etc.)
- **Historical forecast browsing** with full reasoning trails

### 📊 Simulated Trading Engine

FutureShow includes a realistic trading simulation:
- **Order book simulation** using live Polymarket CLOB data
- **Slippage modeling** with configurable liquidity impact
- **Position tracking** with JSONL ledger persistence
- **PnL calculation** with NAV (Net Asset Value) history

---

## 🖼️ Screenshots

<div align="center">
<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshot-forecasts.png" alt="Forecasts Overview" />
      <br/><b>📊 Forecasts Overview</b><br/>
      <sub>Main dashboard showing all prediction markets. Each card displays event title, market probability, and model predictions with colored icons indicating YES/NO votes.</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshot-details.png" alt="Event Detail Page" />
      <br/><b>📋 Event Detail Page</b><br/>
      <sub>Deep dive into a specific market with full prediction history, AI reasoning trails, probability charts, and final outcomes for closed events.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshot-leaderboard.png" alt="Model Leaderboard" />
      <br/><b>🏆 Model Leaderboard</b><br/>
      <sub>Competitive rankings showing accuracy, human baseline comparison, and Prediction Value — measuring how much alpha each model generates vs market consensus.</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshot-batchpred.gif" alt="Batch Prediction Demo" />
      <br/><b>⚡ Batch Prediction in Action</b><br/>
      <sub>Watch multiple AI agents analyze markets in parallel with real-time logging, concurrent execution, and automatic result persistence.</sub>
    </td>
  </tr>
</table>
</div>

---

## 🏗️ System Architecture

<div align="center">
<img src="assets/Architecture.png" alt="FutureShow Architecture" width="100%" />
</div>

---

## 🏃 Quick Start

### 1️⃣ Environment Setup

```bash
# Clone the repository
git clone https://github.com/HKUDS/FutureShow.git
cd FutureShow

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e .[dev]
```

### 2️⃣ API Key Configuration

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# ═══════════════════════════════════════════════════════════════
# LLM Provider API Keys (configure at least one)
# ═══════════════════════════════════════════════════════════════
DEEPSEEK_API_KEY="sk-xxx"                # DeepSeek models
DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"

OPENROUTER_API_BASE="https://openrouter.ai/api/v1"
OPENROUTER_API_KEY="sk-or-xxx"           # Access 100+ models via OpenRouter

OPENAI_API_BASE="https://api.openai.com/v1"  # Or custom endpoint
OPENAI_API_KEY="sk-xxx"                  # OpenAI GPT models

# Optional: Additional LLM providers
PRIVATE_API_BASE=""                      # Custom LLM endpoint
PRIVATE_API_KEY=""

LITE_API_BASE=""                         # LiteLLM proxy endpoint
LITE_API_KEY=""

# ═══════════════════════════════════════════════════════════════
# Search & Intelligence Tools
# ═══════════════════════════════════════════════════════════════
SERPER_API_KEY="xxx"                     # Google Search via Serper.dev
EXA_API_KEY="xxx"                        # Exa semantic search
RAPIDAPI_KEY="xxx"                       # RapidAPI for additional services

# ═══════════════════════════════════════════════════════════════
# Polymarket (optional, for trading mode)
# See "How to Get Polymarket Credentials" below
# ═══════════════════════════════════════════════════════════════
POLYMARKET_API_KEY=""                    # API key from Polymarket
PRIVATE_KEY=""                           # Your wallet private key
KEY=""                                   # Same as PRIVATE_KEY

# ═══════════════════════════════════════════════════════════════
# Agent Configuration
# ═══════════════════════════════════════════════════════════════
AGENT_MAX_STEP=30                        # Max reasoning steps per agent
RUNTIME_ENV_PATH=".runtime_env.json"     # Runtime state file
DEBUG=1                                  # Debug mode (1=enabled, 0=disabled)
```

<details>
<summary><b>📜 How to Get Polymarket Credentials (for Trading Mode)</b></summary>

> **Note:** These credentials are only required for **Live Trading Mode**. The forecasting benchmark works without them.

#### Step 1: Get Your Wallet Private Key (`PRIVATE_KEY` & `KEY`)

1. Create an Ethereum-compatible wallet (e.g., [MetaMask](https://metamask.io/))
2. Fund it with MATIC on **Polygon network** for transaction fees
3. Export your private key:
   - MetaMask: Settings → Security & Privacy → Reveal Secret Recovery Phrase (or export private key for specific account)
   - **⚠️ Never share your private key with anyone!**
4. Set both `PRIVATE_KEY` and `KEY` to the same value (your wallet private key)

#### Step 2: Generate Polymarket API Key (`POLYMARKET_API_KEY`)

Use the provided script to generate your API credentials:

```bash
# Make sure PRIVATE_KEY is set in your .env file first
python futureshow/utils/generate_poly_apikey.py
```

This script uses [py-clob-client](https://github.com/Polymarket/py-clob-client) to call `create_or_derive_api_creds()`, which derives your API key from your wallet signature.

Alternatively, generate via Polymarket UI:
1. Go to [Polymarket](https://polymarket.com) and connect your wallet
2. Navigate to **Settings → API**
3. Enable API trading and generate credentials

#### Resources

- [Polymarket Official Documentation](https://docs.polymarket.com/)
- [Builder Profile & Keys Guide](https://docs.polymarket.com/developers/builders/builder-profile)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)

</details>

### 3️⃣ Run Forecasting Benchmark

Start the AI forecasting agents to predict Polymarket events:

```bash
# ─── Single Round ───
# Run all enabled models once on current watchlist
python run_forecast_loop.py --once

# ─── Continuous Loop ───
# Run predictions every 6 hours (default), refresh watchlist each round
python run_forecast_loop.py --refresh --interval 21600

# ─── Custom Configuration ───
# Limit to 4 models, target specific month's events
python run_forecast_loop.py \
  --limit 4 \
  --month 1 \
  --year 2025 \
  --refresh
```

### 4️⃣ Track Results & Launch Dashboard

```bash
# Start event tracker (monitors market status & prices every 30 min)
python run_forecast_trackers.py --interval 1800 &

# Launch the forecasting dashboard
python web_server_pred.py
# Open http://localhost:10086
```

The dashboard displays:
- **Forecasts page**: All active/closed predictions with model votes
- **Detail page**: Full prediction history and AI reasoning for each event
- **Leaderboard**: Model accuracy rankings vs human baseline

---

### 🎰 Optional: Live Trading Mode

<details>
<summary><b>Enable simulated trading with PnL tracking</b></summary>

For advanced users who want to run live trading simulations.

**Prerequisites:** Configure `POLYMARKET_API_KEY`, `PRIVATE_KEY`, and `KEY` in your `.env` file.

```bash
# ─── Run Trading Agents ───
# Single round with trading enabled
python main.py configs/default_config.json

# Continuous trading loop (every 40 minutes)
python run_agents_loop.py \
  --interval 2400 \
  --overrun-pause 900 \
  --config configs/default_config.json

# ─── Track PnL & Launch Trading Dashboard ───
# Start PnL tracking (updates every 10 seconds)
python run_pnl_trackers.py --interval 10 --config configs/default_config.json &

# Launch trading dashboard
python web_server.py
# Open http://localhost:10032
```

</details>

---

## 🔧 MCP Tools Reference

FutureShow provides agents with these [Model Context Protocol](https://modelcontextprotocol.io/) tools:

### 📊 Polymarket Data Tools

| Tool | Function | Parameters | Returns |
|------|----------|------------|---------|
| `list_events` | List active events with category balancing | `query`, `tags_any`, `tags_all`, `exclude_tags`, `categories`, `limit`, `per_category`, `detailed` | Formatted event list with probability, volume, category |
| `list_markets` | List markets with filters | `query`, `tags_any`, `only_open`, `only_active`, `sort`, `trending_only`, `min_liquidity`, `limit` | Market objects with prices |
| `get_polymarket_info_by_slug` | Get market/event details | `slug` | Full market or event object with outcomes, prices |
| `get_market_prices` | Get current prices | `market_slug` | `{outcome: price}` mapping |
| `get_market_history` | Get price history | `market_slug`, `interval` | Historical price series per outcome |

<details>
<summary><b>Example: list_events output</b></summary>

```
01. trump-2028 | p=0.234 | vol=1523000.0 | OI=892341 | cat=US Politics | Will Trump run in 2028?
    tags: Politics, Elections, Trump
    time: end=2028-11-15T00:00:00Z | updated=2025-01-20T12:00:00Z
    liq: 45000 | comments=234
    market0: slug=trump-2028-yes | outcomes=['Yes', 'No'] | prices=[0.234, 0.766] | mid=0.234

02. btc-100k-jan | p=0.891 | vol=982000.0 | OI=456123 | cat=Crypto | Bitcoin above $100k by Jan 31?
    ...
```
</details>

### 🔍 Search Tools

| Tool | Source | Parameters | Returns |
|------|--------|------------|---------|
| `google_web_search` | Google via Serper | `query`, `num_results`, `location`, `hl`, `gl` | Formatted results with Knowledge Graph, Answer Box, organic results |
| `google_news_search` | Google News via Serper | `query`, `num_results`, `hl`, `gl` | News articles with title, snippet, source, date |
| `google_url2text` | Jina AI | `url` | Extracted article text |
| `reddit_search` | Reddit API | `query`, `subreddit`, `sort`, `limit` | Post titles, scores, comments |
| `reddit_post_details` | Reddit API | `post_id` | Full post with top comments |
| `search_tweets` | Twitter/X API | `query`, `max_results` | Recent tweets with engagement |

### 💹 Trading Simulation Tools

| Tool | Action | Parameters | Effect |
|------|--------|------------|--------|
| `buy` | Purchase shares | `market_slug`, `outcome`, `cost_usd` | Deduct cash, add shares, simulate slippage |
| `sell` | Sell shares | `market_slug`, `outcome`, `shares` | Add cash, remove shares, simulate slippage |
| `settle` | Settle closed market | `market_slug` | Pay out winning positions at $1/share |

<details>
<summary><b>Trading simulation features</b></summary>

- **Order Book Simulation**: Fetches real CLOB data from Polymarket
- **Slippage Modeling**: Consumes liquidity levels based on order size
- **Liquidity Overlay**: Tracks consumed liquidity with decay over time
- **Partial Fills**: Handles insufficient liquidity gracefully
- **JSONL Ledger**: All trades recorded with full execution details

</details>

### 🔢 Utility Tools

| Tool | Function | Parameters |
|------|----------|------------|
| `math_tool` | Evaluate mathematical expressions | `expression` |

---

## 📊 Forecasting Pipeline

### Agent Workflow

<div align="center">
<img src="assets/Workflow.png" alt="Forecasting Agent Workflow" width="90%" />
</div>

### Prediction Format

Agents output predictions in a structured format:

```xml
<PREDICTION>market-slug|YES</PREDICTION>
```

Or for binary markets without explicit slug:

```xml
<PREDICTION>YES</PREDICTION>
```

Supported values: `YES`, `NO`, `ABSTAIN`

---

## 🌐 Dashboard & API

### Web Server

```bash
python web_server.py
# Serves on http://0.0.0.0:10032 by default
```

Environment variables:
- `WEB_HOST`: Bind address (default: `0.0.0.0`)
- `WEB_PORT`: Port number (default: `10032`)

### REST API Endpoints

| Endpoint | Method | Description | Parameters |
|----------|--------|-------------|------------|
| `/api/status` | GET | System status, available models | `signature` |
| `/api/models` | GET | List all model signatures | - |
| `/api/positions` | GET | Latest positions & trades | `signature` |
| `/api/pnl` | GET | PnL history for date | `signature`, `date`, `full` |
| `/api/messages` | GET | Agent reasoning logs | `signature` |
| `/api/polymarket_info` | GET | Proxy to Polymarket data | `slug` |

<details>
<summary><b>Example API Response: /api/pnl</b></summary>

```json
{
  "ok": true,
  "signature": "gpt-5",
  "date": "2025-01-20",
  "times": ["2025-01-20T00:00:00Z", "2025-01-20T01:00:00Z", ...],
  "nav": [10000.0, 10023.45, 10089.12, ...],
  "returns": [0.0, 0.23, 0.89, ...],
  "latest": {
    "timestamp": "2025-01-20T23:59:00Z",
    "nav": 10234.56,
    "cash": 5234.56,
    "positions_value": 5000.0
  },
  "count": 24,
  "full": false
}
```
</details>

---

## ⚙️ Advanced Configuration

### Config File Structure

```json
{
  "agent_type": "PolymarketAgent",
  
  "date_range": {
    "init_date": "2025-01-01",
    "end_date": "2025-12-31"
  },
  
  "agent_config": {
    "max_steps": 50,           // Max tool calls per event
    "max_retries": 3,          // Retry on transient failures
    "base_delay": 0.5,         // Retry backoff base (seconds)
    "initial_cash": 10000.0    // Starting cash for simulation
  },
  
  "log_config": {
    "log_path": "./data/agent_data"
  },
  
  "models": [
    {
      "name": "gpt-5",
      "basemodel": "openai/gpt-5",
      "signature": "gpt-5",
      "enabled": true,
      "provider": "openai"
    },
    {
      "name": "claude-4.5-sonnet",
      "basemodel": "openrouter/anthropic/claude-sonnet-4.5",
      "signature": "claude-4.5-sonnet",
      "enabled": true,
      "provider": "openrouter"
    },
    {
      "name": "gemini-2.5-pro",
      "basemodel": "openrouter/google/gemini-2.5-pro",
      "signature": "gemini-2.5-pro",
      "enabled": true,
      "provider": "openrouter"
    },
    {
      "name": "deepseek-v3.1",
      "basemodel": "openrouter/deepseek/deepseek-chat-v3.1",
      "signature": "deepseek-v3.1",
      "enabled": true,
      "provider": "openrouter"
    }
  ]
}
```

### Runtime Environment

The system writes `.runtime_env.json` to coordinate state:

```json
{
  "SIGNATURE": "gpt-5",
  "CURRENT_DATETIME": "2025-01-20T15:30:00Z",
  "INIT_DATETIME": "2025-01-01T00:00:00Z",
  "IF_TRADE": false
}
```

### Watchlist Management

Edit `futureshow/utils/polymarket_watchlist.json` or use API:

```python
from futureshow.utils.polymarket_watchlist import (
    refresh_trending_watchlist,
    load_watchlist,
    add_events_to_watchlist,
    remove_events_from_watchlist,
)

# Refresh with trending events
refresh_trending_watchlist(year=2025, month=1)

# Manual additions
add_events_to_watchlist(["custom-event-slug"])
```

---

## 📁 Data Formats & Output

### Directory Structure

```
data/
├── agent_data/
│   └── {model_signature}/
│       ├── position/
│       │   ├── position.jsonl    # Trade ledger
│       │   └── liquidity.json    # Simulated liquidity state
│       ├── pnl/
│       │   └── intraday_{date}.jsonl  # NAV snapshots
│       └── log/
│           └── {date}/
│               └── log.jsonl     # Agent reasoning traces
│
├── forecasts/
│   └── {model_signature}/
│       └── {event_slug}/
│           ├── forecasts.jsonl   # Predictions over time
│           ├── tracking.jsonl    # Market state snapshots
│           └── result.json       # Final resolution
│
└── cache/
    └── polymarket_markets/       # API response cache
        └── {slug}.json
```

### Position Ledger Format (position.jsonl)

```json
{
  "timestamp": "2025-01-20T15:30:00Z",
  "id": 42,
  "this_action": {
    "action": "buy",
    "market": "btc-100k-jan",
    "outcome": "Yes",
    "requested_cost": 1000.0,
    "spent": 998.45,
    "shares": 1123.5,
    "avg_price": 0.889,
    "partial_fill": false,
    "levels": [
      {"price": 0.888, "shares": 500, "cost": 444.0},
      {"price": 0.890, "shares": 623.5, "cost": 554.45}
    ]
  },
  "positions": {
    "CASH": 4001.55,
    "btc-100k-jan:Yes": 1123.5,
    "trump-2028:No": 500.0
  }
}
```

### Forecast Record Format (forecasts.jsonl)

```json
{
  "timestamp": "2025-01-20T15:30:00Z",
  "signature": "gpt-5",
  "event_slug": "btc-100k-jan",
  "event_title": "Bitcoin above $100k by Jan 31?",
  "forecast": "Based on current momentum and institutional inflows...\n\n<PREDICTION>btc-100k-jan-yes|YES</PREDICTION>",
  "predictions": [
    {"slug": "btc-100k-jan-yes", "outcome": "YES"}
  ]
}
```

---

## 🛠️ Development

### Running Tests

```bash
# All tests
pytest -q

# Specific module
pytest tests/test_polymarket_data.py -v

# With coverage
pytest --cov=futureshow --cov-report=html
```

### Code Quality

```bash
# Lint
ruff check futureshow tests

# Format
ruff format futureshow tests

# Type check
mypy futureshow
```

### Project Structure

```
FutureShow/
├── futureshow/                    # 🎯 Core package
│   ├── agent/                     # Agent implementations
│   │   ├── __init__.py
│   │   └── polymarket/
│   │       ├── polymarket_agent.py         # Trading agent
│   │       ├── polymarket_forecast_agent.py # Forecast-only agent
│   │       └── market_preview.py           # Market analysis utils
│   ├── prompt/                    # System prompts
│   │   ├── polymarket_agent_prompt.py
│   │   └── polymarket_forecast_prompt.py
│   ├── tool/                      # MCP tools (FastMCP + function_tool)
│   │   ├── tool_polymarket_data.py   # Market data (1170 lines)
│   │   ├── tool_polymarket_trade.py  # Trading simulation (655 lines)
│   │   ├── tool_google.py            # Serper search
│   │   ├── tool_exa.py               # Semantic search
│   │   ├── tool_reddit.py            # Reddit API
│   │   ├── tool_twitter.py           # X/Twitter API
│   │   └── tool_math.py              # Math evaluation
│   └── utils/                     # Helpers
│       ├── agent_logs.py             # Logging hooks
│       ├── general_tools.py          # Config helpers
│       ├── polymarket_watchlist.py   # Watchlist management
│       └── polymarket_position_tools.py
│
├── frontend/                      # 🖥️ Web dashboard
│   ├── index.html
│   ├── app.js                     # Chart.js + fetch API
│   ├── styles.css
│   └── icons/                     # Model logos
│
├── configs/                       # ⚙️ Configuration
│   └── default_config.json
│
├── tests/                         # 🧪 pytest suite
│   ├── conftest.py
│   ├── test_polymarket_data.py
│   ├── test_polymarket_trade.py
│   └── ...
│
├── main.py                        # Entry point
├── web_server.py                  # Dashboard server (358 lines)
├── run_agents_once.py             # Single-pass runner
├── run_agents_loop.py             # Continuous runner
├── run_pnl_trackers.py            # PnL tracking loop
└── run_forecast_loop.py           # Forecast-only loop
```

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing-feature`
3. **Commit** changes: `git commit -m 'Add amazing feature'`
4. **Push** to branch: `git push origin feature/amazing-feature`
5. **Open** a Pull Request

### Guidelines

- Follow existing code style (ruff formatting)
- Add tests for new tools/agents
- Update documentation for API changes
- Include sample output for new features

---

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

**🌟 Found FutureShow useful? Star us on GitHub!**

**Built with curiosity by [HKUDS](https://github.com/HKUDS)**

</div>
