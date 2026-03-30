"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { authApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { formatDate, TIER_INFO } from "@/lib/utils";
import { CheckCircle2 } from "lucide-react";

const TIERS = [
  { ...TIER_INFO.fast, id: "fast", quota: 50, desc: "50 analyses/day, basic sentiment" },
  { ...TIER_INFO.balanced, id: "balanced", quota: 100, desc: "100 analyses/day, full analysis", current: true },
  { ...TIER_INFO.max, id: "max", quota: 500, desc: "500 analyses/day, Gemini causality, priority queue" },
];

export default function ProfilePage() {
  const { user, refresh } = useAuth();
  const qc = useQueryClient();
  const [email, setEmail] = useState(user?.email ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  const updateMutation = useMutation({
    mutationFn: () => authApi.updateMe({ email, full_name: fullName }),
    onSuccess: () => {
      setSuccess("Profile updated");
      setError("");
      refresh();
      qc.invalidateQueries({ queryKey: ["me"] });
      setTimeout(() => setSuccess(""), 3000);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Update failed");
    },
  });

  if (!user) return null;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Profile & Plan</h1>
        <p className="text-zinc-500 text-sm mt-1">Manage your account details and subscription tier</p>
      </div>

      <div className="max-w-2xl space-y-6">
        {/* Profile card */}
        <Card>
          <CardHeader title="Account details" />
          <div className="space-y-4">
            <div className="flex items-center gap-4 pb-4 border-b border-zinc-800">
              <div className="w-14 h-14 rounded-full bg-violet-600 flex items-center justify-center text-xl font-bold uppercase">
                {user.username[0]}
              </div>
              <div>
                <p className="font-semibold">{user.username}</p>
                <p className="text-sm text-zinc-500">Member since {formatDate(user.created_at)}</p>
                <p className="text-xs text-zinc-600 mt-0.5">
                  {user.role === "admin" ? "Administrator" : "Standard user"} · Quota: {user.quota_limit}/day
                </p>
              </div>
            </div>

            <Input
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Input
              label="Full name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />

            {success && (
              <div className="flex items-center gap-2 text-sm text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 rounded-lg px-3 py-2">
                <CheckCircle2 className="w-4 h-4" />
                {success}
              </div>
            )}
            {error && <p className="text-sm text-red-400">{error}</p>}

            <Button onClick={() => updateMutation.mutate()} loading={updateMutation.isPending}>
              Save changes
            </Button>
          </div>
        </Card>

        {/* Quota status */}
        <Card>
          <CardHeader title="Daily quota" subtitle="Resets at midnight UTC" />
          <div className="flex justify-between text-sm mb-3">
            <span className="text-zinc-400">Used today</span>
            <span className="font-medium">{user.quota_used_today} / {user.quota_limit}</span>
          </div>
          <div className="w-full bg-zinc-800 rounded-full h-2 mb-2">
            <div
              className="bg-violet-500 h-2 rounded-full transition-all"
              style={{ width: `${Math.min((user.quota_used_today / user.quota_limit) * 100, 100)}%` }}
            />
          </div>
          <p className="text-xs text-zinc-500">{user.quota_limit - user.quota_used_today} analyses remaining today</p>
        </Card>

        {/* Plan upgrade */}
        <Card>
          <CardHeader title="Plan & pricing" subtitle="All plans are pay-per-analysis — no subscription required" />
          <div className="grid grid-cols-3 gap-3">
            {TIERS.map((t) => (
              <div
                key={t.id}
                className={`border rounded-xl p-4 relative ${
                  t.id === "balanced"
                    ? `${t.bg} border-current`
                    : "border-zinc-700"
                }`}
              >
                {t.id === "balanced" && (
                  <span className="absolute -top-2.5 left-3 text-xs bg-violet-600 text-white px-2 py-0.5 rounded-full">
                    Your plan
                  </span>
                )}
                <p className={`font-semibold text-sm ${t.color}`}>{t.label}</p>
                <p className={`text-2xl font-bold mt-1 ${t.color}`}>{t.cost}</p>
                <p className="text-xs text-zinc-500 mt-1">per analysis</p>
                <p className="text-xs text-zinc-500 mt-2">{t.desc}</p>
              </div>
            ))}
          </div>
          <p className="text-xs text-zinc-600 mt-4">
            Quota limit changes are applied by an admin. Contact support to request a limit increase.
          </p>
        </Card>
      </div>
    </AppShell>
  );
}
