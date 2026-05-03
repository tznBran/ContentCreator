"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, type Project, api } from "@/lib/api";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listProjects()
      .then((rows) => {
        if (!cancelled) setProjects(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError) {
          setError(`API error ${err.status}`);
        } else if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("Unknown error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-12">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <Link
          href="/projects/new"
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
        >
          New project
        </Link>
      </div>

      {error && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          Couldn&apos;t reach the API: {error}. Make sure the backend is running on{" "}
          <code>{process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}</code>
          .
        </div>
      )}

      {!error && projects === null && (
        <p className="mt-6 text-sm text-zinc-500">Loading…</p>
      )}

      {!error && projects?.length === 0 && (
        <div className="mt-6 rounded-md border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
          No projects yet. Create your first one.
        </div>
      )}

      {!error && projects && projects.length > 0 && (
        <ul className="mt-6 space-y-3">
          {projects.map((project) => (
            <li key={project.id}>
              <Link
                href={`/projects/${project.id}`}
                className="block rounded-lg border border-zinc-200 bg-white p-4 hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"
              >
                <div className="flex items-center justify-between">
                  <h2 className="font-medium">{project.title}</h2>
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                    {project.status}
                  </span>
                </div>
                {project.prompt && (
                  <p className="mt-1 line-clamp-2 text-sm text-zinc-600 dark:text-zinc-400">
                    {project.prompt}
                  </p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
