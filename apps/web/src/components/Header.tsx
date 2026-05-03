import Link from "next/link";

export function Header() {
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link
          href="/"
          className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-50"
        >
          ContentCreator
        </Link>
        <nav className="flex items-center gap-6 text-sm text-zinc-600 dark:text-zinc-400">
          <Link
            href="/projects"
            className="hover:text-zinc-900 dark:hover:text-zinc-50"
          >
            Projects
          </Link>
          <Link
            href="/projects/new"
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            New project
          </Link>
        </nav>
      </div>
    </header>
  );
}
