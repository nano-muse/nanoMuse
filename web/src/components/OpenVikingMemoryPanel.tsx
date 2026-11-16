import { ArrowLeft, Folder, Loader2, Pencil, RefreshCw, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import type { OpenVikingDocument, OpenVikingPage, OpenVikingStatus } from "../types";
import { LoadError } from "./LoadError";
import { PersonalProfilePanel } from "./PersonalProfilePanel";

export function OpenVikingMemoryPanel({ version, space = "personal" }: { version: number; space?: string }) {
  const t = useT();
  const [status, setStatus] = useState<OpenVikingStatus | null>(null);
  const [page, setPage] = useState<OpenVikingPage | null>(null);
  const [directory, setDirectory] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [document, setDocument] = useState<OpenVikingDocument | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    void (async () => {
      try {
        const next = await api.openVikingStatus(space);
        if (!alive) return;
        setStatus(next);
        if (next.enabled) {
          const result = await api.openVikingEntries(directory, search, offset, space);
          if (alive) setPage(result);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [version, directory, search, offset, refresh, space]);

  const extracting = status?.tasks.filter((task) => ["pending", "running", "cancelling"].includes(task.state)).length ?? 0;
  const failures = status?.tasks.filter((task) => ["failed", "cancelled"].includes(task.state)).length ?? 0;
  useEffect(() => {
    if (!extracting && !status?.pending) return;
    const timer = setInterval(() => setRefresh((n) => n + 1), 15000);
    return () => clearInterval(timer);
  }, [extracting, status?.pending]);

  const action = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setActionError("");
    try {
      await run();
      setRefresh((n) => n + 1);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = (uri: string) => action(async () => {
    const next = await api.openVikingRead(uri, space);
    setDocument(next);
    setDraft(next.content);
  });

  const navigate = (uri: string) => {
    setDirectory(uri);
    setSearch("");
    setQuery("");
    setOffset(0);
    setPage(null);
  };

  if (status?.enabled === false) return null;

  const button = "rounded-xl bg-surface-2 px-3 py-2 text-sm font-medium disabled:opacity-50";
  return (
    <section aria-label={t("OpenViking memories")} className="rounded-3xl border border-border/70 bg-surface p-4 space-y-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t("OpenViking memories")}</h2>
        <button type="button" className={button} aria-label={t("Refresh OpenViking memories")} disabled={loading || busy} onClick={() => setRefresh((n) => n + 1)}>
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-muted">{t("Memories extracted from conversations. Local memories are managed below.")}</p>
      {status && (
        <>
          <label className="flex items-center justify-between gap-3 text-sm">
            {t("Automatically save conversations")}
            <input type="checkbox" checked={status.capture} disabled={busy} onChange={(event) => {
              const enabled = event.target.checked;
              void action(async () => {
                await api.openVikingCapture(enabled, space);
                setStatus((old) => old ? { ...old, capture: enabled } : old);
              });
            }} />
          </label>
          <p className="text-xs text-muted">{t("Turning this off keeps existing memories and queued turns. You can still explicitly ask to save a fact.")}</p>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted" aria-live="polite">
            <span>{t("Waiting to sync: {n}", { n: status.pending })}</span>
            <span>{t("Extracting: {n}", { n: extracting })}</span>
            {status.pending > 0 && <button type="button" className={button} disabled={busy} onClick={() => void action(() => api.openVikingRetry(space))}>{t("Retry pending turns")}</button>}
          </div>
          {failures > 0 && <p className="text-xs text-rose-600">{t("Recent extraction failures: {n}. Check the tasks in OpenViking.", { n: failures })}</p>}
        </>
      )}
      {status?.enabled && <PersonalProfilePanel version={version + refresh} space={space} />}
      {actionError && <p role="alert" className="text-sm text-rose-600">{t(actionError)}</p>}
      {error && <LoadError message={error} onRetry={() => setRefresh((n) => n + 1)} />}
      {loading && !page && <Loader2 size={20} className="animate-spin text-muted" />}
      {status?.enabled && (
        <form className="flex gap-2" onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setSearch(query.trim());
          setRefresh((n) => n + 1);
        }}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label={t("Search OpenViking memories")} placeholder={t("Search OpenViking memories")} className="min-w-0 flex-1 rounded-xl bg-surface-2 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-accent/40" />
          <button type="submit" className={button} aria-label={t("Search OpenViking memories")} disabled={busy || loading}><Search size={16} /></button>
        </form>
      )}
      {page && (
        <>
          {(page.uri !== page.root || search) && <button type="button" className={`${button} flex items-center gap-1.5`} onClick={() => navigate(search ? page.root : page.uri.slice(0, page.uri.lastIndexOf("/")))}><ArrowLeft size={14} />{t("Back to memory folders")}</button>}
          {!loading && page.items.length === 0 && <p className="py-3 text-sm text-muted">{t("No remote memories found. Extraction may still be running.")}</p>}
          <ul className="divide-y divide-border/70">
            {page.items.map((item) => (
              <li key={item.uri} className="py-3">
                <button type="button" disabled={busy || loading} onClick={() => item.directory ? navigate(item.uri) : void open(item.uri)} className="flex w-full items-start gap-2 text-left disabled:opacity-50">
                  {item.directory ? <Folder size={17} className="mt-0.5 shrink-0 text-accent" /> : <Pencil size={16} className="mt-0.5 shrink-0 text-muted" />}
                  <span className="min-w-0">
                    <span className="block break-words text-sm font-medium">{item.name.replace(/\.md$/, "").replace(/_/g, " ")}</span>
                    {item.abstract && <span className="mt-1 block line-clamp-3 whitespace-pre-wrap break-words text-xs text-muted">{item.abstract}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            {offset > 0 && <button type="button" className={button} disabled={loading} onClick={() => setOffset((n) => Math.max(0, n - 50))}>{t("Previous memories")}</button>}
            {page.has_more && <button type="button" className={button} disabled={loading} onClick={() => setOffset((n) => n + 50)}>{t("More memories")}</button>}
          </div>
        </>
      )}
      {document && (
        <div className="rounded-2xl border border-border p-3 space-y-3">
          <h3 className="break-words text-sm font-medium">{document.uri.split("/").pop()?.replace(/\.md$/, "").replace(/_/g, " ")}</h3>
          <textarea rows={8} maxLength={32000} value={draft} disabled={busy} onChange={(event) => setDraft(event.target.value)} aria-label={t("Edit OpenViking memory")} className="w-full rounded-xl bg-surface-2 p-3 text-sm outline-none focus:ring-2 focus:ring-accent/40" />
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={`${button} !bg-accent text-accent-fg`} disabled={busy || !draft.trim() || draft === document.content} onClick={() => void action(async () => {
              await api.openVikingUpdate({ ...document, content: draft }, space);
              setDocument(null);
            })}>{t("Save")}</button>
            <button type="button" className={button} disabled={busy} onClick={() => {
              if (draft !== document.content && !window.confirm(t("Reload this memory and discard your unsaved edit?"))) return;
              void open(document.uri);
            }}>{t("Reload memory")}</button>
            <button type="button" className={button} disabled={busy} onClick={() => {
              setDocument(null);
              setActionError("");
            }}>{t("Cancel")}</button>
            <button type="button" className={`${button} ml-auto text-rose-600 flex items-center gap-1.5`} disabled={busy} onClick={() => {
              if (!window.confirm(t("Delete this OpenViking memory? Archived conversations are kept."))) return;
              void action(async () => {
                await api.openVikingDelete({ uri: document.uri, revision: document.revision }, space);
                setDocument(null);
              });
            }}><Trash2 size={14} />{t("Delete")}</button>
          </div>
          <p className="text-xs text-muted">{t("Deleting a memory removes its extracted file. Archived conversations can produce it again if reprocessed.")}</p>
        </div>
      )}
    </section>
  );
}
