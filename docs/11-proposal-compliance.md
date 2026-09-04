# Authoritative Proposal Compliance — Additive Pass

This matrix follows the six rows in the signed proposal feature table. Existing
multimodal fusion, topic analysis, local models, Tailscale workers, and Meet
integration remain additive capabilities and were not removed.

| # | Authoritative feature | Implementation evidence | Verification |
|---|---|---|---|
| 1 | Temporal Emotion Profiling | Timestamped fused intensity timeline, `0.10` hysteresis, stabilized state changes, transition count, and deterministic overall arc | Proposal test constructs a neutral to anger profile and verifies exactly one stabilized transition |
| 2 | Causal Trigger Extraction (Explainability) | Exact transcript-substring trigger phrase plus evidence-grounded explanation from emotion, modality, acoustic, and topic changes; local Qwen wording with deterministic fallback | Trigger-substring, grounded evidence, timeout, malformed-output, and fallback tests pass |
| 3 | Intelligent Speech Transcription & Processing | Faster-Whisper `base.en`, `small.en`, and `medium.en`; timestamped English transcript prepared for the shared causal engine | All three models executed offline on this machine; proposal test locks the tier mapping |
| 4 | Real-Time Analysis API | Authenticated multipart file REST API, chunked-body REST stream API, live PCM16 WebSocket, Redis routing, JSON polling/results, and webhooks | Public route contract tested; real multipart and WebSocket distributed-equivalent E2E evidence saved |
| 5 | Web-Based User Dashboard | MP3/WAV upload, live microphone view, transcript, temporal chart, fused confidence, causes, trigger phrases, topics, acoustics, and summary | Frontend lint/build and full result-schema test pass |
| 6 | API Telemetry & Usage Tracking | Request count/logs, average and p95 API latency, hourly/overall errors, worker stage latency, queue/worker health, per-user/API-key usage, compute units, quotas, and UTC daily reset | Telemetry schema and quota-reset tests pass; metrics are visible in the admin dashboard |

## Verified on this machine

- Twenty-one authoritative, deterministic, and protocol unit tests pass.
- Python compilation, frontend lint, and Next.js production build pass.
- PostgreSQL, authenticated Redis, FastAPI, file worker, and live worker passed locally.
- Base, worker, and production Compose files validate.
- Actual live p95 was 4,914 ms on the GTX 1660 SUPER.
- Actual warm upload processing was 3,496 ms for a 21.39-second WAV.
- No external inference implementation, dependency, configuration, or UI wording remains.

## Additive capabilities retained

- Seven-label audio/text fusion and rolling TF-IDF topic shifts.
- Acoustic pitch, RMS energy, speech-rate, and duration evidence.
- Offline Qwen3-0.6B wording with a bounded deterministic fallback.
- Tailscale GPU-worker deployment with live-priority scheduling.
- Google Meet side-panel and main-stage surfaces.

## External deployment evidence still required

The implementation is locally compliant. The real RTX 5070/Tailscale/VPS topology,
hosted HTTPS origin, and Google Meet developer installation still require their
external machines and accounts. No IEMOCAP dataset was present, so no accuracy
claim is made.
