import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { useStore } from "../store";

export function MemorySpacesPanel({ space, onSpace, version, onChange }: { space: string; onSpace: (space: string) => void; version: number; onChange: () => void }) {
  const t = useT();
  const { openThread, setTab } = useStore();
  const [state, setState] = useState<Awaited<ReturnType<typeof api.memorySpaces>> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("");
  const [revision, setRevision] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let alive = true;
    void api.memorySpaces(space).then((result) => { if (alive) setState(result); }).catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [space, version, refresh]);
  const action = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try { await work(); setRefresh((n) => n + 1); onChange(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const button = "rounded-xl bg-surface-2 px-3 py-2 text-xs font-medium disabled:opacity-50";
  return (
    <section aria-label={t("Memory spaces")} className="rounded-2xl border border-border p-4 space-y-3">
      <h2 className="text-sm font-semibold">{t("Memory spaces")}</h2>
      <p className="text-xs text-muted">{t("Each new conversation uses one space. Profile facts, local notes and remote recall stay in that space. These are spaces for one runtime owner, not separate user accounts.")}</p>
      <div className="flex flex-wrap gap-2">
        <select aria-label={t("Memory space")} value={space} disabled={busy} onChange={(e) => onSpace(e.target.value)} className="min-w-0 rounded-xl bg-surface-2 px-3 py-2 text-sm">
          {(state?.spaces ?? [{ id: "personal", label: "Personal" }]).map((item) => <option value={item.id} key={item.id}>{t(item.label)}</option>)}
        </select>
        <button className={button} disabled={busy || !state?.owner} onClick={() => void action(async () => {
          const thread = await api.createThread(t("New conversation"), space);
          openThread(thread.id); setTab("chat");
        })}>{t("Start a conversation in this space")}</button>
      </div>
      {state?.owner && <>
        <div className="flex flex-wrap gap-2">
          <input aria-label={t("New space name")} placeholder={t("New space name")} value={label} maxLength={80} disabled={busy} onChange={(e) => setLabel(e.target.value)} className="min-w-0 flex-1 rounded-xl bg-surface-2 px-3 py-2 text-sm" />
          <button className={button} disabled={busy || !label.trim()} onClick={() => void action(async () => {
            const created = await api.createMemorySpace("", label.trim()); setLabel(""); onSpace(created.id);
          })}>{t("Add space")}</button>
        </div>
        <p className="text-xs text-muted">{t("Profile learning: {pending} queued, {failed} failed", state.learning)}</p>
        {state.learning.failed > 0 && <button className={button} disabled={busy} onClick={() => void action(async () => { await api.retryLearning(space); })}>{t("Retry profile learning")}</button>}
        <details className="text-xs text-muted space-y-3">
          <summary className="cursor-pointer">{t("Export, restore or clear this space")}</summary>
          <p>{t("Backups include profile facts, local notes, remote memory files and recorded turns. Original chat timelines, audit logs and untracked remote sessions are separate. Restoring adopts facts without replaying conversations or queued learning.")}</p>
          <div className="flex flex-wrap gap-2">
            <button className={button} disabled={busy} onClick={() => void action(async () => {
              const backup = await api.exportMemory(space);
              const url = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" }));
              const link = document.createElement("a"); link.href = url; link.download = `nanomuse-memory-${space}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
              setRevision(backup.revision);
            })}>{t("Download memory backup")}</button>
            <label className={button}>{t("Restore backup")}
              <input className="block max-w-full mt-1" aria-label={t("Restore backup")} type="file" accept="application/json,.json" disabled={busy} onChange={(e) => {
                const file = e.target.files?.[0]; e.target.value = "";
                if (!file) return;
                void action(async () => {
                  if (file.size > 10_000_000) throw new Error("Memory backup exceeds 10 MB");
                  const data: unknown = JSON.parse(await file.text());
                  if (window.confirm(t("Restore facts from this backup into the selected space? Existing newer facts are kept."))) {
                    await api.restoreMemorySpace(space, data); setRevision("");
                  }
                });
              }} />
            </label>
            <button className={button + " text-rose-600"} disabled={busy || !revision} onClick={() => {
              if (window.confirm(t("Clear this space and its recorded remote sessions? Capture will be turned off. Chat timelines and audit logs remain. Keep the downloaded backup to restore facts."))) void action(async () => { await api.clearMemorySpace(space, revision); setRevision(""); });
            }}>{t("Clear after exporting")}</button>
          </div>
        </details>
      </>}
      {error && <p role="alert" className="text-sm text-rose-600 break-words">{t(error)}</p>}
    </section>
  );
}
