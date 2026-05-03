/**
 * Thin typed client for the ContentCreator FastAPI backend.
 *
 * All methods throw `ApiError` on non-2xx responses so callers can distinguish
 * "the server said no" from network failures.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type ProjectStatus =
  | "draft"
  | "generating"
  | "ready"
  | "published"
  | "archived";

export interface Project {
  id: string;
  title: string;
  prompt: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  title: string;
  prompt?: string;
}

export interface ProjectUpdate {
  title?: string;
  prompt?: string;
  status?: ProjectStatus;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Ignore — body might be empty or non-JSON.
    }
    throw new ApiError(
      `API ${response.status} on ${path}`,
      response.status,
      body,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type ClipStatus =
  | "pending"
  | "generating"
  | "downloading"
  | "scoring"
  | "succeeded"
  | "failed";

export type GenerationStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Clip {
  id: string;
  project_id: string;
  generation_job_id: string | null;
  variant_index: number;
  prompt: string;
  status: ClipStatus;
  storage_key: string | null;
  public_url: string | null;
  duration_seconds: number | null;
  score: number | null;
  score_explanation: string | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Generation {
  id: string;
  project_id: string;
  prompt: string;
  n_variants: number;
  aspect_ratio: string;
  duration_seconds: number;
  model: string;
  status: GenerationStatus;
  best_clip_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface GenerationDetail extends Generation {
  clips: Clip[];
}

export interface GenerationCreate {
  prompt: string;
  n_variants?: number;
  aspect_ratio?: string;
  duration_seconds?: number;
  model?: string;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: ProjectCreate) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateProject: (id: string, payload: ProjectUpdate) =>
    request<Project>(`/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),

  listGenerations: (projectId: string) =>
    request<Generation[]>(`/projects/${projectId}/generations`),
  createGeneration: (projectId: string, payload: GenerationCreate) =>
    request<GenerationDetail>(`/projects/${projectId}/generations`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getGeneration: (jobId: string) =>
    request<GenerationDetail>(`/generations/${jobId}`),
  setWinner: (jobId: string, clipId: string) =>
    request<GenerationDetail>(`/generations/${jobId}/winner`, {
      method: "POST",
      body: JSON.stringify({ clip_id: clipId }),
    }),
  getClip: (clipId: string) => request<Clip>(`/clips/${clipId}`),

  // Storyboard / shots (Phase 2)
  listShots: (projectId: string) =>
    request<Shot[]>(`/projects/${projectId}/shots`),
  createShot: (projectId: string, payload: ShotCreate) =>
    request<Shot>(`/projects/${projectId}/shots`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateShot: (shotId: string, payload: Partial<ShotCreate> & { selected_clip_id?: string | null }) =>
    request<Shot>(`/shots/${shotId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteShot: (shotId: string) =>
    request<void>(`/shots/${shotId}`, { method: "DELETE" }),
  generateStoryboard: (projectId: string, payload: StoryboardCreate) =>
    request<Shot[]>(`/projects/${projectId}/storyboard`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generateShotClips: (shotId: string, nVariants = 3) =>
    request<GenerationDetail>(
      `/shots/${shotId}/generations?n_variants=${nVariants}`,
      { method: "POST" },
    ),

  // Timeline (Phase 2)
  getTimeline: (projectId: string) =>
    request<TimelineItem[]>(`/projects/${projectId}/timeline`),
  putTimeline: (projectId: string, items: TimelineItemWrite[]) =>
    request<TimelineItem[]>(`/projects/${projectId}/timeline`, {
      method: "PUT",
      body: JSON.stringify({ items }),
    }),

  // Exports (Phase 2)
  createExport: (projectId: string, payload: ExportCreate) =>
    request<ExportRead>(`/projects/${projectId}/exports`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listExports: (projectId: string) =>
    request<ExportRead[]>(`/projects/${projectId}/exports`),
  getExport: (exportId: string) => request<ExportRead>(`/exports/${exportId}`),
};

// --- Phase 2 types ---

export interface Shot {
  id: string;
  project_id: string;
  order_index: number;
  prompt: string;
  duration_seconds: number;
  aspect_ratio: string;
  notes: string | null;
  generation_job_id: string | null;
  selected_clip_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ShotCreate {
  prompt: string;
  duration_seconds?: number;
  aspect_ratio?: string;
  notes?: string | null;
  order_index?: number;
}

export interface StoryboardCreate {
  prompt?: string;
  n_shots?: number;
  total_duration_seconds?: number;
  aspect_ratio?: string;
}

export type TimelineItemType = "clip" | "audio" | "text";

export interface TimelineItem {
  id: string;
  project_id: string;
  order_index: number;
  item_type: TimelineItemType;
  clip_id: string | null;
  source_start_ms: number;
  duration_ms: number;
  transition_in: string | null;
  transition_out: string | null;
  text_overlay: string | null;
  audio_storage_key: string | null;
  volume: number;
  created_at: string;
  updated_at: string;
}

export interface TimelineItemWrite {
  id?: string;
  item_type?: TimelineItemType;
  clip_id?: string | null;
  source_start_ms?: number;
  duration_ms?: number;
  transition_in?: string | null;
  transition_out?: string | null;
  text_overlay?: string | null;
  audio_storage_key?: string | null;
  volume?: number;
}

export type ExportStatus =
  | "pending"
  | "rendering"
  | "uploading"
  | "succeeded"
  | "failed";

export interface ExportRead {
  id: string;
  project_id: string;
  status: ExportStatus;
  width: number;
  height: number;
  fps: number;
  storage_key: string | null;
  public_url: string | null;
  duration_ms: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExportCreate {
  width?: number;
  height?: number;
  fps?: number;
}
