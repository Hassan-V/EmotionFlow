# EmotionFlow evaluation audit — 2026-07-18

> This is the pre-implementation baseline. For the current result, see `11-proposal-compliance.md`.

## Scope and source of truth

This audit compares the seven features in `FYP_Proposal_Multimodal_Emotion_Detection.docx`
against the current `final-version` branch (`feature/vps-model-hosting`). Later SRS/SDD/SDG
claims are not treated as proof. A checked-in result is historical evidence only; a feature is
considered verified only when the current implementation and a reproducible check support it.

## Proposal feature matrix

| # | Proposal feature | Status | Current evidence | What is still missing |
|---|---|---|---|---|
| 1 | Text-Based Sentiment & Topic Analysis | **Partial** | `app/services/emotion_service.py` contains real Transformer-based text emotion classification. The WebSocket path calls it. | The queued/file worker does not call it. No topic extraction, topic labels, or topic-change output exists. |
| 2 | Audio Emotion Detection | **Implemented, not currently re-verified** | `audio_emotion_service.py` runs wav2vec2/HuBERT-style SER on timestamped audio segments. `worker.py` uses it. A historical IEMOCAP result and old tier benchmark exist. | Re-run against the current model tiers and a labelled evaluation set. The checked-in benchmarks predate the current tier mapping. |
| 3 | Multimodal Fusion | **Missing** | Both text and audio classifiers exist separately. | No production path runs both and fuses their scores. File jobs use audio only; streaming uses text only. There is no fusion algorithm, confidence calibration, disagreement handling, or fused output. |
| 4 | Emotional Shift Tracking | **Partial / mostly implemented** | Timestamped timeline, transition objects, persisted job results, timeline chart, transcript seeking, and causality graph exist. | The legacy transition detector depended on a cloud model and had no deterministic fallback. The UI also counted segments as “Emotion shifts.” |
| 5 | Causal Detection Engine | **Partial** | The legacy cloud prompt requested trigger phrases and explanations. Results were saved and visualized. | It was cloud-dependent LLM reasoning, not a trained/validated causal model. Topic changes and local causality were absent. |
| 6 | Real-Time Dashboard | **Partial, demo path currently broken** | A live recorder, WebSocket endpoint, five-second incremental ASR, dashboard, timeline, graph, and polling job UI exist. | Live client/server message fields disagree (`data` vs `segment`, top-level `summary` vs `result.summary`), the server never sends the client’s expected `final_result`, and independently decoding one-second WebM chunks is unreliable. File-job results are asynchronous, not live. |
| 7 | Application Integration Ready | **Partial / good foundation** | JWT/API-key auth, REST upload/status endpoints, WebSocket, webhooks with signatures/retries, OpenAPI, quotas, and billing exist. | No actual Zoom, Teams, or call-centre adapter/plugin has been built or demonstrated. “Ready” should be presented as API/webhook-ready, not as an existing integration. |

## Current processing paths

```text
File upload path (current)
audio -> Whisper -> audio SER -> cloud explanation -> PostgreSQL -> dashboard
                         ^
                         no text classifier and no multimodal fusion

Live recorder path (current)
browser WebM chunks -> API process -> Whisper -> text classifier -> cloud explanation at end
                                      ^
                                      no audio SER or fusion; protocol bugs break the UI
```

The two user-facing paths therefore implement different models and cannot currently be
described as one consistent multimodal system.

## Deployment topology audit

The intended hybrid topology is structurally sound:

```text
Browser -> VPS Nginx -> Next.js/FastAPI -> PostgreSQL + Redis
                              |
                       authenticated audio download
                              |
                  Tailscale LAN GPU worker(s)
                  -> direct Redis queue / PostgreSQL result write
```

Implemented pieces include a separate worker compose file, GPU reservation, worker heartbeat,
Redis atomic job claiming, an authenticated internal file/model endpoint, temporary worker-side
downloads, and horizontally repeatable worker processes.

Deployment gaps/risk:

- The checked-in `.env` only defined a legacy cloud key and `ENVIRONMENT`; it was not a runnable
  worker/VPS configuration by itself.
- PostgreSQL and Redis are published from the VPS compose for workers. Access must be restricted
  to the Tailscale interface/firewall. Redis authentication/TLS is not configured in the compose.
- PostgreSQL TLS is enabled in production compose, but the worker connection must explicitly
  require and trust that TLS configuration.
- Remote-worker topology has not been reproduced in this audit because no compose services are
  currently running.
- File download is protected by one shared worker secret. Rotation and per-worker credentials are
  not implemented.

## Verification state

| Check | Result |
|---|---|
| Git worktree | Clean before this audit; branch `feature/vps-model-hosting` |
| Python syntax compilation | Passed for `app/` using both available Python interpreters |
| Frontend lint | Failed: 2 errors, 3 warnings |
| Frontend production build | Not verified; WSL stopped responding during the build attempt |
| Backend integration suite | Not run: it is a standalone live-service script, not pytest; PostgreSQL/Redis/API were not running |
| Current end-to-end AI pipeline | Not run |
| Historical E2E evidence | A 2-second job completed in 15.2 s on 2026-03-26 |
| Historical IEMOCAP evidence | A 132-second fast-tier file produced transcript, timeline, causes, and transitions |

The documentation claim of “60 pytest tests” is inaccurate: `test_integration.py` is a custom
HTTP script, and pytest is not installed in the project virtual environment. The script is also
likely stale because it logs in immediately after registration while the current auth flow
enforces email verification.

## Other evaluation-critical findings

1. Current Whisper tiers are `small`, `medium`, and `large-v3`; checked-in benchmarks and docs
   describe `tiny`, `small`, and `medium`. Do not quote the old 13.7/21/59 second results for the
   current code.
2. “Fast” now loads Whisper `small`, so cold-start and demo latency are likely worse than the
   historical fast-tier result.
3. All transcript rows are labelled `Speaker 1`; speaker diarization is not implemented.
4. The legacy cloud service could overwrite SER emotion and intensity. The UI did not expose
whether a label came from audio, text, fusion, or a later adjustment.
5. The historical IEMOCAP output contains implausible interpretations (for example treating
   “I’m getting an ID” as joy). A confidence/disagreement view and evaluation metrics are more
   defensible than presenting every generated explanation as fact.

## Recommended order for the evaluation build

### P0 — make one demo path truthful and reliable

1. Restore a reproducible local stack and seed a verified demo account.
2. Fix frontend lint/build and the live WebSocket protocol, or hide “live” for the evaluation if
   it cannot be made reliable.
3. Add deterministic shift detection so transitions exist with no network dependency.
4. Run text and audio classifiers on the same segments and add a simple documented fusion rule.
5. Correct the UI’s shift count and show modality confidences and fused confidence.
6. Run one short scripted sample and one labelled sample end to end; save the exact result and
   timing from the current commit.

### P1 — improve the evaluation story

1. Add topic labels/topic-change markers.
2. Make causality degrade gracefully to a local rules/small-model implementation.
3. Add a compact metrics page: per-stage latency, emotion distribution, transition count,
   modality agreement, and model provenance.
4. Verify the Tailscale worker from a second machine and document the exact commands.

### P2 — only after the demo is stable

Fine-tune or adapter-tune a tiny local causality model. Training a model before defining a
labelled causal dataset and evaluation rubric would add risk without proving the proposal. For
tomorrow, a small local inference model plus schema-constrained prompting or a deterministic
fallback is a safer target; fine-tuning can be presented as the next experimental phase.

## Honest one-sentence evaluation summary

The project has a substantial asynchronous audio-analysis platform and a working historical
audio-to-causality pipeline, but the proposal's central multimodal-fusion claim is not yet
implemented, live mode is inconsistent with file mode, and the current commit still needs a
fresh reproducible end-to-end test.
