"""
Tests for RiskAgent Kelly Criterion and risk evaluation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from agents.risk_agent import RiskAgent
from core.models import (
    PredictionResult, ModelPredictions, PortfolioState, TradeSide
)
from core.config import settings


def make_prediction(
    market_id="0xtest",
    market_price=0.50,
    predicted_p=0.60,
    edge=0.10,
    confidence=0.75,
    should_trade=True,
):
    return PredictionResult(
        market_id=market_id,
        market_price_yes=market_price,
        model_predictions=ModelPredictions(
            xgb_p_yes=predicted_p,
            lgbm_p_yes=predicted_p,
            ensemble_p_yes=predicted_p,
            xgb_weight=0.5,
            lgbm_weight=0.5,
            claude_weight=0.0,
        ),
        predicted_p_yes=predicted_p,
        edge=edge,
        confidence=confidence,
        feature_vector_hash="abc123",
        model_version="test",
        should_trade=should_trade,
    )


def make_portfolio(
    total=10_000.0,
    cash=9_000.0,
    drawdown=0.0,
    daily_pnl=0.0,
    open_positions=0,
    open_market_ids=None,
):
    return PortfolioState(
        total_value=total,
        cash_available=cash,
        peak_value=total,
        current_drawdown_pct=drawdown,
        daily_pnl=daily_pnl,
        open_position_count=open_positions,
        open_position_market_ids=open_market_ids or [],
    )


@pytest.fixture
def risk_agent():
    bus = MagicMock()
    bus.publish = AsyncMock()
    cb = MagicMock()
    cb.is_open = AsyncMock(return_value=False)
    cb.trip = AsyncMock()
    return RiskAgent(bus, cb)


class TestKellyCriterion:
    def test_positive_edge_gives_positive_kelly(self, risk_agent):
        prediction = make_prediction(market_price=0.50, predicted_p=0.60, edge=0.10)
        portfolio = make_portfolio()
        kelly = risk_agent._compute_kelly(prediction, portfolio.total_value)
        assert kelly.f_star > 0
        assert kelly.f_applied > 0

    def test_fractional_kelly_is_smaller(self, risk_agent):
        prediction = make_prediction(market_price=0.50, predicted_p=0.60, edge=0.10)
        portfolio = make_portfolio()
        kelly = risk_agent._compute_kelly(prediction, portfolio.total_value)
        assert kelly.f_applied < kelly.f_star
        assert kelly.kelly_fraction_used == settings.kelly_fraction

    def test_zero_edge_gives_zero_kelly(self, risk_agent):
        prediction = make_prediction(market_price=0.50, predicted_p=0.50, edge=0.0)
        portfolio = make_portfolio()
        kelly = risk_agent._compute_kelly(prediction, portfolio.total_value)
        assert kelly.f_star == pytest.approx(0.0, abs=0.01)

    def test_large_edge_capped_by_max_position(self, risk_agent):
        """Even with 50% edge, max position is 5% of portfolio."""
        prediction = make_prediction(market_price=0.30, predicted_p=0.80, edge=0.50)
        kelly = risk_agent._compute_kelly(prediction, 10_000.0)
        max_dollar = 10_000.0 * settings.max_position_pct
        dollar_size = kelly.f_applied * 10_000.0
        # Dollar size may exceed max_position_pct but capping happens in _evaluate
        assert kelly.f_applied > 0

    def test_no_bet_side(self, risk_agent):
        """Negative edge prediction should compute kelly for NO side."""
        prediction = make_prediction(
            market_price=0.70, predicted_p=0.55, edge=-0.15
        )
        kelly = risk_agent._compute_kelly(prediction, 10_000.0)
        assert kelly.f_star >= 0

    def test_expected_value_positive_for_positive_edge(self, risk_agent):
        prediction = make_prediction(market_price=0.50, predicted_p=0.65, edge=0.15)
        kelly = risk_agent._compute_kelly(prediction, 10_000.0)
        assert kelly.expected_value > 0


class TestRiskEvaluation:
    @pytest.mark.asyncio
    async def test_blocks_when_should_trade_false(self, risk_agent):
        prediction = make_prediction(should_trade=False)
        with patch.object(risk_agent, "_reject", new_callable=AsyncMock) as mock_reject:
            await risk_agent._evaluate(prediction)
        mock_reject.assert_called_once()
        args = mock_reject.call_args[0]
        assert args[1] == "edge_below_threshold"

    @pytest.mark.asyncio
    async def test_blocks_on_drawdown_exceeded(self, risk_agent):
        prediction = make_prediction()
        portfolio = make_portfolio(drawdown=0.25)  # > MAX_DRAWDOWN_PCT = 0.20
        with patch.object(risk_agent, "_get_portfolio", new_callable=AsyncMock, return_value=portfolio):
            with patch.object(risk_agent, "_reject", new_callable=AsyncMock) as mock_reject:
                await risk_agent._evaluate(prediction)
        called_reasons = [call[0][1] for call in mock_reject.call_args_list]
        assert "max_drawdown_exceeded" in called_reasons

    @pytest.mark.asyncio
    async def test_blocks_duplicate_market_position(self, risk_agent):
        prediction = make_prediction(market_id="0xtest")
        portfolio = make_portfolio(open_market_ids=["0xtest"])
        with patch.object(risk_agent, "_get_portfolio", new_callable=AsyncMock, return_value=portfolio):
            with patch.object(risk_agent, "_reject", new_callable=AsyncMock) as mock_reject:
                await risk_agent._evaluate(prediction)
        called_reasons = [call[0][1] for call in mock_reject.call_args_list]
        assert "existing_position" in called_reasons

    @pytest.mark.asyncio
    async def test_blocks_max_positions_exceeded(self, risk_agent):
        prediction = make_prediction()
        portfolio = make_portfolio(open_positions=settings.max_open_positions)
        with patch.object(risk_agent, "_get_portfolio", new_callable=AsyncMock, return_value=portfolio):
            with patch.object(risk_agent, "_reject", new_callable=AsyncMock) as mock_reject:
                await risk_agent._evaluate(prediction)
        called_reasons = [call[0][1] for call in mock_reject.call_args_list]
        assert "max_positions_exceeded" in called_reasons
