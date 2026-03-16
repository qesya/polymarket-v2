"""
Tests for SentimentAnalyzer VADER and social momentum logic.
No Claude API calls in unit tests.
"""
import pytest
from sentiment.analyzer import SentimentAnalyzer


@pytest.fixture
def analyzer():
    return SentimentAnalyzer(anthropic_client=None)


class TestVADERSentiment:
    def test_positive_text(self, analyzer):
        result = analyzer.analyze_batch(["This is a great, wonderful, amazing outcome!"])
        assert result.positive > result.negative

    def test_negative_text(self, analyzer):
        result = analyzer.analyze_batch(["This is terrible, awful, a complete disaster and failure."])
        assert result.negative > result.positive

    def test_neutral_text(self, analyzer):
        result = analyzer.analyze_batch(["The event will occur on Tuesday."])
        assert result.neutral > 0.5

    def test_empty_list(self, analyzer):
        result = analyzer.analyze_batch([])
        assert result.source_count == 0
        assert result.positive == 0.0
        assert result.negative == 0.0

    def test_batch_averages(self, analyzer):
        texts = [
            "Great news! Excellent performance!",
            "Terrible outcome, awful results.",
            "The meeting happened today.",
        ]
        result = analyzer.analyze_batch(texts)
        assert result.source_count == 3
        assert 0 <= result.positive <= 1
        assert 0 <= result.negative <= 1

    def test_compound_range(self, analyzer):
        result = analyzer.analyze_batch(["Test text"])
        assert -1.0 <= result.compound <= 1.0

    def test_uncertainty_detected(self, analyzer):
        uncertain_text = "It is unclear whether this might possibly happen or not."
        result = analyzer.analyze_batch([uncertain_text])
        assert result.uncertainty > 0

    def test_urls_cleaned(self, analyzer):
        text = "Check this out https://example.com/article great news!"
        result = analyzer.analyze_batch([text])
        assert result.source_count == 1  # should not crash


class TestSocialMomentum:
    def test_accelerating_momentum(self, analyzer):
        # Recent hours have more tweets than average
        hourly = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 50]
        momentum = analyzer.compute_social_momentum(hourly)
        assert momentum > 1.0

    def test_declining_momentum(self, analyzer):
        # Recent hours have fewer tweets
        hourly = [50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 1]
        momentum = analyzer.compute_social_momentum(hourly)
        assert momentum < 1.0

    def test_empty_returns_neutral(self, analyzer):
        momentum = analyzer.compute_social_momentum([])
        assert momentum == 1.0

    def test_single_item(self, analyzer):
        momentum = analyzer.compute_social_momentum([10])
        assert momentum == 1.0  # no baseline to compare
