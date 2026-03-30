"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Upload,
  Key,
  CreditCard,
  Settings,
  LogOut,
  Webhook,
  BarChart3,
  Users,
  MessageSquare,
  Activity,
  Zap,
} from "lucide-react";

const userNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/analyze", label: "Analyze", icon: Upload },
  { href: "/api-keys", label: "API Keys", icon: Key },
  { href: "/webhooks", label: "Webhooks", icon: Webhook },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/profile", label: "Profile", icon: Settings },
  { href: "/discord-bot", label: "Discord Bot", icon: MessageSquare },
];

const adminNav = [
  { href: "/admin", label: "Overview", icon: Activity },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/billing", label: "Billing", icon: BarChart3 },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const router = useRouter();

  const isAdmin = user?.role === "admin";
  const nav = isAdmin && pathname.startsWith("/admin") ? adminNav : userNav;

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <aside className="w-60 shrink-0 flex flex-col bg-zinc-900 border-r border-zinc-800 min-h-screen">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-zinc-800">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-violet-400" />
          <span className="font-semibold text-sm tracking-wide">EmotionFlow</span>
        </Link>
      </div>

      {/* Admin toggle */}
      {isAdmin && (
        <div className="px-3 pt-3">
          <div className="flex rounded-lg bg-zinc-800 p-1 gap-1">
            <Link
              href="/dashboard"
              className={cn(
                "flex-1 text-center text-xs py-1.5 rounded-md transition-colors",
                !pathname.startsWith("/admin")
                  ? "bg-violet-600 text-white"
                  : "text-zinc-400 hover:text-zinc-200"
              )}
            >
              User
            </Link>
            <Link
              href="/admin"
              className={cn(
                "flex-1 text-center text-xs py-1.5 rounded-md transition-colors",
                pathname.startsWith("/admin")
                  ? "bg-violet-600 text-white"
                  : "text-zinc-400 hover:text-zinc-200"
              )}
            >
              Admin
            </Link>
          </div>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
              pathname === href || (href !== "/dashboard" && pathname.startsWith(href))
                ? "bg-violet-600/20 text-violet-300"
                : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
            )}
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </Link>
        ))}
      </nav>

      {/* User footer */}
      <div className="border-t border-zinc-800 px-4 py-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 rounded-full bg-violet-600 flex items-center justify-center text-xs font-medium uppercase">
            {user?.username?.[0] ?? "?"}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{user?.username}</p>
            <p className="text-xs text-zinc-500 truncate">{user?.email}</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 text-xs text-zinc-500 hover:text-red-400 transition-colors w-full"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
