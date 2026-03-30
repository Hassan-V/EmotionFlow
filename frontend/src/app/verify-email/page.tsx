"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api";
import { Zap, CheckCircle, XCircle, Loader2 } from "lucide-react";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Missing verification token");
      return;
    }

    authApi
      .verifyEmail(token)
      .then((r) => {
        setStatus("success");
        setMessage(r.message);
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err?.response?.data?.detail ?? "Verification failed");
      });
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm text-center">
        <div className="flex items-center justify-center gap-2 mb-8">
          <Zap className="w-5 h-5 text-violet-400" />
          <span className="font-semibold">EmotionFlow</span>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8">
          {status === "loading" && (
            <>
              <Loader2 className="w-10 h-10 text-violet-400 animate-spin mx-auto mb-4" />
              <p className="text-zinc-400">Verifying your email…</p>
            </>
          )}

          {status === "success" && (
            <>
              <CheckCircle className="w-10 h-10 text-green-400 mx-auto mb-4" />
              <h1 className="text-xl font-semibold mb-2">Email Verified</h1>
              <p className="text-zinc-400 mb-6">{message}</p>
              <Link
                href="/login"
                className="bg-violet-600 hover:bg-violet-500 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors"
              >
                Sign in
              </Link>
            </>
          )}

          {status === "error" && (
            <>
              <XCircle className="w-10 h-10 text-red-400 mx-auto mb-4" />
              <h1 className="text-xl font-semibold mb-2">Verification Failed</h1>
              <p className="text-zinc-400 mb-6">{message}</p>
              <Link
                href="/login"
                className="text-violet-400 hover:text-violet-300 text-sm"
              >
                Go to sign in
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-zinc-950">
          <Loader2 className="w-8 h-8 text-violet-400 animate-spin" />
        </div>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  );
}
