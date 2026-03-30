import { cn } from "@/lib/utils";
import { forwardRef } from "react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className, ...props }, ref) => (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-sm font-medium text-zinc-300">
          {label}
        </label>
      )}
      <input
        ref={ref}
        {...props}
        className={cn(
          "w-full bg-zinc-800/60 border rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500",
          "focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500/40",
          "transition-colors",
          error ? "border-red-500/50" : "border-zinc-700",
          className
        )}
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      {hint && !error && <p className="text-xs text-zinc-500">{hint}</p>}
    </div>
  )
);
Input.displayName = "Input";
