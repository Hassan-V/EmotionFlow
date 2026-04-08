"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { adminApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { TIER_INFO } from "@/lib/utils";
import type { BillingUserEntry } from "@/lib/types";

export default function AdminBillingPage() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-billing", year, month],
    queryFn: () => adminApi.billing(year, month),
  });

  const totalCU = data?.by_user.reduce((acc, u) => acc + u.total_compute_units, 0) ?? 0;

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Billing Summary</h1>
          <p className="text-zinc-500 text-sm mt-1">Metered usage from the immutable billing ledger</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none"
          >
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {new Date(2000, i, 1).toLocaleString("default", { month: "long" })}
              </option>
            ))}
          </select>
          <input
            type="number"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm w-20 focus:outline-none"
          />
        </div>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <Card>
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Total compute units</p>
          <p className="text-3xl font-bold text-emerald-400">{totalCU} CU</p>
          <p className="text-xs text-zinc-500 mt-1">
            {new Date(year, month - 1).toLocaleString("default", { month: "long" })} {year}
          </p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Paying users</p>
          <p className="text-3xl font-bold">{data?.by_user.filter((u) => u.total_compute_units > 0).length ?? 0}</p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Total jobs</p>
          <p className="text-3xl font-bold">{data?.by_user.reduce((a, u) => a + u.jobs_completed + u.jobs_failed, 0) ?? 0}</p>
        </Card>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10">
          <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <Card padding={false}>
          <div className="px-6 py-4 border-b border-zinc-800">
            <h2 className="text-sm font-semibold">Usage by user</h2>
          </div>
          {!data?.by_user.length ? (
            <p className="text-center py-10 text-sm text-zinc-500">No billing data for this period</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-zinc-500 border-b border-zinc-800">
                  <th className="text-left px-6 py-3">User</th>
                  <th className="text-left px-6 py-3">Completed</th>
                  <th className="text-left px-6 py-3">Failed</th>
                  <th className="text-left px-6 py-3">Tier breakdown</th>
                  <th className="text-right px-6 py-3">CU</th>
                </tr>
              </thead>
              <tbody>
                {data.by_user.map((u: BillingUserEntry) => (
                  <tr key={u.user_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                    <td className="px-6 py-3">
                      <p className="font-medium">{u.email}</p>
                      <p className="text-xs text-zinc-600">ID: {u.user_id}</p>
                    </td>
                    <td className="px-6 py-3 text-emerald-400">{u.jobs_completed}</td>
                    <td className="px-6 py-3 text-red-400">{u.jobs_failed}</td>
                    <td className="px-6 py-3">
                      <div className="flex gap-2 flex-wrap">
                        {Object.entries(u.tier_breakdown).map(([tier, info]) => (
                          <span
                            key={tier}
                            className={`text-xs px-2 py-0.5 rounded border ${TIER_INFO[tier as keyof typeof TIER_INFO]?.bg ?? "bg-zinc-800 border-zinc-700"} ${TIER_INFO[tier as keyof typeof TIER_INFO]?.color ?? "text-zinc-400"}`}
                          >
                            {tier}: {info.completed}×
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-3 text-right font-mono font-medium text-emerald-400">
                      {u.total_compute_units} CU
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </AppShell>
  );
}
