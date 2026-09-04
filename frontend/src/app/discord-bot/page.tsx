"use client";

import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/Card";
import { MessageSquare, Key, Zap, BookOpen, ExternalLink } from "lucide-react";
import Link from "next/link";

const STEPS = [
  {
    icon: Key,
    title: "1. Create an API key",
    desc: "Generate a key on the API Keys page. The bot uses this to submit jobs on behalf of your server.",
    action: { label: "Go to API Keys", href: "/api-keys" },
  },
  {
    icon: MessageSquare,
    title: "2. Add the bot to your server",
    desc: "Click the button below to invite EmotionFlow Bot to your Discord server. You'll need Manage Server permissions.",
    action: { label: "Invite Bot", href: "#invite", external: true },
  },
  {
    icon: Zap,
    title: "3. Configure with /setup",
    desc: 'Run the /emotionflow setup command in any channel and paste your API key when prompted. The bot will store it securely.',
    action: null,
  },
  {
    icon: BookOpen,
    title: "4. Start analyzing",
    desc: 'Use /analyze in any channel to upload an audio file. Results post as a rich embed with emotion timeline.',
    action: null,
  },
];

const COMMANDS = [
  { cmd: "/analyze", desc: "Upload and analyze an audio file (up to 50MB)" },
  { cmd: "/status <job_id>", desc: "Check the status of a running job" },
  { cmd: "/history", desc: "View your last 10 analyses" },
  { cmd: "/setup", desc: "Configure your API key (server admin only)" },
  { cmd: "/tier <fast|balanced|max>", desc: "Set the default analysis tier for this server" },
];

export default function DiscordBotPage() {
  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Discord Bot</h1>
        <p className="text-zinc-500 text-sm mt-1">Analyze audio directly from your Discord server</p>
      </div>

      <div className="max-w-2xl space-y-6">
        {/* Hero */}
        <Card className="bg-gradient-to-br from-indigo-900/30 to-violet-900/20 border-indigo-700/30">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-indigo-600/30 flex items-center justify-center">
              <MessageSquare className="w-7 h-7 text-indigo-300" />
            </div>
            <div>
              <h2 className="text-lg font-bold">EmotionFlow for Discord</h2>
              <p className="text-sm text-zinc-400 mt-0.5">
                Emotion analysis where your community already talks
              </p>
            </div>
          </div>
          <div className="mt-5 flex gap-3">
            <a
              href="#invite"
              className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-5 py-2.5 rounded-lg transition-colors font-medium"
            >
              <MessageSquare className="w-4 h-4" />
              Add to Discord
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </Card>

        {/* Setup steps */}
        <Card padding={false}>
          <div className="px-6 py-4 border-b border-zinc-800">
            <h2 className="text-sm font-semibold">Setup guide</h2>
          </div>
          <div className="divide-y divide-zinc-800">
            {STEPS.map(({ icon: Icon, title, desc, action }) => (
              <div key={title} className="px-6 py-5 flex gap-4">
                <div className="w-8 h-8 rounded-lg bg-violet-600/10 flex items-center justify-center text-violet-400 shrink-0">
                  <Icon className="w-4 h-4" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium mb-1">{title}</p>
                  <p className="text-sm text-zinc-500">{desc}</p>
                  {action && (
                    <div className="mt-3">
                      {action.external ? (
                        <a
                          href={action.href}
                          className="text-sm text-violet-400 hover:text-violet-300 inline-flex items-center gap-1"
                        >
                          {action.label} <ExternalLink className="w-3 h-3" />
                        </a>
                      ) : (
                        <Link href={action.href} className="text-sm text-violet-400 hover:text-violet-300">
                          {action.label} →
                        </Link>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Commands */}
        <Card padding={false}>
          <div className="px-6 py-4 border-b border-zinc-800">
            <h2 className="text-sm font-semibold">Available commands</h2>
          </div>
          <div className="divide-y divide-zinc-800">
            {COMMANDS.map(({ cmd, desc }) => (
              <div key={cmd} className="px-6 py-3 flex gap-6 items-start">
                <code className="text-xs font-mono text-violet-400 bg-violet-400/10 px-2 py-1 rounded whitespace-nowrap shrink-0">
                  {cmd}
                </code>
                <p className="text-sm text-zinc-500">{desc}</p>
              </div>
            ))}
          </div>
        </Card>

        {/* API key reminder */}
        <Card className="bg-zinc-900/50 border-zinc-800">
          <p className="text-sm text-zinc-400">
            The bot uses your EmotionFlow API key — every analysis charges at your configured tier rate and counts toward your daily quota.
            Create a dedicated key for the bot on the{" "}
            <Link href="/api-keys" className="text-violet-400 hover:text-violet-300">API Keys</Link> page.
          </p>
        </Card>
      </div>
    </AppShell>
  );
}
