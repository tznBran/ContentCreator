"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { ApiError, type Project, api } from "@/lib/api";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ProjectDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getProject(id)
      .then((p) => {
        if (!cancelled) setProject(p);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setError("Project not found.");
        } else if (err instanceof ApiError) {
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
  }, [id]);

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-12">
      <Link
        href="/projects"
        className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-50"
      >
        ← All projects
      </Link>

      {error && <p className="mt-6 text-sm text-red-600">{error}</p>}

      {!error && project === null && (
        <p className="mt-6 text-sm text-zinc-500">Loading…</p>
      )}

      {project && (
        <article className="mt-6 space-y-6">
          <header className="flex items-start justify-between gap-4">
            <h1 className="text-2xl font-semibold tracking-tight">
              {project.title}
            </h1>
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
              {project.status}
            </span>
          </header>

          {project.prompt && (
            <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                Prompt
              </h2>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                {project.prompt}
              </p>
            </section>
          )}

          <section className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
            Clip generation, timeline editor, voice clone, and publishing land
            in phases 1–4. This page will become the project workspace.
          </section>
        </article>
      )}
    </div>
  );
}
