import unittest
from concurrent.futures import TimeoutError
from unittest.mock import patch

from app.services.local_causality_service import deterministic_cause, explain_transition, select_trigger_phrase
from app.services.multimodal_service import (
    analyze_topics,
    build_transitions,
    fuse_modalities,
    normalize_scores,
    overall_sentiment,
    stabilize_emotions,
)


class FakeFuture:
    def __init__(self, result=None, error=None):
        self.value = result
        self.error = error

    def result(self, timeout=None):
        if self.error:
            raise self.error
        return self.value

    def cancel(self):
        return True


class MultimodalUnitTests(unittest.TestCase):
    def test_label_mapping_and_normalization(self):
        scores = normalize_scores({"ang": 0.6, "hap": 0.3, "neu": 0.1})
        self.assertAlmostEqual(scores["anger"], 0.6)
        self.assertAlmostEqual(scores["joy"], 0.3)
        self.assertAlmostEqual(sum(scores.values()), 1.0)

    def test_exact_weighted_fusion(self):
        result = fuse_modalities({"anger": 0.8, "neutral": 0.2}, {"anger": 0.4, "neutral": 0.6})
        self.assertEqual(result["emotion"], "anger")
        self.assertAlmostEqual(result["scores"]["anger"], 0.62)
        self.assertAlmostEqual(result["scores"]["neutral"], 0.38)

    def test_missing_modality_falls_back(self):
        text_only = fuse_modalities({}, {"joy": 0.7, "neutral": 0.3})
        self.assertEqual(text_only["emotion"], "joy")
        self.assertEqual(text_only["audio_weight"], 0.0)
        self.assertEqual(text_only["text_weight"], 1.0)
        audio_only = fuse_modalities({"anger": 0.8, "neutral": 0.2}, {})
        self.assertEqual(audio_only["emotion"], "anger")
        self.assertEqual(audio_only["audio_weight"], 1.0)
        self.assertEqual(audio_only["text_weight"], 0.0)

    def test_hysteresis_rejects_weak_change(self):
        segments = [
            {"modalities": {"fused": {"emotion": "neutral", "scores": {"neutral": 0.6, "anger": 0.4}}}},
            {"modalities": {"fused": {"emotion": "anger", "scores": {"neutral": 0.44, "anger": 0.50}}}},
        ]
        stabilize_emotions(segments)
        self.assertEqual(segments[1]["emotion"], "neutral")

    def test_transition_count_uses_stabilized_changes(self):
        segments = [
            {"emotion": "neutral", "intensity": 0.7, "text": "one", "topic": {}, "acoustic": {}, "modalities": {}},
            {"emotion": "neutral", "intensity": 0.8, "text": "two", "topic": {}, "acoustic": {}, "modalities": {}},
            {"emotion": "anger", "intensity": 0.9, "text": "not acceptable", "topic": {}, "acoustic": {}, "modalities": {}},
        ]
        with patch("app.services.local_causality_service._executor.submit", return_value=FakeFuture("A grounded explanation of the observed change.")):
            self.assertEqual(len(build_transitions(segments)), 1)

    def test_topic_change_threshold(self):
        topics = analyze_topics([
            "invoice payment account billing",
            "invoice payment account balance",
            "garden weather flowers sunshine",
        ])
        self.assertFalse(topics[1]["is_shift"])
        self.assertTrue(topics[2]["is_shift"])
        self.assertLess(topics[2]["similarity_to_previous"], 0.25)

    def test_trigger_is_exact_substring(self):
        text = "I waited for an hour, and this is not acceptable."
        trigger = select_trigger_phrase(text)
        self.assertIsNotNone(trigger)
        self.assertIn(trigger, text)

    def test_deterministic_cause_uses_grounded_evidence(self):
        previous = {"emotion": "neutral", "topic": {"label": "account"}}
        current = {
            "emotion": "anger", "topic": {"label": "service delay", "is_shift": True},
            "acoustic": {"energy_delta_db": 4.0},
            "modalities": {"audio": {"emotion": "anger"}, "text": {"emotion": "anger"}},
        }
        cause = deterministic_cause(previous, current)
        self.assertIn("neutral to anger", cause)
        self.assertIn("service delay", cause)
        self.assertIn("vocal energy", cause)

    def test_overall_sentiment_is_deterministic(self):
        self.assertEqual(overall_sentiment([{"emotion": "joy", "intensity": 0.9}]), "positive")
        self.assertEqual(overall_sentiment([{"emotion": "anger", "intensity": 0.9}]), "negative")

    def test_qwen_timeout_uses_deterministic_fallback(self):
        current = {"emotion": "anger", "text": "not acceptable", "topic": {}, "acoustic": {}, "modalities": {}}
        with patch("app.services.local_causality_service._executor.submit", return_value=FakeFuture(error=TimeoutError())):
            cause, source = explain_transition(None, current)
        self.assertEqual(source, "deterministic-fallback")
        self.assertIn("anger", cause)

    def test_qwen_malformed_output_uses_deterministic_fallback(self):
        current = {"emotion": "joy", "text": "thank you", "topic": {}, "acoustic": {}, "modalities": {}}
        with patch("app.services.local_causality_service._executor.submit", return_value=FakeFuture("short")):
            _, source = explain_transition(None, current)
        self.assertEqual(source, "deterministic-fallback")


if __name__ == "__main__":
    unittest.main()
