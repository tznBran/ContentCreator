import Link from "next/link";

const features = [
  {
    title: "AI clip generation",
    description:
      "Turn a prompt into shot lists and generate video with Seedance 2.0 via OpenRouter. Multiple variants per shot, scored automatically.",
  },
  {
    title: "Full-timeline editor",
    description:
      "Trim, reorder, layer captions, overlays, and BGM on a multi-track timeline. Render with Remotion + ffmpeg.",
  },
  {
    title: "Voice cloning",
    description:
      "Record ~30 seconds of your voice and narrate any project in your own voice with self-hosted F5-TTS.",
  },
  {
    title: "One-click publishing",
    description:
      "Connect TikTok, YouTube, and Instagram once, then publish the same video everywhere with per-platform metadata.",
  },
];

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-16 px-6 py-16">
      <section className="flex flex-col items-start gap-6">
        <span className="rounded-full border border-zinc-200 px-3 py-1 text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          Phase 0 · skeleton
        </span>
        <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
          Prompt to published video, in one place.
        </h1>
        <p className="max-w-2xl text-lg leading-7 text-zinc-600 dark:text-zinc-400">
          ContentCreator generates AI clips with Seedance 2.0, stitches them on a
          full-timeline editor, narrates them in your cloned voice, and uploads to
          TikTok, YouTube, and Instagram. This page is the skeleton — features
          land as we ship phases 1–4.
        </p>
        <div className="flex gap-3">
          <Link
            href="/projects"
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            View projects
          </Link>
          <Link
            href="/projects/new"
            className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
          >
            New project
          </Link>
        </div>
      </section>

      <section className="grid gap-6 sm:grid-cols-2">
        {features.map((feature) => (
          <article
            key={feature.title}
            className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
          >
            <h2 className="text-lg font-semibold">{feature.title}</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
              {feature.description}
            </p>
          </article>
        ))}
      </section>
    </div>
  );
}
