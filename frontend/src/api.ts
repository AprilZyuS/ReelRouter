export type GenerationMode = "text_to_video" | "image_to_video";
export type JobStatus = "queued" | "processing" | "completed" | "failed";

export interface CreateJobInput {
  prompt: string;
  mode: GenerationMode;
  duration_seconds: number;
  budget_usd: number;
  min_quality_score: number;
  reference_image_url?: string;
}

export interface CostRecord {
  estimated_usd: number;
  reported_usd: number | null;
  source: "estimated" | "provider_reported";
}

export interface VideoJob {
  job_id: string;
  model_id: string;
  provider: string;
  status: JobStatus;
  cost: CostRecord;
  output_url: string | null;
  failure_code: string | null;
  failure_message: string | null;
  retryable: boolean | null;
  output_review: VideoOutputReview | null;
}

export interface VideoOutputReview {
  accepted: boolean;
  visual_quality_score: number;
  prompt_alignment_score: number;
  feedback: string;
}

export interface WorkflowResponse {
  thread_id: string;
  status: "submitted" | "awaiting_human_review" | "rejected" | "failed";
  selection: {
    model_id: string;
    estimated_cost_usd: number;
    reason: string;
  } | null;
  job: VideoJob | null;
  approval_status: "approved" | "rejected" | null;
  error: string | null;
  interrupt: {
    message: string;
    budget_reason: string;
    options: string[];
  } | null;
}

const baseUrl = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null && "detail" in payload
      ? String(payload.detail)
      : `请求失败（HTTP ${response.status}）。`;
    throw new Error(detail);
  }
  return payload as T;
}

export function createVideoJob(input: CreateJobInput) {
  return request<WorkflowResponse>("/video/jobs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function approveVideoJob(threadId: string, action: "approve" | "reject", feedback: string) {
  return request<WorkflowResponse>(`/video/jobs/${threadId}/approval`, {
    method: "POST",
    body: JSON.stringify({ action, feedback }),
  });
}

export function getVideoJob(jobId: string) {
  return request<VideoJob>(`/video/jobs/${jobId}`);
}

export function reviewVideoJob(jobId: string, review: VideoOutputReview) {
  return request<VideoJob>(`/video/jobs/${jobId}/output-review`, {
    method: "POST",
    body: JSON.stringify(review),
  });
}
