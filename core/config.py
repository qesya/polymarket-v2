"""
System configuration loaded from environment variables.
All thresholds and parameters are tunable without code changes.
"""
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Infrastructure ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    postgres_url: str = "postgresql://trader:pass@localhost:5432/polymarket"
    chroma_url: str = "http://localhost:8000"
    postgres_password: str = "changeme"

    # ── API Keys ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    polymarket_api_key: str = ""
    polymarket_private_key: str = ""
    twitter_bearer_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    newsapi_key: str = ""

    # ── Polymarket Endpoints ──────────────────────────────────────────────────
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"

    # ── Market Scanner Filters ────────────────────────────────────────────────
    min_volume_24h: float = 5_000.0
    max_bid_ask_spread: float = 0.05
    min_liquidity: float = 10_000.0
    min_time_to_resolution_hours: float = 4.0
    max_time_to_resolution_days: float = 90.0
    min_price: float = 0.05
    max_price: float = 0.95
    markets_per_cycle: int = 50

    # ── Prediction Model ──────────────────────────────────────────────────────
    min_edge_threshold: float = 0.04
    min_confidence_threshold: float = 0.60
    claude_disagreement_threshold: float = 0.08
    xgb_weight: float = 0.45
    lgbm_weight: float = 0.35
    claude_weight: float = 0.20
    probability_clip_low: float = 0.10
    probability_clip_high: float = 0.90

    # ── Risk Management ───────────────────────────────────────────────────────
    kelly_fraction: float = 0.25
    max_position_pct: float = 0.05
    max_drawdown_pct: float = 0.20
    daily_loss_limit_pct: float = 0.08
    max_correlation_existing: float = 0.70
    max_open_positions: int = 20

    # ── Execution ────────────────────────────────────────────────────────────
    max_slippage_pct: float = 0.02
    order_timeout_seconds: float = 60.0
    order_retry_attempts: int = 3
    order_retry_backoff_seconds: float = 2.0

    # ── Learning ─────────────────────────────────────────────────────────────
    training_window_days: int = 90
    min_trades_to_retrain: int = 50
    model_brier_degradation_threshold: float = 0.15

    # ── Cycle Timing ─────────────────────────────────────────────────────────
    scanner_interval_seconds: float = 60.0
    research_timeout_seconds: float = 30.0
    resolution_poll_interval_seconds: float = 300.0

    # ── Claude Model ─────────────────────────────────────────────────────────
    claude_model: str = "claude-sonnet-4-6"

    # ── RSS Feeds ─────────────────────────────────────────────────────────────
    rss_feeds: List[str] = [
        "https://feeds.reuters.com/reuters/topNews",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://www.politico.com/rss/politicopicks.xml",
    ]


# Singleton settings instance
settings = Settings()
