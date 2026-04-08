"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { TIER_INFO } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { Mic, MicOff, Square, Loader2, Wifi, WifiOff } from "lucide-react";
import type { ModelTier } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

interface EmotionSegment {
  emotion: string;
  intensity: number;
  trigger_phrase?: string;
  cause?: string;
}

interface StreamMessage {
  type: "connected" | "transcript" | "emotion" | "causality" | "final_result" | "status" | "error";
  segment?: TranscriptSegment;
  segments?: TranscriptSegment[];
  data?: EmotionSegment;
  result?: unknown;
  message?: string;
  session_id?: string;
}

const EMOTION_COLORS: Record<string, string> = {
  joy: "text-yellow-400",
  anger: "text-red-400",
  sadness: "text-blue-400",
  fear: "text-purple-400",
  disgust: "text-green-400",
  surprise: "text-orange-400",
  neutral: "text-zinc-400",
};

function emotionColor(e: string) {
  return EMOTION_COLORS[e?.toLowerCase()] ?? "text-zinc-400";
}

// ─── Component ────────────────────────────────────────────────────────────────

interface LiveRecorderProps {
  token: string;
  apiBase: string;
}

export function LiveRecorder({ token, apiBase }: LiveRecorderProps) {
  const [tier, setTier] = useState<ModelTier>("balanced");
  const [state, setState] = useState<"idle" | "connecting" | "recording" | "processing" | "done" | "error">("idle");
  const [statusMsg, setStatusMsg] = useState("");
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [emotions, setEmotions] = useState<EmotionSegment[]>([]);
  const [causalSummary, setCausalSummary] = useState("");
  const [error, setError] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    // Signal end of stream to server
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end_stream" }));
      setState("processing");
      setStatusMsg("Processing final analysis…");
    }
  }, []);

  const startRecording = useCallback(async () => {
    setError("");
    setTranscript([]);
    setEmotions([]);
    setCausalSummary("");
    setStatusMsg("");
    setState("connecting");

    // Build WebSocket URL
    const wsBase = apiBase.replace(/^http/, "ws");
    const wsUrl = `${wsBase}/ws/stream?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = async () => {
      // Send config first
      ws.send(JSON.stringify({ type: "config", model_tier: tier }));

      // Request microphone access
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;

        // Pick a supported mimeType
        const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"].find(
          (m) => MediaRecorder.isTypeSupported(m)
        ) ?? "";

        const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        mediaRecorderRef.current = mr;

        mr.ondataavailable = (e) => {
          if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
            const reader = new FileReader();
            reader.onload = () => {
              const base64 = (reader.result as string).split(",")[1];
              ws.send(JSON.stringify({ type: "audio_chunk", data: base64, format: "webm" }));
            };
            reader.readAsDataURL(e.data);
          }
        };

        mr.onstop = () => {
          // onstop fires after stopRecording sends end_stream
        };

        mr.start(1000); // send a chunk every 1 second
        setState("recording");
        setStatusMsg("Recording… speak clearly into your microphone");
      } catch (err) {
        setError("Microphone access denied. Please allow microphone permission and try again.");
        setState("error");
        ws.close();
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg: StreamMessage = JSON.parse(event.data);
        switch (msg.type) {
          case "connected":
            break;
          case "status":
            setStatusMsg(msg.message ?? "");
            break;
          case "transcript":
            if (msg.segment) setTranscript((p) => [...p, msg.segment!]);
            if (msg.segments) setTranscript((p) => [...p, ...msg.segments!]);
            break;
          case "emotion":
            if (msg.data) setEmotions((p) => [...p, msg.data!]);
            break;
          case "causality":
            if ((msg as unknown as { summary?: string }).summary) {
              setCausalSummary((msg as unknown as { summary: string }).summary);
            }
            break;
          case "final_result":
            setState("done");
            setStatusMsg("Analysis complete");
            break;
          case "error":
            setError(msg.message ?? "Stream error");
            setState("error");
            break;
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection failed. Check that you are signed in.");
      setState("error");
    };

    ws.onclose = (e) => {
      if (state === "recording") {
        // Unexpected close
        setError(`Connection closed unexpectedly (code ${e.code})`);
        setState("error");
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
    };
  }, [tier, token, apiBase, state]);

  const reset = () => {
    wsRef.current?.close();
    wsRef.current = null;
    setTranscript([]);
    setEmotions([]);
    setCausalSummary("");
    setError("");
    setStatusMsg("");
    setState("idle");
  };

  const isRecording = state === "recording";
  const isbusy = state === "connecting" || state === "processing";

  return (
    <div className="space-y-6">
      {/* Tier selector */}
      <Card>
        <h2 className="text-sm font-semibold mb-4">Analysis tier</h2>
        <div className="grid grid-cols-3 gap-3">
          {(Object.keys(TIER_INFO) as ModelTier[]).map((t) => {
            const info = TIER_INFO[t];
            const disabled = isRecording || isbusy;
            return (
              <button
                key={t}
                onClick={() => !disabled && setTier(t)}
                disabled={disabled}
                className={cn(
                  "border rounded-xl p-4 text-left transition-all",
                  tier === t
                    ? `${info.bg} border-current`
                    : "border-zinc-700 hover:border-zinc-600 hover:bg-zinc-800/30",
                  disabled && "opacity-50 cursor-not-allowed"
                )}
              >
                <p className={cn("font-semibold text-sm", tier === t ? info.color : "text-zinc-300")}>
                  {info.label}
                </p>
                <p className={cn("text-xl font-bold mt-1", tier === t ? info.color : "text-zinc-400")}>
                  {info.cost}
                </p>
                <p className="text-xs text-zinc-500 mt-1">{info.desc}</p>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Record controls */}
      <Card>
        <div className="flex flex-col items-center gap-5 py-4">
          {/* Status indicator */}
          <div className="flex items-center gap-2 text-sm">
            {state === "idle" && <><WifiOff className="w-4 h-4 text-zinc-600" /><span className="text-zinc-500">Ready to record</span></>}
            {state === "connecting" && <><Loader2 className="w-4 h-4 text-violet-400 animate-spin" /><span className="text-violet-400">Connecting…</span></>}
            {isRecording && (
              <>
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
                </span>
                <span className="text-red-400 font-medium">Recording</span>
                <Wifi className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400 text-xs">Streaming live</span>
              </>
            )}
            {state === "processing" && <><Loader2 className="w-4 h-4 text-yellow-400 animate-spin" /><span className="text-yellow-400">Processing…</span></>}
            {state === "done" && <><span className="text-emerald-400">✓</span><span className="text-emerald-400">Analysis complete</span></>}
            {state === "error" && <><span className="text-red-400">✗</span><span className="text-red-400">Error</span></>}
          </div>

          {statusMsg && state !== "idle" && (
            <p className="text-xs text-zinc-500 text-center max-w-xs">{statusMsg}</p>
          )}

          {/* Record / Stop button */}
          {(state === "idle" || state === "error" || state === "done") && (
            <div className="flex gap-3">
              <button
                onClick={startRecording}
                className="flex items-center gap-2 bg-red-600 hover:bg-red-500 text-white rounded-full px-6 py-3 font-semibold text-sm transition-colors"
              >
                <Mic className="w-4 h-4" />
                Start Recording
              </button>
              {(state === "done" || state === "error") && (
                <Button variant="ghost" onClick={reset}>Reset</Button>
              )}
            </div>
          )}

          {isRecording && (
            <button
              onClick={stopRecording}
              className="flex items-center gap-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-full px-6 py-3 font-semibold text-sm transition-colors"
            >
              <Square className="w-4 h-4 fill-current" />
              Stop & Analyze
            </button>
          )}

          {isbusy && (
            <div className="flex items-center gap-2 text-zinc-400 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              Please wait…
            </div>
          )}
        </div>
      </Card>

      {error && (
        <p className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">{error}</p>
      )}

      {/* Live transcript */}
      {transcript.length > 0 && (
        <Card>
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            Transcript
            {isRecording && <span className="text-xs text-emerald-400 font-normal animate-pulse">● live</span>}
          </h2>
          <div className="space-y-2 max-h-60 overflow-y-auto text-sm pr-1">
            {transcript.map((seg, i) => (
              <div key={i} className="flex gap-3 text-zinc-300">
                <span className="text-xs text-zinc-600 font-mono min-w-[3rem] mt-0.5">
                  {seg.start.toFixed(1)}s
                </span>
                <p className="leading-relaxed">{seg.text}</p>
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
        </Card>
      )}

      {/* Live emotions */}
      {emotions.length > 0 && (
        <Card>
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            Emotion stream
            {isRecording && <span className="text-xs text-emerald-400 font-normal animate-pulse">● live</span>}
          </h2>
          <div className="flex flex-wrap gap-2">
            {emotions.map((e, i) => (
              <span
                key={i}
                className={cn(
                  "text-xs px-3 py-1 rounded-full border border-current/30 font-medium capitalize",
                  emotionColor(e.emotion)
                )}
              >
                {e.emotion} <span className="opacity-60">{(e.intensity * 100).toFixed(0)}%</span>
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* Causality summary */}
      {causalSummary && (
        <Card>
          <h2 className="text-sm font-semibold mb-2">Causal analysis</h2>
          <p className="text-sm text-zinc-300 leading-relaxed">{causalSummary}</p>
        </Card>
      )}

      {/* Mic icon idle state placeholder */}
      {state === "idle" && transcript.length === 0 && (
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <MicOff className="w-10 h-10 text-zinc-700" />
          <p className="text-zinc-500 text-sm">
            Click <span className="text-zinc-300 font-medium">Start Recording</span> to begin a live analysis session.
            <br/>Your audio streams directly to the AI pipeline in real time.
          </p>
        </div>
      )}
    </div>
  );
}
