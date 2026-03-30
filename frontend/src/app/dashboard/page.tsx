"use client";

import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery } from "@tanstack/react-query";
import { analysisApi } from "@/lib/api";
import { Card, StatCard } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDateTime, formatMs } from "@/lib/utils";
import { BarChart3, Upload, Clock, CheckCircle } from "lucide-react";
import Link from "next/link";
import type { Job } from "@/lib/types";

export default function DashboardPage() {
  const { user } = useAuth();
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => analysisApi.listJobs({ limit: 10 }),
  });

  const completed = jobs.filter((j) => j.status === "completed").length;
  const failed = jobs.filter((j) => j.status === "failed").length;
  const quotaPct = user ? Math.round((user.quota_used_today / user.quota_limit) * 100) : 0;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-zinc-500 text-sm mt-1">Welcome back, {user?.full_name ?? user?.username}</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard label="Jobs today" value={user?.quota_used_today ?? 0} icon={<Upload className="w-5 h-5" />} />
        <StatCard label="Completed" value={completed} icon={<CheckCircle className="w-5 h-5" />} />
        <StatCard label="Failed" value={failed} icon={<BarChart3 className="w-5 h-5" />} />
        <StatCard
          label="Quota used"
          value={`${quotaPct}%`}
          sub={`${user?.quota_used_today} / ${user?.quota_limit}`}
          icon={<Clock className="w-5 h-5" />}
          trend={quotaPct > 80 ? "down" : "neutral"}
        />
      </div>

      {/* Quota bar */}
      <Card className="mb-8">
        <div className="flex justify-between text-sm mb-2">
          <span className="text-zinc-400">Daily quota</span>
          <span className="text-zinc-500">{user?.quota_used_today} / {user?.quota_limit} analyses</span>
        </div>
        <div className="w-full bg-zinc-800 rounded-full h-2">
          <div
            className="bg-violet-500 h-2 rounded-full transition-all"
            style={{ width: `${Math.min(quotaPct, 100)}%` }}
          />
        </div>
        {quotaPct > 80 && (
          <p className="text-xs text-yellow-400 mt-2">Approaching daily limit — quota resets at midnight UTC</p>
        )}
      </Card>

      {/* Recent jobs */}
      <Card padding={false}>
        <div className="px-6 py-4 border-b border-zinc-800 flex justify-between items-center">
          <h2 className="text-sm font-semibold">Recent jobs</h2>
          <Link href="/analyze" className="text-xs text-violet-400 hover:text-violet-300">
            + New analysis
          </Link>
        </div>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-12 text-zinc-500 text-sm">
            No jobs yet.{" "}
            <Link href="/analyze" className="text-violet-400 hover:text-violet-300">
              Upload your first file
            </Link>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-500 border-b border-zinc-800">
                <th className="text-left px-6 py-3">Job</th>
                <th className="text-left px-6 py-3">Tier</th>
                <th className="text-left px-6 py-3">Status</th>
                <th className="text-left px-6 py-3">Time</th>
                <th className="text-left px-6 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job: Job) => (
                <tr key={job.job_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                  <td className="px-6 py-3">
                    <Link href={`/jobs/${job.job_id}`} className="text-violet-400 hover:text-violet-300 font-mono text-xs">
                      {job.job_id.slice(0, 8)}…
                    </Link>
                    {job.result?.filename && (
                      <p className="text-xs text-zinc-500 mt-0.5 truncate max-w-[180px]">{job.result.filename}</p>
                    )}
                  </td>
                  <td className="px-6 py-3 capitalize text-xs text-zinc-400">{job.model_tier}</td>
                  <td className="px-6 py-3">
                    <StatusBadge status={job.status} />
                  </td>
                  <td className="px-6 py-3 text-xs text-zinc-400">
                    {job.processing_time_ms ? formatMs(job.processing_time_ms) : "—"}
                  </td>
                  <td className="px-6 py-3 text-xs text-zinc-500">{formatDateTime(job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </AppShell>
  );
}
