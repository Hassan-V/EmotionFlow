"use client";

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";
import { Code2, Key, Webhook, Zap, FileAudio, ChevronRight } from "lucide-react";

// ─── Section data ─────────────────────────────────────────────────────────────

const SECTIONS = [
  { id: "overview",    label: "Overview",       icon: Zap },
  { id: "auth",        label: "Authentication", icon: Key },
  { id: "analysis",   label: "Analysis API",   icon: FileAudio },
  { id: "webhooks",   label: "Webhooks",        icon: Webhook },
  { id: "errors",     label: "Error Codes",     icon: Code2 },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

// ─── Code block helper ────────────────────────────────────────────────────────

function CodeBlock({ code, lang = "bash" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="relative group mt-3 mb-4">
      <pre className="bg-zinc-950 border border-zinc-800 rounded-xl px-5 py-4 text-xs text-zinc-300 font-mono leading-relaxed overflow-x-auto">
        <code>{code.trim()}</code>
      </pre>
      <button
        onClick={copy}
        className="absolute top-2.5 right-2.5 text-xs text-zinc-500 hover:text-zinc-200 transition-colors px-2 py-0.5 rounded border border-zinc-700 opacity-0 group-hover:opacity-100"
      >
        {copied ? "Copied!" : "Copy"}
      </button>
      {lang && (
        <span className="absolute bottom-2.5 right-2.5 text-[10px] text-zinc-600 font-mono select-none">
          {lang}
        </span>
      )}
    </div>
  );
}

function Badge({ children, color = "violet" }: { children: React.ReactNode; color?: "violet" | "emerald" | "amber" | "red" | "blue" }) {
  const colors = {
    violet: "bg-violet-600/15 text-violet-300 border-violet-500/25",
    emerald: "bg-emerald-600/15 text-emerald-300 border-emerald-500/25",
    amber:   "bg-amber-500/15 text-amber-300 border-amber-500/25",
    red:     "bg-red-500/15 text-red-300 border-red-500/25",
    blue:    "bg-blue-500/15 text-blue-300 border-blue-500/25",
  };
  return (
    <span className={cn("inline-block text-xs font-mono px-2 py-0.5 rounded border font-semibold", colors[color])}>
      {children}
    </span>
  );
}

function Method({ m }: { m: string }) {
  const colors: Record<string, string> = {
    GET: "text-emerald-400", POST: "text-blue-400", PATCH: "text-amber-400",
    DELETE: "text-red-400", PUT: "text-orange-400",
  };
  return <span className={cn("font-mono font-bold text-sm mr-2", colors[m] ?? "text-zinc-300")}>{m}</span>;
}

function Endpoint({ method, path, desc }: { method: string; path: string; desc?: string }) {
  return (
    <div className="flex items-start gap-2 py-2 border-b border-zinc-800/60 last:border-0">
      <Method m={method} />
      <div>
        <code className="text-sm text-zinc-200 font-mono">{path}</code>
        {desc && <p className="text-xs text-zinc-500 mt-0.5">{desc}</p>}
      </div>
    </div>
  );
}

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="text-xl font-bold text-white mb-4 pt-2 flex items-center gap-2">
      <ChevronRight className="w-5 h-5 text-violet-400" />
      {children}
    </h2>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-zinc-200 mt-6 mb-2">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-zinc-400 leading-relaxed">{children}</p>;
}

// ─── Section: Overview ────────────────────────────────────────────────────────

function OverviewSection() {
  return (
    <section id="overview" className="mb-12">
      <SectionHeading id="overview">Overview</SectionHeading>
      <P>
        EmotionFlow exposes a REST API and a WebSocket streaming API. All HTTP endpoints use
        JSON bodies and return JSON responses. Authentication uses either a short-lived JWT
        Bearer token or a long-lived API key.
      </P>

      <SubHeading>Base URL</SubHeading>
      <CodeBlock lang="text" code={`https://dev.emotionflow.site/api\n\n# or locally:\nhttp://localhost:8000`} />

      <SubHeading>Rate Limits</SubHeading>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-sm border border-zinc-800 rounded-xl overflow-hidden">
          <thead>
            <tr className="bg-zinc-900 text-zinc-400 text-xs">
              <th className="text-left px-4 py-2">Scope</th>
              <th className="text-left px-4 py-2">Limit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 text-zinc-300">
            <tr><td className="px-4 py-2">Default accounts</td><td className="px-4 py-2">100 jobs / day</td></tr>
            <tr><td className="px-4 py-2">Test accounts</td><td className="px-4 py-2">5 jobs / day · fast tier only</td></tr>
            <tr><td className="px-4 py-2">File size</td><td className="px-4 py-2">50 MB per upload</td></tr>
            <tr><td className="px-4 py-2">Webhooks per user</td><td className="px-4 py-2">10</td></tr>
            <tr><td className="px-4 py-2">API keys per user</td><td className="px-4 py-2">10</td></tr>
          </tbody>
        </table>
      </div>

      <SubHeading>Compute Units</SubHeading>
      <P>
        Analysis jobs consume compute units rather than dollars. Units are deducted from your
        account quota on successful completion; failed jobs cost 0 CU.
      </P>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-sm border border-zinc-800 rounded-xl overflow-hidden">
          <thead>
            <tr className="bg-zinc-900 text-zinc-400 text-xs">
              <th className="text-left px-4 py-2">Tier</th>
              <th className="text-left px-4 py-2">CU / job</th>
              <th className="text-left px-4 py-2">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 text-zinc-300">
            <tr><td className="px-4 py-2"><Badge color="emerald">fast</Badge></td><td className="px-4 py-2">1 CU</td><td className="px-4 py-2">Fastest turnaround — basic emotion detection</td></tr>
            <tr><td className="px-4 py-2"><Badge color="violet">balanced</Badge></td><td className="px-4 py-2">5 CU</td><td className="px-4 py-2">Full emotion analysis with transcript — recommended</td></tr>
            <tr><td className="px-4 py-2"><Badge color="amber">max</Badge></td><td className="px-4 py-2">20 CU</td><td className="px-4 py-2">Full analysis + AI causality — deepest insight</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─── Section: Authentication ──────────────────────────────────────────────────

function AuthSection() {
  return (
    <section id="auth" className="mb-12">
      <SectionHeading id="auth">Authentication</SectionHeading>

      <P>
        Every protected endpoint accepts one of two auth schemes. They may be used
        interchangeably on the same endpoint.
      </P>

      <SubHeading>1 — JWT Bearer (user sessions)</SubHeading>
      <P>
        Obtain a short-lived access token (30 min) by posting credentials to{" "}
        <code className="text-violet-400 text-xs font-mono">/auth/login</code>. Refresh it
        using the 7-day refresh token.
      </P>
      <CodeBlock lang="bash" code={`# Login
curl -X POST https://dev.emotionflow.site/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email": "you@example.com", "password": "YourPassword1"}'

# Response
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}

# Use it
curl https://dev.emotionflow.site/auth/me \\
  -H "Authorization: Bearer eyJ..."`} />

      <SubHeading>2 — API Key (server-to-server)</SubHeading>
      <P>
        Create a key from the API Keys page. Keys start with{" "}
        <code className="text-violet-400 text-xs font-mono">ef_</code> and are shown once only
        — store them securely.
      </P>
      <CodeBlock lang="bash" code={`curl -X POST https://dev.emotionflow.site/analysis/analyze-file \\
  -H "X-API-Key: ef_YourKeyHere" \\
  -F "file=@interview.mp3" \\
  -F "model_tier=balanced"`} />

      <SubHeading>Key endpoints</SubHeading>
      <div className="rounded-xl border border-zinc-800 overflow-hidden px-4 py-1 bg-zinc-900/40">
        <Endpoint method="POST" path="/auth/register" desc="Create a new account" />
        <Endpoint method="POST" path="/auth/login" desc="Get JWT tokens" />
        <Endpoint method="POST" path="/auth/refresh" desc="Refresh access token" />
        <Endpoint method="GET"  path="/auth/me" desc="Get current user profile" />
        <Endpoint method="PATCH" path="/auth/me" desc="Update profile (email, full_name)" />
        <Endpoint method="POST" path="/api-keys/" desc="Create an API key (raw key shown once)" />
        <Endpoint method="GET"  path="/api-keys/" desc="List all API keys" />
        <Endpoint method="DELETE" path="/api-keys/{key_id}" desc="Revoke a key" />
      </div>
    </section>
  );
}

// ─── Section: Analysis API ────────────────────────────────────────────────────

function AnalysisSection() {
  return (
    <section id="analysis" className="mb-12">
      <SectionHeading id="analysis">Analysis API</SectionHeading>

      <P>
        Analysis is asynchronous. You submit a file, receive a <code className="text-violet-400 text-xs font-mono">job_id</code>,
        then poll or use webhooks to get the result.
      </P>

      <SubHeading>Submit a job</SubHeading>
      <CodeBlock lang="bash" code={`curl -X POST https://dev.emotionflow.site/analysis/analyze-file \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@meeting.wav" \\
  -F "model_tier=balanced"

# 202 Accepted
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Analysis queued with 'balanced' tier."
}`} />

      <SubHeading>Stream an HTTP request body</SubHeading>
      <P>
        Clients that cannot use multipart forms may stream WAV or MP3 bytes with
        chunked HTTP transfer. The response uses the same job and JSON result contract.
      </P>
      <CodeBlock lang="bash" code={`curl -X POST "https://dev.emotionflow.site/analysis/analyze-stream?filename=meeting.wav&model_tier=fast" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: audio/wav" \\
  --data-binary @meeting.wav`} />

      <SubHeading>Poll for result</SubHeading>
      <CodeBlock lang="bash" code={`curl https://dev.emotionflow.site/analysis/jobs/550e8400-... \\
  -H "Authorization: Bearer $TOKEN"

# When complete:
{
  "job_id": "550e8400-...",
  "status": "completed",
  "model_tier": "balanced",
  "processing_time_ms": 17344,
  "result": {
    "filename": "meeting.wav",
    "duration_seconds": 45.2,
    "overall_sentiment": "positive",
    "timeline": [
      {
        "timestamp_start": 0.0,
        "timestamp_end": 5.2,
        "emotion": "neutral",
        "intensity": 0.72,
        "trigger_phrase": null,
        "cause": null
      },
      {
        "timestamp_start": 5.2,
        "timestamp_end": 11.8,
        "emotion": "joy",
        "intensity": 0.85,
        "trigger_phrase": "great news",
        "cause": "Positive announcement in the conversation"
      }
    ],
    "causality_summary": "Speaker showed increasing engagement..."
  }
}`} />

      <SubHeading>Job statuses</SubHeading>
      <div className="flex flex-wrap gap-2 mt-1 mb-4">
        <Badge color="amber">pending</Badge>
        <Badge color="blue">processing</Badge>
        <Badge color="emerald">completed</Badge>
        <Badge color="red">failed</Badge>
      </div>

      <SubHeading>Live WebSocket streaming</SubHeading>
      <P>
        For real-time audio, connect via WebSocket and stream chunks. The server returns
        partial transcript and emotion events as they are processed.
      </P>
      <CodeBlock lang="javascript" code={`const ws = new WebSocket(
  \`wss://emotionflow.site/ws/stream?token=\${accessToken}\`
);

ws.onopen = () => {
  // 1. Send config first
  ws.send(JSON.stringify({
    type: "config", tier: "fast", session_id: crypto.randomUUID(),
    encoding: "pcm_s16le", sample_rate: 16000, chunk_ms: 250
  }));

  // 2. Send each 250 ms AudioWorklet PCM16 ArrayBuffer as binary
  ws.send(pcm16ArrayBuffer);

  // 3. Signal end of stream
  ws.send(JSON.stringify({ type: "end_stream" }));
};

ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  // connected | status | transcript | emotion | causality | final_result | error
};`} />

      <SubHeading>Endpoints</SubHeading>
      <div className="rounded-xl border border-zinc-800 overflow-hidden px-4 py-1 bg-zinc-900/40">
        <Endpoint method="POST" path="/analysis/analyze-file" desc="Submit audio file for async analysis" />
        <Endpoint method="POST" path="/analysis/analyze-stream" desc="Stream a raw WAV/MP3 HTTP body for async analysis" />
        <Endpoint method="GET"  path="/analysis/jobs/{job_id}" desc="Get job status and result" />
        <Endpoint method="GET"  path="/analysis/jobs" desc="List all jobs for the current user" />
        <Endpoint method="WS"   path="/ws/stream?token=..." desc="Binary PCM16 live streaming" />
      </div>
    </section>
  );
}

// ─── Section: Webhooks ────────────────────────────────────────────────────────

function WebhooksSection() {
  return (
    <section id="webhooks" className="mb-12">
      <SectionHeading id="webhooks">Webhooks</SectionHeading>

      <P>
        Register an HTTPS endpoint and EmotionFlow will POST a signed JSON payload when a
        job completes or fails — no polling required.
      </P>

      <SubHeading>Register a webhook</SubHeading>
      <CodeBlock lang="bash" code={`curl -X POST https://dev.emotionflow.site/webhooks/ \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://your-server.com/hooks/emotionflow",
    "name": "Production",
    "events": ["job.completed", "job.failed"]
  }'

# 201 Created — secret shown ONCE, store it securely
{
  "id": 1,
  "url": "https://your-server.com/hooks/emotionflow",
  "secret": "a1b2c3d4...64hex",
  "events": ["job.completed", "job.failed"],
  "is_active": true
}`} />

      <SubHeading>Payload format</SubHeading>
      <CodeBlock lang="json" code={`{
  "event": "job.completed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-04-08T10:30:00Z",
  "data": {
    "status": "completed",
    "model_tier": "balanced",
    "processing_time_ms": 17344
  }
}`} />

      <SubHeading>Verify the signature</SubHeading>
      <P>
        Every delivery includes{" "}
        <code className="text-violet-400 text-xs font-mono">X-EmotionFlow-Signature</code> — an
        HMAC-SHA256 hex digest of the raw request body. Always verify it before processing the
        payload.
      </P>
      <CodeBlock lang="python" code={`import hmac, hashlib
from flask import request, abort

WEBHOOK_SECRET = "your-secret-from-registration"

@app.post("/hooks/emotionflow")
def receive():
    sig = request.headers.get("X-EmotionFlow-Signature", "")
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        request.data,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        abort(400, "Invalid signature")  # reject forged requests
    payload = request.json
    # handle job...
    return "", 200`} />

      <SubHeading>Retry policy</SubHeading>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-sm border border-zinc-800 rounded-xl overflow-hidden">
          <thead>
            <tr className="bg-zinc-900 text-zinc-400 text-xs">
              <th className="text-left px-4 py-2">Attempt</th>
              <th className="text-left px-4 py-2">Delay</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 text-zinc-300">
            <tr><td className="px-4 py-2">1</td><td className="px-4 py-2">immediate</td></tr>
            <tr><td className="px-4 py-2">2</td><td className="px-4 py-2">30 s</td></tr>
            <tr><td className="px-4 py-2">3</td><td className="px-4 py-2">60 s</td></tr>
            <tr><td className="px-4 py-2">4</td><td className="px-4 py-2">120 s</td></tr>
            <tr><td className="px-4 py-2">5</td><td className="px-4 py-2">300 s</td></tr>
            <tr><td className="px-4 py-2">6+</td><td className="px-4 py-2 text-red-400">give up — marked failed</td></tr>
          </tbody>
        </table>
      </div>
      <p className="text-xs text-zinc-500 mt-2">
        A delivery succeeds when your endpoint returns any <code className="text-emerald-400">2xx</code> status
        within 10 seconds. View delivery history at{" "}
        <code className="text-violet-400 text-xs font-mono">GET /webhooks/{"{id}"}/deliveries</code>.
      </p>

      <SubHeading>Endpoints</SubHeading>
      <div className="rounded-xl border border-zinc-800 overflow-hidden px-4 py-1 bg-zinc-900/40">
        <Endpoint method="POST"   path="/webhooks/" desc="Register a new webhook" />
        <Endpoint method="GET"    path="/webhooks/" desc="List all webhooks" />
        <Endpoint method="PATCH"  path="/webhooks/{id}" desc="Update URL, events, or active status" />
        <Endpoint method="DELETE" path="/webhooks/{id}" desc="Delete webhook and all delivery logs" />
        <Endpoint method="POST"   path="/webhooks/{id}/test" desc="Send a test delivery immediately" />
        <Endpoint method="GET"    path="/webhooks/{id}/deliveries" desc="List delivery history (limit, status_filter)" />
      </div>
    </section>
  );
}

// ─── Section: Errors ─────────────────────────────────────────────────────────

function ErrorsSection() {
  return (
    <section id="errors" className="mb-12">
      <SectionHeading id="errors">Error Codes</SectionHeading>

      <P>
        All errors follow the same JSON envelope:{" "}
        <code className="text-violet-400 text-xs font-mono">{"{ \"detail\": \"Human-readable message\" }"}</code>
      </P>

      <div className="overflow-x-auto mt-4">
        <table className="w-full text-sm border border-zinc-800 rounded-xl overflow-hidden">
          <thead>
            <tr className="bg-zinc-900 text-zinc-400 text-xs">
              <th className="text-left px-4 py-2">Code</th>
              <th className="text-left px-4 py-2">Meaning</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 text-zinc-300">
            <tr><td className="px-4 py-2"><Badge color="emerald">200 / 201 / 202</Badge></td><td className="px-4 py-2">Success / Created / Accepted (async job queued)</td></tr>
            <tr><td className="px-4 py-2"><Badge color="amber">400</Badge></td><td className="px-4 py-2">Bad request — invalid body or parameters</td></tr>
            <tr><td className="px-4 py-2"><Badge color="amber">401</Badge></td><td className="px-4 py-2">Missing or expired credential</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">403</Badge></td><td className="px-4 py-2">Forbidden — e.g. test account tier restriction</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">404</Badge></td><td className="px-4 py-2">Resource not found or belongs to another user</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">409</Badge></td><td className="px-4 py-2">Conflict — e.g. email/username already taken</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">413</Badge></td><td className="px-4 py-2">File too large (max 50 MB)</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">415</Badge></td><td className="px-4 py-2">Unsupported file type</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">422</Badge></td><td className="px-4 py-2">Validation error — field-level details in <code className="font-mono">detail</code> array</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">429</Badge></td><td className="px-4 py-2">Daily quota / rate limit exceeded</td></tr>
            <tr><td className="px-4 py-2"><Badge color="red">500</Badge></td><td className="px-4 py-2">Internal server error</td></tr>
          </tbody>
        </table>
      </div>

      <SubHeading>Interactive docs</SubHeading>
      <P>
        The FastAPI auto-generated interactive documentation is available at{" "}
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/docs`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-violet-400 hover:underline font-mono text-xs"
        >
          /docs
        </a>{" "}
        (Swagger UI) and{" "}
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/redoc`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-violet-400 hover:underline font-mono text-xs"
        >
          /redoc
        </a>{" "}
        (ReDoc). You can try every endpoint there using your Bearer token.
      </P>
    </section>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DeveloperPage() {
  const [active, setActive] = useState<SectionId>("overview");

  const scrollTo = (id: SectionId) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Developer Docs</h1>
        <p className="text-zinc-500 text-sm mt-1">API reference, webhook integration, and code examples</p>
      </div>

      <div className="flex gap-6 items-start">
        {/* Sidebar nav */}
        <nav className="hidden lg:block w-44 shrink-0 sticky top-6">
          <ul className="space-y-1">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  onClick={() => scrollTo(id)}
                  className={cn(
                    "w-full text-left text-sm flex items-center gap-2 px-3 py-2 rounded-lg transition-colors",
                    active === id
                      ? "bg-violet-600/15 text-violet-300 font-medium"
                      : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
                  )}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Content */}
        <Card className="flex-1 max-w-3xl">
          <OverviewSection />
          <AuthSection />
          <AnalysisSection />
          <WebhooksSection />
          <ErrorsSection />
        </Card>
      </div>
    </AppShell>
  );
}
