"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { authApi, clearTokens, ensureFreshAccessToken } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const token = await ensureFreshAccessToken();
      if (!token) throw new Error("Authentication required");
      const me = await authApi.me();
      setUser(me);
    } catch {
      setUser(null);
      clearTokens();
    }
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void refresh().finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [refresh]);

  const login = async (email: string, password: string) => {
    await authApi.login(email, password);
    const me = await authApi.me();
    setUser(me);
  };

  const logout = () => {
    clearTokens();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
