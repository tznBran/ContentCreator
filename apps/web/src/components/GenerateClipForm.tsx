"use client";

import { type FormEvent, useState } from "react";

import { ApiError, type GenerationDetail, api } from "@/lib/api";

interface Props {
  projectId: string;
  defaultPrompt?: string;
  onCreated: (job: GenerationDetail) => void;
}

const ASPECT_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4"] as const;

export function GenerateClipForm({ projectId, defaultPrompt = "", onCreated }: Props) {
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [nVariants, setNVariants] = useState(3);
  const [aspectRatio, setAspectRatio] = useState<typeof ASPECT_RATIOS[number]>("9:16");
  const [durationSeconds, setDurationSeconds] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createGeneration(projectId, {
        prompt,
        n_variants: nVariants,
        aspect_ratio: aspectRatio,
        duration_seconds: durationSeconds,
      });
      onCreated(job);
    } catch (err: unknown) {
      if (err instanceof ApiError) setError(`API error ${err.status}`);
      else if (err instanceof Error) setError(err.message);
      else setError("Unknown error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900"
    >
      <div>
        <label htmlFor="g-prompt" className="block text-sm font-medium">
          Prompt
        </label>
        <textarea
          id="g-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          required
          maxLength={4000}
          placeholder="A 5-second cinematic shot of a cat surfing a neon wave at night."
          className="mt-2 block w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-800"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="g-variants" className="block text-sm font-medium">
            Variants ({nVariants})
          </label>
          <input
            id="g-variants"
            type="range"
            min={1}
            max={6}
            value={nVariants}
            onChange={(e) => setNVariants(Number(e.target.value))}
            className="mt-2 w-full"
          />
        </div>
        <div>
          <label htmlFor="g-aspect" className="block text-sm font-medium">
            Aspect ratio
          </label>
          <select
            id="g-aspect"
            value={aspectRatio}
            onChange={(e) => setAspectRatio(e.target.value as typeof ASPECT_RATIOS[number])}
            className="mt-2 block w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm dark:border-zinc-700 dark:bg-zinc-800"
          >
            {ASPECT_RATIOS.map((ar) => (
              <option key={ar} value={ar}>
                {ar}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="g-duration" className="block text-sm font-medium">
            Duration ({durationSeconds}s)
          </label>
          <input
            id="g-duration"
            type="range"
            min={3}
            max={15}
            value={durationSeconds}
            onChange={(e) => setDurationSeconds(Number(e.target.value))}
            className="mt-2 w-full"
          />
        </div>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !prompt.trim()}
        className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-50 hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
      >
        {submitting ? "Submitting…" : `Generate ${nVariants} variants`}
      </button>
    </form>
  );
}
