"use client";

import { useEffect, useState } from "react";

import {
  type CaptionSegment,
  type NarrationRead,
  type Voice,
  api,
} from "@/lib/api";

interface VoicePanelProps {
  projectId: string;
}

const TERMINAL_VOICE = new Set<Voice["status"]>(["ready", "failed"]);
const TERMINAL_NARRATION = new Set<NarrationRead["status"]>([
  "succeeded",
  "failed",
]);

export function VoicePanel({ projectId }: VoicePanelProps) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [narrations, setNarrations] = useState<NarrationRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Initial load + polling (voices and narrations).
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listVoices(), api.listNarrations(projectId)])
      .then(([v, n]) => {
        if (cancelled) return;
        setVoices(v);
        setNarrations(n);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load voices");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    const pendingVoices = voices.filter((v) => !TERMINAL_VOICE.has(v.status));
    const pendingNarrations = narrations.filter(
      (n) => !TERMINAL_NARRATION.has(n.status),
    );
    if (pendingVoices.length === 0 && pendingNarrations.length === 0) return;
    const handle = setInterval(async () => {
      const [vs, ns] = await Promise.all([
        Promise.all(
          pendingVoices.map((v) => api.getVoice(v.id).catch(() => v)),
        ),
        Promise.all(
          pendingNarrations.map((n) => api.getNarration(n.id).catch(() => n)),
        ),
      ]);
      setVoices((prev) => {
        const map = new Map(prev.map((v) => [v.id, v]));
        for (const u of vs) map.set(u.id, u);
        return Array.from(map.values()).sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        );
      });
      setNarrations((prev) => {
        const map = new Map(prev.map((n) => [n.id, n]));
        for (const u of ns) map.set(u.id, u);
        return Array.from(map.values()).sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        );
      });
    }, 3000);
    return () => clearInterval(handle);
  }, [voices, narrations]);

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600">{error}</p>}
      <VoiceCreateForm
        busy={busy}
        onCreate={async (form) => {
          setBusy(true);
          setError(null);
          try {
            const created = await api.createVoice(form);
            setVoices((prev) => [created, ...prev]);
          } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Voice upload failed");
          } finally {
            setBusy(false);
          }
        }}
      />

      {voices.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No voices yet. Record a 10–30s sample and upload above.
        </p>
      ) : (
        <ul className="space-y-2">
          {voices.map((v) => (
            <li
              key={v.id}
              className="rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800"
            >
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="font-medium">{v.name}</span>
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                  {v.status}
                </span>
                <span className="text-xs text-zinc-500">{v.provider}</span>
                {v.sample_public_url && (
                  <audio src={v.sample_public_url} controls className="h-8" />
                )}
                <button
                  type="button"
                  onClick={async () => {
                    await api.deleteVoice(v.id);
                    setVoices((prev) => prev.filter((x) => x.id !== v.id));
                  }}
                  className="ml-auto rounded border border-red-300 px-2 py-0.5 text-xs text-red-600 dark:border-red-700"
                >
                  Delete
                </button>
              </div>
              {v.error && (
                <p className="mt-1 text-xs text-red-600">{v.error}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      <hr className="border-zinc-200 dark:border-zinc-800" />

      <NarrationForm
        projectId={projectId}
        voices={voices.filter((v) => v.status === "ready")}
        onCreate={(narration) => setNarrations((prev) => [narration, ...prev])}
      />

      {narrations.length > 0 && (
        <ul className="space-y-2">
          {narrations.map((n) => (
            <NarrationRow key={n.id} narration={n} />
          ))}
        </ul>
      )}
    </div>
  );
}

interface VoiceCreateFormProps {
  busy: boolean;
  onCreate: (form: FormData) => Promise<void>;
}

function VoiceCreateForm({ busy, onCreate }: VoiceCreateFormProps) {
  const [name, setName] = useState("");
  const [referenceText, setReferenceText] = useState("");
  const [file, setFile] = useState<File | null>(null);

  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!file || !name.trim()) return;
        const form = new FormData();
        form.set("name", name.trim());
        if (referenceText.trim()) form.set("reference_text", referenceText.trim());
        form.set("audio", file);
        await onCreate(form);
        setName("");
        setReferenceText("");
        setFile(null);
      }}
    >
      <div className="flex flex-wrap gap-2">
        <input
          required
          type="text"
          placeholder="Voice name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 min-w-[140px] rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <input
          type="file"
          accept="audio/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="flex-1 min-w-[160px] text-xs"
        />
      </div>
      <textarea
        placeholder="Optional: transcript of the sample (improves clone quality for F5-TTS)"
        value={referenceText}
        onChange={(e) => setReferenceText(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
      />
      <button
        type="submit"
        disabled={busy || !file || !name.trim()}
        className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-50 hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
      >
        {busy ? "Uploading…" : "Upload voice sample"}
      </button>
    </form>
  );
}

interface NarrationFormProps {
  projectId: string;
  voices: Voice[];
  onCreate: (narration: NarrationRead) => void;
}

function NarrationForm({ projectId, voices, onCreate }: NarrationFormProps) {
  const [chosenVoiceId, setChosenVoiceId] = useState<string>("");
  const [script, setScript] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Effective voiceId: explicit choice if it still matches an available voice,
  // otherwise the first ready voice. This avoids `setState` inside an effect
  // (forbidden by react-hooks/set-state-in-effect lint rule).
  const voiceId =
    chosenVoiceId && voices.some((v) => v.id === chosenVoiceId)
      ? chosenVoiceId
      : voices[0]?.id ?? "";

  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!voiceId || !script.trim()) return;
        setBusy(true);
        setError(null);
        try {
          const narration = await api.createNarration(projectId, {
            voice_id: voiceId,
            script: script.trim(),
          });
          onCreate(narration);
          setScript("");
        } catch (err: unknown) {
          setError(err instanceof Error ? err.message : "Narration failed");
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="text-sm font-medium">Generate narration</p>
      {voices.length === 0 ? (
        <p className="text-xs text-zinc-500">
          Upload a voice sample first; the voice must be in &ldquo;ready&rdquo; state.
        </p>
      ) : (
        <>
          <select
            value={voiceId}
            onChange={(e) => setChosenVoiceId(e.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
          >
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
          <textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder="Paste the narration script here…"
            rows={3}
            className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="submit"
            disabled={busy || !script.trim()}
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-50 hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
          >
            {busy ? "Synthesizing…" : "Generate narration + captions"}
          </button>
          {error && <p className="text-xs text-red-600">{error}</p>}
        </>
      )}
    </form>
  );
}

function NarrationRow({ narration }: { narration: NarrationRead }) {
  let captions: CaptionSegment[] = [];
  if (narration.captions_json) {
    try {
      captions = JSON.parse(narration.captions_json) as CaptionSegment[];
    } catch {
      captions = [];
    }
  }
  return (
    <li className="rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
          {narration.status}
        </span>
        {narration.duration_ms != null && (
          <span className="text-xs text-zinc-500">
            {(narration.duration_ms / 1000).toFixed(1)}s
          </span>
        )}
        {narration.public_url && (
          <audio src={narration.public_url} controls className="h-8" />
        )}
      </div>
      <p className="mt-1 truncate text-xs text-zinc-500">{narration.script}</p>
      {narration.error && (
        <p className="mt-1 text-xs text-red-600">{narration.error}</p>
      )}
      {captions.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-zinc-500">
            Captions ({captions.length} segments)
          </summary>
          <ol className="mt-2 space-y-1 text-xs">
            {captions.map((seg, idx) => (
              <li key={idx} className="font-mono">
                {(seg.start_ms / 1000).toFixed(2)}–{(seg.end_ms / 1000).toFixed(2)}s
                <span className="ml-2 font-sans">{seg.text}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </li>
  );
}
