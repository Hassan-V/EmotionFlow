"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery } from "@tanstack/react-query";
import { adminApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card, StatCard } from "@/components/ui/Card";
import {
  Users, Activity, CheckCircle, XCircle, Clock, Zap, AlertTriangle, Cpu,
} from "lucide-react";
import { formatMs } from "@/lib/utils";

export default function AdminPage() {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user && user.role !== "admin") router.replace("/dashboard");
  }, [user, router]);

  const { data: tel, isLoading } = useQuery({
    queryKey: ["admin-telemetry"],
    queryFn: adminApi.telemetry,
    refetchInterval: 15_000,
  });

  const { data: workerStatus } = useQuery({
    queryKey: ["admin-workers"],
    queryFn: adminApi.workers,
    refetchInterval: 10_000,
  });

  if (isLoading || !tel) {
    return (
      <AppShell>
        <div className="flex justify-center py-20">
          <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Admin Overview</h1>
          <p className="text-zinc-500 text-sm mt-1">Live system telemetry — refreshes every 15s</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs text-zinc-500">Live</span>
        </div>
      </div>

      {/* Health indicator */}
      {tel.error_rate_percent > 10 && (
        <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/20 rounded-xl px-4 py-3 mb-6 text-sm text-yellow-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Error rate is elevated: {tel.error_rate_percent.toFixed(1)}%
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        <StatCard label="Total users" value={tel.total_users} icon={<Users className="w-5 h-5" />} />
        <StatCard label="Active today" value={tel.active_users_today} icon={<Activity className="w-5 h-5" />} />
        <StatCard label="Requests (last hr)" value={tel.requests_last_hour} icon={<Zap className="w-5 h-5" />} />
        <StatCard label="API latency p95" value={formatMs(tel.p95_api_latency_ms)} icon={<Clock className="w-5 h-5" />} />
        <StatCard
          label="Avg job processing"
          value={tel.avg_processing_time_ms ? formatMs(tel.avg_processing_time_ms) : "—"}
          icon={<Clock className="w-5 h-5" />}
        />
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Job breakdown */}
        <Card>
          <h2 className="text-sm font-semibold mb-4">Job breakdown</h2>          <div className="space-y-3">
            {[
              { label: "Total",     value: tel.total_analysis_jobs,  color: "bg-zinc-600" },
              { label: "Completed", value: tel.jobs_completed,        color: "bg-emerald-500" },
              { label: "Failed",    value: tel.jobs_failed,           color: "bg-red-500" },
              { label: "Pending",   value: tel.jobs_pending,          color: "bg-yellow-500" },
            ].map(({ label, value, color }) => {
              const pct = tel.total_analysis_jobs > 0 ? (value / tel.total_analysis_jobs) * 100 : 0;
              return (
                <div key={label}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-zinc-400">{label}</span>
                    <span className="font-medium">{value}</span>
                  </div>
                  <div className="w-full bg-zinc-800 rounded-full h-1.5">
                    <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Error rate card */}
        <Card>
          <h2 className="text-sm font-semibold mb-4">System health</h2>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Error rate</span>
              <div className="flex items-center gap-2">
                {tel.error_rate_percent > 10
                  ? <XCircle className="w-4 h-4 text-red-400" />
                  : <CheckCircle className="w-4 h-4 text-emerald-400" />}
                <span className={tel.error_rate_percent > 10 ? "text-red-400" : "text-emerald-400"}>
                  {tel.error_rate_percent.toFixed(1)}%
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Total requests</span>
              <span className="font-medium">{tel.total_requests.toLocaleString()}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Average API latency</span>
              <span className="font-medium">{formatMs(tel.avg_api_latency_ms)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">API errors (last hour)</span>
              <span className={tel.api_errors_last_hour ? "font-medium text-red-400" : "font-medium text-emerald-400"}>{tel.api_errors_last_hour}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Total users</span>
              <span className="font-medium">{tel.total_users}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Completion rate</span>
              <span className="font-medium text-emerald-400">
                {tel.total_analysis_jobs > 0
                  ? ((tel.jobs_completed / tel.total_analysis_jobs) * 100).toFixed(1)
                  : "—"}%
              </span>
            </div>
          </div>
        </Card>
      </div>

      {/* Workers */}
      <div className="mt-6">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Workers</h2>
            <div className="flex items-center gap-4 text-xs text-zinc-500">
              <span>Queue depth: <span className="font-medium text-zinc-300">{workerStatus?.queue_depth ?? "—"}</span></span>
              <span>{workerStatus?.worker_count ?? 0} active</span>
            </div>
          </div>
          {!workerStatus || workerStatus.workers.length === 0 ? (
            <div className="flex items-center gap-3 text-sm text-zinc-500 py-2">
              <XCircle className="w-4 h-4 text-red-400" />
              No workers online
            </div>
          ) : (
            <div className="space-y-2">
              {workerStatus.workers.map((w, i) => {
                const parts = w.id.split("-");
                const pid = parts[parts.length - 1];
                const host = parts.slice(0, -1).join("-").slice(0, 8);
                const ago = Math.max(0, w.last_seen_ago_s);
                const agoLabel = ago < 2 ? "just now" : `${ago}s ago`;
                return (
                <div key={w.id} className="flex items-center gap-3 py-2 border-t border-zinc-800 first:border-0">
                  <Cpu className="w-4 h-4 text-violet-400 shrink-0" />
                  <span className="text-sm text-zinc-300 flex-1">
                    Worker {i + 1}
                    <span className="ml-2 font-mono text-xs text-zinc-500" title={w.id}>{host}… · PID {pid}</span>
                  </span>
                  <span className="text-xs text-zinc-500">{agoLabel}</span>
                  <span className="flex items-center gap-1 text-xs text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
                    alive
                  </span>
                </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
