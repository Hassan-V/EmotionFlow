import { cn } from "@/lib/utils";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "error" | "info" | "muted";
  className?: string;
}

const variants = {
  default: "bg-zinc-800 text-zinc-300",
  success: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
  warning: "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20",
  error: "bg-red-500/10 text-red-400 border border-red-500/20",
  info: "bg-blue-500/10 text-blue-400 border border-blue-500/20",
  muted: "bg-zinc-800/60 text-zinc-500",
};

export function Badge({ children, variant = "default", className }: BadgeProps) {
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-xs font-medium", variants[variant], className)}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, BadgeProps["variant"]> = {
    completed: "success",
    failed: "error",
    processing: "info",
    pending: "warning",
    delivered: "success",
    active: "success",
    inactive: "muted",
  };
  return <Badge variant={map[status] ?? "default"}>{status}</Badge>;
}
