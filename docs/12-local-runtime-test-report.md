# Local Runtime Test Report

Tested on 18 July 2026 against base commit
`f1a333649eab03e17bd87445f6e1e8bb6cd062b4` plus the working-tree implementation.

## Test machine

- Windows host with WSL2 Ubuntu, Python 3.12.3
- NVIDIA GeForce GTX 1660 SUPER, 6 GB VRAM
- CUDA visible to PyTorch; CTranslate2 used CUDA 12 compatibility libraries
- PostgreSQL and authenticated Redis in Docker
- All model executions used `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and local-only model loading

This GPU is materially weaker than the planned RTX 5070 worker, so it is a useful
lower-bound demo test.

## Passed gates

| Gate | Observed result |
|---|---|
| Faster-Whisper `base.en` | Pass; 7 segments; 1,970 ms including initial load |
| Faster-Whisper `small.en` | Pass; 7 segments; 1,820 ms including initial load |
| Faster-Whisper `medium.en` | Pass; 4 segments; 4,391 ms including initial load |
| Unified local file engine | Pass; 7 fused segments and 1 stabilized transition |
| Local 3-second window | Pass; 1,031 ms processing time |
| Authenticated live WebSocket E2E | Pass; 35 messages, all six result/control message types, 15 segments, 1 transition |
| Live latency | Pass on GTX 1660 SUPER; 4,914 ms p95 end to end |
| Authenticated upload E2E | Pass; API → Redis → worker → API download → PostgreSQL |
| Authenticated HTTP stream E2E | Pass; chunked WAV body, 31.65 ms submit latency, 7 segments, 1 transition, transcript and cause |
| Warm upload processing | Pass; 3,496 ms for a 21.39-second WAV |
| Audio download authorization/integrity | Pass; 943,184 bytes and byte-identical to upload |
| Multimodal result contract | Pass; audio, text, and fused scores on every upload segment |
| Billing ledger | Pass; completed event with 1 compute unit |
| Local Qwen3-0.6B | Pass; actual grounded generation ran locally in FP16 |
| Qwen timeout fallback | Pass; GTX generation above 1.5 s returned deterministic evidence immediately |
| Unit/protocol/proposal suite | Pass; 21/21 |
| Frontend lint | Pass; zero errors |
| Next.js production build | Pass; includes `/meet/side-panel` and `/meet/main-stage` |
| Compose validation | Pass; local, production, and Tailscale worker definitions |
| API health | Pass; PostgreSQL, Redis, and one live worker ready |
| External inference scan | Pass; no external inference implementation or dependency remains |

The live run initially measured 5,871 ms on its first window. The cause was lazy
CUDA-kernel initialization inside already-loaded Transformers pipelines. The live
worker now executes one small text and audio inference before publishing its
heartbeat; the repeated clean run measured 4,914 ms p95.

## Defects found and fixed during runtime testing

1. Legacy databases lacked `users.is_verified` and `users.is_test_account`.
2. The WebSocket authenticator imported a removed async session-factory name.
3. Transformers 5 received `local_files_only` in the wrong argument location.
4. CTranslate2 required CUDA 12 compatibility libraries on this CUDA 13 host.
5. BF16 was unsuitable for the GTX 1660; Qwen now selects FP16 below compute capability 8.
6. The first live inference missed the latency gate; true warm-up inference fixed it.
7. The legacy billing schema lacked `compute_units` and required `cost_usd`; startup migration now handles both layouts.

## Evidence files

- `docs/evidence/local-runtime-result.json`: real model tiers and unified-engine output
- `docs/evidence/local-websocket-result.json`: full authenticated live protocol result and latency samples
- `docs/evidence/local-upload-e2e-result.json`: full queued upload result, provenance, timings, and ledger check

- `docs/evidence/local-rest-stream-result.json`: authenticated chunked HTTP transport and full JSON analysis result
## Boundaries that cannot be certified on this machine

- The real RTX 5070/Tailscale/VPS topology still needs the deployment rehearsal; the same worker/API/Redis code paths were exercised locally over separate processes.
- Google Meet Marketplace developer installation requires the real Cloud project, hosted HTTPS origin, and a live Meet. The routes, SDK integration, manifest, iframe headers, microphone pipeline, lint, and production build pass locally.
- No IEMOCAP subset was present, so no classification-accuracy number is reported. Do not claim perfect accuracy.
- Qwen's wording is an evidence-grounded explanation, not scientifically proven causation.

## Re-run

```bash
bash scripts/demo_gate.sh
python scripts/local_runtime_test.py
python scripts/local_websocket_e2e.py
python scripts/local_upload_e2e.py
```

The model-prefetch and worker environment variables in `docs/10-demo-runbook.md`
must be applied before running these commands offline.
