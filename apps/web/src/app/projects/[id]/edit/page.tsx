"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";

import {
  type Clip,
  type ExportRead,
  type GenerationDetail,
  type Project,
  type Shot,
  type TimelineItem,
  type TimelineItemWrite,
  api,
} from "@/lib/api";

interface PageProps {
  params: Promise<{ id: string }>;
}

const TERMINAL_GENERATION_STATUSES = new Set(["succeeded", "failed", "cancelled"]);
const TERMINAL_EXPORT_STATUSES = new Set(["succeeded", "failed"]);

export default function ProjectEditorPage({ params }: PageProps) {
  const { id: projectId } = use(params);

  const [project, setProject] = useState<Project | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [exports, setExports] = useState<ExportRead[]>([]);
  const [shotGenerations, setShotGenerations] = useState<Record<string, GenerationDetail>>({});
  const [shotClips, setShotClips] = useState<Record<string, Clip[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.getProject(projectId),
      api.listShots(projectId),
      api.getTimeline(projectId),
      api.listExports(projectId),
    ])
      .then(([p, s, t, e]) => {
        if (cancelled) return;
        setProject(p);
        setShots(s);
        setItems(t);
        setExports(e);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof Error) setError(err.message);
        else setError("Failed to load project");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Poll active shot generations.
  useEffect(() => {
    const ids = Object.entries(shotGenerations)
      .filter(([, g]) => !TERMINAL_GENERATION_STATUSES.has(g.status))
      .map(([shotId, g]) => ({ shotId, jobId: g.id }));
    if (ids.length === 0) return;
    const handle = setInterval(async () => {
      for (const { shotId, jobId } of ids) {
        try {
          const next = await api.getGeneration(jobId);
          setShotGenerations((prev) => ({ ...prev, [shotId]: next }));
          setShotClips((prev) => ({ ...prev, [shotId]: next.clips }));
          // If finalized with a winner and shot has no selection, default it.
          if (next.best_clip_id) {
            setShots((prev) =>
              prev.map((s) =>
                s.id === shotId && !s.selected_clip_id
                  ? { ...s, selected_clip_id: next.best_clip_id }
                  : s,
              ),
            );
          }
        } catch {
          // ignore transient
        }
      }
    }, 3000);
    return () => clearInterval(handle);
  }, [shotGenerations]);

  // Poll active exports.
  useEffect(() => {
    const active = exports.filter((e) => !TERMINAL_EXPORT_STATUSES.has(e.status));
    if (active.length === 0) return;
    const handle = setInterval(async () => {
      const updated = await Promise.all(
        active.map((e) => api.getExport(e.id).catch(() => e)),
      );
      setExports((prev) => {
        const map = new Map(prev.map((e) => [e.id, e]));
        for (const u of updated) map.set(u.id, u);
        return Array.from(map.values()).sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        );
      });
    }, 3000);
    return () => clearInterval(handle);
  }, [exports]);

  const generateStoryboard = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await api.generateStoryboard(projectId, {
        n_shots: 5,
        total_duration_seconds: 30,
      });
      setShots(out);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Storyboard failed");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  const addEmptyShot = useCallback(async () => {
    const created = await api.createShot(projectId, {
      prompt: "New shot",
      duration_seconds: 5,
    });
    setShots((prev) => [...prev, created]);
  }, [projectId]);

  const updateShot = useCallback(
    async (shotId: string, patch: Partial<Shot>) => {
      // optimistic
      setShots((prev) => prev.map((s) => (s.id === shotId ? { ...s, ...patch } : s)));
      await api.updateShot(shotId, patch);
    },
    [],
  );

  const deleteShot = useCallback(async (shotId: string) => {
    await api.deleteShot(shotId);
    setShots((prev) => prev.filter((s) => s.id !== shotId));
  }, []);

  const generateShot = useCallback(async (shotId: string, n: number) => {
    const job = await api.generateShotClips(shotId, n);
    setShotGenerations((prev) => ({ ...prev, [shotId]: job }));
    setShotClips((prev) => ({ ...prev, [shotId]: job.clips }));
  }, []);

  const buildTimelineFromShots = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const ordered = [...shots].sort((a, b) => a.order_index - b.order_index);
      const writes: TimelineItemWrite[] = ordered
        .filter((s) => s.selected_clip_id)
        .map((s) => ({
          item_type: "clip",
          clip_id: s.selected_clip_id,
          source_start_ms: 0,
          duration_ms: s.duration_seconds * 1000,
        }));
      const out = await api.putTimeline(projectId, writes);
      setItems(out);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to build timeline");
    } finally {
      setBusy(false);
    }
  }, [projectId, shots]);

  const moveItem = useCallback(
    async (index: number, dir: -1 | 1) => {
      const newIndex = index + dir;
      if (newIndex < 0 || newIndex >= items.length) return;
      const reordered = [...items];
      [reordered[index], reordered[newIndex]] = [reordered[newIndex], reordered[index]];
      setItems(reordered);
      await api.putTimeline(
        projectId,
        reordered.map((it) => ({
          id: it.id,
          item_type: it.item_type,
          clip_id: it.clip_id,
          source_start_ms: it.source_start_ms,
          duration_ms: it.duration_ms,
          transition_in: it.transition_in,
          transition_out: it.transition_out,
          text_overlay: it.text_overlay,
          audio_storage_key: it.audio_storage_key,
          volume: it.volume,
        })),
      );
    },
    [items, projectId],
  );

  const trimItem = useCallback(
    async (itemId: string, durationMs: number) => {
      setItems((prev) =>
        prev.map((it) =>
          it.id === itemId ? { ...it, duration_ms: durationMs } : it,
        ),
      );
      const next = items.map((it) =>
        it.id === itemId ? { ...it, duration_ms: durationMs } : it,
      );
      await api.putTimeline(
        projectId,
        next.map((it) => ({
          id: it.id,
          clip_id: it.clip_id,
          source_start_ms: it.source_start_ms,
          duration_ms: it.duration_ms,
          item_type: it.item_type,
        })),
      );
    },
    [items, projectId],
  );

  const removeItem = useCallback(
    async (itemId: string) => {
      const next = items.filter((it) => it.id !== itemId);
      setItems(next);
      await api.putTimeline(
        projectId,
        next.map((it) => ({
          id: it.id,
          clip_id: it.clip_id,
          source_start_ms: it.source_start_ms,
          duration_ms: it.duration_ms,
          item_type: it.item_type,
        })),
      );
    },
    [items, projectId],
  );

  const triggerExport = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await api.createExport(projectId, {
        width: 1080,
        height: 1920,
        fps: 30,
      });
      setExports((prev) => [job, ...prev]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  const totalDurationMs = useMemo(
    () => items.reduce((sum, it) => sum + it.duration_ms, 0),
    [items],
  );

  if (error && !project) {
    return (
      <div className="mx-auto w-full max-w-5xl p-6">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="mx-auto w-full max-w-5xl p-6">
        <p className="text-sm text-zinc-500">Loading…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-6 py-10">
      <div className="flex items-center gap-3 text-sm text-zinc-500">
        <Link href={`/projects/${projectId}`} className="hover:text-zinc-900 dark:hover:text-zinc-50">
          ← {project.title}
        </Link>
        <span>/ Editor</span>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Storyboard
        </h2>
        <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mb-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={generateStoryboard}
              disabled={busy}
              className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-50 hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
            >
              Generate storyboard from prompt
            </button>
            <button
              type="button"
              onClick={addEmptyShot}
              disabled={busy}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Add empty shot
            </button>
            <button
              type="button"
              onClick={buildTimelineFromShots}
              disabled={busy || shots.length === 0}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Build timeline from shots
            </button>
          </div>

          {shots.length === 0 ? (
            <p className="text-sm text-zinc-500">
              No shots yet. Generate a storyboard or add a shot manually.
            </p>
          ) : (
            <ol className="space-y-3">
              {shots.map((shot) => (
                <ShotRow
                  key={shot.id}
                  shot={shot}
                  generation={shotGenerations[shot.id]}
                  clips={shotClips[shot.id] ?? []}
                  onUpdate={(patch) => updateShot(shot.id, patch)}
                  onDelete={() => deleteShot(shot.id)}
                  onGenerate={(n) => generateShot(shot.id, n)}
                />
              ))}
            </ol>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Timeline ({(totalDurationMs / 1000).toFixed(1)}s)
        </h2>
        <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          {items.length === 0 ? (
            <p className="text-sm text-zinc-500">
              Timeline is empty. Click &ldquo;Build timeline from shots&rdquo;
              once the storyboard has selected clips.
            </p>
          ) : (
            <ol className="space-y-3">
              {items.map((it, index) => (
                <TimelineRow
                  key={it.id}
                  item={it}
                  index={index}
                  total={items.length}
                  onMove={(dir) => moveItem(index, dir)}
                  onTrim={(ms) => trimItem(it.id, ms)}
                  onRemove={() => removeItem(it.id)}
                />
              ))}
            </ol>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Export
        </h2>
        <div className="space-y-3 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <button
            type="button"
            onClick={triggerExport}
            disabled={busy || items.length === 0}
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-50 hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
          >
            Render timeline to mp4
          </button>
          {exports.length === 0 ? (
            <p className="text-sm text-zinc-500">
              No exports yet. Once you render, the latest mp4 will appear here.
            </p>
          ) : (
            <ul className="space-y-2">
              {exports.map((e) => (
                <li
                  key={e.id}
                  className="flex flex-wrap items-center gap-3 rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800"
                >
                  <span className="font-mono text-xs">{e.id.slice(0, 8)}</span>
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                    {e.status}
                  </span>
                  <span className="text-xs text-zinc-500">
                    {e.width}×{e.height} @ {e.fps}fps
                  </span>
                  {e.public_url && (
                    <a
                      href={e.public_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-600 underline dark:text-blue-400"
                    >
                      Download mp4
                    </a>
                  )}
                  {e.error && (
                    <span className="text-xs text-red-600">{e.error}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

interface ShotRowProps {
  shot: Shot;
  generation: GenerationDetail | undefined;
  clips: Clip[];
  onUpdate: (patch: Partial<Shot>) => void;
  onDelete: () => void;
  onGenerate: (n: number) => void;
}

function ShotRow({ shot, generation, clips, onUpdate, onDelete, onGenerate }: ShotRowProps) {
  const [pending, setPending] = useState(false);
  return (
    <li className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex items-start gap-3">
        <span className="mt-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-medium dark:bg-zinc-800">
          {shot.order_index + 1}
        </span>
        <div className="flex-1 space-y-2">
          <input
            type="text"
            value={shot.prompt}
            onChange={(e) => onUpdate({ prompt: e.target.value })}
            className="block w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            <label>
              Duration{" "}
              <input
                type="number"
                min={1}
                max={30}
                value={shot.duration_seconds}
                onChange={(e) =>
                  onUpdate({ duration_seconds: Number(e.target.value) })
                }
                className="w-14 rounded border border-zinc-300 bg-white px-1 dark:border-zinc-700 dark:bg-zinc-900"
              />
              s
            </label>
            <button
              type="button"
              disabled={pending}
              onClick={async () => {
                setPending(true);
                try {
                  await onGenerate(3);
                } finally {
                  setPending(false);
                }
              }}
              className="rounded-md border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              {pending ? "…" : "Generate 3 variants"}
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="rounded-md border border-red-300 px-2 py-0.5 text-xs text-red-600 hover:bg-red-50 dark:border-red-700 dark:hover:bg-red-950"
            >
              Delete
            </button>
          </div>

          {generation && (
            <div className="text-xs text-zinc-500">
              Generation: {generation.status}
              {clips.length > 0 && (
                <ul className="mt-2 grid gap-2 sm:grid-cols-3">
                  {clips
                    .slice()
                    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
                    .map((clip) => (
                      <li
                        key={clip.id}
                        className={`rounded border p-1.5 ${
                          shot.selected_clip_id === clip.id
                            ? "border-green-500"
                            : "border-zinc-200 dark:border-zinc-800"
                        }`}
                      >
                        {clip.public_url ? (
                          <video
                            src={clip.public_url}
                            controls
                            playsInline
                            className="aspect-video w-full rounded bg-black"
                          />
                        ) : (
                          <div className="flex aspect-video items-center justify-center bg-zinc-100 text-xs dark:bg-zinc-800">
                            {clip.status}
                          </div>
                        )}
                        <div className="mt-1 flex items-center justify-between">
                          <span className="text-xs">
                            {clip.score != null ? `${clip.score.toFixed(0)}/100` : clip.status}
                          </span>
                          {clip.status === "succeeded" && (
                            <button
                              type="button"
                              onClick={() => onUpdate({ selected_clip_id: clip.id })}
                              className="text-xs text-blue-600 underline dark:text-blue-400"
                            >
                              {shot.selected_clip_id === clip.id ? "Selected" : "Use"}
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

interface TimelineRowProps {
  item: TimelineItem;
  index: number;
  total: number;
  onMove: (dir: -1 | 1) => void;
  onTrim: (ms: number) => void;
  onRemove: () => void;
}

function TimelineRow({ item, index, total, onMove, onTrim, onRemove }: TimelineRowProps) {
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-zinc-100 text-xs font-medium dark:bg-zinc-800">
        {index + 1}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium">
          {item.item_type === "clip" ? `Clip ${item.clip_id?.slice(0, 8)}` : item.item_type}
        </p>
        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
          <label className="flex items-center gap-1">
            Duration
            <input
              type="number"
              min={0.5}
              step={0.5}
              value={(item.duration_ms / 1000).toFixed(1)}
              onChange={(e) =>
                onTrim(Math.max(100, Math.round(Number(e.target.value) * 1000)))
              }
              className="w-16 rounded border border-zinc-300 bg-white px-1 dark:border-zinc-700 dark:bg-zinc-900"
            />
            s
          </label>
          <span>start {item.source_start_ms}ms</span>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={index === 0}
          onClick={() => onMove(-1)}
          className="rounded border border-zinc-300 px-2 py-0.5 text-xs disabled:opacity-30 dark:border-zinc-700"
        >
          ↑
        </button>
        <button
          type="button"
          disabled={index === total - 1}
          onClick={() => onMove(1)}
          className="rounded border border-zinc-300 px-2 py-0.5 text-xs disabled:opacity-30 dark:border-zinc-700"
        >
          ↓
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="rounded border border-red-300 px-2 py-0.5 text-xs text-red-600 dark:border-red-700"
        >
          Remove
        </button>
      </div>
    </li>
  );
}
