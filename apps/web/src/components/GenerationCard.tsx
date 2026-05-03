"use client";

import { useEffect, useState } from "react";

import { type Clip, type GenerationDetail, api } from "@/lib/api";

interface Props {
  initial: GenerationDetail;
  onWinnerChosen?: (clip: Clip) => void;
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  generating: "Generating",
  downloading: "Downloading",
  scoring: "Scoring",
  succeeded: "Ready",
  failed: "Failed",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  generating: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  downloading: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
  scoring: "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-200",
  succeeded: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
};

export function GenerationCard({ initial, onWinnerChosen }: Props) {
  const [job, setJob] = useState<GenerationDetail>(initial);
  const [pickingId, setPickingId] = useState<string | null>(null);

  useEffect(() => {
    if (TERMINAL_STATUSES.has(job.status)) return;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const next = await api.getGeneration(job.id);
        if (!cancelled) setJob(next);
      } catch {
        // ignore transient errors
      }
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [job.id, job.status]);

  async function pickWinner(clipId: string) {
    setPickingId(clipId);
    try {
      const updated = await api.setWinner(job.id, clipId);
      setJob(updated);
      const winner = updated.clips.find((c) => c.id === clipId);
      if (winner && onWinnerChosen) onWinnerChosen(winner);
    } finally {
      setPickingId(null);
    }
  }

  const sortedClips = [...job.clips].sort((a, b) => {
    if (a.score == null && b.score == null) return a.variant_index - b.variant_index;
    if (a.score == null) return 1;
    if (b.score == null) return -1;
    return b.score - a.score;
  });

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{job.prompt}</p>
          <p className="mt-1 text-xs text-zinc-500">
            {job.n_variants} variants · {job.aspect_ratio} · {job.duration_seconds}s · {job.model}
          </p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_COLOR[job.status] ?? "bg-zinc-100 text-zinc-700"}`}>
          {job.status}
        </span>
      </header>

      {job.error && (
        <p className="mb-3 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {job.error}
        </p>
      )}

      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sortedClips.map((clip) => (
          <li
            key={clip.id}
            className={`flex flex-col gap-2 rounded-md border p-3 ${
              job.best_clip_id === clip.id
                ? "border-green-500 bg-green-50 dark:border-green-700 dark:bg-green-950"
                : "border-zinc-200 dark:border-zinc-800"
            }`}
          >
            <div className="flex items-center justify-between text-xs text-zinc-500">
              <span>Variant {clip.variant_index + 1}</span>
              <span className={`rounded-full px-2 py-0.5 ${STATUS_COLOR[clip.status] ?? "bg-zinc-100 text-zinc-700"}`}>
                {STATUS_LABEL[clip.status] ?? clip.status}
              </span>
            </div>

            {clip.public_url ? (
              <video
                src={clip.public_url}
                controls
                playsInline
                className="aspect-video w-full rounded bg-black"
              />
            ) : (
              <div className="flex aspect-video w-full items-center justify-center rounded bg-zinc-100 text-xs text-zinc-500 dark:bg-zinc-800">
                {clip.status === "failed" ? "Failed" : "Generating…"}
              </div>
            )}

            {clip.score != null && (
              <div>
                <p className="text-sm font-medium">Score: {clip.score.toFixed(0)}/100</p>
                {clip.score_explanation && (
                  <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
                    {clip.score_explanation}
                  </p>
                )}
              </div>
            )}

            {clip.error && (
              <p className="text-xs text-red-600 dark:text-red-400">{clip.error}</p>
            )}

            {clip.status === "succeeded" && job.best_clip_id !== clip.id && (
              <button
                type="button"
                disabled={pickingId === clip.id}
                onClick={() => pickWinner(clip.id)}
                className="rounded-md border border-zinc-300 px-3 py-1 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                {pickingId === clip.id ? "Saving…" : "Use this clip"}
              </button>
            )}
            {job.best_clip_id === clip.id && (
              <span className="text-xs font-medium text-green-700 dark:text-green-300">
                ★ Winner
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
