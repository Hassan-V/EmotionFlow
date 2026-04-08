"use client";

import { useState, useRef, useCallback } from "react";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LiveRecorder } from "@/components/LiveRecorder";
import { analysisApi, getAccessToken } from "@/lib/api";
import { TIER_INFO } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { Upload, Music, CheckCircle2, Mic } from "lucide-react";
import { useRouter } from "next/navigation";
import type { ModelTier } from "@/lib/types";

const ALLOWED = [".mp3", ".wav", ".m4a", ".flac"];
type Tab = "file" | "live";

export default function AnalyzePage() {
  const [tab, setTab] = useState<Tab>("file");
  const [file, setFile] = useState<File | null>(null);
  const [tier, setTier] = useState<ModelTier>("balanced");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";

  const handleFile = (f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED.includes(`.${ext}`)) {
      setError(`Unsupported format. Allowed: ${ALLOWED.join(", ")}`);
      return;
    }
    if (f.size > 50 * 1024 * 1024) {
      setError("File too large. Maximum size is 50MB.");
      return;
    }
    setError("");
    setFile(f);
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, []);

  const handleSubmit = async () => {
    if (!file) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await analysisApi.submit(file, tier);
      router.push(`/jobs/${res.job_id}`);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to submit job");
      setSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">New Analysis</h1>
        <p className="text-zinc-500 text-sm mt-1">Upload a file or record live audio to analyze emotion patterns</p>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-xl p-1 mb-6 max-w-xs">
        <button
          onClick={() => setTab("file")}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 text-sm font-medium py-2 rounded-lg transition-colors",
            tab === "file" ? "bg-zinc-700 text-white" : "text-zinc-500 hover:text-zinc-300"
          )}
        >
          <Upload className="w-3.5 h-3.5" />
          File Upload
        </button>
        <button
          onClick={() => setTab("live")}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 text-sm font-medium py-2 rounded-lg transition-colors",
            tab === "live" ? "bg-violet-600 text-white" : "text-zinc-500 hover:text-zinc-300"
          )}
        >
          <Mic className="w-3.5 h-3.5" />
          Live Record
        </button>
      </div>

      <div className="max-w-2xl space-y-6">
        {tab === "live" ? (
          <LiveRecorder token={getAccessToken() ?? ""} apiBase={apiBase} />
        ) : (
          <>
          {/* Drop zone */}
          <Card>
          <div
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onClick={() => fileRef.current?.click()}
            className={cn(
              "border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors",
              dragging ? "border-violet-500 bg-violet-500/5" : "border-zinc-700 hover:border-zinc-500 hover:bg-zinc-800/30",
              file && "border-emerald-500/40 bg-emerald-500/5"
            )}
          >
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".mp3,.wav,.m4a,.flac"
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
            {file ? (
              <div className="flex flex-col items-center gap-3">
                <CheckCircle2 className="w-10 h-10 text-emerald-400" />
                <div>
                  <p className="font-medium text-emerald-400">{file.name}</p>
                  <p className="text-sm text-zinc-500 mt-1">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
                <p className="text-xs text-zinc-500">Click to change file</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <Upload className="w-10 h-10 text-zinc-600" />
                <div>
                  <p className="text-zinc-300 font-medium">Drop audio file here</p>
                  <p className="text-sm text-zinc-500 mt-1">or click to browse</p>
                </div>
                <div className="flex items-center gap-2 mt-2">
                  {ALLOWED.map((ext) => (
                    <span key={ext} className="flex items-center gap-1 text-xs text-zinc-600 bg-zinc-800 px-2 py-1 rounded">
                      <Music className="w-3 h-3" />
                      {ext}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-zinc-600 mt-1">Max 50 MB</p>
              </div>
            )}
          </div>
          </Card>

          {/* Tier selector */}
          <Card>
            <h2 className="text-sm font-semibold mb-4">Analysis tier</h2>
            <div className="grid grid-cols-3 gap-3">
              {(Object.keys(TIER_INFO) as ModelTier[]).map((t) => {
                const info = TIER_INFO[t];
                return (
                  <button
                    key={t}
                    onClick={() => setTier(t)}
                    className={cn(
                      "border rounded-xl p-4 text-left transition-all",
                      tier === t
                        ? `${info.bg} border-current`
                        : "border-zinc-700 hover:border-zinc-600 hover:bg-zinc-800/30"
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

          {error && (
            <p className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">{error}</p>
          )}

          <Button
            onClick={handleSubmit}
            loading={submitting}
            disabled={!file}
            size="lg"
            className="w-full"
          >
            <Upload className="w-4 h-4" />
            Submit for analysis
          </Button>
          </>
        )}
      </div>
    </AppShell>
  );
}
