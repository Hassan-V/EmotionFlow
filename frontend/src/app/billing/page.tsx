"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analysisApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDateTime, formatMs, TIER_INFO } from "@/lib/utils";
import Link from "next/link";
import type { Job } from "@/lib/types";

const STATUSES = ["", "pending", "processing", "completed", "failed"];

export default function BillingPage() {
  const [statusFilter, setStatusFilter] = useState("");

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["jobs", "all", statusFilter],
    queryFn: () => analysisApi.listJobs({ status_filter: statusFilter || undefined, limit: 100 }),
  });

  const completed = jobs.filter((j) => j.status === "completed");
  const totalCU = completed.reduce((acc, j) => {
    const tierCU = { fast: 1, balanced: 5, max: 20 };
    return acc + (tierCU[j.model_tier as keyof typeof tierCU] ?? 0);
  }, 0);

  const tierCounts = jobs.reduce<Record<string, number>>((acc, j) => {
    acc[j.model_tier] = (acc[j.model_tier] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Billing & Usage</h1>
        <p className="text-zinc-500 text-sm mt-1">Your job history and estimated costs</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <Card>
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Compute units used</p>
          <p className="text-3xl font-bold text-violet-400">{totalCU} CU</p>
          <p className="text-xs text-zinc-500 mt-1">Based on {completed.length} completed jobs</p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-3">Usage by tier</p>
          <div className="space-y-2">
            {(["fast", "balanced", "max"] as const).map((t) => (
              <div key={t} className="flex justify-between items-center">
                <span className={`text-xs font-medium ${TIER_INFO[t].color}`}>{TIER_INFO[t].label}</span>
                <span className="text-sm font-bold">{tierCounts[t] ?? 0}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Total jobs</p>
          <p className="text-3xl font-bold">{jobs.length}</p>
          <div className="flex gap-3 mt-2">
            <span className="text-xs text-emerald-400">{jobs.filter((j) => j.status === "completed").length} done</span>
            <span className="text-xs text-red-400">{jobs.filter((j) => j.status === "failed").length} failed</span>
          </div>
        </Card>
      </div>

      {/* Job history table */}
      <Card padding={false}>
        <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Job history</h2>
          <div className="flex gap-1">
            {STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                  statusFilter === s ? "bg-violet-600 text-white" : "text-zinc-500 hover:bg-zinc-800"
                }`}
              >
                {s || "All"}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-10">
            <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : jobs.length === 0 ? (
          <p className="text-center py-10 text-sm text-zinc-500">No jobs found</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-500 border-b border-zinc-800">
                <th className="text-left px-6 py-3">Job ID</th>
                <th className="text-left px-6 py-3">Tier</th>
                <th className="text-left px-6 py-3">Status</th>
                <th className="text-left px-6 py-3">CU</th>
                <th className="text-left px-6 py-3">Processing</th>
                <th className="text-left px-6 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job: Job) => {
                const tierCU = { fast: 1, balanced: 5, max: 20 };
                const cu = job.status === "completed" ? tierCU[job.model_tier as keyof typeof tierCU] ?? 0 : 0;
                return (
                  <tr key={job.job_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                    <td className="px-6 py-3">
                      <Link href={`/jobs/${job.job_id}`} className="text-violet-400 hover:text-violet-300 font-mono text-xs">
                        {job.job_id.slice(0, 8)}…
                      </Link>
                    </td>
                    <td className="px-6 py-3">
                      <span className={`text-xs font-medium ${TIER_INFO[job.model_tier].color}`}>
                        {TIER_INFO[job.model_tier].label}
                      </span>
                    </td>
                    <td className="px-6 py-3"><StatusBadge status={job.status} /></td>
                    <td className="px-6 py-3 text-xs font-mono">
                      {job.status === "completed" ? `${cu} CU` : "—"}
                    </td>
                    <td className="px-6 py-3 text-xs text-zinc-400">
                      {job.processing_time_ms ? formatMs(job.processing_time_ms) : "—"}
                    </td>
                    <td className="px-6 py-3 text-xs text-zinc-500">{formatDateTime(job.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </AppShell>
  );
}
