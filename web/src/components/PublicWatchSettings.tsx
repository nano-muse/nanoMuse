import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { getLocale, useT } from "../i18n";
import type { PublicSourceKind, PublicWatch, PublicWatchView } from "../types";
import { inputCls, primaryBtn, Toggle } from "./Form";

const sourceKinds: Record<PublicSourceKind, { label: string; field: string }> = {
  github_repo: { label: "GitHub repository", field: "Repository (owner/name)" },
  github_user: { label: "GitHub account", field: "GitHub username" },
  research_author: { label: "Researcher", field: "ORCID or OpenAlex author ID" },
  research_work: { label: "Paper citations", field: "Paper DOI" },
  research_topic: { label: "Research topic", field: "Topic or keywords" },
  feed: { label: "Website or RSS/Atom feed", field: "HTTPS website or feed URL" },
};

const allKinds = Object.keys(sourceKinds) as PublicSourceKind[];
const scholarKinds: PublicSourceKind[] = ["research_author", "research_work"];
const actionButton = "text-sm font-medium text-accent disabled:opacity-40";

function SourceForm({ scholar = false, disabled, onSave, onCancel }: {
  scholar?: boolean;
  disabled: boolean;
  onSave: (kind: PublicSourceKind, target: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const kinds = scholar ? scholarKinds : allKinds;
  const [kind, setKind] = useState<PublicSourceKind>(kinds[0]);
  const [target, setTarget] = useState("");
  const trimmed = target.trim();
  return (
    <form className="space-y-2 rounded-xl border border-border bg-surface p-3" onSubmit={e => {
      e.preventDefault();
      if (!disabled && trimmed) onSave(kind, trimmed);
    }}>
      {scholar && <p className="text-sm text-muted">{t("Check the Google Scholar profile, then enter the matching ORCID, OpenAlex author ID or the DOI of a paper you want to follow.")}</p>}
      <label className="block text-sm">{t("Source type")}
        <select className={inputCls} value={kind} disabled={disabled} onChange={e => {
          setKind(e.target.value as PublicSourceKind);
          setTarget("");
        }}>{kinds.map(k => <option key={k} value={k}>{t(sourceKinds[k].label)}</option>)}</select>
      </label>
      <label className="block text-sm">{t(sourceKinds[kind].field)}
        <input className={inputCls} type="text" value={target} required disabled={disabled}
          autoCapitalize="none" autoComplete="off" spellCheck={false}
          onChange={e => setTarget(e.target.value)} />
      </label>
      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" className={primaryBtn} disabled={disabled || !trimmed}>
          {scholar ? t("Link and follow") : t("Follow source")}
        </button>
        <button type="button" className={actionButton} onClick={onCancel} disabled={disabled}>{t("Cancel")}</button>
      </div>
    </form>
  );
}

export function PublicWatchSettings() {
  const t = useT();
  const [view, setView] = useState<PublicWatchView | null>(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const saving = useRef(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [linking, setLinking] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.publicWatches().then(value => { if (live) { setView(value); setStale(false); } })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : "Could not load."); });
    return () => { live = false; };
  }, [reload]);

  const save = async (update: (revision: string) => Promise<PublicWatchView>) => {
    if (!view || stale || saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      setView(await update(view.revision));
      setAdding(false);
      setLinking(null);
    } catch (e) {
      // A concurrent edit or a lost response can make the previous revision stale.
      // Read the current settings before allowing another edit. Never replay a write.
      setError(e instanceof Error ? e.message : "Your nanoMuse could not do that.");
      setStale(true);
      setReload(n => n + 1);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const disabled = busy || stale;
  const change = (watch: PublicWatch, action: "confirm" | "pause" | "resume" | "dismiss") =>
    void save(revision => api.changePublicWatch(watch.id, { revision, action }));
  return (
    <section className="space-y-3 rounded-2xl bg-surface-2 px-3.5 py-3" aria-label={t("Public sources")}>
      <h3 className="text-sm font-semibold">{t("Public sources")}</h3>
      {error && <p role="alert" className="text-sm text-muted">{t(error)} {(!view || stale) &&
        <button type="button" className={actionButton} onClick={() => { setError(""); setReload(n => n + 1); }}>{t("Retry")}</button>}</p>}
      {!view && !error && <p role="status" className="text-sm text-muted">{t("Loading sources…")}</p>}
      {view && <>
        <Toggle label={t("Follow public sources")} checked={view.enabled} disabled={disabled}
          hint={t("nanoMuse looks for sources in your context. It checks the sources you follow for changes and can message you in your main chat.")}
          onChange={enabled => void save(revision => api.setPublicWatches(revision, enabled))} />
        {view.can_share !== undefined && <Toggle label={t("Sync public updates to my devices")}
          checked={view.share_public_updates === true} disabled={disabled || !view.can_share}
          hint={view.can_share ? t("When conversation sync is on, new messages based only on public sources can appear in your main chat on other devices.") : t("Sign in to share public updates across your devices.")}
          onChange={on => void save(revision => api.sharePublicWatchUpdates(revision, on))} />}
        {view.watches.map(watch => {
          const suggested = watch.status === "suggested";
          const scholar = watch.kind === "scholar_profile";
          const paused = watch.status === "paused";
          return (
            <div key={watch.id} role="group" aria-label={watch.label || watch.target}
              className="space-y-1.5 border-t border-border pt-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="break-all text-sm font-medium">{watch.label || watch.target}</span>
                <span className="text-xs text-muted">{suggested ? t("Needs confirmation") : paused ? t("Paused") : t("Following")}</span>
              </div>
              <p className="break-all text-xs text-muted">
                {watch.kind === "scholar_profile" ? t("Google Scholar profile") : t(sourceKinds[watch.kind]?.label ?? watch.kind)}
                {watch.target !== watch.label && watch.label ? ` · ${watch.target}` : ""}
              </p>
              {suggested && watch.origin && watch.origin !== "manual" && <p className="text-xs text-muted">
                {t({ chat: "Mentioned in your main chat.", recurring: "Mentioned in more than one of your messages.", connected: "Found in a source you enabled for review." }[watch.origin])}
              </p>}
              {scholar && <a className={actionButton} href={`https://scholar.google.com/citations?user=${encodeURIComponent(watch.target)}`} target="_blank" rel="noreferrer">{t("Open Google Scholar profile")}</a>}
              {watch.last_checked && <p className="text-xs text-muted">
                {t("Last background check: {time}", { time: new Date(watch.last_checked).toLocaleString(getLocale()) })}
              </p>}
              {watch.unavailable && <p className="text-xs text-muted">{t("This source could not be read at the last check.")}</p>}
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {suggested && <button type="button" className={actionButton} disabled={disabled || !view.enabled}
                  onClick={() => {
                    if (scholar) { setLinking(watch.id); setAdding(false); }
                    else change(watch, "confirm");
                  }}>
                  {scholar ? t("Link author or paper") : t("Follow source")}
                </button>}
                {!suggested && <button type="button" className={actionButton} disabled={disabled || (paused && !view.enabled)}
                  onClick={() => change(watch, paused ? "resume" : "pause")}>{paused ? t("Resume") : t("Pause")}</button>}
                <button type="button" className={actionButton} disabled={disabled} onClick={() => change(watch, "dismiss")}>
                  {suggested ? t("Don’t suggest again") : t("Stop following")}
                </button>
              </div>
              {scholar && suggested && linking === watch.id && <SourceForm scholar disabled={disabled || !view.enabled}
                onCancel={() => setLinking(null)}
                onSave={(kind, target) => void save(revision => api.changePublicWatch(watch.id, { revision, action: "confirm", kind, target }))} />}
            </div>
          );
        })}
        {view.enabled && (adding
          ? <SourceForm disabled={disabled} onCancel={() => setAdding(false)}
              onSave={(kind, target) => void save(revision => api.addPublicWatch(revision, kind, target))} />
          : <button type="button" disabled={disabled} className={actionButton}
              onClick={() => { setAdding(true); setLinking(null); }}>{t("Add a public source")}</button>)}
      </>}
    </section>
  );
}
