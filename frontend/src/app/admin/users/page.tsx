"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDate } from "@/lib/utils";
import { Search } from "lucide-react";
import type { UserAdminView } from "@/lib/types";

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [quotaEdit, setQuotaEdit] = useState<{ id: number; value: number } | null>(null);

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminApi.users({ limit: 200 }),
  });

  const quotaMutation = useMutation({
    mutationFn: ({ id, quota }: { id: number; quota: number }) => adminApi.updateQuota(id, quota),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setQuotaEdit(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (id: number) => adminApi.toggleUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const toggleTestMutation = useMutation({
    mutationFn: (id: number) => adminApi.toggleTestUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const filtered = users.filter(
    (u: UserAdminView) =>
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      u.username.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Users</h1>
          <p className="text-zinc-500 text-sm mt-1">{users.length} total users</p>
        </div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search users…"
            className="bg-zinc-800 border border-zinc-700 rounded-lg pl-9 pr-4 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500/40 w-56"
          />
        </div>
      </div>

      <Card padding={false}>
        {isLoading ? (
          <div className="flex justify-center py-10">
            <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-500 border-b border-zinc-800">
                <th className="text-left px-6 py-3">User</th>
                <th className="text-left px-6 py-3">Role</th>
                <th className="text-left px-6 py-3">Status</th>
                <th className="text-left px-6 py-3">Jobs</th>
                <th className="text-left px-6 py-3">Quota (used / limit)</th>
                <th className="text-left px-6 py-3">Joined</th>
                <th className="px-6 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((u: UserAdminView) => (
                <tr key={u.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                  <td className="px-6 py-3">
                    <p className="font-medium">{u.username}</p>
                    <p className="text-xs text-zinc-500">{u.email}</p>
                    {u.is_test_account && <span className="text-xs text-yellow-400 font-medium">test</span>}
                  </td>
                  <td className="px-6 py-3 capitalize text-xs text-zinc-400">{u.role}</td>
                  <td className="px-6 py-3">
                    <StatusBadge status={u.is_active ? "active" : "inactive"} />
                  </td>
                  <td className="px-6 py-3">{u.total_jobs}</td>
                  <td className="px-6 py-3">
                    {quotaEdit?.id === u.id ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          className="w-20 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-sm focus:outline-none"
                          value={quotaEdit.value}
                          onChange={(e) => setQuotaEdit({ id: u.id, value: Number(e.target.value) })}
                        />
                        <Button size="sm" onClick={() => quotaMutation.mutate({ id: u.id, quota: quotaEdit.value })} loading={quotaMutation.isPending}>
                          Save
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setQuotaEdit(null)}>✕</Button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setQuotaEdit({ id: u.id, value: u.quota_limit })}
                        className="text-zinc-400 hover:text-violet-400 transition-colors text-xs"
                      >
                        {u.quota_used_today} / <span className="underline decoration-dashed">{u.quota_limit}</span>
                      </button>
                    )}
                  </td>
                  <td className="px-6 py-3 text-xs text-zinc-500">{formatDate(u.created_at)}</td>
                  <td className="px-6 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant={u.is_test_account ? "secondary" : "ghost"}
                        size="sm"
                        loading={toggleTestMutation.isPending}
                        onClick={() => toggleTestMutation.mutate(u.id)}
                      >
                        {u.is_test_account ? "Unmark Test" : "Mark Test"}
                      </Button>
                      <Button
                        variant={u.is_active ? "danger" : "secondary"}
                        size="sm"
                        loading={toggleMutation.isPending}
                        onClick={() => {
                          if (confirm(`${u.is_active ? "Disable" : "Enable"} user ${u.username}?`))
                            toggleMutation.mutate(u.id);
                        }}
                      >
                        {u.is_active ? "Disable" : "Enable"}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </AppShell>
  );
}
