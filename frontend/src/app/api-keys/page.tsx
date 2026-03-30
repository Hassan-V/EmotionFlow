"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiKeysApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";
import { Copy, Plus, Trash2, CheckCheck } from "lucide-react";
import type { ApiKeyCreated } from "@/lib/types";

export default function ApiKeysPage() {
  const qc = useQueryClient();
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: keys = [], isLoading } = useQuery({
    queryKey: ["api-keys"],
    queryFn: apiKeysApi.list,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => apiKeysApi.create(name),
    onSuccess: (data) => {
      setCreated(data);
      setNewName("");
      setShowCreate(false);
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiKeysApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  const copyKey = async (key: string) => {
    await navigator.clipboard.writeText(key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="text-zinc-500 text-sm mt-1">Manage keys for programmatic access</p>
        </div>
        <Button onClick={() => setShowCreate(!showCreate)} size="sm">
          <Plus className="w-3.5 h-3.5" />
          New key
        </Button>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card className="mb-6">
          <CardHeader title="Create API key" />
          <div className="flex gap-3 items-end">
            <Input
              label="Key name"
              placeholder="e.g. Discord Bot, Production"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="flex-1"
            />
            <Button
              onClick={() => createMutation.mutate(newName || "Default Key")}
              loading={createMutation.isPending}
            >
              Create
            </Button>
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
          </div>
        </Card>
      )}

      {/* Newly created key — show raw key once */}
      {created && (
        <Card className="mb-6 border-emerald-500/20 bg-emerald-500/5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-emerald-400 mb-2">
                Key created — copy it now, it won&apos;t be shown again
              </p>
              <code className="text-xs font-mono bg-zinc-900 border border-zinc-700 px-3 py-2 rounded-lg block break-all">
                {created.raw_key}
              </code>
            </div>
            <Button variant="secondary" size="sm" onClick={() => copyKey(created.raw_key)} className="shrink-0">
              {copied ? <CheckCheck className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <Button variant="ghost" size="sm" className="mt-3" onClick={() => setCreated(null)}>
            Dismiss
          </Button>
        </Card>
      )}

      {/* Keys list */}
      <Card padding={false}>
        <div className="px-6 py-4 border-b border-zinc-800">
          <h2 className="text-sm font-semibold">Your keys ({keys.length})</h2>
        </div>
        {isLoading ? (
          <div className="flex justify-center py-10">
            <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : keys.length === 0 ? (
          <p className="text-center py-10 text-sm text-zinc-500">No keys yet</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-500 border-b border-zinc-800">
                <th className="text-left px-6 py-3">Name</th>
                <th className="text-left px-6 py-3">Prefix</th>
                <th className="text-left px-6 py-3">Status</th>
                <th className="text-left px-6 py-3">Uses</th>
                <th className="text-left px-6 py-3">Last used</th>
                <th className="text-left px-6 py-3">Created</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                  <td className="px-6 py-3 font-medium">{key.name}</td>
                  <td className="px-6 py-3 font-mono text-xs text-zinc-400">{key.key_prefix}…</td>
                  <td className="px-6 py-3">
                    <StatusBadge status={key.is_active ? "active" : "inactive"} />
                  </td>
                  <td className="px-6 py-3 text-zinc-400">{key.usage_count}</td>
                  <td className="px-6 py-3 text-xs text-zinc-500">
                    {key.last_used_at ? formatDateTime(key.last_used_at) : "Never"}
                  </td>
                  <td className="px-6 py-3 text-xs text-zinc-500">{formatDateTime(key.created_at)}</td>
                  <td className="px-6 py-3">
                    <Button
                      variant="danger"
                      size="sm"
                      loading={deleteMutation.isPending}
                      onClick={() => {
                        if (confirm(`Revoke key "${key.name}"? This cannot be undone.`))
                          deleteMutation.mutate(key.id);
                      }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Usage info */}
      <Card className="mt-6 bg-zinc-900/50">
        <h3 className="text-sm font-medium mb-3">Using your API key</h3>
        <p className="text-xs text-zinc-500 mb-2">Pass the key via the <code className="text-violet-400">X-API-Key</code> header:</p>
        <pre className="text-xs font-mono bg-zinc-800 rounded-lg px-4 py-3 text-zinc-300 overflow-x-auto">
{`curl -X POST https://your-domain/analysis/analyze-file \\
  -H "X-API-Key: ef_your_key_here" \\
  -F "file=@audio.mp3" \\
  -F "model_tier=balanced"`}
        </pre>
      </Card>
    </AppShell>
  );
}
