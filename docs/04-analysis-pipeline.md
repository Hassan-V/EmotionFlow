# Local Multimodal Analysis Pipeline

## Models

| Stage | Fast/live | Balanced upload | Max upload |
|---|---|---|---|
| ASR | `faster-whisper base.en` | `small.en` | `medium.en` |
| Text emotion | `j-hartmann/emotion-english-distilroberta-base` | same | same |
| Audio emotion | `superb/wav2vec2-base-superb-er` | same | same |
| Explanation | `Qwen/Qwen3-0.6B` | same | same |

All models use local cache files only in production and remain resident in the live worker.

## Per-segment processing

1. Faster-Whisper emits English transcript segments and timestamps with beam size 1.
2. Audio and text classifiers map scores to `anger, disgust, fear, joy, neutral, sadness, surprise`.
3. Valid modalities are normalized and fused at 55% audio and 45% text. If either input is unavailable, the valid modality receives full weight.
4. Acoustic evidence records median pitch, RMS dB, speech rate, and duration.
5. Rolling TF-IDF emits three keywords and a readable label. Cosine similarity below `0.25` marks a topic shift.
6. Emotion hysteresis retains the previous label unless a challenger exceeds it by at least `0.10`.
7. A transition is emitted only when the stabilized label changes. The transition count is therefore not the segment count.
8. Qwen receives only measured evidence and an exact transcript trigger substring. It has 1.5 seconds and 96 output tokens; timeout or malformed output immediately uses the deterministic explanation.

Qwen cannot change labels, scores, timestamps, topics, or acoustic evidence. Overall sentiment is computed from the stabilized timeline; the language model only phrases the summary.

## Result contract

Existing timeline keys are retained. Each entry additionally contains `modalities`, `topic`, `acoustic`, `trigger_phrase`, `cause`, and `cause_source`. Final results add `transitions`, `model_provenance`, and `stage_timings_ms`.

## Live latency budget

The three-second analysis window leaves approximately two seconds for ASR, emotion inference, fusion, publication, and transport. Models must be warmed before a worker heartbeat appears. The dashboard reports capture-to-result latency from the beginning of the analyzed window.
