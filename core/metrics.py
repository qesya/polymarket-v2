"""
Prometheus metrics registry. All agents import from here.
Metrics are registered once at module load; duplicate registration is a bug.
"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, start_http_server

# Use default registry (prometheus_client global)
# Start metrics server on port 8001 by calling start_metrics_server() at startup

# ── Trading Performance ───────────────────────────────────────────────────────

TRADES_TOTAL = Counter(
    "trades_total",
    "Total trades placed",
    ["market_category", "side"],
)

TRADE_PNL = Histogram(
    "trade_pnl_dollars",
    "P&L per settled trade in USD",
    buckets=[-500, -200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200, 500],
)

EDGE_PREDICTED = Histogram(
    "edge_predicted",
    "Predicted edge before trade",
    buckets=[-0.20, -0.10, -0.05, -0.02, 0, 0.02, 0.05, 0.10, 0.15, 0.20],
)

EDGE_REALIZED = Histogram(
    "edge_realized",
    "Actual realized edge after settlement",
    buckets=[-0.20, -0.10, -0.05, -0.02, 0, 0.02, 0.05, 0.10, 0.15, 0.20],
)

PORTFOLIO_VALUE = Gauge("portfolio_value_usd", "Current total portfolio value in USD")

DRAWDOWN_PCT = Gauge("drawdown_pct", "Current drawdown from peak as fraction")

CASH_AVAILABLE = Gauge("cash_available_usd", "Available uninvested cash in USD")

OPEN_POSITIONS = Gauge("open_positions_count", "Number of open positions")

# ── Agent Performance ─────────────────────────────────────────────────────────

AGENT_CYCLE_DURATION = Histogram(
    "agent_cycle_seconds",
    "Wall-clock time for one agent cycle",
    ["agent_name"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120],
)

AGENT_ERRORS = Counter(
    "agent_errors_total",
    "Unhandled errors per agent",
    ["agent_name", "error_type"],
)

MARKETS_SCANNED = Counter("markets_scanned_total", "Markets fetched from Polymarket API per cycle")

MARKETS_SELECTED = Counter("markets_selected_total", "Markets passing scanner filters per cycle")

TRADES_REJECTED_RISK = Counter(
    "trades_rejected_risk_total",
    "Trades blocked by RiskAgent",
    ["reason"],
)

# ── Model Performance ─────────────────────────────────────────────────────────

MODEL_BRIER_SCORE = Gauge(
    "model_brier_score",
    "Rolling 7-day Brier score (lower is better)",
    ["model_name"],
)

MODEL_CALIBRATION_ERROR = Gauge(
    "model_calibration_error",
    "Expected calibration error (lower is better)",
    ["model_name"],
)

PREDICTIONS_TOTAL = Counter(
    "predictions_total",
    "Predictions generated",
    ["model_name", "traded"],
)

# ── Claude API ────────────────────────────────────────────────────────────────

CLAUDE_API_CALLS = Counter(
    "claude_api_calls_total",
    "Claude API invocations",
    ["agent_name", "model"],
)

CLAUDE_TOKENS = Counter(
    "claude_tokens_total",
    "Claude API tokens consumed",
    ["agent_name", "direction"],  # direction: input|output
)

# ── Infrastructure ─────────────────────────────────────────────────────────────

API_REQUEST_DURATION = Histogram(
    "api_request_seconds",
    "External API latency",
    ["api_name", "endpoint", "status"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
)

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state: 0=closed (healthy), 1=open (blocking)",
    ["breaker_name"],
)

SLIPPAGE_BPS = Histogram(
    "slippage_bps",
    "Order fill slippage in basis points",
    buckets=[0, 5, 10, 25, 50, 100, 200, 500],
)


def start_metrics_server(port: int = 8001) -> None:
    """Start Prometheus HTTP metrics endpoint. Call once at process startup."""
    start_http_server(port)
