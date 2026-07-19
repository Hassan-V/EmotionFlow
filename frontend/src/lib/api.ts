import axios from "axios";
import type {
  User,
  TokenResponse,
  Job,
  JobSubmitResponse,
  ModelTier,
  ApiKey,
  ApiKeyCreated,
  Webhook,
  WebhookDelivery,
  TelemetrySummary,
  UserAdminView,
  BillingSummary,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = axios.create({
  baseURL: BASE,
  withCredentials: false,
});

// ─── Token management (module-level, no DOM dep so SSR safe) ──────────────────

let _access: string | null = null;
let _refresh: string | null = null;

export function setTokens(access: string, refresh: string) {
  _access = access;
  _refresh = refresh;
  if (typeof window !== "undefined") {
    localStorage.setItem("ef_access", access);
    localStorage.setItem("ef_refresh", refresh);
  }
}

export function clearTokens() {
  _access = null;
  _refresh = null;
  if (typeof window !== "undefined") {
    localStorage.removeItem("ef_access");
    localStorage.removeItem("ef_refresh");
  }
}

export function loadTokensFromStorage() {
  if (typeof window !== "undefined") {
    _access = localStorage.getItem("ef_access");
    _refresh = localStorage.getItem("ef_refresh");
  }
}

export function getAccessToken(): string | null {
  if (!_access && typeof window !== "undefined") {
    _access = localStorage.getItem("ef_access");
  }
  return _access;
}

// ─── Axios interceptors ───────────────────────────────────────────────────────

api.interceptors.request.use((config) => {
  if (!_access) loadTokensFromStorage();
  if (_access) config.headers["Authorization"] = `Bearer ${_access}`;
  return config;
});

let _refreshing: Promise<void> | null = null;

function tokenExpiresSoon(token: string, leadTimeMs = 60_000): boolean {
  try {
    const encoded = token.split(".")[1];
    if (!encoded) return true;
    const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(window.atob(padded)) as { exp?: number };
    return !payload.exp || payload.exp * 1000 <= Date.now() + leadTimeMs;
  } catch {
    return true;
  }
}

async function refreshTokens(): Promise<void> {
  if (!_refresh) throw new Error("No refresh token is available");
  if (!_refreshing) {
    _refreshing = api
      .post<TokenResponse>("/auth/refresh", { refresh_token: _refresh })
      .then((r) => setTokens(r.data.access_token, r.data.refresh_token))
      .catch((error) => {
        clearTokens();
        throw error;
      })
      .finally(() => (_refreshing = null));
  }
  await _refreshing;
}

export async function ensureFreshAccessToken(fallbackToken?: string): Promise<string | null> {
  loadTokensFromStorage();
  if (!_access && fallbackToken) _access = fallbackToken;
  if (!_access) return null;
  if (!tokenExpiresSoon(_access)) return _access;
  try {
    await refreshTokens();
    return _access;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    const isRefreshRequest = typeof original?.url === "string" && original.url.includes("/auth/refresh");
    if (error.response?.status === 401 && !isRefreshRequest && !original._retry && _refresh) {
      original._retry = true;
      await refreshTokens();
      if (_access) {
        original.headers["Authorization"] = `Bearer ${_access}`;
        return api(original);
      }
    }
    return Promise.reject(error);
  }
);

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const authApi = {
  register: (data: { email: string; username: string; password: string; full_name?: string }) =>
    api.post<User>("/auth/register", data).then((r) => r.data),

  login: async (email: string, password: string) => {
    const r = await api.post<TokenResponse>("/auth/login", { email, password });
    setTokens(r.data.access_token, r.data.refresh_token);
    return r.data;
  },

  google: async (credential: string) => {
    const r = await api.post<TokenResponse>("/auth/google", { credential });
    setTokens(r.data.access_token, r.data.refresh_token);
    return r.data;
  },

  verifyEmail: (token: string) =>
    api.post<{ message: string }>("/auth/verify-email", null, { params: { token } }).then((r) => r.data),

  resendVerification: () =>
    api.post<{ message: string }>("/auth/resend-verification").then((r) => r.data),

  me: () => api.get<User>("/auth/me").then((r) => r.data),

  updateMe: (data: { email?: string; full_name?: string }) =>
    api.patch<User>("/auth/me", data).then((r) => r.data),

  logout: () => clearTokens(),
};

// ─── Analysis ─────────────────────────────────────────────────────────────────

export const analysisApi = {
  submit: (file: File, tier: ModelTier, sessionId?: string) => {
    const form = new FormData();
    form.append("file", file);
    return api
      .post<JobSubmitResponse>(`/analysis/analyze-file?model_tier=${tier}${sessionId ? `&session_id=${sessionId}` : ""}`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },

  getJob: (jobId: string) => api.get<Job>(`/analysis/jobs/${jobId}`).then((r) => r.data),

  listJobs: (params?: { status_filter?: string; limit?: number; offset?: number }) =>
    api.get<Job[]>("/analysis/jobs", { params }).then((r) => r.data),

  getAudioUrl: async (jobId: string): Promise<string> => {
    const resp = await api.get(`/analysis/jobs/${jobId}/audio`, { responseType: "blob" });
    return URL.createObjectURL(resp.data);
  },
};

// ─── API Keys ─────────────────────────────────────────────────────────────────

export const apiKeysApi = {
  list: () => api.get<ApiKey[]>("/api-keys/").then((r) => r.data),
  create: (name: string) => api.post<ApiKeyCreated>("/api-keys/", { name }).then((r) => r.data),
  delete: (id: number) => api.delete(`/api-keys/${id}`),
};

// ─── Webhooks ─────────────────────────────────────────────────────────────────

export const webhooksApi = {
  list: () => api.get<Webhook[]>("/webhooks/").then((r) => r.data),
  create: (data: { url: string; name?: string; events?: string[] }) =>
    api.post<Webhook>("/webhooks/", data).then((r) => r.data),
  update: (id: number, data: Partial<{ name: string; url: string; events: string[]; is_active: boolean }>) =>
    api.patch<Webhook>(`/webhooks/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/webhooks/${id}`),
  deliveries: (id: number) => api.get<WebhookDelivery[]>(`/webhooks/${id}/deliveries`).then((r) => r.data),
  test: (id: number) => api.post<{ success: boolean; status_code: number }>(`/webhooks/${id}/test`).then((r) => r.data),
};

// ─── Admin ────────────────────────────────────────────────────────────────────

export const adminApi = {
  telemetry: () => api.get<TelemetrySummary>("/admin/telemetry").then((r) => r.data),
  users: (params?: { limit?: number; offset?: number }) =>
    api.get<UserAdminView[]>("/admin/users", { params }).then((r) => r.data),
  updateQuota: (userId: number, quota: number) =>
    api.patch<User>(`/admin/users/${userId}/quota`, { quota_limit: quota }).then((r) => r.data),
  toggleUser: (userId: number) => api.patch<User>(`/admin/users/${userId}/toggle-active`).then((r) => r.data),
  toggleTestUser: (userId: number) => api.patch<User>(`/admin/users/${userId}/toggle-test`).then((r) => r.data),
  billing: (year: number, month: number) =>
    api.get<BillingSummary>("/admin/billing/summary", { params: { year, month } }).then((r) => r.data),
  logs: (count?: number) =>
    api.get<{ logs: unknown[]; count: number }>("/admin/logs", { params: { count } }).then((r) => r.data),
  workers: () =>
    api.get<{ workers: { id: string; status: string; last_seen_ago_s: number; ttl_s: number }[]; worker_count: number; queue_depth: number }>("/admin/workers").then((r) => r.data),
};

// ─── Health ───────────────────────────────────────────────────────────────────

export const healthApi = {
  check: () =>
    api.get<{ status: string; database: string; redis: string; version: string }>("/health").then((r) => r.data),
};
