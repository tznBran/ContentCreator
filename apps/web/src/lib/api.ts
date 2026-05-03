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
};
