import { cn } from "@/lib/utils";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: boolean;
}

export function Card({ children, className, padding = true }: CardProps) {
  return (
    <div className={cn("bg-zinc-900 border border-zinc-800 rounded-xl", padding && "p-6", className)}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h2 className="text-base font-semibold text-zinc-100">{title}</h2>
        {subtitle && <p className="text-sm text-zinc-500 mt-0.5">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  trend,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon?: React.ReactNode;
  trend?: "up" | "down" | "neutral";
}) {
  return (
    <Card className="flex items-center gap-4">
      {icon && (
        <div className="w-10 h-10 rounded-lg bg-violet-600/10 flex items-center justify-center text-violet-400 shrink-0">
          {icon}
        </div>
      )}
      <div className="min-w-0">
        <p className="text-xs text-zinc-500 uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-bold text-zinc-100 mt-0.5">{value}</p>
        {sub && <p className={cn("text-xs mt-0.5", trend === "up" ? "text-emerald-400" : trend === "down" ? "text-red-400" : "text-zinc-500")}>{sub}</p>}
      </div>
    </Card>
  );
}
