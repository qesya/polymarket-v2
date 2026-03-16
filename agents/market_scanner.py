"""
MarketScannerAgent

Continuously scans Polymarket for inefficiency candidates.
Runs every 60 seconds, applies multi-factor filters, scores markets,
and publishes top-N candidates to the research queue.
"""
from __future__ import annotations

import asyncio
import logging
import math
import statistics
from typing import List, Dict, Any

import pandas as pd

from agents.base_agent import BaseAgent
from core.bus import CHANNEL_MARKET_SCAN
from core.config import settings
from core.models import MarketCandidate, MarketCategory, OrderbookLevel
from core import metrics as m
from core.circuit_breaker import CircuitBreaker
from data.polymarket_client import PolymarketClient, estimate_slippage

logger = logging.getLogger(__name__)


class MarketScannerAgent(BaseAgent):
    """
    Scans all active Polymarket markets and surfaces the best
    inefficiency candidates for downstream research + prediction.

    Scoring formula (opportunity_score):
        score = edge_proxy * liquidity_factor * urgency_factor

    where:
        edge_proxy     = price distance from 0.5 (but not extreme)
        liquidity_factor = log(volume_24h) / log(MAX_VOLUME)
        urgency_factor = clamp(TTR_days / 30, 0.1, 1.0)  — prefer near-term
    """

    name = "market_scanner"
    cycle_interval_seconds = settings.scanner_interval_seconds

    def __init__(self, bus, circuit_breaker: CircuitBreaker) -> None:
        super().__init__(bus, circuit_breaker)
        self._client = PolymarketClient(
            api_key=settings.polymarket_api_key,
            private_key=settings.polymarket_private_key,
        )

    async def tick(self) -> None:
        if await self.check_circuit("api"):
            return

        try:
            raw_markets = await self._client.get_all_active_markets()
        except Exception as exc:
            await self.cb.record_failure("api", str(exc))
            self._log.error("Failed to fetch markets: %s", exc)
            return

        await self.cb.record_success("api")

        candidates = self._filter_and_score(raw_markets)
        m.MARKETS_SELECTED.inc(len(candidates))

        self._log.info(
            "Scanned %d markets → %d candidates",
            len(raw_markets),
            len(candidates),
        )

        for candidate in candidates:
            await self.publish(CHANNEL_MARKET_SCAN, candidate)
            await asyncio.sleep(0.05)  # small yield to avoid flooding the bus

    async def tick(self) -> None:
        if await self.check_circuit("api"):
            return

        try:
            raw_markets = await self._client.get_all_active_markets()
        except Exception as exc:
            await self.cb.record_failure("api", str(exc))
            self._log.error("Failed to fetch markets: %s", exc)
            return

        await self.cb.record_success("api")

        candidates = self._filter_and_score(raw_markets)
        m.MARKETS_SELECTED.inc(len(candidates))

        self._log.info(
            "Scanned %d markets → %d candidates", len(raw_markets), len(candidates)
        )

        for candidate in candidates:
            await self.publish(CHANNEL_MARKET_SCAN, candidate)
            await asyncio.sleep(0.05)

    def _filter_and_score(self, raw_markets: List[Dict[str, Any]]) -> List[MarketCandidate]:
        """
        Apply filter pipeline and return top-N scored candidates.
        All operations are vectorized via pandas for speed.
        """
        if not raw_markets:
            return []

        df = pd.DataFrame(raw_markets)

        # ── Normalize field names from Polymarket API ──────────────────────
        df = self._normalize_columns(df)

        # ── Hard filters ───────────────────────────────────────────────────
        df = df[df["volume_24h"] >= settings.min_volume_24h]
        df = df[df["liquidity"] >= settings.min_liquidity]
        df = df[df["spread"] <= settings.max_bid_ask_spread]
        df = df[df["ttr_hours"] >= settings.min_time_to_resolution_hours]
        df = df[df["ttr_hours"] <= settings.max_time_to_resolution_days * 24]
        df = df[df["price_yes"] >= settings.min_price]
        df = df[df["price_yes"] <= settings.max_price]

        if df.empty:
            return []

        # ── Derived features ───────────────────────────────────────────────
        df["orderbook_imbalance"] = (
            df["bid_depth"] - df["ask_depth"]
        ) / (df["bid_depth"] + df["ask_depth"] + 1e-9)

        max_vol = df["volume_24h"].max() + 1
        df["liquidity_factor"] = df["volume_24h"].apply(
            lambda v: math.log(v + 1) / math.log(max_vol + 1)
        )

        df["urgency_factor"] = (df["ttr_hours"] / (30 * 24)).clip(0.1, 1.0)

        # Edge proxy: distance from 0.5, discounted near extremes
        df["edge_proxy"] = df["price_yes"].apply(
            lambda p: abs(p - 0.5) * (1 - abs(p - 0.5))
        )

        df["volatility_bonus"] = df["volatility_7d"].clip(0, 0.3) / 0.3

        df["opportunity_score"] = (
            df["edge_proxy"] * 0.40
            + df["liquidity_factor"] * 0.30
            + df["urgency_factor"] * 0.20
            + df["volatility_bonus"] * 0.10
        )

        df = df.sort_values("opportunity_score", ascending=False)
        df = df.head(settings.markets_per_cycle)

        return [self._row_to_candidate(row) for _, row in df.iterrows()]

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map Polymarket API field names to our internal schema."""
        rename = {
            "conditionId": "market_id",
            "condition_id": "market_id",
            "question": "question",
            "outcomePrices": "outcome_prices",
            "volume": "volume_24h",
            "volume24hr": "volume_24h",
            "liquidity": "liquidity",
            "endDate": "resolves_at",
            "end_date_iso": "resolves_at",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        # Extract YES price from outcome prices array (index 0 = YES)
        if "outcome_prices" in df.columns:
            df["price_yes"] = df["outcome_prices"].apply(
                lambda x: float(x[0]) if isinstance(x, list) and x else 0.5
            )
        elif "price_yes" not in df.columns:
            df["price_yes"] = 0.5

        df["price_no"] = 1.0 - df["price_yes"]

        # Compute time to resolution in hours
        if "resolves_at" in df.columns:
            df["ttr_hours"] = (
                pd.to_datetime(df["resolves_at"], utc=True, errors="coerce")
                - pd.Timestamp.now(tz="UTC")
            ).dt.total_seconds() / 3600
            df["ttr_hours"] = df["ttr_hours"].fillna(24.0).clip(lower=0)
        else:
            df["ttr_hours"] = 24.0

        # Fill missing numeric columns with safe defaults
        for col, default in [
            ("volume_24h", 0.0),
            ("liquidity", 0.0),
            ("spread", 0.05),
            ("volatility_7d", 0.0),
            ("bid_depth", 0.0),
            ("ask_depth", 0.0),
            ("volume_7d", 0.0),
            ("market_age_days", 0.0),
            ("whale_trade_count_24h", 0),
            ("unique_traders_7d", 0),
        ]:
            if col not in df.columns:
                df[col] = default

        # Compute spread if not provided
        if "spread" not in df.columns or df["spread"].isna().all():
            df["spread"] = (df["price_yes"] - df["price_no"]).abs().clip(0, 1)

        if "market_id" not in df.columns:
            df["market_id"] = df.index.astype(str)

        return df

    def _row_to_candidate(self, row: pd.Series) -> MarketCandidate:
        category_map = {
            "politics": MarketCategory.POLITICS,
            "sports": MarketCategory.SPORTS,
            "crypto": MarketCategory.CRYPTO,
            "finance": MarketCategory.FINANCE,
        }
        raw_cat = str(row.get("category", "")).lower()
        category = category_map.get(raw_cat, MarketCategory.OTHER)

        return MarketCandidate(
            market_id=str(row["market_id"]),
            question=str(row.get("question", "")),
            category=category,
            price_yes=float(row["price_yes"]),
            price_no=float(row["price_no"]),
            volume_24h=float(row["volume_24h"]),
            volume_7d=float(row.get("volume_7d", row["volume_24h"] * 7)),
            liquidity=float(row["liquidity"]),
            bid_ask_spread=float(row["spread"]),
            time_to_resolution_hours=float(row["ttr_hours"]),
            market_age_days=float(row.get("market_age_days", 0.0)),
            volatility_7d=float(row.get("volatility_7d", 0.0)),
            orderbook_imbalance=float(row.get("orderbook_imbalance", 0.0)),
            whale_trade_count_24h=int(row.get("whale_trade_count_24h", 0)),
            unique_traders_7d=int(row.get("unique_traders_7d", 0)),
            opportunity_score=float(row["opportunity_score"]),
        )
