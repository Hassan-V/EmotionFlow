"use client";

import Link from "next/link";
import { Zap, Mic, BarChart3, Key, Webhook, Shield } from "lucide-react";

const features = [
  { icon: Mic, title: "Speech Emotion AI", desc: "Whisper ASR + emotion classification on any audio file up to 50MB" },
  { icon: BarChart3, title: "Deep Causality", desc: "Max tier uses Gemini to explain what triggered each emotion shift" },
  { icon: Key, title: "API-First", desc: "Full REST API with API key auth for integrations and bots" },
  { icon: Webhook, title: "Webhooks", desc: "Real-time notifications with HMAC-signed payloads on job events" },
  { icon: Shield, title: "Metered Billing", desc: "Pay-per-analysis with immutable audit ledger for every request" },
  { icon: Zap, title: "Async Workers", desc: "Background workers scale independently — GPU or CPU" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col">
      <nav className="border-b border-zinc-800 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-violet-400" />
          <span className="font-semibold text-sm">EmotionFlow</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Sign in</Link>
          <Link href="/register" className="bg-violet-600 hover:bg-violet-500 text-white text-sm px-4 py-2 rounded-lg transition-colors">Get started</Link>
        </div>
      </nav>

      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 pb-24 pt-20">
        <div className="inline-flex items-center gap-2 text-xs bg-violet-600/10 border border-violet-600/20 text-violet-300 px-3 py-1 rounded-full mb-8">
          <Zap className="w-3 h-3" />
          AI-powered audio emotion analysis
        </div>
        <h1 className="text-5xl font-bold text-zinc-100 max-w-2xl leading-tight mb-6">
          Understand the{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-violet-400 to-blue-400">emotion</span>{" "}
          behind every word
        </h1>
        <p className="text-zinc-400 text-lg max-w-xl mb-10">
          Upload audio, get a full emotion timeline with transcript, intensity scores, and AI causality analysis — in seconds.
        </p>
        <div className="flex items-center gap-4">
          <Link href="/register" className="bg-violet-600 hover:bg-violet-500 text-white px-6 py-3 rounded-xl font-medium text-sm transition-colors">Start for free</Link>
          <Link href="/login" className="border border-zinc-700 hover:bg-zinc-800 text-zinc-300 px-6 py-3 rounded-xl text-sm transition-colors">Sign in</Link>
        </div>
        <div className="mt-20 grid grid-cols-3 gap-4 max-w-2xl w-full">
          {[{ name: "Fast", price: "1 CU", desc: "Quick sentiment" }, { name: "Balanced", price: "5 CU", desc: "Full analysis" }, { name: "Max", price: "20 CU", desc: "AI causality" }].map((t) => (
            <div key={t.name} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-left">
              <p className="text-sm font-medium text-zinc-200">{t.name}</p>
              <p className="text-2xl font-bold text-violet-400 mt-1">{t.price}</p>
              <p className="text-xs text-zinc-500 mt-1">{t.desc} / analysis</p>
            </div>
          ))}
        </div>
      </div>

      <div className="border-t border-zinc-800 bg-zinc-900/50 px-8 py-16">
        <div className="max-w-4xl mx-auto grid grid-cols-3 gap-6">
          {features.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="space-y-2">
              <Icon className="w-5 h-5 text-violet-400" />
              <h3 className="text-sm font-medium text-zinc-200">{title}</h3>
              <p className="text-sm text-zinc-500">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
