"use client";

import { useEffect, useState } from "react";
import { meet } from "@googleworkspace/meet-addons/meet.addons";
import type { MeetSidePanelClient } from "@googleworkspace/meet-addons/meet.addons";
import { LiveRecorder } from "@/components/LiveRecorder";
import { authApi, getAccessToken } from "@/lib/api";

const MEET_PROJECT_NUMBER = process.env.NEXT_PUBLIC_GOOGLE_MEET_PROJECT_NUMBER;

export function MeetSurface({ frame }: { frame: "side-panel" | "main-stage" }) {
  const [meetReady, setMeetReady] = useState(false);
  const [sidePanelClient, setSidePanelClient] = useState<MeetSidePanelClient | null>(null);
  const [meetError, setMeetError] = useState(MEET_PROJECT_NUMBER ? "" : "NEXT_PUBLIC_GOOGLE_MEET_PROJECT_NUMBER is not configured");
  const [token, setToken] = useState(() => getAccessToken() ?? "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";

  const signIn = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    try {
      const response = await authApi.login(email, password);
      setToken(response.access_token);
    } catch (error: unknown) {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setAuthError(message ?? "Invalid email or password");
    } finally {
      setAuthLoading(false);
    }
  };

  useEffect(() => {
    if (!MEET_PROJECT_NUMBER) return;
    void (async () => {
      const session = await meet.addon.createAddonSession({ cloudProjectNumber: MEET_PROJECT_NUMBER });
      if (frame === "side-panel") setSidePanelClient(await session.createSidePanelClient());
      else await session.createMainStageClient();
      setMeetReady(true);
    })().catch((error: unknown) => setMeetError(error instanceof Error ? error.message : "Meet initialization failed"));
  }, [frame]);

  return (
    <main className="min-h-screen bg-zinc-950 p-4 text-zinc-100">
      <div className="mx-auto max-w-3xl">
        <div className="mb-4 flex items-center justify-between border-b border-zinc-800 pb-3">
          <div>
            <p className="text-lg font-bold">EmotionFlow</p>
            <p className="text-xs text-zinc-500">Local multimodal meeting analysis</p>
          </div>
          <span className={`rounded-full px-2 py-1 text-[10px] ${meetReady ? "bg-emerald-500/10 text-emerald-400" : "bg-zinc-800 text-zinc-500"}`}>
            {meetReady ? "Meet connected" : "Initializing"}
          </span>
        </div>
        {!token ? (
          <form onSubmit={signIn} className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
            <p className="text-sm font-medium text-zinc-200">Sign in inside Meet</p>
            <p className="text-xs text-zinc-500">This securely stores the session in Meet&apos;s embedded app context.</p>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Email"
              autoComplete="username"
              required
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-violet-500"
            />
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              autoComplete="current-password"
              required
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-violet-500"
            />
            {authError && <p className="rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-xs text-red-400">{authError}</p>}
            <button type="submit" disabled={authLoading} className="w-full rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold disabled:opacity-60">
              {authLoading ? "Signing in…" : "Sign in"}
            </button>
          </form>
        ) : (
          <LiveRecorder token={token} apiBase={apiBase} compact={frame === "side-panel"} />
        )}
        {frame === "side-panel" && sidePanelClient && (
          <button
            type="button"
            onClick={() => void sidePanelClient.startActivity({ mainStageUrl: `${window.location.origin}/meet/main-stage` }).catch((error: unknown) => setMeetError(error instanceof Error ? error.message : "Could not open main stage"))}
            className="mt-3 w-full rounded-lg border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Open shared main stage
          </button>
        )}
        {meetError && <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-300">{meetError}. The page remains available for browser verification.</p>}
        <p className="mt-4 text-center text-[10px] leading-relaxed text-zinc-600">Only the consenting local participant&apos;s microphone is analyzed. EmotionFlow does not capture other meeting participants.</p>
      </div>
    </main>
  );
}
