"""
Pydantic v2 domain models for inter-agent communication via Redis bus.
These are the canonical data contracts between all agents.
"""
from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum


class MarketCategory(str, Enum):
    POLITICS = "politics"
    SPORTS = "sports"
    CRYPTO = "crypto"
    FINANCE = "finance"
    SCIENCE = "science"
    ENTERTAINMENT = "entertainment"
    OTHER = "other"


class TradeSide(str, Enum):
    YES = "YES"
    NO = "NO"


class TradeStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class MistakeCategory(str, Enum):
    MODEL_ERROR = "model_error"
    DATA_QUALITY = "data_quality"
    EXECUTION = "execution"
    BAD_LUCK = "bad_luck"
    DISTRIBUTION_SHIFT = "distribution_shift"


# ── MarketScannerAgent output ─────────────────────────────────────────────────

class OrderbookLevel(BaseModel):
    price: float
    size: float


class MarketCandidate(BaseModel):
    """A market that passed scanner filters and is ready for research + prediction."""
    market_id: str
    question: str
    category: MarketCategory = MarketCategory.OTHER
    price_yes: float                          # current YES probability (0-1)
    price_no: float
    volume_24h: float
    volume_7d: float
    liquidity: float
    bid_ask_spread: float
    time_to_resolution_hours: float
    market_age_days: float
    volatility_7d: float                      # rolling std of hourly prices
    orderbook_imbalance: float                # (bid_depth - ask_depth) / total
    whale_trade_count_24h: int
    unique_traders_7d: int
    opportunity_score: float                  # composite ranking score
    bids: List[OrderbookLevel] = []
    asks: List[OrderbookLevel] = []
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_prices(self) -> "MarketCandidate":
        assert 0.0 < self.price_yes < 1.0, f"Invalid price_yes: {self.price_yes}"
        return self


# ── ResearchAgent output ──────────────────────────────────────────────────────

class SourceBreakdown(BaseModel):
    twitter_count: int = 0
    reddit_count: int = 0
    news_count: int = 0
    rss_count: int = 0


class ResearchSummary(BaseModel):
    """Aggregated research signal for a market candidate."""
    market_id: str
    sentiment_positive: float = 0.0          # 0-1 positive sentiment score
    sentiment_negative: float = 0.0
    sentiment_uncertainty: float = 0.0
    social_momentum: float = 0.0             # tweet velocity ratio
    narrative_intensity: float = 0.0         # normalized volume of coverage
    expert_signal_count: int = 0
    news_publication_tier_score: float = 0.0  # weighted outlet credibility 0-1
    information_arrival_rate: float = 0.0    # new sources per hour
    narrative_similarity_score: float = 0.0  # similarity to known resolved narratives
    source_breakdown: SourceBreakdown = Field(default_factory=SourceBreakdown)
    top_headlines: List[str] = []            # for Claude context
    data_quality: str = "HIGH"               # HIGH|MEDIUM|LOW
    researched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── PredictionAgent output ────────────────────────────────────────────────────

class ModelPredictions(BaseModel):
    xgb_p_yes: float
    lgbm_p_yes: float
    claude_p_yes: Optional[float] = None     # None if not invoked
    ensemble_p_yes: float
    xgb_weight: float
    lgbm_weight: float
    claude_weight: float


class PredictionResult(BaseModel):
    """Full prediction output including edge and confidence."""
    market_id: str
    market_price_yes: float
    model_predictions: ModelPredictions
    predicted_p_yes: float                   # final calibrated probability
    edge: float                              # predicted_p_yes - market_price_yes
    confidence: float                        # model agreement / uncertainty measure
    feature_vector_hash: str                 # SHA-256 of feature vector for reproducibility
    model_version: str
    should_trade: bool                       # edge > threshold AND confidence > threshold
    predicted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def trade_side(self) -> TradeSide:
        return TradeSide.YES if self.edge > 0 else TradeSide.NO


# ── RiskAgent output ──────────────────────────────────────────────────────────

class KellyCalculation(BaseModel):
    f_star: float                            # full Kelly fraction
    f_applied: float                         # fractional Kelly applied
    kelly_fraction_used: float               # multiplier (e.g. 0.25)
    expected_value: float


class OrderIntent(BaseModel):
    """A trade that has passed risk checks and is approved for execution."""
    market_id: str
    prediction_id: Optional[int] = None     # FK to predictions table
    side: TradeSide
    shares: float
    dollar_size: float
    limit_price: float                       # price to place limit order at
    max_slippage_pct: float
    kelly_calculation: KellyCalculation
    portfolio_value_at_decision: float
    idempotency_key: str                     # SHA-256 of (market_id, side, size, minute)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskRejection(BaseModel):
    """Trade blocked by RiskAgent - for logging and learning."""
    market_id: str
    prediction_result: PredictionResult
    rejection_reason: str
    circuit_open: bool = False
    rejected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── ExecutionAgent output ─────────────────────────────────────────────────────

class FillReport(BaseModel):
    """Result of order execution."""
    market_id: str
    order_intent: OrderIntent
    order_id: str
    status: TradeStatus
    filled_shares: float
    fill_price: float
    slippage_bps: float
    dollar_spent: float
    filled_at: Optional[datetime] = None


# ── LearningAgent output ──────────────────────────────────────────────────────

class PostmortemResult(BaseModel):
    """Analysis of a resolved trade."""
    trade_id: int
    market_id: str
    predicted_p_yes: float
    actual_outcome: bool
    pnl: float
    mistake_category: MistakeCategory
    claude_analysis: str
    key_learnings: List[str] = []
    chroma_doc_id: Optional[str] = None
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RetrainingResult(BaseModel):
    model_version: str
    xgb_brier_score: float
    lgbm_brier_score: float
    training_samples: int
    deployed: bool
    notes: str = ""
    retrained_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── System-level ──────────────────────────────────────────────────────────────

class CircuitBreakerState(BaseModel):
    name: str
    is_open: bool
    reason: str = ""
    opened_at: Optional[datetime] = None
    consecutive_failures: int = 0


class PortfolioState(BaseModel):
    """Current portfolio snapshot, stored in Redis and refreshed by ExecutionAgent."""
    total_value: float
    cash_available: float
    peak_value: float
    current_drawdown_pct: float
    daily_pnl: float
    open_position_count: int
    open_position_market_ids: List[str] = []
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
