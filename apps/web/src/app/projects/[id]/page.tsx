"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { GenerateClipForm } from "@/components/GenerateClipForm";
import { GenerationCard } from "@/components/GenerationCard";
import {
  ApiError,
  type Generation,
  type GenerationDetail,
  type Project,
  api,
} from "@/lib/api";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ProjectDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generations, setGenerations] = useState<GenerationDetail[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getProject(id), api.listGenerations(id)])
      .then(async ([p, jobs]) => {
        if (cancelled) return;
        setProject(p);
        const details = await Promise.all(jobs.map((j: Generation) => api.getGeneration(j.id)));
        if (!cancelled) setGenerations(details);
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
    <div className="mx-auto w-full max-w-5xl px-6 py-12">
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
        <article className="mt-6 space-y-8">
          <header className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                {project.title}
              </h1>
              {project.prompt && (
                <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                  {project.prompt}
                </p>
              )}
            </div>
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
              {project.status}
            </span>
          </header>

          <section>
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">
              Generate clips
            </h2>
            <GenerateClipForm
              projectId={project.id}
              defaultPrompt={project.prompt}
              onCreated={(job) => setGenerations((current) => [job, ...current])}
            />
          </section>

          <section>
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">
              Generations
            </h2>
            {generations.length === 0 ? (
              <p className="rounded-md border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700">
                No generations yet. Submit the form above to spawn N Seedance 2.0
                variants. The API queues them as RQ jobs; this page polls every
                3 seconds while they run.
              </p>
            ) : (
              <div className="space-y-4">
                {generations.map((g) => (
                  <GenerationCard key={g.id} initial={g} />
                ))}
              </div>
            )}
          </section>
        </article>
      )}
    </div>
  );
}
