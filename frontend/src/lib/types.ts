// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface User {
  id: number;
  email: string;
  username: string;
  full_name: string | null;
  role: "user" | "admin";
  is_active: boolean;
  quota_limit: number;
  quota_used_today: number;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// ─── Analysis ─────────────────────────────────────────────────────────────────

export type ModelTier = "fast" | "balanced" | "max";
export type JobStatus = "pending" | "processing" | "completed" | "failed";

export interface EmotionShift {
  timestamp_start: number;
  timestamp_end: number;
  emotion: string;
  intensity: number;
  trigger_phrase: string | null;
  cause: string | null;
}

export interface EmotionTransition {
  from_segment: number;
  to_segment: number;
  from_emotion: string;
  to_emotion: string;
  explanation: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  speaker: string | null;
}

export interface AnalysisResult {
  filename: string;
  duration_seconds: number;
  overall_sentiment: string;
  summary?: string;
  timeline: EmotionShift[];
  transcript: TranscriptSegment[];
  transitions?: EmotionTransition[];
  model_tier: ModelTier;
  processing_time_ms: number;
}

export interface JobSubmitResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  model_tier: ModelTier;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  processing_time_ms: number | null;
  result: AnalysisResult | null;
  error_message: string | null;
  filename?: string;
}

// ─── API Keys ─────────────────────────────────────────────────────────────────

export interface ApiKey {
  id: number;
  key_prefix: string;
  name: string;
  is_active: boolean;
  usage_count: number;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string;
}

// ─── Webhooks ─────────────────────────────────────────────────────────────────

export interface Webhook {
  id: number;
  name: string;
  url: string;
  events: string;
  is_active: boolean;
  secret?: string;
  created_at: string;
  updated_at: string;
}

export interface WebhookDelivery {
  id: number;
  webhook_id: number;
  job_id: string;
  event_type: string;
  status: "pending" | "delivered" | "failed";
  status_code: number | null;
  error_message: string | null;
  attempt: number;
  max_attempts: number;
  next_retry_at: string | null;
  created_at: string;
  delivered_at: string | null;
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export interface TelemetrySummary {
  total_requests: number;
  total_users: number;
  active_users_today: number;
  total_analysis_jobs: number;
  jobs_completed: number;
  jobs_failed: number;
  jobs_pending: number;
  avg_processing_time_ms: number | null;
  error_rate_percent: number;
  requests_last_hour: number;
}

export interface UserAdminView {
  id: number;
  email: string;
  username: string;
  role: string;
  is_active: boolean;
  quota_limit: number;
  quota_used_today: number;
  total_jobs: number;
  created_at: string;
}

export interface BillingSummary {
  year: number;
  month: number;
  by_user: BillingUserEntry[];
  by_api_key: BillingKeyEntry[];
}

export interface BillingUserEntry {
  user_id: number;
  email: string;
  total_cost_usd: number;
  jobs_completed: number;
  jobs_failed: number;
  tier_breakdown: Record<string, { jobs: number; cost_usd: number }>;
}

export interface BillingKeyEntry {
  api_key_id: number;
  key_prefix: string;
  user_id: number;
  total_cost_usd: number;
  jobs_in_period: number;
  usage_count_total: number;
}
