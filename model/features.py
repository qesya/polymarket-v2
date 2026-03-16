"""
FeatureBuilder

Constructs the 65-dimensional feature vector used by XGBoost and LightGBM.
All features are deterministic given (MarketCandidate, ResearchSummary).
Feature names are stable — do NOT reorder; append new features at the end.
"""
from __future__ import annotations

import hashlib
import math
from typing import List, Tuple

import numpy as np

from core.models import MarketCandidate, ResearchSummary

# Total feature count — update when adding features
N_FEATURES = 65

FEATURE_NAMES: List[str] = [
    # ── Market Microstructure (15) ─────────────────────────────────────────
    "price_yes",
    "price_no",
    "bid_ask_spread",
    "orderbook_imbalance",
    "volume_24h_log",
    "volume_7d_log",
    "volume_ratio_7d_24h",
    "liquidity_log",
    "ttr_hours_log",
    "market_age_days_log",
    "volatility_7d",
    "whale_trade_count_24h",
    "unique_traders_7d_log",
    "price_distance_from_half",
    "market_depth_ratio",          # liquidity / volume_24h
    # ── Sentiment / Research (15) ──────────────────────────────────────────
    "sentiment_positive",
    "sentiment_negative",
    "sentiment_uncertainty",
    "sentiment_net",               # positive - negative
    "sentiment_abs",               # abs(positive - negative)
    "social_momentum",
    "narrative_intensity",
    "expert_signal_count_log",
    "news_publication_tier_score",
    "information_arrival_rate_log",
    "source_count_twitter_log",
    "source_count_reddit_log",
    "source_count_news_log",
    "source_count_total_log",
    "data_quality_score",          # HIGH=1.0, MEDIUM=0.5, LOW=0.0
    # ── Interaction Features (10) ─────────────────────────────────────────
    "sentiment_net_x_momentum",
    "sentiment_neg_x_uncertainty",
    "volume_x_sentiment_abs",
    "narrative_x_expert",
    "spread_x_uncertainty",
    "price_x_sentiment_net",
    "ttr_x_narrative",
    "liquidity_x_spread",
    "momentum_x_tier",
    "volatility_x_sentiment_abs",
    # ── Category One-Hot (7) ──────────────────────────────────────────────
    "cat_politics",
    "cat_sports",
    "cat_crypto",
    "cat_finance",
    "cat_science",
    "cat_entertainment",
    "cat_other",
    # ── Temporal Cyclical (8) ────────────────────────────────────────────
    "hour_sin",
    "hour_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "ttr_urgency",                 # 1/sqrt(ttr_hours) — increases as resolution approaches
    "price_extremity",             # how far from 0.5 (both directions)
    "vol_momentum",                # volume_24h / volume_7d (daily vs weekly pace)
    "spread_norm",                 # spread / price_yes — normalized cost of being wrong
    # ── Portfolio Context (10) ────────────────────────────────────────────
    # These are filled with defaults when no portfolio data available
    "portfolio_exposure_pct",
    "portfolio_win_rate_30d",
    "portfolio_avg_edge_30d",
    "portfolio_drawdown_pct",
    "portfolio_open_positions",
    "model_confidence_30d",
    "similar_market_accuracy_30d",
    "base_rate_prior",
    "days_since_similar_resolved",
    "narrative_similarity_score",
]

assert len(FEATURE_NAMES) == N_FEATURES, f"Feature count mismatch: {len(FEATURE_NAMES)} != {N_FEATURES}"


class FeatureBuilder:
    """
    Stateless feature builder.
    All inputs are Pydantic models; output is a numpy float32 array.
    """

    def build(
        self,
        market: MarketCandidate,
        research: ResearchSummary,
        portfolio_context: dict | None = None,
    ) -> Tuple[np.ndarray, str]:
        """
        Build feature vector.
        Returns (feature_array, feature_hash) where hash is for reproducibility.
        """
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        ctx = portfolio_context or {}

        # ── Market Microstructure ─────────────────────────────────────────
        price_yes = float(market.price_yes)
        price_no = float(market.price_no)
        spread = float(market.bid_ask_spread)
        ob_imb = float(market.orderbook_imbalance)
        vol_24h_log = math.log1p(float(market.volume_24h))
        vol_7d_log = math.log1p(float(market.volume_7d))
        vol_ratio = float(market.volume_24h) / (float(market.volume_7d) / 7.0 + 1e-9)
        liq_log = math.log1p(float(market.liquidity))
        ttr_log = math.log1p(float(market.time_to_resolution_hours))
        age_log = math.log1p(float(market.market_age_days))
        vol_7d = float(market.volatility_7d)
        whale = float(market.whale_trade_count_24h)
        traders_log = math.log1p(float(market.unique_traders_7d))
        dist_half = abs(price_yes - 0.5)
        depth_ratio = float(market.liquidity) / (float(market.volume_24h) + 1e-9)

        # ── Sentiment / Research ──────────────────────────────────────────
        sent_pos = float(research.sentiment_positive)
        sent_neg = float(research.sentiment_negative)
        sent_unc = float(research.sentiment_uncertainty)
        sent_net = sent_pos - sent_neg
        sent_abs = abs(sent_net)
        momentum = float(research.social_momentum)
        narrative = float(research.narrative_intensity)
        expert_log = math.log1p(float(research.expert_signal_count))
        tier = float(research.news_publication_tier_score)
        arrival_log = math.log1p(float(research.information_arrival_rate))
        tw_log = math.log1p(float(research.source_breakdown.twitter_count))
        rd_log = math.log1p(float(research.source_breakdown.reddit_count))
        nw_log = math.log1p(float(research.source_breakdown.news_count))
        total_src = (
            research.source_breakdown.twitter_count
            + research.source_breakdown.reddit_count
            + research.source_breakdown.news_count
            + research.source_breakdown.rss_count
        )
        total_log = math.log1p(float(total_src))
        dq_map = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.0}
        dq = dq_map.get(research.data_quality, 0.5)

        # ── Interaction Features ──────────────────────────────────────────
        int_1 = sent_net * momentum
        int_2 = sent_neg * sent_unc
        int_3 = vol_24h_log * sent_abs
        int_4 = narrative * expert_log
        int_5 = spread * sent_unc
        int_6 = price_yes * sent_net
        int_7 = ttr_log * narrative
        int_8 = liq_log * spread
        int_9 = momentum * tier
        int_10 = vol_7d * sent_abs

        # ── Category One-Hot ──────────────────────────────────────────────
        cat = market.category.value
        cat_vec = [
            1.0 if cat == "politics" else 0.0,
            1.0 if cat == "sports" else 0.0,
            1.0 if cat == "crypto" else 0.0,
            1.0 if cat == "finance" else 0.0,
            1.0 if cat == "science" else 0.0,
            1.0 if cat == "entertainment" else 0.0,
            1.0 if cat == "other" else 0.0,
        ]

        # ── Temporal ─────────────────────────────────────────────────────
        hour = now.hour
        dow = now.weekday()
        hour_sin = math.sin(2 * math.pi * hour / 24)
        hour_cos = math.cos(2 * math.pi * hour / 24)
        dow_sin = math.sin(2 * math.pi * dow / 7)
        dow_cos = math.cos(2 * math.pi * dow / 7)
        ttr_urgency = 1.0 / math.sqrt(float(market.time_to_resolution_hours) + 1.0)
        price_extremity = dist_half * 2  # 0 at 0.5, 1 at 0 or 1
        vol_momentum_feat = min(vol_ratio, 5.0) / 5.0
        spread_norm = spread / (price_yes + 1e-9)

        # ── Portfolio Context ─────────────────────────────────────────────
        port_exp = float(ctx.get("portfolio_exposure_pct", 0.0))
        win_rate = float(ctx.get("portfolio_win_rate_30d", 0.5))
        avg_edge = float(ctx.get("portfolio_avg_edge_30d", 0.0))
        drawdown = float(ctx.get("portfolio_drawdown_pct", 0.0))
        open_pos = float(ctx.get("portfolio_open_positions", 0))
        model_conf = float(ctx.get("model_confidence_30d", 0.6))
        sim_acc = float(ctx.get("similar_market_accuracy_30d", 0.5))
        base_rate = float(ctx.get("base_rate_prior", 0.5))
        days_since = float(ctx.get("days_since_similar_resolved", 30))
        narr_sim = float(research.narrative_similarity_score)

        # ── Assemble ──────────────────────────────────────────────────────
        features = np.array([
            # microstructure (15)
            price_yes, price_no, spread, ob_imb, vol_24h_log,
            vol_7d_log, vol_ratio, liq_log, ttr_log, age_log,
            vol_7d, whale, traders_log, dist_half, depth_ratio,
            # sentiment (15)
            sent_pos, sent_neg, sent_unc, sent_net, sent_abs,
            momentum, narrative, expert_log, tier, arrival_log,
            tw_log, rd_log, nw_log, total_log, dq,
            # interactions (10)
            int_1, int_2, int_3, int_4, int_5,
            int_6, int_7, int_8, int_9, int_10,
            # category (7)
            *cat_vec,
            # temporal (8)
            hour_sin, hour_cos, dow_sin, dow_cos,
            ttr_urgency, price_extremity, vol_momentum_feat, spread_norm,
            # portfolio (10)
            port_exp, win_rate, avg_edge, drawdown, open_pos,
            model_conf, sim_acc, base_rate, days_since, narr_sim,
        ], dtype=np.float32)

        assert len(features) == N_FEATURES, f"Built {len(features)} features, expected {N_FEATURES}"

        # Replace any NaN/Inf with 0 (defensive)
        features = np.nan_to_num(features, nan=0.0, posinf=5.0, neginf=-5.0)

        feature_hash = hashlib.sha256(features.tobytes()).hexdigest()[:16]
        return features, feature_hash

    def get_feature_names(self) -> List[str]:
        return FEATURE_NAMES.copy()
