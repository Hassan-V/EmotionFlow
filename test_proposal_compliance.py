"""Acceptance tests for the six authoritative proposal features."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from app.main import app
from app.models.schemas import AnalysisResult, TelemetrySummary
from app.models.user import User
from app.routers.analysis import _validate_audio_filename, reset_daily_quota_if_due
from app.services.asr_service import TIER_MODEL_MAP
from app.services.local_causality_service import deterministic_cause, select_trigger_phrase
from app.services.multimodal_service import build_transitions, stabilize_emotions


class ProposalComplianceTests(unittest.TestCase):
    def test_1_temporal_emotion_profile_tracks_stabilized_changes(self):
        segments = [
            {
                "text": "The call started normally.",
                "modalities": {"fused": {"emotion": "neutral", "scores": {"neutral": 0.75, "anger": 0.25}}},
                "intensity": 0.75, "topic": {}, "acoustic": {},
            },
            {
                "text": "This delay is not acceptable.",
                "modalities": {"fused": {"emotion": "anger", "scores": {"neutral": 0.20, "anger": 0.80}}},
                "intensity": 0.80, "topic": {}, "acoustic": {},
            },
        ]
        stabilize_emotions(segments)
        for segment in segments:
            segment["emotion"] = segment.get("emotion") or segment["modalities"]["fused"]["emotion"]
        with patch(
            "app.services.local_causality_service.explain_transition",
            return_value=("The emotion changes from neutral to anger.", "deterministic-fallback"),
        ):
            transitions = build_transitions(segments)
        self.assertEqual([segment["emotion"] for segment in segments], ["neutral", "anger"])
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_emotion"], "neutral")
        self.assertEqual(transitions[0]["to_emotion"], "anger")

    def test_2_causal_trigger_is_exact_and_explanation_is_grounded(self):
        text = "The delivery is late, and this is not acceptable."
        trigger = select_trigger_phrase(text)
        self.assertIn(trigger, text)
        previous = {"emotion": "neutral", "topic": {"label": "order status"}}
        current = {
            "emotion": "anger",
            "text": text,
            "topic": {"label": "delivery delay", "is_shift": True},
            "acoustic": {"energy_delta_db": 5.2},
            "modalities": {"audio": {"emotion": "anger"}, "text": {"emotion": "anger"}},
        }
        explanation = deterministic_cause(previous, current)
        self.assertIn("neutral to anger", explanation)
        self.assertIn("delivery delay", explanation)

    def test_3_asr_tiers_are_local_faster_whisper_models(self):
        self.assertEqual(
            TIER_MODEL_MAP,
            {"fast": "base.en", "balanced": "small.en", "max": "medium.en"},
        )

    def test_4_rest_file_stream_and_live_routes_are_public(self):
        def flatten(routes):
            for route in routes:
                if getattr(route, "path", None):
                    yield route
                nested = getattr(route, "routes", None)
                if nested is None:
                    nested = getattr(getattr(route, "original_router", None), "routes", [])
                yield from flatten(nested)

        route_methods = {
            (route.path, method)
            for route in flatten(app.routes)
            for method in (getattr(route, "methods", None) or {"WEBSOCKET"})
        }
        self.assertIn(("/analysis/analyze-file", "POST"), route_methods)
        self.assertIn(("/analysis/analyze-stream", "POST"), route_methods)
        self.assertIn(("/ws/stream", "WEBSOCKET"), route_methods)
        self.assertEqual(_validate_audio_filename("sample.wav")[0], ".wav")
        self.assertEqual(_validate_audio_filename("sample.mp3")[0], ".mp3")

    def test_5_json_report_contains_timeline_emotions_and_causes(self):
        result = AnalysisResult.model_validate({
            "filename": "sample.wav",
            "duration_seconds": 3.0,
            "overall_sentiment": "negative",
            "summary": "The conversation shifts from neutral to anger.",
            "timeline": [{
                "timestamp_start": 0.0,
                "timestamp_end": 3.0,
                "emotion": "anger",
                "intensity": 0.82,
                "text": "This is not acceptable.",
                "trigger_phrase": "This is not acceptable.",
                "cause": "The emotion changes from neutral to anger.",
                "cause_source": "deterministic-fallback",
            }],
            "transcript": [{"start": 0.0, "end": 3.0, "text": "This is not acceptable."}],
            "transitions": [{
                "from_segment": 0, "to_segment": 1,
                "from_emotion": "neutral", "to_emotion": "anger",
                "explanation": "The emotion changes from neutral to anger.",
            }],
            "model_tier": "fast",
            "processing_time_ms": 800,
        })
        payload = result.model_dump(mode="json")
        self.assertEqual(payload["timeline"][0]["emotion"], "anger")
        self.assertTrue(payload["timeline"][0]["cause"])
        self.assertTrue(payload["timeline"][0]["trigger_phrase"])

    def test_6_daily_quota_resets_and_telemetry_exposes_required_metrics(self):
        now = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
        user = User(quota_used_today=9, quota_reset_at=now - timedelta(seconds=1))
        self.assertTrue(reset_daily_quota_if_due(user, now))
        self.assertEqual(user.quota_used_today, 0)
        self.assertGreater(user.quota_reset_at, now)

        telemetry = TelemetrySummary(
            total_requests=100, total_users=2, active_users_today=1,
            total_analysis_jobs=10, jobs_completed=9, jobs_failed=1, jobs_pending=0,
            avg_processing_time_ms=1200, error_rate_percent=1.0, requests_last_hour=50,
            avg_api_latency_ms=24.5, p95_api_latency_ms=49.0, api_errors_last_hour=1,
        )
        self.assertEqual(telemetry.p95_api_latency_ms, 49.0)
        self.assertEqual(telemetry.api_errors_last_hour, 1)

    def test_quota_upgrade_initializes_boundary_without_erasing_usage(self):
        now = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
        user = User(quota_used_today=4, quota_reset_at=None)
        self.assertFalse(reset_daily_quota_if_due(user, now))
        self.assertEqual(user.quota_used_today, 4)
        self.assertGreater(user.quota_reset_at, now)


if __name__ == "__main__":
    unittest.main()
