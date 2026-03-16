"""
ResearchAgent

Consumes MarketCandidate from the scan bus.
Runs Twitter, Reddit, and News searches in parallel.
Produces a ResearchSummary with aggregated sentiment + research signals.

One ResearchAgent instance handles the async queue; multiple instances
can be deployed for parallel processing (each subscribes independently).
"""
from __future__ import annotations

import asyncio
import logging
from typing import List

from agents.base_agent import BaseAgent
from core.bus import CHANNEL_MARKET_SCAN, CHANNEL_RESEARCH_JOBS
from core.models import MarketCandidate, ResearchSummary, SourceBreakdown
from core.config import settings
from data.twitter_client import TwitterClient
from data.reddit_client import RedditClient
from data.news_client import NewsClient
from sentiment.analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


def _extract_keywords(question: str, max_words: int = 5) -> str:
    """Extract key query terms from market question for search."""
    stopwords = {
        "will", "the", "a", "an", "in", "on", "at", "to", "for", "of",
        "and", "or", "by", "is", "be", "this", "that", "win", "lose",
        "happen", "occur", "before", "after", "during", "?",
    }
    words = [w.strip("?.,!") for w in question.split()]
    keywords = [w for w in words if w.lower() not in stopwords and len(w) > 2]
    return " ".join(keywords[:max_words])


class ResearchAgent(BaseAgent):
    """
    Reactive agent: wakes up on each MarketCandidate message.
    Gathers multi-source data asynchronously, produces ResearchSummary.
    """

    name = "research"
    cycle_interval_seconds = 999999  # driven by messages, not timer

    def __init__(self, bus, circuit_breaker, redis_client=None, anthropic_client=None) -> None:
        super().__init__(bus, circuit_breaker)
        self._twitter = TwitterClient(redis_client=redis_client)
        self._reddit = RedditClient()
        self._news = NewsClient(redis_client=redis_client)
        self._sentiment = SentimentAnalyzer(anthropic_client=anthropic_client)
        self._redis = redis_client
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def tick(self) -> None:
        """Drain one item from the local queue and process it."""
        try:
            candidate: MarketCandidate = await asyncio.wait_for(
                self._queue.get(), timeout=5.0
            )
            summary = await self._research_market(candidate)
            await self.publish(CHANNEL_RESEARCH_JOBS, summary)
            self._queue.task_done()
        except asyncio.TimeoutError:
            pass  # normal — no pending work

    async def enqueue(self, candidate: MarketCandidate) -> None:
        """Called by the orchestrator when a MarketCandidate arrives."""
        try:
            self._queue.put_nowait(candidate)
        except asyncio.QueueFull:
            logger.warning("Research queue full — dropping market %s", candidate.market_id)

    async def _research_market(self, candidate: MarketCandidate) -> ResearchSummary:
        """
        Gather all research data for a single market in parallel.
        Hard timeout: settings.research_timeout_seconds.
        """
        query = _extract_keywords(candidate.question)
        category = candidate.category.value

        self._log.debug("Researching market %s: '%s'", candidate.market_id, query)

        # Run all data sources in parallel with a shared timeout
        try:
            (
                tweets,
                reddit_posts,
                news_articles,
                rss_articles,
            ) = await asyncio.wait_for(
                asyncio.gather(
                    self._twitter.search_recent(query, max_results=100),
                    self._reddit.search_posts(query, category=category, limit=50),
                    self._news.search_news(query, days_back=7),
                    self._news.fetch_rss_feeds(keywords=query.split()),
                    return_exceptions=True,
                ),
                timeout=settings.research_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Research timeout for market %s", candidate.market_id)
            return self._empty_summary(candidate.market_id, data_quality="LOW")

        # Flatten exceptions to empty lists
        tweets = tweets if isinstance(tweets, list) else []
        reddit_posts = reddit_posts if isinstance(reddit_posts, list) else []
        news_articles = news_articles if isinstance(news_articles, list) else []
        rss_articles = rss_articles if isinstance(rss_articles, list) else []

        # ── Aggregate all text for sentiment analysis ─────────────────────
        all_texts = (
            [t.get("text", "") for t in tweets]
            + [p.get("title", "") + " " + p.get("text", "") for p in reddit_posts]
            + [a.get("title", "") + " " + a.get("summary", "") for a in news_articles]
            + [a.get("title", "") + " " + a.get("summary", "") for a in rss_articles]
        )
        all_texts = [t for t in all_texts if t.strip()]

        sentiment = self._sentiment.analyze_batch(all_texts)

        # ── Social momentum (tweet velocity) ─────────────────────────────
        tweet_hourly = [1] * len(tweets)  # simplified: each tweet = 1 unit
        momentum = self._sentiment.compute_social_momentum(tweet_hourly)

        # ── Source tier score ─────────────────────────────────────────────
        tier_scores = [a.get("source_tier", 0.5) for a in news_articles + rss_articles]
        avg_tier = sum(tier_scores) / len(tier_scores) if tier_scores else 0.5

        # ── Expert signal count ───────────────────────────────────────────
        expert_count = sum(
            1 for t in tweets
            if t.get("author_followers", 0) > 10_000 or t.get("author_verified", False)
        )

        # ── Information arrival rate ──────────────────────────────────────
        total_sources = len(tweets) + len(reddit_posts) + len(news_articles) + len(rss_articles)
        arrival_rate = total_sources / (settings.research_timeout_seconds / 3600.0)

        # ── Narrative intensity ───────────────────────────────────────────
        max_expected_sources = 200
        narrative_intensity = min(total_sources / max_expected_sources, 1.0)

        # ── Top headlines for Claude context ──────────────────────────────
        headlines = [
            a["title"] for a in (news_articles + rss_articles)[:5] if a.get("title")
        ]

        # ── Data quality assessment ───────────────────────────────────────
        data_quality = "HIGH" if total_sources >= 20 else ("MEDIUM" if total_sources >= 5 else "LOW")

        return ResearchSummary(
            market_id=candidate.market_id,
            sentiment_positive=sentiment.positive,
            sentiment_negative=sentiment.negative,
            sentiment_uncertainty=sentiment.uncertainty,
            social_momentum=momentum,
            narrative_intensity=narrative_intensity,
            expert_signal_count=expert_count,
            news_publication_tier_score=avg_tier,
            information_arrival_rate=arrival_rate,
            source_breakdown=SourceBreakdown(
                twitter_count=len(tweets),
                reddit_count=len(reddit_posts),
                news_count=len(news_articles),
                rss_count=len(rss_articles),
            ),
            top_headlines=headlines,
            data_quality=data_quality,
        )

    def _empty_summary(self, market_id: str, data_quality: str = "LOW") -> ResearchSummary:
        return ResearchSummary(
            market_id=market_id,
            data_quality=data_quality,
        )
