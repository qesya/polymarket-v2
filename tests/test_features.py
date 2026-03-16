"""
Tests for FeatureBuilder — verifies output shape, dtype, and determinism.
"""
import pytest
import numpy as np

from model.features import FeatureBuilder, N_FEATURES, FEATURE_NAMES
from core.models import (
    MarketCandidate, ResearchSummary, MarketCategory, SourceBreakdown
)


def make_market(**overrides):
    base = dict(
        market_id="0xtest",
        question="Will X happen?",
        category=MarketCategory.POLITICS,
        price_yes=0.55,
        price_no=0.45,
        volume_24h=50_000.0,
        volume_7d=300_000.0,
        liquidity=100_000.0,
        bid_ask_spread=0.03,
        time_to_resolution_hours=72.0,
        market_age_days=14.0,
        volatility_7d=0.08,
        orderbook_imbalance=0.10,
        whale_trade_count_24h=5,
        unique_traders_7d=200,
        opportunity_score=0.72,
    )
    base.update(overrides)
    return MarketCandidate(**base)


def make_research(**overrides):
    base = dict(
        market_id="0xtest",
        sentiment_positive=0.45,
        sentiment_negative=0.20,
        sentiment_uncertainty=0.35,
        social_momentum=1.5,
        narrative_intensity=0.6,
        expert_signal_count=3,
        news_publication_tier_score=0.8,
        information_arrival_rate=10.0,
        source_breakdown=SourceBreakdown(
            twitter_count=50, reddit_count=20, news_count=10, rss_count=5
        ),
        top_headlines=["Headline 1", "Headline 2"],
        data_quality="HIGH",
    )
    base.update(overrides)
    return ResearchSummary(**base)


class TestFeatureBuilder:
    def test_output_shape(self):
        fb = FeatureBuilder()
        features, _ = fb.build(make_market(), make_research())
        assert features.shape == (N_FEATURES,)

    def test_output_dtype(self):
        fb = FeatureBuilder()
        features, _ = fb.build(make_market(), make_research())
        assert features.dtype == np.float32

    def test_deterministic(self):
        fb = FeatureBuilder()
        market, research = make_market(), make_research()
        f1, h1 = fb.build(market, research)
        f2, h2 = fb.build(market, research)
        np.testing.assert_array_equal(f1, f2)
        assert h1 == h2

    def test_no_nan_or_inf(self):
        fb = FeatureBuilder()
        features, _ = fb.build(make_market(), make_research())
        assert not np.any(np.isnan(features))
        assert not np.any(np.isinf(features))

    def test_feature_names_count(self):
        assert len(FEATURE_NAMES) == N_FEATURES

    def test_price_yes_feature(self):
        fb = FeatureBuilder()
        features, _ = fb.build(make_market(price_yes=0.70), make_research())
        price_idx = FEATURE_NAMES.index("price_yes")
        assert features[price_idx] == pytest.approx(0.70, abs=1e-5)

    def test_category_one_hot_politics(self):
        fb = FeatureBuilder()
        features, _ = fb.build(make_market(category=MarketCategory.POLITICS), make_research())
        cat_idx = FEATURE_NAMES.index("cat_politics")
        assert features[cat_idx] == pytest.approx(1.0)
        other_cat_idx = FEATURE_NAMES.index("cat_sports")
        assert features[other_cat_idx] == pytest.approx(0.0)

    def test_category_one_hot_crypto(self):
        fb = FeatureBuilder()
        features, _ = fb.build(make_market(category=MarketCategory.CRYPTO), make_research())
        assert features[FEATURE_NAMES.index("cat_crypto")] == pytest.approx(1.0)
        assert features[FEATURE_NAMES.index("cat_politics")] == pytest.approx(0.0)

    def test_handles_zero_values(self):
        fb = FeatureBuilder()
        market = make_market(volume_24h=0, volume_7d=0, liquidity=0)
        features, _ = fb.build(market, make_research())
        assert not np.any(np.isnan(features))

    def test_portfolio_context_applied(self):
        fb = FeatureBuilder()
        ctx = {"portfolio_exposure_pct": 0.30, "portfolio_drawdown_pct": 0.05}
        features, _ = fb.build(make_market(), make_research(), portfolio_context=ctx)
        exp_idx = FEATURE_NAMES.index("portfolio_exposure_pct")
        assert features[exp_idx] == pytest.approx(0.30, abs=1e-4)

    def test_hash_changes_with_different_inputs(self):
        fb = FeatureBuilder()
        _, h1 = fb.build(make_market(price_yes=0.50), make_research())
        _, h2 = fb.build(make_market(price_yes=0.80), make_research())
        assert h1 != h2
