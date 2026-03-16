"""
Polymarket REST (Gamma) and CLOB API client.
All external HTTP calls go through here — single point for rate limiting,
retry logic, circuit breaker integration, and latency metrics.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from core import metrics as m

logger = logging.getLogger(__name__)

GAMMA_URL = settings.polymarket_gamma_url
CLOB_URL = settings.polymarket_clob_url

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds, doubles each retry


class PolymarketClient:
    """
    Async HTTP client for Polymarket APIs.
    Instantiate once per agent process; shares underlying httpx connection pool.
    """

    def __init__(self, api_key: str = "", private_key: str = "") -> None:
        self._api_key = api_key
        self._private_key = private_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=30.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    # ── Market data (read-only, no auth required) ─────────────────────────────

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch paginated market list from Gamma API."""
        params = {"limit": limit, "offset": offset, "active": str(active).lower()}
        data = await self._get(GAMMA_URL, "/markets", params=params, api_name="gamma")
        return data if isinstance(data, list) else data.get("markets", [])

    async def get_all_active_markets(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """Paginate through all active markets."""
        markets = []
        offset = 0
        while True:
            page = await self.get_markets(limit=page_size, offset=offset)
            if not page:
                break
            markets.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        m.MARKETS_SCANNED.inc(len(markets))
        return markets

    async def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch L2 orderbook for a market token from CLOB.
        token_id is the ERC-1155 token address for YES or NO shares.
        """
        data = await self._get(CLOB_URL, f"/book", params={"token_id": token_id}, api_name="clob")
        return data

    async def get_market_trades(
        self, market_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch recent trade history for a market (for volatility calculation)."""
        params = {"market": market_id, "limit": limit}
        data = await self._get(GAMMA_URL, "/trades", params=params, api_name="gamma")
        return data if isinstance(data, list) else data.get("trades", [])

    # ── Order placement (requires auth) ──────────────────────────────────────

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """
        Place a limit order on the CLOB.
        Returns order ID and status on success.
        Raises on API error after retries exhausted.
        """
        if not self._api_key:
            raise ValueError("API key required for order placement")

        payload = {
            "market": market_id,
            "asset_id": token_id,
            "side": side.upper(),     # BUY or SELL
            "price": round(price, 4),
            "size": round(size, 2),
            "type": "LIMIT",
            "time_in_force": "GTD",   # Good Till Day
            "expiration": 86400,      # 24 hours
        }
        headers = {
            "POLY-API-KEY": self._api_key,
            "POLY-IDEMPOTENCY-KEY": idempotency_key,
        }
        return await self._post(CLOB_URL, "/order", payload, headers=headers, api_name="clob")

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        headers = {"POLY-API-KEY": self._api_key}
        return await self._get(
            CLOB_URL, f"/order/{order_id}", headers=headers, api_name="clob"
        )

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        headers = {"POLY-API-KEY": self._api_key}
        return await self._delete(CLOB_URL, f"/order/{order_id}", headers=headers, api_name="clob")

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    async def _get(
        self,
        base: str,
        path: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        api_name: str = "polymarket",
    ) -> Any:
        return await self._request("GET", base + path, params=params, headers=headers, api_name=api_name)

    async def _post(
        self,
        base: str,
        path: str,
        json_body: Any,
        headers: Optional[Dict] = None,
        api_name: str = "polymarket",
    ) -> Any:
        return await self._request("POST", base + path, json_body=json_body, headers=headers, api_name=api_name)

    async def _delete(
        self,
        base: str,
        path: str,
        headers: Optional[Dict] = None,
        api_name: str = "polymarket",
    ) -> Any:
        return await self._request("DELETE", base + path, headers=headers, api_name=api_name)

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_body: Any = None,
        headers: Optional[Dict] = None,
        api_name: str = "polymarket",
    ) -> Any:
        endpoint = url.split("?")[0].split("/")[-1]
        last_exc = None

        for attempt in range(MAX_RETRIES):
            start = time.perf_counter()
            try:
                response = await self._client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
                elapsed = time.perf_counter() - start
                status = str(response.status_code)
                m.API_REQUEST_DURATION.labels(
                    api_name=api_name, endpoint=endpoint, status=status
                ).observe(elapsed)

                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", RETRY_BACKOFF * (2 ** attempt)))
                    logger.warning("Rate limited on %s — waiting %.1fs", url, retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning("HTTP %d on %s (attempt %d)", exc.response.status_code, url, attempt + 1)
                if exc.response.status_code < 500:
                    raise  # 4xx errors are client errors — don't retry
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))

            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("Network error on %s (attempt %d): %s", url, attempt + 1, exc)
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))

        raise RuntimeError(f"All {MAX_RETRIES} attempts failed for {url}") from last_exc

    async def close(self) -> None:
        await self._client.aclose()


def estimate_slippage(
    orderbook: Dict[str, Any],
    side: str,
    target_size: float,
) -> tuple[float, float]:
    """
    Walk the orderbook to estimate fill price and slippage for target_size shares.

    Returns:
        (estimated_fill_price, slippage_pct)
    """
    # CLOB returns asks sorted ascending, bids sorted descending
    levels = orderbook.get("asks" if side == "YES" else "bids", [])
    if not levels:
        return 0.0, 1.0  # No liquidity — maximum slippage

    mid_price = float(levels[0]["price"])
    remaining = target_size
    total_cost = 0.0

    for level in levels:
        price = float(level["price"])
        available = float(level["size"])
        fill = min(remaining, available)
        total_cost += fill * price
        remaining -= fill
        if remaining <= 0:
            break

    if remaining > 0:
        # Order larger than available depth
        return 0.0, 1.0

    avg_fill = total_cost / target_size
    slippage_pct = abs(avg_fill - mid_price) / mid_price
    return avg_fill, slippage_pct
