"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { webhooksApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";
import { Plus, Trash2, Send, ChevronDown, ChevronUp } from "lucide-react";
import type { Webhook } from "@/lib/types";

const ALL_EVENTS = ["job.completed", "job.failed", "job.processing"];

export default function WebhooksPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [form, setForm] = useState({ url: "", name: "", events: ["job.completed", "job.failed"] });
  const [createdSecret, setCreatedSecret] = useState<{ id: number; secret: string } | null>(null);
  const [testResult, setTestResult] = useState<{ id: number; success: boolean; status_code: number | null; error: string | null } | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: webhooks = [], isLoading } = useQuery({
    queryKey: ["webhooks"],
    queryFn: webhooksApi.list,
  });

  const createMutation = useMutation({
    mutationFn: () => webhooksApi.create({ url: form.url, name: form.name, events: form.events }),
    onSuccess: (data) => {
      if (data.secret) setCreatedSecret({ id: data.id, secret: data.secret });
      setShowCreate(false);
      setCreateError(null);
      setForm({ url: "", name: "", events: ["job.completed", "job.failed"] });
      qc.invalidateQueries({ queryKey: ["webhooks"] });
    },
    onError: (err: unknown) => {
      const axiosDetail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setCreateError(axiosDetail ?? "Failed to register webhook");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => webhooksApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });

  const testMutation = useMutation({
    mutationFn: (id: number) => webhooksApi.test(id),
    onSuccess: (data, id) => setTestResult({ id, error: null, ...data }),
    onError: (_err, id) => setTestResult({ id, success: false, status_code: null, error: "Request failed" }),
  });

  const toggleEvent = (event: string) => {
    setForm((f) => ({
      ...f,
      events: f.events.includes(event) ? f.events.filter((e) => e !== event) : [...f.events, event],
    }));
  };

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Webhooks</h1>
          <p className="text-zinc-500 text-sm mt-1">Get notified when jobs complete via HTTPS POST</p>
        </div>
        <Button onClick={() => setShowCreate(!showCreate)} size="sm">
          <Plus className="w-3.5 h-3.5" />
          Add webhook
        </Button>
      </div>

      {/* Secret reveal */}
      {createdSecret && (
        <Card className="mb-6 border-emerald-500/20 bg-emerald-500/5">
          <p className="text-sm font-medium text-emerald-400 mb-2">
            Webhook secret — copy now, won&apos;t be shown again
          </p>
          <code className="text-xs font-mono bg-zinc-900 border border-zinc-700 px-3 py-2 rounded-lg block break-all">
            {createdSecret.secret}
          </code>
          <p className="text-xs text-zinc-500 mt-2">
            Verify requests using HMAC-SHA256: <code className="text-violet-400">X-EmotionFlow-Signature: sha256=&lt;hex&gt;</code>
          </p>
          <Button variant="ghost" size="sm" className="mt-2" onClick={() => setCreatedSecret(null)}>Dismiss</Button>
        </Card>
      )}

      {/* Create form */}
      {showCreate && (
        <Card className="mb-6">
          <h2 className="text-sm font-semibold mb-4">New webhook</h2>
          <div className="space-y-4">
            <Input label="Endpoint URL" placeholder="https://your-server.com/hooks/emotionflow" value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} />
            <Input label="Name (optional)" placeholder="Production webhook" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            <div>
              <p className="text-sm font-medium text-zinc-300 mb-2">Events</p>
              <div className="flex gap-2">
                {ALL_EVENTS.map((e) => (
                  <button
                    key={e}
                    onClick={() => toggleEvent(e)}
                    className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                      form.events.includes(e)
                        ? "bg-violet-600/20 border-violet-500/40 text-violet-300"
                        : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                    }`}
                  >
                    {e}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => createMutation.mutate()} loading={createMutation.isPending} disabled={!form.url}>
                {createMutation.isPending ? "Validating endpoint…" : "Create webhook"}
              </Button>
              <Button variant="ghost" onClick={() => { setShowCreate(false); setCreateError(null); }}>Cancel</Button>
            </div>
            {createError && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{createError}</p>
            )}
          </div>
        </Card>
      )}

      {/* List */}
      {isLoading ? (
        <div className="flex justify-center py-10">
          <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : webhooks.length === 0 ? (
        <Card className="text-center py-12 text-zinc-500 text-sm">No webhooks configured</Card>
      ) : (
        <div className="space-y-3">
          {webhooks.map((wh: Webhook) => (
            <Card key={wh.id} padding={false}>
              <div
                className="px-6 py-4 flex items-center gap-4 cursor-pointer"
                onClick={() => setExpanded(expanded === wh.id ? null : wh.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <p className="font-medium text-sm">{wh.name}</p>
                    <StatusBadge status={wh.is_active ? "active" : "inactive"} />
                  </div>
                  <p className="text-xs text-zinc-500 mt-0.5 truncate">{wh.url}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={(e) => { e.stopPropagation(); setTestResult(null); testMutation.mutate(wh.id); }}
                    loading={testMutation.isPending && testMutation.variables === wh.id}
                  >
                    <Send className="w-3 h-3" />
                    Test
                  </Button>
                  {testResult?.id === wh.id && (
                    <span className={`text-xs px-2 py-1 rounded-md font-medium ${testResult.success ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"}`}>
                      {testResult.success ? `✓ ${testResult.status_code}` : testResult.error ?? `✗ ${testResult.status_code ?? "error"}`}
                    </span>
                  )}
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm("Delete this webhook?")) deleteMutation.mutate(wh.id);
                    }}
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                  {expanded === wh.id ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
                </div>
              </div>
              {expanded === wh.id && (
                <div className="border-t border-zinc-800 px-6 py-4">
                  <div className="flex gap-2 flex-wrap mb-3">
                    {wh.events.split(",").map((e) => (
                      <span key={e} className="text-xs bg-violet-600/10 text-violet-400 border border-violet-600/20 px-2 py-0.5 rounded">{e.trim()}</span>
                    ))}
                  </div>
                  <p className="text-xs text-zinc-500">Created {formatDateTime(wh.created_at)} · Updated {formatDateTime(wh.updated_at)}</p>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}
