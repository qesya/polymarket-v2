# Polymarket AI Trading System

A production-grade multi-agent system for automated prediction market trading. Scans markets, detects pricing inefficiencies, estimates true probabilities with ML + LLMs, manages risk with Kelly Criterion, executes trades, and learns from mistakes.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         REDIS PUB/SUB BUS                               │
│  market.scan ─ research.jobs ─ predictions.ready ─ risk.signals         │
└──┬──────────────┬──────────────┬──────────────┬──────────────┬──────────┘
   │              │              │              │              │
   ▼              ▼              ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
│ Market   │  │ Research │  │Prediction│  │  Risk    │  │  Execution   │
│ Scanner  │─►│  Agent   │─►│  Agent   │─►│  Agent   │─►│    Agent     │
│          │  │          │  │          │  │          │  │              │
│Polymarket│  │Twitter   │  │XGBoost + │  │Kelly     │  │Place orders  │
│CLOB API  │  │Reddit    │  │LightGBM  │  │Criterion │  │Monitor fills │
│          │  │News/RSS  │  │+ Claude  │  │Drawdown  │  │Track PnL     │
└──────────┘  └──────────┘  └──────────┘  │Guard     │  └──────────────┘
                                           └──────────┘
                                                │
                                         ┌──────▼──────┐
                                         │  Learning   │
                                         │   Agent     │
                                         │             │
                                         │Postmortem   │
                                         │Retrain      │
                                         │ChromaDB     │
                                         └─────────────┘

Storage:  PostgreSQL (trades/predictions) │ Redis (state/cache) │ ChromaDB (embeddings)
Monitor:  Prometheus metrics ─────────────────────────► Grafana dashboards
```

### Agent Responsibilities

| Agent | Trigger | Input | Output |
|-------|---------|-------|--------|
| **MarketScannerAgent** | Every 60s | Polymarket API | `MarketCandidate` × N |
| **ResearchAgent** | Per market | `MarketCandidate` | `ResearchSummary` |
| **PredictionAgent** | Per market | `MarketCandidate` + `ResearchSummary` | `PredictionResult` |
| **RiskAgent** | Per prediction | `PredictionResult` | `OrderIntent` or rejection |
| **ExecutionAgent** | Per approval | `OrderIntent` | `FillReport` + DB record |
| **LearningAgent** | Every 5min + nightly | Resolved trades | Postmortem + retrained models |

---

## Project Structure

```
polymarket-v2/
├── main.py                    # Entry point — wires all agents
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
│
├── agents/                    # Agent implementations
│   ├── base_agent.py          # ABC: run loop, pub/sub, metrics
│   ├── market_scanner.py      # Scan + filter Polymarket markets
│   ├── research_agent.py      # Twitter/Reddit/News aggregation
│   ├── prediction_agent.py    # ML ensemble + Claude probability
│   ├── risk_agent.py          # Kelly Criterion, drawdown guard
│   ├── execution_agent.py     # Order placement, fill monitoring
│   └── learning_agent.py      # Postmortem analysis, retraining
│
├── core/                      # Shared infrastructure
│   ├── config.py              # All settings (pydantic-settings)
│   ├── models.py              # Pydantic data models (inter-agent contracts)
│   ├── bus.py                 # Redis pub/sub message bus
│   ├── circuit_breaker.py     # System-level circuit breaker
│   ├── metrics.py             # Prometheus metrics registry
│   └── storage.py             # PostgreSQL + Redis + ChromaDB helpers
│
├── model/                     # ML prediction layer
│   ├── features.py            # 65-dimensional feature builder
│   ├── ensemble.py            # XGBoost + LightGBM ensemble
│   └── trainer.py             # Nightly retraining pipeline
│
├── data/                      # External data clients
│   ├── polymarket_client.py   # Polymarket REST + CLOB API
│   ├── twitter_client.py      # Twitter API v2
│   ├── reddit_client.py       # Reddit PRAW
│   └── news_client.py         # NewsAPI + RSS aggregator
│
├── sentiment/
│   └── analyzer.py            # VADER + Claude sentiment
│
├── tests/                     # pytest unit tests
│   ├── test_market_scanner.py
│   ├── test_risk_agent.py
│   ├── test_features.py
│   └── test_sentiment.py
│
├── migrations/
│   └── 001_initial.sql        # PostgreSQL schema
│
├── monitoring/
│   └── prometheus.yml         # Prometheus scrape config
│
└── utils/
    └── logging_config.py      # JSON structured logging
```

---

## Prediction Model

### Feature Vector (65 dimensions)

| Group | Count | Examples |
|-------|-------|---------|
| Market microstructure | 15 | price, volume, spread, volatility, liquidity |
| Sentiment/research | 15 | sentiment_positive, momentum, expert_signals |
| Interaction features | 10 | sentiment × momentum, volume × sentiment |
| Category one-hot | 7 | politics, sports, crypto, finance, ... |
| Temporal cyclical | 8 | hour_sin/cos, urgency, price_extremity |
| Portfolio context | 10 | drawdown, win_rate, exposure_pct |

### Ensemble

```
XGBoost (45%) ─┐
LightGBM (35%) ─┼─► Weighted ensemble ─► Edge = P_model - P_market
Claude  (20%) ─┘     (weights updated nightly by LearningAgent)
```

Claude is only invoked when XGBoost and LightGBM **disagree by > 8%** — keeping LLM API costs at ~$2-5/day.

### Trade Signal

```python
edge = predicted_probability - market_price
adjusted_edge = edge - (bid_ask_spread / 2)   # cost-adjusted
should_trade = (
    abs(adjusted_edge) >= 0.04    # minimum 4-cent edge
    and confidence >= 0.60         # model agreement
    and data_quality != "LOW"      # sufficient research data
)
```

---

## Risk Management

### Kelly Criterion

For a binary market at price `p`:
```
b       = (1 - p) / p          # net odds
f*      = (p_win × (b+1) - 1) / b
f_applied = f* × 0.25          # fractional Kelly (25%)
```

### Hard Limits

| Rule | Value | Rationale |
|------|-------|-----------|
| Max position size | 5% of portfolio | Even full Kelly is capped |
| Max drawdown | 20% | Halts all new trades |
| Daily loss limit | 8% | Resets at midnight UTC |
| Max open positions | 20 | Concentration risk |
| Max slippage | 2% | Reject orders that move price |
| Min edge | 4¢ | Must beat transaction costs |

### Circuit Breakers

```
api       → trips after 3 consecutive Polymarket API failures
trading   → trips on drawdown or daily loss limit breach
model     → trips when Brier score degrades > 15%
execution → trips after 3 consecutive order failures
```

---

## Setup

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- Polymarket account (for live trading)
- API keys (see `.env.example`)

### Local Development

```bash
# 1. Clone and set up environment
git clone <repo>
cd polymarket-v2
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — add your API keys

# 3. Start infrastructure (Redis + Postgres + ChromaDB)
docker compose up redis postgres chromadb -d

# 4. Initialize database
psql -U trader -h localhost -d polymarket -f migrations/001_initial.sql

# 5. Run in dry-run mode (no real trades)
python main.py --dry-run

# 6. Run tests
pytest tests/ -v
```

### Docker Deployment (recommended)

```bash
# Start all services
docker compose up -d

# Watch agent logs
docker compose logs -f agents

# Dry-run mode (scanner + prediction, no execution)
docker compose --profile dryrun up agents_dryrun -d

# Trigger manual model retrain
docker compose run --rm agents python main.py --retrain

# Monitor in Grafana
open http://localhost:3000   # admin / (GRAFANA_PASSWORD from .env)

# Prometheus metrics
open http://localhost:9090
```

### Scheduled Jobs

```bash
# Add to crontab for nightly retraining at 02:00 UTC
0 2 * * * cd /path/to/polymarket-v2 && docker compose run --rm agents python main.py --retrain >> /var/log/retrain.log 2>&1
```

---

## API Keys Reference

| Service | Purpose | Free Tier | Link |
|---------|---------|-----------|------|
| Anthropic | Claude LLM analysis | Pay-per-use | [console.anthropic.com](https://console.anthropic.com) |
| Polymarket | Market data + trading | Free read / paid trade | [polymarket.com](https://polymarket.com) |
| Twitter API | Social signals | 500k tokens/mo | [developer.twitter.com](https://developer.twitter.com) |
| Reddit (PRAW) | Forum sentiment | Free | [reddit.com/prefs/apps](https://reddit.com/prefs/apps) |
| NewsAPI | News articles | 100 req/day free | [newsapi.org](https://newsapi.org) |

**Minimum viable setup**: Only `ANTHROPIC_API_KEY` is required. The system degrades gracefully — Twitter/Reddit/News sources fall back to empty when keys are missing. Trading requires `POLYMARKET_API_KEY`.

---

## Monitoring

### Grafana Dashboards (localhost:3000)

| Dashboard | Key Metrics |
|-----------|------------|
| **Trading** | Portfolio value, daily PnL, win rate, drawdown |
| **Models** | Brier score (7d rolling), calibration error, prediction count |
| **Agents** | Cycle duration, error rate, queue depth |
| **Infrastructure** | Redis lag, API latency, circuit breaker states |

### Key Prometheus Metrics

```
portfolio_value_usd              # Current total value
drawdown_pct                     # Current drawdown from peak
trades_total{side, category}     # Trade count
trade_pnl_dollars (histogram)    # P&L distribution
model_brier_score{model}         # 7-day rolling Brier score
agent_cycle_seconds{agent}       # Per-agent latency
claude_tokens_total{direction}   # LLM token usage
circuit_breaker_state{breaker}   # 0=closed, 1=open
```

---

## Performance Expectations

| Metric | Target | Notes |
|--------|--------|-------|
| Markets scanned per cycle | 200-500 | Depends on Polymarket API |
| Markets selected per cycle | 10-50 | After filtering |
| Prediction latency | < 500ms | ML-only, no Claude |
| Prediction latency (Claude) | 2-5s | Only for ambiguous cases |
| Model Brier score | < 0.22 | Lower = better calibration |
| Minimum edge to trade | 4¢ | After transaction costs |
| Max daily trades | ~20 | Kelly sizing naturally limits |

---

## Important Disclaimers

- **This is experimental software.** Prediction markets carry real financial risk.
- **Always run `--dry-run` first.** Verify all signals look reasonable before enabling execution.
- **Start with a small bankroll.** Even well-calibrated models lose money on individual trades.
- **Monitor drawdown continuously.** The 20% circuit breaker is a hard stop, not a suggestion.
- **Brier score degrades over time.** Market dynamics change — retrain frequently.
- **No guarantees of profitability.** Past model performance does not predict future results.

---

## License

MIT License — see LICENSE file.
