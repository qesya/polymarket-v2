"""
Reddit client using PRAW (Python Reddit API Wrapper).
Searches relevant subreddits for posts related to market keywords.
Read-only — no posting, no auth beyond client credentials.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any

from core.config import settings

logger = logging.getLogger(__name__)

# Subreddits to search by market category
CATEGORY_SUBREDDITS = {
    "politics": ["politics", "worldnews", "news", "PoliticalDiscussion", "Ask_Politics"],
    "sports":   ["sports", "nfl", "nba", "soccer", "baseball", "hockey"],
    "crypto":   ["CryptoCurrency", "Bitcoin", "ethereum", "CryptoMarkets", "defi"],
    "finance":  ["investing", "stocks", "wallstreetbets", "Economics", "financialindependence"],
    "other":    ["worldnews", "news", "AskReddit"],
}


class RedditClient:
    def __init__(self) -> None:
        self._reddit = None
        self._initialized = False

    def _init(self) -> None:
        if self._initialized:
            return
        try:
            import praw
            self._reddit = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent="polymarket-research-bot/1.0",
            )
            self._initialized = True
        except Exception as exc:
            logger.warning("Reddit init failed: %s — using mock data", exc)
            self._reddit = None
            self._initialized = True

    async def search_posts(
        self,
        query: str,
        category: str = "other",
        limit: int = 50,
        time_filter: str = "week",
    ) -> List[Dict[str, Any]]:
        """
        Search Reddit posts across category-relevant subreddits.
        Returns list of post dicts with title, score, num_comments, body snippet.
        time_filter: 'hour', 'day', 'week', 'month'
        """
        self._init()
        if self._reddit is None:
            return []

        subreddits = CATEGORY_SUBREDDITS.get(category, CATEGORY_SUBREDDITS["other"])
        subreddit_str = "+".join(subreddits)

        posts = []
        try:
            subreddit = self._reddit.subreddit(subreddit_str)
            for submission in subreddit.search(
                query,
                sort="relevance",
                time_filter=time_filter,
                limit=limit,
            ):
                posts.append({
                    "id": submission.id,
                    "title": submission.title,
                    "text": submission.selftext[:500] if submission.selftext else "",
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "num_comments": submission.num_comments,
                    "subreddit": str(submission.subreddit),
                    "created_utc": submission.created_utc,
                    "url": submission.url,
                })
        except Exception as exc:
            logger.error("Reddit search error: %s", exc)

        return posts

    async def get_comments(self, post_id: str, limit: int = 20) -> List[str]:
        """Fetch top comments for a specific post."""
        self._init()
        if self._reddit is None:
            return []
        try:
            submission = self._reddit.submission(id=post_id)
            submission.comments.replace_more(limit=0)
            return [
                comment.body[:300]
                for comment in submission.comments[:limit]
                if hasattr(comment, "body")
            ]
        except Exception as exc:
            logger.error("Reddit comments error: %s", exc)
            return []
