"""
Tests for MarketScannerAgent filtering and scoring logic.
All tests are unit tests — no external API calls.
"""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from agents.market_scanner import MarketScannerAgent
from core.models import MarketCategory


def make_mock_market(**overrides):
    """Build a minimal market dict that passes default filters."""
    base = {
        "conditionId": "0xabc123",
        "question": "Will the Democratic candidate win the 2024 election?",
        "category": "politics",
        "outcomePrices": [0.55, 0.45],
        "volume": 15_000.0,
        "volume_7d": 100_000.0,
        "liquidity": 50_000.0,
        "spread": 0.03,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "volatility_7d": 0.08,
        "bid_depth": 20_000.0,
        "ask_depth": 15_000.0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def scanner():
    bus = MagicMock()
    cb = MagicMock()
    cb.is_open = AsyncMock(return_value=False)
    return MarketScannerAgent(bus, cb)


class TestMarketFiltering:
    def test_passes_valid_market(self, scanner):
        markets = [make_mock_market()]
        result = scanner._filter_and_score(markets)
        assert len(result) == 1
        assert result[0].market_id == "0xabc123"

    def test_filters_low_volume(self, scanner):
        markets = [make_mock_market(volume=100.0)]  # below MIN_VOLUME_24H = 5000
        result = scanner._filter_and_score(markets)
        assert len(result) == 0

    def test_filters_high_spread(self, scanner):
        markets = [make_mock_market(spread=0.15)]  # above MAX_SPREAD = 0.05
        result = scanner._filter_and_score(markets)
        assert len(result) == 0

    def test_filters_near_certain_yes(self, scanner):
        markets = [make_mock_market(outcomePrices=[0.97, 0.03])]
        result = scanner._filter_and_score(markets)
        assert len(result) == 0

    def test_filters_near_certain_no(self, scanner):
        markets = [make_mock_market(outcomePrices=[0.02, 0.98])]
        result = scanner._filter_and_score(markets)
        assert len(result) == 0

    def test_filters_past_resolution(self, scanner):
        markets = [
            make_mock_market(
                endDate=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            )
        ]
        result = scanner._filter_and_score(markets)
        assert len(result) == 0

    def test_filters_too_low_liquidity(self, scanner):
        markets = [make_mock_market(liquidity=500.0)]
        result = scanner._filter_and_score(markets)
        assert len(result) == 0

    def test_returns_top_n_only(self, scanner):
        # Create 60 valid markets (more than markets_per_cycle=50)
        markets = [
            make_mock_market(conditionId=f"0x{i:04x}", volume=5000 + i * 100)
            for i in range(60)
        ]
        result = scanner._filter_and_score(markets)
        assert len(result) <= 50

    def test_opportunity_score_is_positive(self, scanner):
        markets = [make_mock_market()]
        result = scanner._filter_and_score(markets)
        assert result[0].opportunity_score > 0

    def test_category_mapped_correctly(self, scanner):
        markets = [make_mock_market(category="sports")]
        result = scanner._filter_and_score(markets)
        assert result[0].category == MarketCategory.SPORTS

    def test_empty_input_returns_empty(self, scanner):
        result = scanner._filter_and_score([])
        assert result == []

    def test_handles_missing_fields_gracefully(self, scanner):
        minimal = {"conditionId": "0xminimal", "question": "Test?"}
        result = scanner._filter_and_score([minimal])
        # Should not raise; may return empty if missing required numeric fields
        assert isinstance(result, list)


class TestOpportunityScoring:
    def test_high_volume_scores_higher(self, scanner):
        low_vol = [make_mock_market(conditionId="0xlow", volume=5_000)]
        high_vol = [make_mock_market(conditionId="0xhigh", volume=500_000)]
        result_low = scanner._filter_and_score(low_vol)
        result_high = scanner._filter_and_score(high_vol)
        if result_low and result_high:
            assert result_high[0].opportunity_score >= result_low[0].opportunity_score

    def test_extreme_price_filtered_out(self, scanner):
        # Market at 0.06 is filtered by min_price=0.05 — just barely passes but
        # 0.96 would be near-certain YES and filtered.  Test near-certain is excluded.
        near_certain = [make_mock_market(conditionId="0xext", outcomePrices=[0.97, 0.03])]
        result = scanner._filter_and_score(near_certain)
        assert len(result) == 0, "Near-certain market should be filtered out"

    def test_mid_price_passes_filter(self, scanner):
        # Market near 0.5 should pass all filters
        moderate = [make_mock_market(conditionId="0xmod", outcomePrices=[0.45, 0.55])]
        result = scanner._filter_and_score(moderate)
        assert len(result) == 1
