import { Loader2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useLocale, useT } from "../i18n";
import { CATALOGUE, providerName } from "../providers";
import type { SentinelReviewUpdate, SentinelReviewView } from "../types";
import { inputCls, primaryBtn } from "./Form";

const providers = CATALOGUE.filter((p) => p.id !== "custom" && p.capabilities.includes("chat") && ["openai", "openai-responses"].includes(p.protocol));

function isSeparate(value: SentinelReviewView): boolean {
  return !!(value.provider || value.model || value.base_url || value.has_api_key);
}

/** Observation is configured apart from permissions: this form never changes Sentinel mode. */
export function SentinelReviewSettings({ value, chatModel, onSave }: {
  value: SentinelReviewView;
  chatModel: string;
  onSave: (update: SentinelReviewUpdate) => Promise<SentinelReviewView>;
}) {
  const t = useT();
  const locale = useLocale();
  const id = useId();
  const [enabled, setEnabled] = useState(value.mode === "observe");
  const [separate, setSeparate] = useState(isSeparate(value));
  const [provider, setProvider] = useState(value.provider);
  const [model, setModel] = useState(value.model);
  const [baseURL, setBaseURL] = useState(value.base_url);
  const [key, setKey] = useState("");
  const [removeKey, setRemoveKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setEnabled(value.mode === "observe");
    setSeparate(!!(value.provider || value.model || value.base_url || value.has_api_key));
    setProvider(value.provider);
    setModel(value.model);
    setBaseURL(value.base_url);
    setKey("");
    setRemoveKey(false);
  }, [value.mode, value.provider, value.model, value.base_url, value.has_api_key]);

  const dirty = enabled !== (value.mode === "observe") || separate !== isSeparate(value)
    || (separate && (provider !== value.provider || model !== value.model || baseURL !== value.base_url || !!key.trim() || removeKey));
  const keyDestinationChanged = provider.trim() !== value.provider || baseURL.trim() !== value.base_url;
  const knownProvider = !provider || provider === "openai_responses" || provider === "chatgpt" || providers.some((p) => p.id === provider);

  const save = async () => {
    if (saving || !dirty) return;
    const update: SentinelReviewUpdate = {
      mode: enabled ? "observe" : "off",
      provider: separate ? provider.trim() : "",
      model: separate ? model.trim() : "",
      base_url: separate ? baseURL.trim() : "",
    };
    // A blank password input keeps the secret. Reusing chat explicitly removes the
    // separate credential too, so it cannot silently override the chat model's key.
    if (!separate || removeKey) update.api_key = "";
    else if (key.trim()) update.api_key = key.trim();
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await onSave(update);
      setKey("");
      setRemoveKey(false);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); void save(); }} className="rounded-2xl border border-border p-3.5 space-y-3">
      <div>
        <h3 className="font-medium">{t("Model review (observe only)")}</h3>
        <p className="mt-1 text-[12.5px] text-muted">{t("Suggestions are recorded in the audit log. They never approve or block an action, or change your permissions.")}</p>
      </div>
      <fieldset disabled={saving} className="space-y-3 disabled:opacity-60">
        <label className="flex items-center gap-2 text-[14px]">
          <input type="checkbox" checked={enabled} onChange={(e) => { setEnabled(e.target.checked); setSaved(false); }} className="accent-accent" />
          {t("Enable observation")}
        </label>
        {enabled && <>
          <p className="text-[12.5px] text-muted">{t("The selected model receives the current operation and its task context, not the full conversation. No extra files are read. Reviews use additional model calls.")}</p>
          <label className="block space-y-1 text-[13px]">
            <span>{t("Review model")}</span>
            <select value={separate ? "separate" : "chat"} onChange={(e) => { setSeparate(e.target.value === "separate"); setSaved(false); }} className={inputCls}>
              <option value="chat">{t("Use the chat model")}</option>
              <option value="separate">{t("Configure a separate model")}</option>
            </select>
          </label>
          {!separate && <p className="text-[12.5px] text-muted">{t("Follows the active chat model and its credentials. Current model: {model}", { model: chatModel })}</p>}
          {separate && <div className="space-y-3">
            <label className="block space-y-1 text-[13px]">
              <span>{t("Provider")}</span>
              <select value={provider} onChange={(e) => { setProvider(e.target.value); setKey(""); setSaved(false); }} className={inputCls}>
                <option value="">{t("Same provider as chat")}</option>
                {providers.map((p) => <option key={p.id} value={p.id}>{providerName(p, locale)}</option>)}
                <option value="openai_responses">OpenAI Responses</option>
                <option value="chatgpt">ChatGPT</option>
                {!knownProvider && <option value={provider}>{provider}</option>}
              </select>
            </label>
            <label className="block space-y-1 text-[13px]">
              <span>{t("Model")}</span>
              <input value={model} onChange={(e) => { setModel(e.target.value); setSaved(false); }} placeholder={t("Leave blank to use the chat model name")} className={inputCls} autoComplete="off" />
            </label>
            <label className="block space-y-1 text-[13px]">
              <span>{t("Base URL")}</span>
              <input type="url" value={baseURL} onChange={(e) => { setBaseURL(e.target.value); setKey(""); setSaved(false); }} placeholder={t("Default endpoint")} className={inputCls} autoComplete="off" spellCheck={false} />
            </label>
            <label className="block space-y-1 text-[13px]">
              <span>{t("API key")}</span>
              <input type="password" value={key} onChange={(e) => { setKey(e.target.value); setRemoveKey(false); setSaved(false); }} placeholder={value.has_api_key && !keyDestinationChanged ? t("A key is saved. Leave blank to keep it.") : t("API key (optional)")} className={inputCls} autoComplete="new-password" aria-describedby={`${id}-key-hint`} />
            </label>
            <p id={`${id}-key-hint`} className="text-[12.5px] text-muted">{keyDestinationChanged ? t("Changing the provider or endpoint does not reuse the previous key. Add the key for the new destination if it needs one.") : t("Changing only the model can reuse the chat credentials. A different provider or endpoint needs its own credentials.")}</p>
            {value.has_api_key && <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={removeKey} onChange={(e) => { setRemoveKey(e.target.checked); if (e.target.checked) setKey(""); setSaved(false); }} className="accent-accent" />
              {t("Clear the saved review key")}
            </label>}
          </div>}
        </>}
      </fieldset>
      {error && <p role="alert" className="text-[13px] text-rose-600 dark:text-rose-300">{error}</p>}
      {saved && <p role="status" className="text-[13px] text-muted">{t("Saved")}</p>}
      <button type="submit" disabled={saving || !dirty} className={primaryBtn}>
        {saving && <Loader2 size={15} className="animate-spin" />}{t("Save")}
      </button>
    </form>
  );
}
