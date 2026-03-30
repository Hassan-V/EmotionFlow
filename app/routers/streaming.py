"""
WebSocket Streaming Endpoint — Real-time audio emotion analysis.

Clients connect via WebSocket and stream audio chunks.
The server processes them incrementally:
  1. Buffer audio chunks until we have enough for a segment (~5-10s)
  2. Run Whisper ASR on the buffer
  3. Run emotion classification on the new transcript
  4. Optionally run Gemini causality on accumulated segments
  5. Push results back to client in real-time

Protocol (JSON messages):

Client -> Server:
  {"type": "audio_chunk", "data": "<base64 audio>", "format": "wav"}
  {"type": "config", "model_tier": "balanced", "session_id": "abc"}
  {"type": "end_stream"}

Server -> Client:
  {"type": "transcript", "segment": {...}}
  {"type": "emotion", "segment": {...}}
  {"type": "causality", "result": {...}}
  {"type": "error", "message": "..."}
  {"type": "status", "message": "..."}
"""
import asyncio
import base64
import json
import io
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import soundfile as sf
import numpy as np

logger = logging.getLogger("emotionflow.streaming")

router = APIRouter(tags=["Streaming"])

# Minimum buffer duration (seconds) before triggering ASR
MIN_BUFFER_SECONDS = 5.0
SAMPLE_RATE = 16000  # Whisper expects 16kHz


class StreamSession:
    """Manages state for a single WebSocket streaming session."""

    def __init__(self, model_tier: str = "fast", session_id: str = ""):
        self.model_tier = model_tier
        self.session_id = session_id
        self.audio_buffer = np.array([], dtype=np.float32)
        self.all_segments: list[dict] = []
        self.all_classified: list[dict] = []
        self.total_duration: float = 0.0
        self.segment_offset: float = 0.0

    def append_audio(self, audio_data: np.ndarray):
        self.audio_buffer = np.concatenate([self.audio_buffer, audio_data])

    @property
    def buffer_duration(self) -> float:
        return len(self.audio_buffer) / SAMPLE_RATE

    def flush_buffer(self) -> Optional[str]:
        """Write buffer to a temp file and reset. Returns file path."""
        if len(self.audio_buffer) < SAMPLE_RATE:  # < 1 second
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        sf.write(tmp.name, self.audio_buffer, SAMPLE_RATE)
        self.segment_offset += self.buffer_duration
        self.audio_buffer = np.array([], dtype=np.float32)
        return tmp.name


def decode_audio_chunk(b64_data: str, audio_format: str = "wav") -> np.ndarray:
    """Decode a base64-encoded audio chunk to numpy array."""
    raw_bytes = base64.b64decode(b64_data)
    audio_io = io.BytesIO(raw_bytes)

    try:
        data, sr = sf.read(audio_io, dtype="float32")
    except Exception:
        # If soundfile can't read it, try raw PCM interpretation
        data = np.frombuffer(raw_bytes, dtype=np.float32)
        sr = SAMPLE_RATE

    # Convert to mono if stereo
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    # Resample to 16kHz if needed
    if sr != SAMPLE_RATE:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=SAMPLE_RATE)

    return data


@router.websocket("/ws/stream")
async def stream_analysis(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """
    WebSocket endpoint for real-time audio streaming analysis.

    Query params:
      token: JWT access token for authentication
    """
    # Authenticate
    user = None
    if token:
        try:
            from app.core.security import decode_token
            from app.core.database import async_session_factory
            from sqlalchemy import select
            from app.models.user import User

            payload = decode_token(token)
            user_id = payload.get("sub")
            if user_id:
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(User).where(User.id == int(user_id))
                    )
                    user = result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"WS auth failed: {e}")

    await websocket.accept()

    if not user:
        await websocket.send_json({
            "type": "error",
            "message": "Authentication required. Pass ?token=<jwt>",
        })
        await websocket.close(code=4001)
        return

    session = StreamSession()
    logger.info(f"WebSocket connected: user={user.id}")

    await websocket.send_json({
        "type": "status",
        "message": "Connected. Send 'config' message or start streaming audio_chunk messages.",
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "config":
                session.model_tier = msg.get("model_tier", "fast")
                session.session_id = msg.get("session_id", "")
                await websocket.send_json({
                    "type": "status",
                    "message": f"Config set: tier={session.model_tier}, session={session.session_id}",
                })

            elif msg_type == "audio_chunk":
                b64_data = msg.get("data", "")
                if not b64_data:
                    continue

                try:
                    audio = decode_audio_chunk(b64_data, msg.get("format", "wav"))
                    session.append_audio(audio)
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"Audio decode error: {e}"})
                    continue

                # Process when buffer is long enough
                if session.buffer_duration >= MIN_BUFFER_SECONDS:
                    await _process_buffer(websocket, session, user.id)

            elif msg_type == "end_stream":
                # Process remaining buffer
                if session.buffer_duration > 1.0:
                    await _process_buffer(websocket, session, user.id)

                # Run final Gemini analysis on all accumulated segments
                if session.all_classified:
                    await _run_final_causality(websocket, session, user.id)

                await websocket.send_json({
                    "type": "status",
                    "message": "Stream ended. Analysis complete.",
                })
                break

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user.id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _process_buffer(websocket: WebSocket, session: StreamSession, user_id: int):
    """Process the current audio buffer through ASR + emotion classification."""
    tmp_path = session.flush_buffer()
    if not tmp_path:
        return

    try:
        # Run ASR in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()

        from app.services.asr_service import transcribe
        asr_result = await loop.run_in_executor(
            None, transcribe, tmp_path, session.model_tier
        )

        # Adjust timestamps by offset
        offset = session.segment_offset - (asr_result["duration_seconds"])
        for seg in asr_result["segments"]:
            seg["start"] = round(seg["start"] + offset, 2)
            seg["end"] = round(seg["end"] + offset, 2)

        # Send transcript segments
        for seg in asr_result["segments"]:
            session.all_segments.append(seg)
            await websocket.send_json({
                "type": "transcript",
                "segment": seg,
            })

        # Run emotion classification
        from app.services.emotion_service import classify_segments
        classified = await loop.run_in_executor(
            None, classify_segments, asr_result["segments"], session.model_tier
        )

        # Adjust timestamps and send
        for seg in classified:
            session.all_classified.append(seg)
            await websocket.send_json({
                "type": "emotion",
                "segment": {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "emotion": seg["emotion"],
                    "intensity": seg["intensity"],
                },
            })

    except Exception as e:
        logger.error(f"Buffer processing error: {e}")
        await websocket.send_json({"type": "error", "message": f"Processing error: {e}"})
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def _run_final_causality(websocket: WebSocket, session: StreamSession, user_id: int):
    """Run Gemini causal analysis on all accumulated segments."""
    from app.core.config import get_settings
    from app.services.gemini_service import analyze_causality

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        await websocket.send_json({
            "type": "status",
            "message": "Skipping causality — no Gemini API key configured.",
        })
        return

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            analyze_causality,
            session.all_classified,
            settings.GEMINI_API_KEY,
            None,  # session_context
        )

        await websocket.send_json({
            "type": "causality",
            "result": result,
        })
    except Exception as e:
        logger.error(f"Causality error: {e}")
        await websocket.send_json({"type": "error", "message": f"Causality error: {e}"})
