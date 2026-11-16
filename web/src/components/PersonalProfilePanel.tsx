import { useEffect, useState } from "react";
import { api } from "../api";
import { useLocale, useT } from "../i18n";
import type { PersonalFact, PersonalProfile } from "../types";
import { LoadError } from "./LoadError";

const statusWords = { active: "In use", candidate: "Needs confirmation", expired: "Expired", rejected: "Removed", superseded: "Replaced" };
const kindWords = { profile: "Background", preference: "Preference", project: "Project", state: "Temporary state", experience: "Experience" };

export function PersonalProfilePanel({ version, space = "personal" }: { version: number; space?: string }) {
  const t = useT();
  const locale = useLocale();
  const [profile, setProfile] = useState<PersonalProfile | null>(null);
  const [history, setHistory] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<PersonalFact | null>(null);
  const [draft, setDraft] = useState("");
  useEffect(() => {
    let alive = true;
    setError("");
    void api.personalProfile(history, space).then((result) => {
      if (alive) setProfile(result);
    }).catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [version, history, refresh, space]);

  const review = async (item: PersonalFact, action: "confirm" | "reject" | "edit") => {
    setBusy(true);
    setActionError("");
    try {
      await api.personalReview(item, action, action === "edit" ? draft : "", space);
      setEditing(null);
      setRefresh((n) => n + 1);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const button = "rounded-xl bg-surface-2 px-3 py-2 text-xs font-medium disabled:opacity-50";
  return (
    <section aria-label={t("Personal profile")} className="rounded-2xl border border-border p-3 space-y-3">
      <h3 className="text-sm font-semibold">{t("Personal profile")}</h3>
      <p className="text-xs text-muted">{t("Active facts shape future replies. Suggested preferences need your confirmation. The conversation capture switch also controls profile learning.")}</p>
      {profile?.learning_enabled === false && <p className="text-xs text-muted">{t("Profile personalization is disabled in the runtime configuration.")}</p>}
      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={history} disabled={busy} onChange={(event) => setHistory(event.target.checked)} />
        {t("Show previous and expired facts")}
      </label>
      {error && <LoadError message={error} onRetry={() => setRefresh((n) => n + 1)} />}
      {actionError && <p role="alert" className="text-sm text-rose-600">{t(actionError)}</p>}
      {profile?.items.length === 0 && <p className="text-xs text-muted">{t("No profile facts yet. Share a lasting preference in chat.")}</p>}
      <ul className="divide-y divide-border/70">
        {profile?.items.slice(0, 100).map((item) => (
          <li key={item.id} className="py-3 space-y-2">
            <div className="flex flex-wrap gap-2 text-xs text-muted">
              <span>{t(kindWords[item.kind])}</span>
              <span className={item.status === "candidate" ? "text-amber-600" : ""}>{t(statusWords[item.status])}</span>
              <span>{t(item.confidence === "confirmed" ? "Confirmed by you" : item.confidence === "explicit" ? "Stated by you" : "Suggested preference")}</span>
            </div>
            <p className="break-words whitespace-pre-wrap text-sm">{item.value}</p>
            <p className="text-xs text-muted break-words">{t("Applies to: {scope}", { scope: item.scope.join(", ") || t("General") })}</p>
            {item.expires_at && <p className="text-xs text-muted">{t("Valid until: {time}", { time: new Date(item.expires_at).toLocaleString(locale) })}</p>}
            <details className="text-xs text-muted">
              <summary className="cursor-pointer">{t("Evidence ({n})", { n: item.evidence.length })}</summary>
              {item.evidence.map((evidence, index) => (
                <blockquote key={index} className="mt-2 border-l-2 border-border pl-2 break-words whitespace-pre-wrap">
                  <p>{evidence.quote}</p>
                  {evidence.before && evidence.before !== evidence.quote && <p>{t("Previously: {value}", { value: evidence.before })}</p>}
                  <time dateTime={evidence.at}>{new Date(evidence.at).toLocaleString(locale)}</time>
                </blockquote>
              ))}
            </details>
            {editing?.id === item.id ? (
              <div className="space-y-2">
                <textarea rows={3} maxLength={500} value={draft} disabled={busy} onChange={(event) => setDraft(event.target.value)} aria-label={t("Edit personal profile fact")} className="w-full rounded-xl bg-surface-2 p-3 text-sm" />
                <div className="flex gap-2">
                  <button type="button" className={button} disabled={busy || !draft.trim()} onClick={() => void review(editing, "edit")}>{t("Save")}</button>
                  <button type="button" className={button} disabled={busy} onClick={() => { setEditing(null); setActionError(""); }}>{t("Cancel")}</button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {item.status !== "active" && <button type="button" className={button} disabled={busy} onClick={() => void review(item, "confirm")}>{t("Use this fact")}</button>}
                <button type="button" className={button} disabled={busy} onClick={() => { setEditing(item); setDraft(item.value); setActionError(""); }}>{t("Correct this fact")}</button>
                {item.status !== "rejected" && <button type="button" className={button} disabled={busy} onClick={() => {
                  if (window.confirm(t("Stop using this profile fact? Remote OpenViking memories are kept."))) void review(item, "reject");
                }}>{t("Stop using")}</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
      {profile && profile.items.length > 100 && <p className="text-xs text-muted">{t("Showing the latest 100 profile facts.")}</p>}
    </section>
  );
}
