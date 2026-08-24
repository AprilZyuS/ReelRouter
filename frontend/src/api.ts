export type ShotImportance = "key" | "standard";
export type JobStatus = "queued" | "processing" | "completed" | "failed";

export interface ProjectInput {
  project_id: string;
  title: string;
  keywords: string[];
  genre: string;
  visual_style: string;
  episode_duration_seconds: number;
  episode_budget_usd: number;
  enable_assembly: boolean;
  confirm_paid_call: boolean;
}

export interface ProjectProfile {
  project_id: string;
  manuscript_document_id: string;
  title: string;
  logline: string;
  style_bible: string;
  planned_episode_count: number;
  keywords: string[];
  genre: string;
  episode_duration_seconds: number;
  episode_budget_usd: number;
  enable_assembly: boolean;
  narrative_version: number;
}

export interface Manuscript {
  project_id: string;
  title: string;
  logline: string;
  manuscript: string;
  style_bible: string;
  planned_episode_count: number;
}

export interface EpisodePlan {
  project_id: string;
  episode_number: number;
  title: string;
  target_duration_seconds: number;
  episode_goal: string;
  closing_hook: string;
  source_chunk_ids: string[];
}

export interface EpisodeReadiness {
  episode_number: number;
  screenplay_approved: boolean;
  previous_episode_summary_ready: boolean;
  storyboard_ready: boolean;
  screenplay_block_reason: string | null;
}

export interface ScreenplayScene {
  scene_id: string;
  order: number;
  narration: string;
  dialogue: string;
  visual_description: string;
  duration_seconds: number;
  source_chunk_ids: string[];
}

export interface ScreenplayCandidate {
  candidate_id: string;
  status: "draft" | "reviewed" | "approved" | "rejected";
  screenplay: {
    project_id: string;
    episode_number: number;
    target_duration_seconds: number;
    scenes: ScreenplayScene[];
  };
  review: {
    passed: boolean;
    feedback: string;
    violations: string[];
    episode_summary: { recap: string; unresolved_loops: string[] } | null;
  } | null;
}

export interface PrioritizedShot {
  shot_id: string;
  scene_id: string;
  order: number;
  visual_prompt: string;
  camera_instruction: string;
  duration_seconds: number;
  source_chunk_ids: string[];
  importance: ShotImportance;
  priority_reason: string;
  min_quality_score: number;
}

export interface PrioritizedStoryboard {
  project_id: string;
  episode_number: number;
  target_duration_seconds: number;
  shots: PrioritizedShot[];
}

export interface VideoJob {
  job_id: string;
  model_id: string;
  provider: string;
  status: JobStatus;
  cost: { estimated_usd: number; reported_usd: number | null; source: string };
  output_url: string | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface VideoPlan {
  estimated_total_usd: number;
  episode_budget_usd: number;
  shots: Array<{
    shot_id: string;
    model_id: string;
    estimated_cost_usd: number;
    mode: string;
    prompt: string;
    importance: ShotImportance;
  }>;
}

const baseUrl = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...options, headers });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null && "detail" in payload
      ? String(payload.detail)
      : `请求失败（HTTP ${response.status}）。`;
    throw new Error(detail);
  }
  return payload as T;
}

export function createNarrativeProject(input: ProjectInput) {
  return request<{ profile: ProjectProfile; manuscript: Manuscript; chunk_count: number }>("/narrative/projects", {
    method: "POST", body: JSON.stringify(input),
  });
}

export function getNarrativeProject(projectId: string) {
  return request<{ profile: ProjectProfile; episodes: EpisodePlan[]; episode_readiness: EpisodeReadiness[] }>(`/narrative/projects/${projectId}`);
}

export function planEpisodes(projectId: string, episodeCount: number) {
  return request<{ plans: EpisodePlan[] }>(`/narrative/projects/${projectId}/episodes/plan`, {
    method: "POST", body: JSON.stringify({ confirm_paid_call: true, episode_count: episodeCount }),
  });
}

export function writeScreenplay(projectId: string, episodeNumber: number) {
  return request<{ candidate: ScreenplayCandidate }>(`/narrative/projects/${projectId}/episodes/screenplay`, {
    method: "POST", body: JSON.stringify({ confirm_paid_call: true, episode_number: episodeNumber }),
  });
}

export function getScreenplayCandidate(candidateId: string) {
  return request<{ candidate: ScreenplayCandidate }>(`/narrative/screenplay-candidates/${candidateId}`);
}

export function reviewScreenplay(candidateId: string) {
  return request<{ candidate: ScreenplayCandidate }>(`/narrative/screenplay-candidates/${candidateId}/review`, {
    method: "POST", body: JSON.stringify({ confirm_paid_call: true }),
  });
}

export function approveScreenplay(candidateId: string) {
  return request<{ candidate: ScreenplayCandidate }>(`/narrative/screenplay-candidates/${candidateId}/approve`, {
    method: "POST", body: JSON.stringify({ confirm_human_approval: true }),
  });
}

export function createStoryboard(projectId: string, episodeNumber: number) {
  return request<{ storyboard: PrioritizedStoryboard }>(`/narrative/projects/${projectId}/episodes/storyboard`, {
    method: "POST", body: JSON.stringify({ confirm_paid_call: true, episode_number: episodeNumber }),
  });
}

export function getStoryboard(projectId: string, episodeNumber: number) {
  return request<{ storyboard: PrioritizedStoryboard }>(`/narrative/projects/${projectId}/episodes/${episodeNumber}/storyboard`);
}

export function previewEpisodeVideos(projectId: string, episodeNumber: number) {
  return request<VideoPlan>(`/narrative/projects/${projectId}/episodes/${episodeNumber}/video-plan`, {
    method: "POST", body: JSON.stringify({ require_reference_assets: false }),
  });
}

export function executeEpisodeVideos(projectId: string, episodeNumber: number) {
  return request<{ estimated_total_usd: number }>(`/narrative/projects/${projectId}/episodes/${episodeNumber}/videos`, {
    method: "POST", body: JSON.stringify({ confirm_video_execution: true, require_reference_assets: false }),
  });
}

export function pollEpisodeVideos(projectId: string, episodeNumber: number) {
  return request<{ jobs: VideoJob[]; terminal: boolean }>(`/narrative/projects/${projectId}/episodes/${episodeNumber}/videos`);
}
