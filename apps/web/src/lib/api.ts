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
};
