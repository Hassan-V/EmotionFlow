"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, MicOff, Square, Wifi, WifiOff } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ensureFreshAccessToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AnalysisResult, EmotionShift, EmotionTransition, TranscriptSegment } from "@/lib/types";

const TEXT_COLORS: Record<string, string> = {
  joy: "text-yellow-400", anger: "text-red-400", sadness: "text-blue-400",
  fear: "text-purple-400", disgust: "text-orange-400", surprise: "text-cyan-400", neutral: "text-zinc-400",
};

type RecorderState = "idle" | "connecting" | "recording" | "processing" | "done" | "error";
type StreamMessage =
  | { type: "connected"; session_id: string; worker_id: string }
  | { type: "status"; message: string }
  | { type: "transcript"; segment: TranscriptSegment; latency_ms?: number }
  | { type: "emotion"; segment: EmotionShift; latency_ms?: number }
  | { type: "causality"; transition: EmotionTransition; latency_ms?: number }
  | { type: "final_result"; result: AnalysisResult }
  | { type: "error"; message: string; recoverable?: boolean };

interface LiveRecorderProps {
  token: string;
  apiBase: string;
  compact?: boolean;
}

export function LiveRecorder({ token, apiBase, compact = false }: LiveRecorderProps) {
  const [state, setState] = useState<RecorderState>("idle");
  const stateRef = useRef<RecorderState>("idle");
  const [status, setStatus] = useState("Ready to record");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [emotions, setEmotions] = useState<EmotionShift[]>([]);
  const [transitions, setTransitions] = useState<EmotionTransition[]>([]);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [finalResult, setFinalResult] = useState<AnalysisResult | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  const moveTo = useCallback((next: RecorderState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  useEffect(() => {
    // Always return undefined. Some newer browsers return a promise-like value
    // from scrollIntoView, which React would otherwise treat as a cleanup.
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const releaseAudio = useCallback(async () => {
    nodeRef.current?.disconnect();
    nodeRef.current = null;
    mediaRef.current?.getTracks().forEach((track) => track.stop());
    mediaRef.current = null;
    if (contextRef.current && contextRef.current.state !== "closed") await contextRef.current.close();
    contextRef.current = null;
  }, []);

  useEffect(() => () => {
    wsRef.current?.close();
    void releaseAudio();
  }, [releaseAudio]);

  const startRecording = useCallback(async () => {
    setError(""); setTranscript([]); setEmotions([]); setTransitions([]); setFinalResult(null); setLatencyMs(null);
    moveTo("connecting"); setStatus("Connecting to the Tailscale GPU worker…");
    const streamToken = await ensureFreshAccessToken(token);
    if (!streamToken) {
      setError("Your session expired. Sign in again before starting live analysis.");
      moveTo("error");
      return;
    }
    const wsBase = (apiBase || window.location.origin).replace(/^http/, "ws");
    const ws = new WebSocket(`${wsBase}/ws/stream?token=${encodeURIComponent(streamToken)}`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onmessage = async (event) => {
      const message = JSON.parse(event.data) as StreamMessage;
      if (message.type === "connected") {
        try {
          const media = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
          const context = new AudioContext();
          await context.audioWorklet.addModule("/pcm-worklet.js");
          const source = context.createMediaStreamSource(media);
          const node = new AudioWorkletNode(context, "emotionflow-pcm");
          node.port.onmessage = (audioEvent: MessageEvent<ArrayBuffer>) => {
            if (ws.readyState === WebSocket.OPEN) ws.send(audioEvent.data);
          };
          source.connect(node);
          node.connect(context.destination);
          mediaRef.current = media; contextRef.current = context; nodeRef.current = node;
          ws.send(JSON.stringify({ type: "config", tier: "fast", session_id: crypto.randomUUID(),
            encoding: "pcm_s16le", sample_rate: 16000, chunk_ms: 250 }));
          moveTo("recording"); setStatus(`Live on ${message.worker_id.split("-")[0]}`);
        } catch {
          setError("Microphone access failed. Allow microphone permission and retry.");
          moveTo("error"); ws.close();
        }
      } else if (message.type === "status") setStatus(message.message);
      else if (message.type === "transcript") {
        setTranscript((current) => [...current, message.segment]);
        if (message.latency_ms != null) setLatencyMs(message.latency_ms);
      } else if (message.type === "emotion") {
        setEmotions((current) => [...current, message.segment]);
        if (message.latency_ms != null) setLatencyMs(message.latency_ms);
      } else if (message.type === "causality") {
        setTransitions((current) => [...current, message.transition]);
        if (message.latency_ms != null) setLatencyMs(message.latency_ms);
      } else if (message.type === "final_result") {
        setFinalResult(message.result); moveTo("done"); setStatus("Analysis complete — fully local inference");
      } else if (message.type === "error") {
        setError(message.message); moveTo("error");
      }
    };
    ws.onerror = () => { setError("Could not connect to the live GPU worker."); moveTo("error"); };
    ws.onclose = () => {
      if (stateRef.current === "recording" || stateRef.current === "connecting") {
        setError("Live connection closed unexpectedly."); moveTo("error");
      }
      void releaseAudio();
    };
  }, [apiBase, moveTo, releaseAudio, token]);

  const stopRecording = useCallback(async () => {
    moveTo("processing"); setStatus("Completing the final local analysis…");
    await releaseAudio();
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "end_stream" }));
  }, [moveTo, releaseAudio]);

  const reset = () => {
    wsRef.current?.close(); wsRef.current = null;
    setTranscript([]); setEmotions([]); setTransitions([]); setFinalResult(null); setError(""); setLatencyMs(null);
    moveTo("idle"); setStatus("Ready to record");
  };

  const latest = emotions.at(-1);
  return (
    <div className={cn("space-y-4", compact && "text-sm")}>
      <Card>
        <div className="flex flex-col items-center gap-4 py-3">
          <div className="flex items-center gap-2 text-sm">
            {state === "idle" && <><WifiOff className="h-4 w-4 text-zinc-600"/><span className="text-zinc-500">{status}</span></>}
            {state === "connecting" && <><Loader2 className="h-4 w-4 animate-spin text-violet-400"/><span>{status}</span></>}
            {state === "recording" && <><span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500"/><span className="text-red-400">Recording</span><Wifi className="h-4 w-4 text-emerald-400"/></>}
            {state === "processing" && <><Loader2 className="h-4 w-4 animate-spin text-yellow-400"/><span>{status}</span></>}
            {state === "done" && <span className="text-emerald-400">✓ {status}</span>}
            {state === "error" && <span className="text-red-400">✕ Live analysis unavailable</span>}
          </div>
          {state === "idle" && <button onClick={startRecording} className="flex items-center gap-2 rounded-full bg-red-600 px-6 py-3 font-semibold hover:bg-red-500"><Mic className="h-4 w-4"/>Start live analysis</button>}
          {state === "recording" && <button onClick={stopRecording} className="flex items-center gap-2 rounded-full bg-zinc-700 px-6 py-3 font-semibold hover:bg-zinc-600"><Square className="h-4 w-4 fill-current"/>Stop</button>}
          {(state === "done" || state === "error") && <Button variant="ghost" onClick={reset}>Reset</Button>}
          {latencyMs != null && <span className={cn("rounded-full border px-3 py-1 text-xs", latencyMs <= 5000 ? "border-emerald-500/30 text-emerald-400" : "border-amber-500/30 text-amber-400")}>{(latencyMs / 1000).toFixed(2)}s capture-to-result</span>}
        </div>
      </Card>

      {error && <p className="rounded-lg border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-400">{error}</p>}
      {latest && <Card><p className="text-xs uppercase tracking-wide text-zinc-500">Current fused emotion</p><div className="mt-2 flex items-end justify-between"><p className={cn("text-3xl font-bold capitalize", TEXT_COLORS[latest.emotion] ?? "text-zinc-300")}>{latest.emotion}</p><p className="text-xl font-semibold">{Math.round(latest.intensity * 100)}%</p></div><div className="mt-3 grid grid-cols-2 gap-3 text-xs"><div className="rounded-lg bg-zinc-900 p-3">Voice: <b className="capitalize">{latest.modalities?.audio.emotion}</b> {Math.round((latest.modalities?.audio.confidence ?? 0) * 100)}%</div><div className="rounded-lg bg-zinc-900 p-3">Text: <b className="capitalize">{latest.modalities?.text.emotion}</b> {Math.round((latest.modalities?.text.confidence ?? 0) * 100)}%</div></div><p className={latest.modalities?.audio.emotion === latest.modalities?.text.emotion ? "mt-2 text-xs text-emerald-400" : "mt-2 text-xs text-amber-400"}>{latest.modalities?.audio.emotion === latest.modalities?.text.emotion ? "Audio and text agree" : "Audio and text disagree; weighted fusion applied"}</p>{latest.topic && <p className="mt-3 text-xs text-zinc-400">Topic: <span className="text-zinc-200">{latest.topic.label}</span>{latest.topic.is_shift && <span className="ml-2 text-cyan-400">topic shift</span>}</p>}{latest.acoustic && <p className="mt-2 text-xs text-zinc-500">Pitch {latest.acoustic.pitch_hz?.toFixed(0) ?? "—"} Hz · {latest.acoustic.rms_db.toFixed(1)} dB · {latest.acoustic.speech_rate_wps.toFixed(1)} words/s</p>}{latest.trigger_phrase && <p className="mt-2 text-xs italic text-cyan-300">“{latest.trigger_phrase}”</p>}{latest.cause && <p className="mt-2 text-xs leading-relaxed text-violet-300">{latest.cause} <span className="text-zinc-600">({latest.cause_source})</span></p>}</Card>}
      {transcript.length > 0 && <Card><h2 className="mb-3 text-sm font-semibold">Live transcript</h2><div className="max-h-52 space-y-2 overflow-y-auto">{transcript.map((segment, index) => <div key={`${segment.start}-${index}`} className="flex gap-3 text-sm"><span className="w-12 shrink-0 font-mono text-xs text-zinc-600">{segment.start.toFixed(1)}s</span><p>{segment.text}</p></div>)}<div ref={transcriptEndRef}/></div></Card>}
      {transitions.length > 0 && <Card><h2 className="mb-3 text-sm font-semibold">Local causal evidence</h2><div className="space-y-3">{transitions.slice(-3).map((transition, index) => <div key={index} className="rounded-lg border border-zinc-800 p-3"><p className="text-xs font-semibold capitalize text-violet-300">{transition.from_emotion} → {transition.to_emotion} · {transition.driver ?? "mixed"}</p><p className="mt-1 text-xs leading-relaxed text-zinc-400">{transition.explanation}</p></div>)}</div></Card>}
      {state === "idle" && !transcript.length && <div className="flex flex-col items-center gap-2 py-5 text-center text-zinc-500"><MicOff className="h-9 w-9 text-zinc-700"/><p className="text-xs">Consenting microphone audio is processed on your private Tailscale GPU worker.</p></div>}
      {finalResult && finalResult.duration_seconds < 6 && <p className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-center text-xs text-amber-300">Short sample: emotion confidence is provisional. Record at least 10 seconds with 2–3 sentences for a reliable multimodal trend.</p>}
      {finalResult && <p className="text-center text-xs text-zinc-500">{finalResult.summary}</p>}
    </div>
  );
}
