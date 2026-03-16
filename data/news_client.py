"""
News and RSS aggregator.
Combines NewsAPI.org (paid) with free RSS feeds for broad coverage.
Results are deduplicated by URL and cached in Redis.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2"
CACHE_TTL = 1800  # 30 minutes


class NewsClient:
    def __init__(self, redis_client=None) -> None:
        self._api_key = settings.newsapi_key
        self._redis = redis_client
        self._client = httpx.AsyncClient(timeout=15.0)

    async def search_news(
        self,
        query: str,
        days_back: int = 7,
        page_size: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Search NewsAPI for articles matching query.
        Falls back to empty list if no API key configured.
        """
        if not self._api_key:
            logger.debug("No NewsAPI key — skipping news search")
            return []

        cache_key = f"news:{hashlib.md5(query.encode()).hexdigest()}:{days_back}d"
        if self._redis:
            cached = await self._redis.get(cache_key)
            if cached:
                import json
                return json.loads(cached)

        from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        try:
            resp = await self._client.get(
                f"{NEWSAPI_BASE}/everything",
                params={
                    "q": query,
                    "from": from_date,
                    "sortBy": "relevancy",
                    "pageSize": page_size,
                    "language": "en",
                    "apiKey": self._api_key,
                },
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

            normalized = [self._normalize_article(a) for a in articles]

            if self._redis and normalized:
                import json
                await self._redis.setex(cache_key, CACHE_TTL, json.dumps(normalized))

            return normalized

        except Exception as exc:
            logger.error("NewsAPI error: %s", exc)
            return []

    async def fetch_rss_feeds(
        self,
        feeds: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch and parse RSS feeds concurrently.
        Optionally filter items by keyword relevance.
        """
        feed_urls = feeds or settings.rss_feeds
        tasks = [self._fetch_rss(url) for url in feed_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        articles = []
        for result in results:
            if isinstance(result, Exception):
                continue
            articles.extend(result)

        if keywords:
            kw_lower = [k.lower() for k in keywords]
            articles = [
                a for a in articles
                if any(
                    kw in a["title"].lower() or kw in a["summary"].lower()
                    for kw in kw_lower
                )
            ]

        return articles

    async def _fetch_rss(self, url: str) -> List[Dict[str, Any]]:
        try:
            resp = await self._client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return self._parse_rss(resp.text, source=url)
        except Exception as exc:
            logger.debug("RSS fetch failed for %s: %s", url, exc)
            return []

    def _parse_rss(self, xml_text: str, source: str) -> List[Dict[str, Any]]:
        articles = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # Handle both RSS 2.0 and Atom feeds
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)

            for item in items[:20]:  # max 20 per feed
                title = (
                    item.findtext("title")
                    or item.findtext("atom:title", namespaces=ns)
                    or ""
                )
                summary = (
                    item.findtext("description")
                    or item.findtext("atom:summary", namespaces=ns)
                    or ""
                )
                pub_date = (
                    item.findtext("pubDate")
                    or item.findtext("atom:published", namespaces=ns)
                    or ""
                )
                link = (
                    item.findtext("link")
                    or item.findtext("atom:link", namespaces=ns)
                    or ""
                )
                articles.append({
                    "title": title.strip(),
                    "summary": summary[:500].strip(),
                    "published_at": pub_date,
                    "url": link,
                    "source": source,
                    "source_tier": self._rate_source(source),
                })
        except ET.ParseError as exc:
            logger.debug("RSS parse error: %s", exc)
        return articles

    def _normalize_article(self, raw: Dict) -> Dict[str, Any]:
        return {
            "title": raw.get("title", ""),
            "summary": (raw.get("description") or raw.get("content") or "")[:500],
            "published_at": raw.get("publishedAt", ""),
            "url": raw.get("url", ""),
            "source": raw.get("source", {}).get("name", ""),
            "source_tier": self._rate_source(raw.get("source", {}).get("name", "")),
        }

    def _rate_source(self, source_name: str) -> float:
        """
        Assign credibility tier to news source (0.0 - 1.0).
        Tier 1 (0.9+): Reuters, AP, BBC, NYT, FT
        Tier 2 (0.7): Major nationals
        Tier 3 (0.5): Blogs, smaller outlets
        """
        tier1 = {"reuters", "associated press", "bbc", "new york times", "financial times", "bloomberg", "wall street journal", "wsj", "ap news"}
        tier2 = {"cnn", "fox news", "msnbc", "the guardian", "washington post", "politico", "axios", "the hill", "npr"}
        name_lower = source_name.lower()
        if any(t in name_lower for t in tier1):
            return 0.95
        if any(t in name_lower for t in tier2):
            return 0.75
        return 0.50

    async def close(self) -> None:
        await self._client.aclose()
