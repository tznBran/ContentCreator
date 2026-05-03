"use client";

import { useEffect, useMemo, useState } from "react";

import {
  type ExportRead,
  type PublishRead,
  type PublishVisibility,
  type SocialAccount,
  type SocialPlatform,
  api,
} from "@/lib/api";

interface PublishPanelProps {
  projectId: string;
  exports: ExportRead[];
}

const PLATFORMS: SocialPlatform[] = ["youtube", "tiktok", "instagram"];

const PLATFORM_LABEL: Record<SocialPlatform, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
};

const TERMINAL_PUBLISH = new Set<PublishRead["status"]>([
  "succeeded",
  "failed",
]);

export function PublishPanel({ projectId, exports }: PublishPanelProps) {
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [publishes, setPublishes] = useState<PublishRead[]>([]);
  const [error, setError] = useState<string | null>(null);

  const successfulExports = useMemo(
    () =>
      exports
        .filter((e) => e.status === "succeeded")
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [exports],
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listAccounts(), api.listPublishes(projectId)])
      .then(([acc, pubs]) => {
        if (cancelled) return;
        setAccounts(acc);
        setPublishes(pubs);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load accounts",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Poll in-flight publishes.
  useEffect(() => {
    const pending = publishes.filter((p) => !TERMINAL_PUBLISH.has(p.status));
    if (pending.length === 0) return;
    const handle = setInterval(async () => {
      const updated = await Promise.all(
        pending.map((p) => api.getPublish(p.id).catch(() => p)),
      );
      setPublishes((prev) => {
        const map = new Map(prev.map((p) => [p.id, p]));
        for (const u of updated) map.set(u.id, u);
        return Array.from(map.values()).sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        );
      });
    }, 3000);
    return () => clearInterval(handle);
  }, [publishes]);

  const connectedFor = (platform: SocialPlatform) =>
    accounts.filter((a) => a.platform === platform);

  const startConnect = async (platform: SocialPlatform) => {
    setError(null);
    try {
      const { authorize_url } = await api.oauthStart(platform);
      window.location.assign(authorize_url);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start OAuth");
    }
  };

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {PLATFORMS.map((p) => {
          const connected = connectedFor(p);
          return (
            <div
              key={p}
              className="rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {PLATFORM_LABEL[p]}
                </span>
                <button
                  type="button"
                  onClick={() => startConnect(p)}
                  className="rounded bg-zinc-900 px-2 py-1 text-xs text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900"
                >
                  {connected.length === 0 ? "Connect" : "Reconnect"}
                </button>
              </div>
              {connected.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {connected.map((a) => (
                    <li
                      key={a.id}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="truncate">{a.account_name}</span>
                      <button
                        type="button"
                        onClick={async () => {
                          await api.deleteAccount(a.id);
                          setAccounts((prev) =>
                            prev.filter((x) => x.id !== a.id),
                          );
                        }}
                        className="ml-2 rounded border border-red-300 px-2 text-red-600 dark:border-red-700"
                      >
                        Disconnect
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <hr className="border-zinc-200 dark:border-zinc-800" />

      {successfulExports.length === 0 ? (
        <p className="text-xs text-zinc-500">
          Run an export first, then publish it to a connected platform.
        </p>
      ) : (
        <PublishForm
          projectId={projectId}
          exports={successfulExports}
          accounts={accounts}
          onCreate={(pub) => setPublishes((prev) => [pub, ...prev])}
        />
      )}

      {publishes.length > 0 && (
        <ul className="space-y-2">
          {publishes.map((p) => (
            <li
              key={p.id}
              className="rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                  {PLATFORM_LABEL[p.platform]}
                </span>
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                  {p.status}
                </span>
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                  {p.visibility}
                </span>
                <span className="truncate">{p.title}</span>
                {p.platform_url && (
                  <a
                    href={p.platform_url}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    Open
                  </a>
                )}
              </div>
              {p.error && (
                <p className="mt-1 text-xs text-red-600">{p.error}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface PublishFormProps {
  projectId: string;
  exports: ExportRead[];
  accounts: SocialAccount[];
  onCreate: (pub: PublishRead) => void;
}

function PublishForm({
  projectId,
  exports,
  accounts,
  onCreate,
}: PublishFormProps) {
  const [accountId, setAccountId] = useState<string>("");
  const [exportId, setExportId] = useState<string>(exports[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<PublishVisibility>("private");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Effective values that fall back to the first available option.
  const effectiveAccount =
    accounts.find((a) => a.id === accountId) ?? accounts[0];
  const effectiveExport =
    exports.find((e) => e.id === exportId) ?? exports[0];

  if (accounts.length === 0) {
    return (
      <p className="text-xs text-zinc-500">
        Connect a platform above to publish.
      </p>
    );
  }

  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!effectiveAccount || !effectiveExport || !title.trim()) return;
        setBusy(true);
        setError(null);
        try {
          const pub = await api.createPublish(projectId, {
            export_id: effectiveExport.id,
            account_id: effectiveAccount.id,
            platform: effectiveAccount.platform,
            title: title.trim(),
            description: description.trim() || undefined,
            visibility,
          });
          onCreate(pub);
          setTitle("");
          setDescription("");
        } catch (err: unknown) {
          setError(err instanceof Error ? err.message : "Publish failed");
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="text-sm font-medium">Publish to platform</p>
      <div className="flex flex-wrap gap-2">
        <select
          value={effectiveAccount?.id ?? ""}
          onChange={(e) => setAccountId(e.target.value)}
          className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {PLATFORM_LABEL[a.platform]} — {a.account_name}
            </option>
          ))}
        </select>
        <select
          value={effectiveExport?.id ?? ""}
          onChange={(e) => setExportId(e.target.value)}
          className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
        >
          {exports.map((ex) => (
            <option key={ex.id} value={ex.id}>
              Export {ex.id.slice(0, 8)} ({ex.width}×{ex.height})
            </option>
          ))}
        </select>
        <select
          value={visibility}
          onChange={(e) =>
            setVisibility(e.target.value as PublishVisibility)
          }
          className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
        >
          <option value="private">Private</option>
          <option value="unlisted">Unlisted</option>
          <option value="public">Public</option>
        </select>
      </div>
      <input
        required
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={3}
        placeholder="Description (optional)"
        className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
      />
      <button
        type="submit"
        disabled={busy || !title.trim()}
        className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-50 hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
      >
        {busy ? "Publishing…" : "Publish"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </form>
  );
}
