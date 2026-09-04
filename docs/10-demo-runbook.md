# Tomorrow Demo Runbook

## Freeze gate

From `final-version` run:

```bash
bash scripts/demo_gate.sh
```

Do not change a model, package version, or protocol after this passes.

## RTX worker deployment

1. Confirm Tailscale reaches the VPS and Docker sees the GPU:

   ```bash
   tailscale ping 100.x.y.z
   docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
   ```

2. Build and prefetch into the shared Docker cache volume:

   ```bash
   docker compose -f docker-compose.worker.yml build worker live-worker
   docker compose -f docker-compose.worker.yml run --rm live-worker python scripts/prefetch_models.py
   ```

3. Set the worker `.env` to authenticated Tailscale URLs, then start both processes:

   ```bash
   docker compose -f docker-compose.worker.yml up -d worker live-worker
   docker compose -f docker-compose.worker.yml logs -f live-worker
   ```

   Wait for `Live GPU worker ready`. The worker deliberately has no heartbeat while models are cold or missing.

### Native WSL worker alternative

On an RTX workstation using NVIDIA's WSL passthrough, Docker and a Linux display
driver are not required. Install both requirements files into `.venv`, prefetch
all six model snapshots, and keep them offline:

```bash
python -m pip install -r requirements.txt -r requirements-worker.txt
python scripts/prefetch_models.py
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/prefetch_models.py
```

CTranslate2 currently needs CUDA 12 cuBLAS beside PyTorch's CUDA 13 runtime.
`requirements-worker.txt` installs it; include both NVIDIA package directories
in `LD_LIBRARY_PATH`. The checked-in user services already do this:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/emotionflow-*-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now emotionflow-live-worker emotionflow-file-worker
```

The service files expect the isolated deployment at
`/home/happy/emotionflow-rtx5070` and a mode-600 `.env.worker.local`.

4. From the VPS, verify:

   ```bash
   curl -fsS https://emotionflow.site/health
   ```

   `live_workers_ready` must be at least `1`.

## Offline proof

After model prefetch, temporarily block outbound internet on the RTX worker. Restart both workers and demonstrate one short upload plus one live session. The result provenance must show `external_inference: false`.

## 30-second live script

Speak naturally with pauses so three-second windows form cleanly:

1. Calm: “I called to ask about the status of my order. Everything seemed normal at first.”
2. Topic change: “The delivery is now two weeks late and nobody has explained the delay.”
3. Strong shift: “This is not acceptable. I need to speak to your manager today.”
4. Resolution: “Thank you for fixing it. I feel much better now.”

Pass conditions:

- First transcript and fused emotion are shown within five seconds from the beginning of the window.
- Rolling capture-to-result latency stays at or below five seconds.
- Voice/text scores, agreement, topic, acoustic evidence, exact trigger phrase, and source-labelled explanation appear.
- “Emotion shifts” equals stabilized transitions, not transcript segments.
- Stopping produces `final_result` and releases the session.

Save a screenshot and browser console, then export/copy the final JSON and record p50/p95 readings. If Qwen exceeds 1.5 seconds, show `deterministic-fallback` as the intended safe behavior.

## Google Meet

Build the frontend with the numeric project number and deploy the exact same commit. Configure the developer deployment using `integrations/google-meet/deployment.json`, install it, open `/meet/side-panel`, sign in, and grant microphone permission. State only: “EmotionFlow analyzes the consenting local participant’s microphone.”

## Evaluation wording

- Say “all six authoritative proposal features are implemented and demonstrable, with multimodal fusion, local inference, and Meet integration retained as additive capabilities.”
- Say “causal explanation is grounded evidence interpretation, not proof of causation.”
- Say “fine-tuning is deferred pending a labelled causal dataset.”
- Report measured emotion accuracy and latency honestly; never claim 100% prediction accuracy.
