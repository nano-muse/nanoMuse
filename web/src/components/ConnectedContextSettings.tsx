import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import type { ContextResource, ContextWatchSettings } from "../types";
import { Toggle } from "./Form";

export function ConnectedContextSettings() {
  const t = useT();
  const [settings, setSettings] = useState<ContextWatchSettings | null>(null);
  const [listed, setListed] = useState<ContextResource[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    api.contextWatch().then(v => { if (live) setSettings(v); }).catch(e => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [attempt]);

  const save = async (change: Partial<Pick<ContextWatchSettings, "mail" | "calendar" | "local_context">> & { resources?: string[] }) => {
    if (!settings || busy) return;
    setBusy(true);
    setError("");
    try {
      setSettings(await api.setContextWatch({
        revision: settings.revision, mail: settings.mail, calendar: settings.calendar,
        local_context: settings.local_context, resources: settings.resources.map(r => r.id), ...change,
      }));
    } catch (e) {
      setError(String(e));
      setAttempt(n => n + 1);
    } finally { setBusy(false); }
  };
  const discover = async () => {
    setBusy(true);
    setError("");
    try { setListed(await api.contextResources()); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const options = new Map((settings?.resources ?? []).map(r => [r.id, r]));
  for (const r of listed ?? []) options.set(r.id, r);
  const selected = settings?.resources.map(r => r.id) ?? [];
  return (
    <div className="space-y-2 rounded-2xl bg-surface-2 px-3.5 py-3">
      <h3 className="text-sm font-semibold">{t("Updates from connected sources")}</h3>
      <p className="text-[13px] text-muted">{t("Your configured model can review changes in the sources you select and leave a message in your main chat when something needs attention.")}</p>
      {error && <div role="alert" className="text-sm text-muted">{error} <button type="button" onClick={() => { setError(""); setAttempt(n => n + 1); }}>{t("Retry")}</button></div>}
      {settings && <>
        <Toggle label={t("New email in my connected inbox")} disabled={busy || !settings.available_mail} checked={settings.mail} onChange={mail => void save({ mail })} />
        <Toggle label={t("Changes in my connected calendars")} disabled={busy || !settings.available_calendar} checked={settings.calendar} onChange={calendar => void save({ calendar })} />
        <button type="button" disabled={busy} className="text-sm font-medium text-accent" onClick={() => void discover()}>{t("Choose MCP resources")}</button>
        {listed && !listed.length && <p className="text-xs text-muted">{t("No connected server offered a text resource.")}</p>}
        {[...options.values()].map(r => <Toggle key={r.id} label={r.label} checked={selected.includes(r.id)} disabled={busy || (selected.length >= 6 && !selected.includes(r.id))}
          onChange={on => void save({ resources: on ? [...selected, r.id] : selected.filter(id => id !== r.id) })} />)}
        {(settings.mail || settings.calendar || selected.length > 0) &&
          <p className="text-xs text-muted">{settings.checked_at
            ? t("Last background check: {time}", {time: new Date(settings.checked_at).toLocaleString()})
            : t("Waiting for the first background check.")} {settings.unavailable && t("Some sources could not be read.")}</p>}
        {(settings.mail || settings.calendar || selected.length > 0 || settings.local_context) &&
          <Toggle label={settings.local_goals ? t("Also consider my recent main chat and active goals") : t("Also consider my recent main chat")} checked={settings.local_context} disabled={busy} onChange={local_context => void save({ local_context })} />}
      </>}
    </div>
  );
}
