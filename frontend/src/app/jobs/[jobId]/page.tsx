"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { analysisApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/Badge";
import { emotionColor, formatMs, formatDuration, TIER_INFO } from "@/lib/utils";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import type { EmotionShift, TranscriptSegment } from "@/lib/types";

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  const { data: job, refetch } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => analysisApi.getJob(jobId),
    refetchInterval: (q) =>
      q.state.data?.status === "pending" || q.state.data?.status === "processing" ? 3000 : false,
  });

  useEffect(() => {
    if (job?.status === "completed" || job?.status === "failed") refetch();
  }, [job?.status, refetch]);

  const seekTo = useCallback((seconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
      audioRef.current.play();
    }
  }, []);

  // Fetch audio blob when job completes
  useEffect(() => {
    if (job?.status !== "completed") return;
    let revoked = false;
    analysisApi.getAudioUrl(jobId).then((url) => {
      if (!revoked) setAudioUrl(url);
    }).catch(() => { /* audio not available */ });
    return () => {
      revoked = true;
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, jobId]);

  if (!job) {
    return (
      <AppShell>
        <div className="flex justify-center py-20">
          <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      </AppShell>
    );
  }

  const result = job.result;
  const tierInfo = TIER_INFO[job.model_tier];

  return (
    <AppShell>
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-bold font-mono">{job.job_id.slice(0, 8)}…</h1>
            <StatusBadge status={job.status} />
            <span className={`text-xs px-2 py-0.5 rounded border ${tierInfo.bg} ${tierInfo.color}`}>
              {tierInfo.label}
            </span>
          </div>
          {result?.filename && <p className="text-zinc-500 text-sm">{result.filename}</p>}
        </div>
        {job.processing_time_ms && (
          <p className="text-sm text-zinc-500">Processed in {formatMs(job.processing_time_ms)}</p>
        )}
      </div>

      {/* Pending / processing */}
      {(job.status === "pending" || job.status === "processing") && (
        <Card className="text-center py-16">
          <div className="flex flex-col items-center gap-4">
            <div className="w-10 h-10 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            <div>
              <p className="font-medium">{job.status === "pending" ? "Queued for processing…" : "Processing audio…"}</p>
              <p className="text-sm text-zinc-500 mt-1">This page updates automatically</p>
            </div>
          </div>
        </Card>
      )}

      {/* Failed */}
      {job.status === "failed" && (
        <Card className="border-red-500/20">
          <p className="text-red-400 font-medium">Analysis failed</p>
          {job.error_message && <p className="text-sm text-zinc-500 mt-2">{job.error_message}</p>}
        </Card>
      )}

      {/* Results */}
      {result && job.status === "completed" && (
        <div className="space-y-6">
          {/* Summary row */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Card>
              <p className="text-xs text-zinc-500 uppercase tracking-wide">Overall sentiment</p>
              <p className="text-xl font-bold capitalize mt-1" style={{ color: emotionColor(result.overall_sentiment) }}>
                {result.overall_sentiment}
              </p>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 uppercase tracking-wide">Duration</p>
              <p className="text-xl font-bold mt-1">{formatDuration(result.duration_seconds)}</p>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 uppercase tracking-wide">Emotion shifts</p>
              <p className="text-xl font-bold mt-1">{result.transitions?.length ?? 0}</p>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 uppercase tracking-wide">Transcript segments</p>
              <p className="text-xl font-bold mt-1">{result.transcript.length}</p>
            </Card>
          </div>

          {result.summary && (
            <Card>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-wide text-zinc-500">Local emotional arc</p>
                  <p className="mt-2 text-sm leading-relaxed text-zinc-300">{result.summary}</p>
                </div>
                <span className="shrink-0 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400">Offline · no external AI</span>
              </div>
            </Card>
          )}

          {/* Emotion timeline chart */}
          {result.timeline.length > 0 && (
            <Card>
              <h2 className="text-sm font-semibold mb-4">Emotion Intensity Timeline</h2>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={result.timeline} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                  <XAxis
                    dataKey="timestamp_start"
                    tickFormatter={(v) => `${v.toFixed(0)}s`}
                    tick={{ fontSize: 11, fill: "#71717a" }}
                  />
                  <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#71717a" }} />
                  <Tooltip
                    contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8 }}
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    formatter={(v: any, _name: any, p: any) => [
                      `${((Number(v) || 0) * 100).toFixed(0)}% — ${(p?.payload as EmotionShift)?.emotion ?? ""}`,
                      "Intensity",
                    ]}
                    labelFormatter={(v) => `${v}s`}
                  />
                  <Bar dataKey="intensity" radius={[3, 3, 0, 0]}>
                    {result.timeline.map((entry, i) => (
                      <Cell key={i} fill={emotionColor(entry.emotion)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {result.timeline.some((entry) => entry.modalities) && (
            <Card padding={false}>
              <div className="border-b border-zinc-800 px-6 py-4">
                <h2 className="text-sm font-semibold">Multimodal evidence</h2>
                <p className="mt-1 text-xs text-zinc-500">Audio 55% + text 45%, with topic and acoustic provenance</p>
              </div>
              <div className="max-h-80 divide-y divide-zinc-800/60 overflow-y-auto">
                {result.timeline.map((entry, index) => (
                  <div key={index} className="grid gap-3 px-6 py-4 text-xs md:grid-cols-[4rem_0.8fr_1fr_1.2fr_1.4fr]">
                    <span className="font-mono text-zinc-500">{entry.timestamp_start.toFixed(1)}s</span>
                    <div><span className="text-zinc-500">Fused</span><p className="mt-1 font-semibold capitalize" style={{ color: emotionColor(entry.emotion) }}>{entry.emotion} {Math.round(entry.intensity * 100)}%</p></div>
                    <div><span className="text-zinc-500">Voice / text</span><p className="mt-1 capitalize text-zinc-300">{entry.modalities?.audio.emotion} {Math.round((entry.modalities?.audio.confidence ?? 0) * 100)}% / {entry.modalities?.text.emotion} {Math.round((entry.modalities?.text.confidence ?? 0) * 100)}%</p><p className={entry.modalities?.audio.emotion === entry.modalities?.text.emotion ? "mt-1 text-emerald-400" : "mt-1 text-amber-400"}>{entry.modalities?.audio.emotion === entry.modalities?.text.emotion ? "modalities agree" : "modalities disagree"}</p></div>
                    <div><span className="text-zinc-500">Acoustic</span><p className="mt-1 text-zinc-300">Pitch {entry.acoustic?.pitch_hz?.toFixed(0) ?? "—"} Hz · {entry.acoustic?.rms_db?.toFixed(1) ?? "—"} dB</p><p className="mt-1 text-zinc-500">{entry.acoustic?.speech_rate_wps?.toFixed(1) ?? "—"} words/s</p></div>
                    <div><span className="text-zinc-500">Topic / evidence</span><p className="mt-1 text-zinc-300">{entry.topic?.label ?? "—"}{entry.topic?.is_shift ? " · shift" : ""}</p>{entry.trigger_phrase && <p className="mt-2 italic text-cyan-300">“{entry.trigger_phrase}”</p>}{entry.cause && <p className="mt-2 leading-relaxed text-violet-300">{entry.cause} <span className="text-zinc-600">({entry.cause_source})</span></p>}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}


          {result.stage_timings && Object.keys(result.stage_timings).length > 0 && (
            <Card>
              <h2 className="mb-3 text-sm font-semibold">Per-stage latency</h2>
              <div className="grid gap-2 text-xs text-zinc-400 sm:grid-cols-3">
                {Object.entries(result.stage_timings).map(([key, value]) => <p key={key}><span className="text-zinc-600">{key.replaceAll("_", " ")}:</span> {formatMs(value)}</p>)}
              </div>
            </Card>
          )}

          {result.transitions && result.transitions.length > 0 && (
            <Card padding={false}>
              <div className="border-b border-zinc-800 px-6 py-4">
                <h2 className="text-sm font-semibold">Conversation turning points</h2>
                <p className="mt-1 text-xs text-zinc-500">Chronological, evidence-grounded shifts—not proof of causation.</p>
              </div>
              <div className="max-h-[42rem] divide-y divide-zinc-800/60 overflow-y-auto">
                {result.transitions.map((transition, index) => {
                  const current = result.timeline[transition.to_segment];
                  if (!current) return null;
                  const audio = current.modalities?.audio;
                  const text = current.modalities?.text;
                  const acoustic = current.acoustic;
                  const agreement = audio?.emotion && audio.emotion === text?.emotion;
                  const delta = (value: number | null | undefined, suffix: string) => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(1)}${suffix}`;
                  return (
                    <div key={`${transition.from_segment}-${transition.to_segment}-${index}`} className="px-6 py-5">
                      <div className="flex flex-wrap items-center gap-2">
                        <button type="button" onClick={() => seekTo(current.timestamp_start)} className="font-mono text-xs text-violet-400 hover:text-violet-300">{current.timestamp_start.toFixed(1)}s</button>
                        <span className="rounded-full px-2 py-1 text-xs font-semibold capitalize" style={{ color: emotionColor(transition.from_emotion), backgroundColor: `${emotionColor(transition.from_emotion)}18` }}>{transition.from_emotion}</span>
                        <span className="text-zinc-600">→</span>
                        <span className="rounded-full px-2 py-1 text-xs font-semibold capitalize" style={{ color: emotionColor(transition.to_emotion), backgroundColor: `${emotionColor(transition.to_emotion)}18` }}>{transition.to_emotion}</span>
                        <span className="rounded-full border border-zinc-700 px-2 py-1 text-[10px] uppercase tracking-wide text-zinc-400">{transition.driver ?? "mixed"} evidence</span>
                      </div>
                      {current.trigger_phrase && <blockquote className="mt-3 border-l-2 border-cyan-500/60 pl-3 text-sm italic text-cyan-200">“{current.trigger_phrase}”</blockquote>}
                      <p className="mt-3 text-sm leading-relaxed text-zinc-300">{transition.explanation}</p>
                      <div className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
                        <div className="rounded-lg bg-zinc-950/70 p-3"><p className="text-zinc-600">Modalities</p><p className={agreement ? "mt-1 text-emerald-400" : "mt-1 text-amber-400"}>{agreement ? "Voice and text agree" : "Voice and text disagree"}</p><p className="mt-1 capitalize text-zinc-400">{audio?.emotion ?? "—"} / {text?.emotion ?? "—"}</p></div>
                        <div className="rounded-lg bg-zinc-950/70 p-3"><p className="text-zinc-600">Topic</p><p className="mt-1 text-zinc-300">{current.topic?.label ?? "No topic label"}</p><p className={current.topic?.is_shift ? "mt-1 text-cyan-400" : "mt-1 text-zinc-600"}>{current.topic?.is_shift ? "Topic changed" : "Topic continued"}</p></div>
                        <div className="rounded-lg bg-zinc-950/70 p-3"><p className="text-zinc-600">Voice movement</p><p className="mt-1 text-zinc-300">Energy {delta(acoustic?.energy_delta_db, " dB")}</p><p className="mt-1 text-zinc-500">Pitch {delta(acoustic?.pitch_delta_hz, " Hz")}</p></div>
                        <div className="rounded-lg bg-zinc-950/70 p-3"><p className="text-zinc-600">Pace</p><p className="mt-1 text-zinc-300">{delta(acoustic?.speech_rate_delta_wps, " words/s")}</p><p className="mt-1 text-zinc-500">Fused confidence {Math.round(current.intensity * 100)}%</p></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {/* Audio player */}
          {audioUrl && (
            <Card>
              <h2 className="text-sm font-semibold mb-3">Audio Playback</h2>
              <audio
                ref={audioRef}
                controls
                className="w-full"
                src={audioUrl}
              />
              <p className="text-xs text-zinc-600 mt-2">Click timestamps in the transcript to seek</p>
            </Card>
          )}

          {/* Transcript with clickable timestamps */}
          {result.transcript.length > 0 && (
            <Card padding={false}>
              <div className="px-6 py-4 border-b border-zinc-800">
                <h2 className="text-sm font-semibold">Transcript</h2>
              </div>
              <div className="divide-y divide-zinc-800/50 max-h-96 overflow-y-auto">
                {result.transcript.map((seg: TranscriptSegment, i: number) => {
                  // Find matching emotion for this segment
                  const match = result.timeline.find(
                    (t: EmotionShift) =>
                      Math.abs(t.timestamp_start - seg.start) < 0.5,
                  );
                  return (
                    <div key={i} className="px-6 py-3 flex gap-4 group hover:bg-zinc-800/40">
                      <button
                        type="button"
                        onClick={() => seekTo(seg.start)}
                        className="text-xs text-zinc-500 shrink-0 pt-0.5 font-mono w-16 text-left hover:text-violet-400 transition-colors"
                        title={`Seek to ${seg.start.toFixed(1)}s`}
                      >
                        {seg.start.toFixed(1)}s
                      </button>
                      {match && (
                        <span
                          className="inline-block w-2 h-2 rounded-full shrink-0 mt-1.5"
                          style={{ background: emotionColor(match.emotion) }}
                          title={`${match.emotion} (${(match.intensity * 100).toFixed(0)}%)`}
                        />
                      )}
                      <p className="text-sm text-zinc-300">{seg.text}</p>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}
        </div>
      )}
    </AppShell>
  );
}
