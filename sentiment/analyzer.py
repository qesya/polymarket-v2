"""
SentimentAnalyzer

Two-tier sentiment analysis:
  1. Fast path: VADER (rule-based, zero cost, <1ms per text)
  2. Slow path: Claude API (semantic understanding, used for ambiguous cases)

Returns calibrated sentiment scores in [0, 1] range.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from core.config import settings
from core import metrics as m

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    positive: float       # 0-1
    negative: float       # 0-1
    neutral: float        # 0-1
    compound: float       # -1 to 1 (raw VADER)
    uncertainty: float    # inferred uncertainty signal
    source_count: int     # number of texts analyzed


class SentimentAnalyzer:
    """
    Aggregates sentiment across multiple text sources.
    Uses VADER for speed; escalates to Claude for low-confidence cases.
    """

    def __init__(self, anthropic_client=None) -> None:
        self._vader = SentimentIntensityAnalyzer()
        self._claude = anthropic_client
        self._uncertainty_words = {
            "uncertain", "unclear", "unknown", "depends", "maybe", "possibly",
            "might", "could", "if", "whether", "question", "doubt", "risk",
            "likely", "unlikely", "potential", "assume", "expect",
        }

    def analyze_batch(self, texts: List[str]) -> SentimentResult:
        """
        Analyze a batch of texts and return aggregated sentiment.
        Fast VADER path — synchronous, suitable for 100+ texts.
        """
        if not texts:
            return SentimentResult(0.0, 0.0, 1.0, 0.0, 0.5, 0)

        scores = [self._vader.polarity_scores(self._clean(t)) for t in texts]

        n = len(scores)
        avg_pos = sum(s["pos"] for s in scores) / n
        avg_neg = sum(s["neg"] for s in scores) / n
        avg_neu = sum(s["neu"] for s in scores) / n
        avg_compound = sum(s["compound"] for s in scores) / n

        # Uncertainty from text content
        uncertainty = self._compute_uncertainty(texts)

        return SentimentResult(
            positive=avg_pos,
            negative=avg_neg,
            neutral=avg_neu,
            compound=avg_compound,
            uncertainty=uncertainty,
            source_count=n,
        )

    async def analyze_with_claude(
        self,
        question: str,
        texts: List[str],
        market_price: float,
    ) -> Optional[Tuple[float, str]]:
        """
        Use Claude to interpret sentiment in context of a specific prediction market question.

        Returns (probability_estimate, reasoning) or None if Claude unavailable.
        Only called when VADER scores are ambiguous or ML models strongly disagree.
        """
        if not self._claude:
            return None

        # Truncate to top 10 most relevant texts to manage token cost
        sample_texts = texts[:10]
        combined = "\n\n".join(
            f"[{i+1}] {t[:300]}" for i, t in enumerate(sample_texts)
        )

        prompt = f"""You are analyzing a prediction market. Your task is to estimate the TRUE probability of the YES outcome based on available evidence.

MARKET QUESTION: {question}

CURRENT MARKET PRICE (implied probability): {market_price:.2%}

RECENT NEWS AND SOCIAL MEDIA ({len(texts)} sources, showing top {len(sample_texts)}):
{combined}

Instructions:
1. Analyze whether the evidence supports YES or NO outcome
2. Consider sentiment, narrative strength, and information quality
3. Identify any strong signals that the market may be mispricing
4. Provide your probability estimate for YES outcome

Respond in this exact format:
PROBABILITY: [number between 0.0 and 1.0]
CONFIDENCE: [HIGH/MEDIUM/LOW]
REASONING: [2-3 sentences max]
KEY_SIGNAL: [the single most important piece of evidence]"""

        try:
            response = self._claude.messages.create(
                model=settings.claude_model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            m.CLAUDE_API_CALLS.labels(agent_name="sentiment", model=settings.claude_model).inc()

            text = response.content[0].text
            usage = response.usage
            m.CLAUDE_TOKENS.labels(agent_name="sentiment", direction="input").inc(usage.input_tokens)
            m.CLAUDE_TOKENS.labels(agent_name="sentiment", direction="output").inc(usage.output_tokens)

            return self._parse_claude_response(text)

        except Exception as exc:
            logger.error("Claude sentiment analysis failed: %s", exc)
            return None

    def compute_social_momentum(
        self,
        hourly_counts: List[int],
        window_hours: int = 24,
    ) -> float:
        """
        Velocity ratio: recent hour count / average of window.
        > 1.0 = accelerating coverage, < 1.0 = declining.
        """
        if not hourly_counts or len(hourly_counts) < 2:
            return 1.0

        recent = hourly_counts[-1]
        baseline = sum(hourly_counts[-window_hours:]) / max(len(hourly_counts[-window_hours:]), 1)
        return recent / (baseline + 1e-9)

    def _clean(self, text: str) -> str:
        """Remove URLs and special chars that confuse VADER."""
        text = re.sub(r"http\S+", "", text)
        text = re.sub(r"@\w+", "", text)
        text = re.sub(r"#(\w+)", r"\1", text)  # keep hashtag word
        return text.strip()

    def _compute_uncertainty(self, texts: List[str]) -> float:
        """
        Proportion of uncertainty-indicating words across all texts.
        Returns 0-1 where 1 = maximum uncertainty.
        """
        if not texts:
            return 0.5
        total_words = 0
        uncertainty_hits = 0
        for text in texts:
            words = text.lower().split()
            total_words += len(words)
            uncertainty_hits += sum(1 for w in words if w in self._uncertainty_words)
        if total_words == 0:
            return 0.5
        return min(uncertainty_hits / total_words * 10, 1.0)  # scale: 10% words → score 1.0

    def _parse_claude_response(self, text: str) -> Optional[Tuple[float, str]]:
        try:
            prob_line = next(l for l in text.split("\n") if l.startswith("PROBABILITY:"))
            prob = float(prob_line.split(":")[1].strip())
            prob = max(0.05, min(0.95, prob))

            reasoning_line = next(
                (l for l in text.split("\n") if l.startswith("REASONING:")), "REASONING: N/A"
            )
            reasoning = reasoning_line.replace("REASONING:", "").strip()

            return prob, reasoning
        except Exception:
            logger.warning("Failed to parse Claude response: %s", text[:200])
            return None
