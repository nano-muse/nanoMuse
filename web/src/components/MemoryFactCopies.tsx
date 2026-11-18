import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";

type Result = Awaited<ReturnType<typeof api.memoryFactCopies>>;

export function MemoryFactCopies({ space, version, onChange }: { space: string; version: number; onChange: () => void }) {
  const t = useT();
  const [term, setTerm] = useState("");
  const [replacement, setReplacement] = useState("");
  const [aliases, setAliases] = useState("");
  const [report, setReport] = useState<Result["report"]>(null);
  const [preview, setPreview] = useState<Result | null>(null);
  const [rules, setRules] = useState<NonNullable<Result["rules"]>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  useEffect(() => { setPreview(null); }, [space, version]);
  const run = async (action: "preview" | "apply" | "status" | "unblock", fragment = term) => {
    setBusy(true); setError(""); setDone(false);
    try {
      const result = await api.memoryFactCopies(space, { action, term: fragment.trim(), replacement: action === "unblock" ? "" : replacement.trim(), revision: preview?.revision, aliases: action === "unblock" || action === "status" ? [] : aliases.split("\n").map((value) => value.trim()).filter(Boolean) });
      if (result.report) setReport(result.report);
      if (action === "preview") setPreview(result);
      else {
        if (result.rules) setRules(result.rules);
        if (action !== "status") { setPreview(null); setDone(true); onChange(); }
      }
    } catch (e) {
      setError((e as Error).message);
      if (action === "apply") {
        setPreview(null);
        try {
          const latest = await api.memoryFactCopies(space, { action: "status" });
          if (latest.report?.state === "incomplete") setReport(latest.report);
        } catch { /* The saved result can be loaded after the connection returns. */ }
      }
    } finally { setBusy(false); }
  };
  const button = "rounded-xl bg-surface-2 px-3 py-2 text-xs font-medium disabled:opacity-50";
  return <section aria-label={t("Find and reconcile memory copies")} className="rounded-2xl border border-border p-4 space-y-3">
    <h2 className="text-sm font-semibold">{t("Find and reconcile memory copies")}</h2>
    <p className="text-xs text-muted">{t("Search an exact fragment in this space's profile, local notes, remote files and recorded archives. Review every match before deleting or replacing it. Other spaces are unchanged.")}</p>
    <label className="block text-xs space-y-1">
      <span>{t("Old text or exact fact fragment")}</span>
      <input aria-label={t("Old text or exact fact fragment")} value={term} maxLength={500} disabled={busy} onChange={(e) => { setTerm(e.target.value); setReport(null); setPreview(null); setDone(false); }} className="block w-full rounded-xl bg-surface-2 p-2 text-sm" />
    </label>
    <label className="block text-xs space-y-1">
      <span>{t("Replacement text, leave empty to delete")}</span>
      <input aria-label={t("Replacement text, leave empty to delete")} value={replacement} maxLength={500} disabled={busy} onChange={(e) => { setReplacement(e.target.value); setReport(null); setPreview(null); setDone(false); }} className="block w-full rounded-xl bg-surface-2 p-2 text-sm" />
    </label>
    <label className="block text-xs space-y-1">
      <span>{t("Other known wording, one per line")}</span>
      <textarea aria-label={t("Other known wording, one per line")} value={aliases} rows={2} maxLength={10020} disabled={busy} onChange={(event) => { setAliases(event.target.value); setPreview(null); setReport(null); setDone(false); }} className="block w-full rounded-xl bg-surface-2 p-2 text-sm" />
    </label>
    <p className="text-xs text-muted">{t("Profile revisions with the same field and scope are linked automatically. Add other known wording above. Review all linked matches before applying.")}</p>
    <button className={button} disabled={busy || term.trim().length < 3} onClick={() => void run("preview")}>{t("Inspect copies")}</button>
    {preview?.revision && <div className="space-y-3">
      <p className="text-xs font-medium">{t("Matched records: {count}", { count: preview.matches?.length ?? 0 })}</p>
      <p className="text-xs text-muted">{t("Deletion removes whole matching records and files, including other facts inside them. Replacement changes the matching fragment in current facts and removes matching history and recorded sessions. Chat timelines, audit logs and untracked archives remain. The old fragment will be excluded from assistant memory until you remove its exclusion.")}</p>
      <ul className="space-y-2 max-h-96 overflow-auto">
        {preview.matches?.map((item, index) => <li key={`${item.source}:${item.id}:${index}`} className="rounded-xl bg-surface-2 p-3 text-xs space-y-2">
          <div className="font-medium break-all">{t(item.source)} · {item.id}</div>
          {item.linked && <p>{t("Linked profile revision")}</p>}
          <pre className="whitespace-pre-wrap break-words">{item.before}</pre>
          <div className="font-medium">{item.after ? t("After replacement") : t("Record will be removed")}</div>
          {item.after && <pre className="whitespace-pre-wrap break-words">{item.after}</pre>}
        </li>)}
      </ul>
      <button className={button + " text-rose-600"} disabled={busy} onClick={() => {
        if (window.confirm(t("Apply these reviewed changes to this space? Matching archives and history cannot be restored here. Download a space backup first if needed."))) void run("apply");
      }}>{replacement.trim() ? t("Confirm replacement across copies") : t("Confirm deletion across copies")}</button>
    </div>}
    {report && <div aria-label={t("Memory operation result")} className="space-y-2 text-xs">
      <p className="font-medium">{t("Memory operation result")} · {t(({ preview: "Inspected", completed: "Applied", incomplete: "Incomplete", in_progress: "In progress" } as Record<string, string>)[report.state] ?? report.state)}</p>
      <div className="overflow-x-auto"><table className="w-full text-left text-xs">
        <thead><tr>{["Source", "Scanned", "Matched", "Changed", "Status"].map((label) => <th className="pr-2 py-1" key={label}>{t(label)}</th>)}</tr></thead>
        <tbody>{report.sources.map((row) => <tr key={row.source}>
          <td className="pr-2 py-1">{t(row.source)}</td><td>{row.scanned}</td><td>{row.matched}</td><td>{row.changed}</td>
          <td>{t(({ checked: "Inspected", completed: "Applied", incomplete: "Incomplete", not_configured: "Not configured" } as Record<string, string>)[row.status] ?? row.status)}</td>
        </tr>)}</tbody>
      </table></div>
      <p>{t("Outside this operation: chat timelines, audit logs, untracked archives and workspace files.")}</p>
      {report.exclusions_active && <p>{t("Retired-text exclusions are active.")}</p>}
      {report.state === "incomplete" && <>
        <p role="status">{t("Some changes are incomplete. Inspect remaining copies before retrying.")}</p>
        <button className={button} disabled={busy || term.trim().length < 3} onClick={() => void run("preview")}>{t("Inspect remaining copies")}</button>
      </>}
    </div>}
    <button className={button} disabled={busy} onClick={() => void run("status")}>{t("Load last operation result")}</button>
    <details>
      <summary className="cursor-pointer text-xs">{t("Retired text exclusions")}</summary>
      <p className="text-xs text-muted my-2">{t("Exclusions prevent old facts from returning through memory. Removing an exclusion permits recall again but does not restore deleted records.")}</p>
      <button className={button} disabled={busy} onClick={() => void run("status")}>{t("Load exclusions")}</button>
      <ul className="space-y-2 mt-2">{rules.map((rule) => <li key={rule.term} className="text-xs break-words">
        <span>{rule.term}{rule.replacement ? ` → ${rule.replacement}` : ""}</span>{" "}
        <button className={button} disabled={busy} onClick={() => {
          if (window.confirm(t("Allow this retired text in memory again?"))) void run("unblock", rule.term);
        }}>{t("Remove exclusion")}</button>
      </li>)}</ul>
    </details>
    {done && <p role="status" className="text-xs">{t("Memory copies updated. Verify in a new conversation.")}</p>}
    {error && <p role="alert" className="text-sm text-rose-600 break-words">{t(error)}</p>}
  </section>;
}
