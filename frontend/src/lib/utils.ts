import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function formatMs(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function emotionColor(emotion: string): string {
  const map: Record<string, string> = {
    // Core emotions
    happy: "#22c55e",
    joy: "#22c55e",
    excited: "#84cc16",
    excitement: "#84cc16",
    surprised: "#eab308",
    surprise: "#eab308",
    neutral: "#94a3b8",
    calm: "#60a5fa",
    sad: "#818cf8",
    sadness: "#818cf8",
    fear: "#a78bfa",
    fearful: "#a78bfa",
    angry: "#f87171",
    anger: "#f87171",
    disgust: "#fb923c",
    contempt: "#f97316",
    // go_emotions extended
    admiration: "#34d399",
    amusement: "#a3e635",
    annoyance: "#fb923c",
    approval: "#2dd4bf",
    caring: "#f472b6",
    confusion: "#c084fc",
    curiosity: "#38bdf8",
    desire: "#e879f9",
    disappointment: "#a78bfa",
    disapproval: "#f97316",
    embarrassment: "#fb7185",
    gratitude: "#4ade80",
    grief: "#6366f1",
    love: "#ec4899",
    nervousness: "#c084fc",
    optimism: "#facc15",
    pride: "#fbbf24",
    realization: "#67e8f9",
    relief: "#5eead4",
    remorse: "#818cf8",
  };
  return map[emotion.toLowerCase()] ?? "#94a3b8";
}

export const TIER_INFO = {
  fast: {
    label: "Fast",
    cost: "1 CU",
    desc: "Local multimodal fusion with base.en ASR",
    color: "text-emerald-400",
    bg: "bg-emerald-400/10 border-emerald-400/20",
  },
  balanced: {
    label: "Balanced",
    cost: "5 CU",
    desc: "Local multimodal fusion with small.en ASR",
    color: "text-blue-400",
    bg: "bg-blue-400/10 border-blue-400/20",
  },
  max: {
    label: "Max",
    cost: "20 CU",
    desc: "Local multimodal fusion with medium.en ASR",
    color: "text-violet-400",
    bg: "bg-violet-400/10 border-violet-400/20",
  },
} as const;
