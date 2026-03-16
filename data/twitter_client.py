"""
Twitter/X API v2 client.
Uses Bearer Token auth (read-only). Caches results in Redis to respect rate limits.
Free tier: 500k tokens/month. Caches results for 1 hour per query.
"""
from __future__ import annotations

import hashlib
import logging
from typing import List, Dict, Any, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"
CACHE_TTL = 3600  # 1 hour


class TwitterClient:
    def __init__(self, bearer_token: str = "", redis_client=None) -> None:
        self._token = bearer_token or settings.twitter_bearer_token
        self._redis = redis_client
        self._client = httpx.AsyncClient(
            base_url=TWITTER_API_BASE,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=15.0,
        )

    async def search_recent(
        self,
        query: str,
        max_results: int = 100,
        hours_back: int = 24,
    ) -> List[Dict[str, Any]]:
        """
        Search recent tweets (last 7 days on Basic tier, last 30s on Academic).
        Returns list of tweet objects with text, author metrics, public_metrics.
        """
        if not self._token:
            logger.warning("No Twitter bearer token — skipping Twitter search")
            return []

        cache_key = f"twitter:{hashlib.md5(query.encode()).hexdigest()}:{hours_back}h"

        if self._redis:
            cached = await self._redis.get(cache_key)
            if cached:
                import json
                return json.loads(cached)

        params = {
            "query": f"{query} -is:retweet lang:en",
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,public_metrics,author_id,context_annotations",
            "expansions": "author_id",
            "user.fields": "public_metrics,verified",
            "sort_order": "recency",
        }

        try:
            resp = await self._client.get("/tweets/search/recent", params=params)
            resp.raise_for_status()
            data = resp.json()
            tweets = data.get("data", [])

            # Enrich with author metrics
            users_map = {
                u["id"]: u
                for u in data.get("includes", {}).get("users", [])
            }
            for tweet in tweets:
                author = users_map.get(tweet.get("author_id", ""), {})
                tweet["author_followers"] = (
                    author.get("public_metrics", {}).get("followers_count", 0)
                )
                tweet["author_verified"] = author.get("verified", False)

            if self._redis and tweets:
                import json
                await self._redis.setex(cache_key, CACHE_TTL, json.dumps(tweets))

            return tweets

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("Twitter rate limit hit — returning empty")
            else:
                logger.error("Twitter API error: %s", exc)
            return []
        except Exception as exc:
            logger.error("Twitter client error: %s", exc)
            return []

    async def get_tweet_volume(self, query: str, granularity: str = "hour") -> List[Dict]:
        """Get tweet count timeseries for volume/momentum calculation."""
        if not self._token:
            return []
        try:
            params = {
                "query": f"{query} -is:retweet lang:en",
                "granularity": granularity,
            }
            resp = await self._client.get("/tweets/counts/recent", params=params)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as exc:
            logger.error("Tweet volume error: %s", exc)
            return []

    async def close(self) -> None:
        await self._client.aclose()
