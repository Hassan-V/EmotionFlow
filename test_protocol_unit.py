import asyncio
import json
import unittest

from app.models.schemas import AnalysisResult
from app.routers.streaming import _enqueue, _select_live_worker


class FakeRedis:
    def __init__(self):
        self.keys_value = []
        self.items = []
        self.expirations = []

    async def keys(self, pattern):
        return self.keys_value

    async def rpush(self, key, value):
        self.items.append((key, value))

    async def expire(self, key, ttl):
        self.expirations.append((key, ttl))


class ProtocolUnitTests(unittest.TestCase):
    def test_ready_worker_selection_is_deterministic(self):
        redis = FakeRedis()
        redis.keys_value = ["live-worker:heartbeat:z-worker", "live-worker:heartbeat:a-worker"]
        self.assertEqual(asyncio.run(_select_live_worker(redis)), "a-worker")

    def test_enqueue_preserves_order_and_ttl(self):
        redis = FakeRedis()
        asyncio.run(_enqueue(redis, "gpu-1", {"type": "audio", "sequence": 7}))
        key, raw = redis.items[0]
        self.assertEqual(key, "live:worker:gpu-1")
        self.assertEqual(json.loads(raw)["sequence"], 7)
        self.assertEqual(redis.expirations[0], (key, 900))

    def test_extended_result_contract_keeps_legacy_fields(self):
        result = AnalysisResult.model_validate({
            "filename": "live-session.pcm",
            "duration_seconds": 3.0,
            "overall_sentiment": "negative",
            "timeline": [{
                "timestamp_start": 0.0,
                "timestamp_end": 3.0,
                "emotion": "anger",
                "intensity": 0.78,
                "text": "This is not acceptable",
                "modalities": {"audio": {"emotion": "anger"}, "text": {"emotion": "neutral"}},
                "topic": {"label": "service complaint", "is_shift": True},
                "acoustic": {"pitch_hz": 214, "rms_db": -18.2},
            }],
            "transcript": [{"start": 0.0, "end": 3.0, "text": "This is not acceptable"}],
            "transitions": [],
            "model_tier": "fast",
            "processing_time_ms": 800,
            "model_provenance": {"external_inference": False},
            "stage_timings": {"asr_time_ms": 300},
        })
        self.assertEqual(result.timeline[0].emotion, "anger")
        self.assertFalse(result.model_provenance["external_inference"])
        self.assertEqual(result.stage_timings["asr_time_ms"], 300)


if __name__ == "__main__":
    unittest.main()
