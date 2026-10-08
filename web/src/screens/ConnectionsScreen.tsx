import {
  Bot,
  BrainCircuit,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronUp,
  Clapperboard,
  Contact as ContactIcon,
  ExternalLink,
  Eye,
  EyeOff,
  Globe,
  Image as ImageIcon,
  KeyRound,
  Loader2,
  LogIn,
  Mail,
  Plug,
  Plus,
  RefreshCw,
  Search,
  Smartphone,
  Trash2,
  Unplug,
  Upload,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { accessibilityState, androidApp } from "../android";
import { api } from "../api";
import { OWN_KEY_DOCS, takePresetHint } from "../components/AllowanceWays";
import { PageBar } from "../components/BackBar";
import { ChatGptSignIn } from "../components/ChatGptSignIn";
import { CloudCard } from "../components/CloudCard";
import { Card, inputCls, primaryBtn, secondaryBtn } from "../components/Form";
import { ModelPicker } from "../components/ModelPicker";
import { getLocale, useT } from "../i18n";
import type { ModelGroup } from "../model-list";
import { useStore } from "../store";
import { CLOUD_ID, CLOUD_KEY_REF, CUSTOM_ID, currentChoice, handsValue, mediaChoices, slotValue, type MediaChoice } from "../models";
import { CATALOGUE, catalogueIdFor, coversLine, editionFor, invalidateProviders, presetFor, providerName, regionOf, unavailableLine, type Capability } from "../providers";
import { modelSees, orderPresets } from "../region";
import type { Contact, ConnectionsData, SharedConnector, TestResult } from "../types";
import { cx, relativeTime } from "../util";

/** the runtime's preset for the account's model, present in `providers` while signed in */
const CLOUD_PRESET = "nanomuse_cloud";

/**
 * Connections: the model, your mailbox, your calendar, a browser, MCP servers — plugged in and out from the
 * phone. Anything secret is typed here and lands in the vault on the server; the model only
 * ever gets the tools that result, never the key or the password.
 */
export function ConnectionsScreen() {
  const { state } = useStore();
  const [data, setData] = useState<ConnectionsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const name = state.profile?.name ?? "nanoMuse";
  const t = useT();

  const load = useCallback(async () => {
    try {
      setData(await api.connections());
      setError(null);
    } catch (e) {
      setError(t((e as Error).message));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load, state.connectionsVersion]);

  return (
    <div className="flex h-full flex-col">
      <PageBar title={t("Connections")} description={t("What {name} can reach; keys stay in the vault on this machine.", { name })} />
      <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-4">
        {error && (
          <div className="rounded-2xl bg-rose-500/12 text-rose-700 dark:text-rose-300 p-3 text-[13.5px]">
            {error}
          </div>
        )}
        {!data && !error && (
          <div className="flex justify-center py-10 text-muted">
            <Loader2 className="animate-spin" size={20} />
          </div>
        )}
        {data && (
          <>
            <ModelCard data={data} onChange={load} />
            {data.image && <MediaSlotCard slot="image" data={data} onChange={load} />}
            {data.video && <MediaSlotCard slot="video" data={data} onChange={load} />}
            <CloudCard account={state.hub?.account ?? null} onChange={load} />
            {data.embeddings.memory_enabled && (
              <RecallCard data={data} onChange={load} />
            )}
            <SearchCard data={data} onChange={load} />
            <EmailCard data={data} onChange={load} />
            <CalendarCard data={data} onChange={load} />
            <ContactsCard data={data} onChange={load} />
            <BrowserCard data={data} onChange={load} />
            <PhoneCard data={data} onChange={load} />
            <MCPCard data={data} onChange={load} />
            <VaultCard data={data} onChange={load} />
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ model
export function ModelCard({
  data,
  onChange,
  compact,
}: {
  data: ConnectionsData;
  onChange: () => void;
  compact?: boolean;
}) {
  const { toast, state } = useStore();
  const t = useT();
  const [open, setOpen] = useState(!!compact);
  const presets = data.providers;
  // a member of the relay may name any model of the provider's for its kind, not only the menu's
  const anyModel = !!state.hub?.account?.any_model;
  const currentPreset =
    Object.entries(presets).find(
      ([id, p]) =>
        id !== "custom" &&
        p.base_url &&
        data.llm.base_url.startsWith(p.base_url) &&
        p.provider === data.llm.provider,
    )?.[0] ??
    Object.entries(presets).find(
      ([id, p]) =>
        id !== "custom" &&
        p.base_url &&
        data.llm.base_url.startsWith(p.base_url),
    )?.[0] ??
    (data.llm.base_url ? "custom" : "deepseek");
  const [preset, setPreset] = useState(currentPreset);
  const [model, setModel] = useState(data.llm.model);
  const [baseUrl, setBaseUrl] = useState(data.llm.base_url);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  // the ChatGPT sign-in, folded under the provider tiles
  const [chatgptOpen, setChatgptOpen] = useState(false);
  const [noKey, setNoKey] = useState(
    data.llm.key_source === "none" && !!presets[currentPreset]?.key_optional,
  );
  const [toolMode, setToolMode] = useState(data.llm.tool_mode || "auto");
  // `[llm] proxy` for this provider's requests; the runtime masks credentials in what it
  // shows, so the field is sent only once edited (typed = set, emptied = cleared)
  const [proxy, setProxy] = useState(data.llm.proxy ?? "");
  const [proxyTouched, setProxyTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  // the hands model (contract C4): "" = the default — the relay's hands model with the
  // account, the chat model otherwise; set here, it goes to [gui] model
  const [guiModel, setGuiModel] = useState(data.gui?.model ?? "");
  // the endpoint's own list of models, fetched when the provider, URL or key changes
  const [models, setModels] = useState<{
    list: string[];
    image: string[];
    video: string[];
    // nanoMuse Cloud, for a member: the menu and the other models under the Cloud key, grouped
    menu: string[];
    catalog: string[];
    imageCatalog: string[];
    videoCatalog: string[];
    vision: string[];
    /** the relay's hands models, recommended first (contract C4) */
    gui: string[];
    source: "live" | "catalogue" | "loading";
  }>({
    list: presets[currentPreset]?.models ?? [],
    image: [],
    video: [],
    menu: [],
    catalog: [],
    imageCatalog: [],
    videoCatalog: [],
    vision: [],
    gui: presets[currentPreset]?.gui_models ?? [],
    source: "catalogue",
  });
  // true once the user edits the model field by hand in this session: that value is never replaced
  const [typed, setTyped] = useState(false);
  // a member on nanoMuse Cloud picks from the grouped list; this flips the field to typing an id
  const [typingModel, setTypingModel] = useState(false);

  useEffect(() => {
    setModel(data.llm.model);
    setBaseUrl(data.llm.base_url);
    setToolMode(data.llm.tool_mode || "auto");
    setProxy(data.llm.proxy ?? "");
    setProxyTouched(false);
    setGuiModel(data.gui?.model ?? "");
    setPreset(currentPreset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.llm, data.gui?.model]);

  const p = presets[preset];
  const effectiveUrl =
    preset === "custom" || !p?.base_url ? baseUrl : p.base_url;

  // ask the endpoint what it serves; the typed model is never replaced by the answer
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const handle = setTimeout(
      () => {
        setModels((m) => ({ ...m, source: "loading" }));
        api
          .llmModels({
            preset,
            base_url: effectiveUrl,
            api_key: key || undefined,
          })
          .then((r) => {
            if (!alive) return;
            setModels({
              list: r.models,
              image: r.image_models ?? [],
              video: r.video_models ?? [],
              menu: r.menu ?? [],
              catalog: r.catalog ?? [],
              imageCatalog: r.image_catalog ?? [],
              videoCatalog: r.video_catalog ?? [],
              vision: r.vision ?? [],
              gui: r.gui ?? presets[preset]?.gui_models ?? [],
              source: r.source,
            });
            // a model left over from another provider yields to what this endpoint actually serves
            if (r.source === "live" && r.models.length && !typed)
              setModel((m) => (r.models.includes(m) ? m : r.models[0]));
          })
          .catch(
            () =>
              alive &&
              setModels({
                list: p?.models ?? [],
                image: [],
                video: [],
                menu: [],
                catalog: [],
                imageCatalog: [],
                videoCatalog: [],
                vision: [],
                gui: p?.gui_models ?? [],
                source: "catalogue",
              }),
          );
      },
      key ? 600 : 150,
    );
    return () => {
      alive = false;
      clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, preset, effectiveUrl, key]);

  const pick = (id: string) => {
    setPreset(id);
    const next = presets[id];
    if (!next) return;
    if (next.base_url) setBaseUrl(next.base_url);
    else if (presets[preset]?.base_url) setBaseUrl("");
    // a model typed by hand stays; an empty field or one from another preset's catalogue moves on
    const cameFromCatalogue =
      !model || Object.values(presets).some((q) => q.models?.includes(model));
    if (
      cameFromCatalogue &&
      next.models?.length &&
      !next.models.includes(model)
    )
      setModel(next.models[0]);
    setModels({
      list: next.models ?? [],
      image: [],
      video: [],
      menu: [],
      catalog: [],
      imageCatalog: [],
      videoCatalog: [],
      vision: [],
      gui: next.gui_models ?? [],
      source: "catalogue",
    });
    // the preset's own hands model comes along, unless the person set one by hand
    if (!data.gui?.model || Object.values(presets).some((q) => q.gui_model === data.gui?.model)) setGuiModel(next.cloud ? "" : (next.gui_model ?? ""));
    setTypingModel(false);
    setTyped(false);
    setNoKey(false);
  };

  // "Set it up" on the allowance card lands here with a provider already chosen (Alibaba
  // Cloud Bailian by default): the card opens on that preset, the key field waits for a paste.
  useEffect(() => {
    const hint = takePresetHint();
    if (hint && presets[hint]) {
      setOpen(true);
      pick(hint);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const keyless = !!p?.no_key || (noKey && !!p?.key_optional);
  const status = data.llm.cloud
    ? { text: t("Your account's model"), tone: "ok" }
    : data.llm.key_source === "none" &&
        !presets[currentPreset]?.no_key &&
        !presets[currentPreset]?.key_optional
      ? { text: t("No key yet"), tone: "warn" }
      : data.llm.key_source === "missing"
        ? { text: t("Key missing from vault"), tone: "warn" }
        : {
            text:
              data.llm.key_source === "vault"
                ? t("Key in vault")
                : data.llm.key_source === "config"
                  ? t("Key from config")
                  : t("No key needed"),
            tone: "ok",
          };

  const save = async () => {
    setSaving(true);
    setTest(null);
    try {
      if (p?.cloud) {
        // the account's key stays the key; only the model is chosen here
        await api.cloudUseAsModel(model.trim());
      } else {
        await api.setLLM({
          provider: p?.provider ?? "openai",
          model: model.trim(),
          base_url: effectiveUrl.trim(),
          tool_mode: toolMode,
          api_key: key ? key : keyless ? "" : null,
          // untouched: null leaves the runtime's value; "" clears it
          proxy: proxyTouched && data.llm.proxy !== undefined ? proxy.trim() : null,
        });
      }
      // the hands model rides on the chat model's endpoint and key (contract C4)
      if (guiModel.trim() !== (data.gui?.model ?? "")) await api.setGui({ model: guiModel.trim() });
      setKey("");
      invalidateProviders();
      toast(t("Model saved"));
      onChange();
      if (!compact) setOpen(false);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    try {
      setTest(await api.testLLM());
    } catch (e) {
      setTest({ ok: false, error: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const groups: Array<{ id: string; title: string; ids: string[] }> = [
    { id: "cloud", title: t("Your account"), ids: [] },
    { id: "openai", title: t("OpenAI-compatible · Chat Completions"), ids: [] },
    { id: "responses", title: t("Responses API"), ids: [] },
    { id: "local", title: t("Local or your own endpoint"), ids: [] },
  ];
  for (const [id, q] of Object.entries(presets))
    (groups.find((g) => g.id === (q.group ?? "openai")) ?? groups[0]).ids.push(
      id,
    );
  // the region's own-key provider first (contract C5): Bailian on the mainland, OpenRouter elsewhere
  for (const g of groups) g.ids = orderPresets(g.ids, presets, state.hub?.account);
  const needsUrl = preset === "custom" || !p?.base_url;
  // what the chosen provider covers, from the catalogue (contract C11); the account's model
  // covers all four through the relay, "custom" is whatever the endpoint happens to serve
  const catalogueEntry = p?.cloud ? null : CATALOGUE.find((c) => c.id === catalogueIdFor(preset)) ?? null;
  const region = regionOf(state.hub?.account);
  const locale = getLocale();
  const lacks = (cap: Capability) => !!catalogueEntry && !catalogueEntry.user_capabilities && !catalogueEntry.capabilities.includes(cap);
  // the hands with nothing set here (the Models contract §3): the account's hands model
  // on nanoMuse Cloud; an own provider's own hands model when it sees; the account's when
  // it cannot and the account is signed in; else the chat model
  const cloudPreset = presets[CLOUD_PRESET];
  const handsDefault = p?.cloud
    ? (models.gui[0] ?? p.gui_model ?? "")
    : catalogueEntry && !catalogueEntry.user_capabilities
      ? catalogueEntry.capabilities.includes("vision")
        ? catalogueEntry.defaults.hands || model.trim()
        : (cloudPreset?.gui_model ?? model.trim())
      : model.trim();
  const handsOnCloud = !p?.cloud && lacks("vision") && !!cloudPreset;
  // what the hands use right now, as the runtime resolved it (the saved state, not the form)
  const handsNow = data.gui ? handsValue(data.gui, data.llm, locale) : "";
  const handsOptions = Array.from(
    new Set([
      ...(p?.cloud ? models.gui : []),
      ...(p?.gui_model ? [p.gui_model] : []),
      ...models.list.filter((m) => models.vision.includes(m) || modelSees(m) === true),
    ]),
  ).filter(Boolean);
  // the hands picker's one group: this provider's models that see, the catalogue's hands
  // default first (the relay's recommended one on nanoMuse Cloud), folded past eight
  const handsProviderLabel = p?.cloud ? "nanoMuse Cloud" : catalogueEntry ? providerName(catalogueEntry, locale) : hostOf(effectiveUrl) || preset;
  const handsPreset = p?.cloud ? (models.gui[0] ?? p.gui_model ?? "") : (catalogueEntry?.defaults.hands ?? p?.gui_model ?? "");
  const handsGroups: ModelGroup[] = [{ key: "hands", label: handsProviderLabel, rows: handsOptions.map((id) => ({ id, name: id })), ...(handsPreset ? { default: handsPreset } : {}) }];
  const willAppendV1 = needsUrl && /^https?:\/\/[^/]+\/?$/.test(baseUrl.trim());

  return (
    <Card
      icon={<Bot size={19} />}
      title={t("Chat model")}
      summary={
        data.llm.cloud
          ? `nanoMuse Cloud · ${data.llm.model || "—"}`
          : `${data.llm.model || "—"}${data.llm.base_url ? ` · ${hostOf(data.llm.base_url)}` : ""}`
      }
      status={status}
      open={open}
      onToggle={compact ? undefined : () => setOpen(!open)}
    >
      <Field label={t("Provider")}>
        <div className="space-y-2.5">
          {groups
            .filter((g) => g.ids.length)
            .map((g) => (
              <div key={g.id}>
                <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">
                  {g.title}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {g.ids.map((id) => {
                    const q = presets[id];
                    return (
                      <button
                        key={id}
                        type="button"
                        onClick={() => pick(id)}
                        className={cx(
                          "rounded-2xl px-3 py-1.5 text-left border leading-tight",
                          preset === id
                            ? "border-accent bg-accent/10 text-accent"
                            : "border-border text-muted",
                        )}
                      >
                        <span
                          className={cx(
                            "block text-[13px]",
                            preset === id && "font-medium",
                          )}
                        >
                          {q.label}
                        </span>
                        {q.subtitle && (
                          <span className="block text-[10.5px] opacity-80">
                            {t(q.subtitle)}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          {catalogueEntry && (
            <p className="text-[12px] text-muted">
              <span className="font-medium text-fg">{providerName(catalogueEntry, locale)}</span> · {coversLine(t, catalogueEntry.capabilities)}
              {". "}
              {locale === "zh-CN" ? catalogueEntry.note_zh : catalogueEntry.note}
            </p>
          )}
          <div>
            <button type="button" onClick={() => setChatgptOpen(!chatgptOpen)} className="inline-flex items-center gap-1.5 text-[12.5px] text-accent">
              <LogIn size={13} /> {t("Or sign in with a ChatGPT plan")} {chatgptOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            {chatgptOpen && (
              <div className="mt-2">
                <ChatGptSignIn
                  compact
                  onChanged={() => {
                    onChange();
                  }}
                />
              </div>
            )}
          </div>
        </div>
      </Field>
      {needsUrl && (
        <Field
          label={t("Base URL")}
          hint={
            willAppendV1
              ? t("/v1 is added when the URL has no path.")
              : t(
                  "The endpoint that serves /chat/completions, for example http://127.0.0.1:8000/v1.",
                )
          }
        >
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            className={inputCls}
            placeholder="https://host/v1"
            inputMode="url"
            autoCapitalize="off"
          />
        </Field>
      )}
      <Field
        label={t("Chat model")}
        hint={
          p?.cloud && anyModel && models.catalog.length
            ? t(
                "{n} models your account may use: the menu first, then everything else the provider lists under the Cloud key. Pick one; the ones beyond the menu are priced as the dearest menu model of their kind.",
                { n: models.list.length },
              )
            : p?.cloud && anyModel
            ? t(
                "Your account may name any model the provider has, not only these: type its id (a chat model here, a picture or clip model below) and it goes through as typed.",
              )
            : models.source === "live"
              ? t("{n} models from the endpoint", { n: models.list.length })
              : models.source === "loading"
              ? t("Asking the endpoint…")
              : models.list.length
                ? t(
                    "Could not list the endpoint's models; these are the usual ones.",
                  )
                : undefined
        }
      >
        {p?.cloud && models.catalog.length > 0 && !typingModel && (!model || models.list.includes(model)) ? (
          // a member: the whole list to pick from, in groups — no id to type
          <select
            value={model}
            onChange={(e) => {
              if (e.target.value === OTHER_MODEL) {
                setTypingModel(true);
                return;
              }
              setModel(e.target.value);
              setTyped(true);
            }}
            className={cx(inputCls, "text-fg")}
          >
            {!model && <option value="">{t("model name")}</option>}
            <optgroup label={t("Menu")}>
              {models.menu.map((m) => (
                <option key={m} value={m}>
                  {models.vision.includes(m) ? `${m} · ${t("reads pictures")}` : m}
                </option>
              ))}
            </optgroup>
            <optgroup label={t("More models on your account")}>
              {models.catalog.map((m) => (
                <option key={m} value={m}>
                  {models.vision.includes(m) ? `${m} · ${t("reads pictures")}` : m}
                </option>
              ))}
            </optgroup>
            <option value={OTHER_MODEL}>{t("Type a model id…")}</option>
          </select>
        ) : (
          <>
            <input
              list="om-models"
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                setTyped(true);
              }}
              className={inputCls}
              placeholder={t("model name")}
              autoCapitalize="off"
              autoCorrect="off"
              autoFocus={typingModel}
            />
            <datalist id="om-models">
              {models.list.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            {p?.cloud && models.catalog.length > 0 && (
              <button
                type="button"
                className="mt-1.5 text-[12px] text-accent"
                onClick={() => {
                  setTypingModel(false);
                  if (!models.list.includes(model)) setModel(models.menu[0] ?? models.list[0] ?? "");
                }}
              >
                {t("Pick from the list")}
              </button>
            )}
          </>
        )}
        {models.list.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(models.menu.length ? models.menu : models.list).slice(0, 8).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setModel(m)}
                className={cx(
                  "rounded-full px-2.5 py-1 text-[12px] border",
                  model === m
                    ? "border-accent bg-accent/10 text-accent font-medium"
                    : "border-border text-muted",
                )}
              >
                {m}
              </button>
            ))}
          </div>
        )}
      </Field>
      <Field
        label={t("Hands model")}
        hint={
          p?.cloud
            ? t("The model that looks at screens when the hands run: the phone, this computer, a page the browser cannot read. Your account's hands model is {model}; the chat model above is a different pick.", { model: handsDefault || "—" })
            : handsOnCloud
              ? t("The model that looks at screens when the hands run. This provider has no model that sees, so the hands use your account's, {model}, unless you pick one here.", { model: handsDefault || "—" })
              : t("The model that looks at screens when the hands run: a small, fast one that takes pictures, on the same endpoint and key. Default: this provider's own hands model.")
        }
      >
        <ModelPicker
          label={t("Hands model")}
          text={guiModel ? `${handsProviderLabel} · ${guiModel}` : t("Automatic")}
          heads={[{ value: "", label: t("Automatic") }]}
          headValue={guiModel ? undefined : ""}
          groups={handsGroups}
          current={guiModel ? { group: "hands", id: guiModel } : undefined}
          onHead={() => setGuiModel("")}
          onPick={(_group, row) => setGuiModel(row.id)}
        />
        {handsNow && <p className="mt-1.5 text-[12px] text-muted">{t("Currently {value}", { value: handsNow })}</p>}
        {!p?.cloud && model.trim() && !guiModel && modelSees(model.trim()) === false && (
          <div className="mt-1.5 text-[12px] text-amber-700 dark:text-amber-300">
            {t("{model} does not take pictures, so the hands would be blind with it. Pick a model that sees for them.", { model: model.trim() })}
          </div>
        )}
        {lacks("vision") && !handsOnCloud && (
          <div className="mt-1.5 text-[12px] text-amber-700 dark:text-amber-300">
            {unavailableLine(t, "vision", region, locale)} <OwnKeyHow />
          </div>
        )}
      </Field>
      {!p?.no_key && (
        <Field
          label={t("API key")}
          hint={
            noKey && p?.key_optional
              ? t("No key will be sent.")
              : data.llm.key_source === "vault" && preset === currentPreset
                ? t("A key is in the vault. Leave blank to keep it.")
                : t("Stored encrypted in the vault as LLM_API_KEY.")
          }
        >
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              disabled={noKey && !!p?.key_optional}
              className={cx(inputCls, "pr-10 disabled:opacity-50")}
              placeholder={
                data.llm.key_source === "vault" && preset === currentPreset
                  ? "••••••••"
                  : p?.key_hint || "sk-…"
              }
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              aria-label={showKey ? t("Hide key") : t("Show key")}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1.5 text-muted"
            >
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2 text-[12px]">
            {p?.key_url ? (
              <a
                href={p.key_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-accent"
              >
                {t("Get a key from {vendor}", { vendor: p.label })}{" "}
                <ExternalLink size={12} />
              </a>
            ) : (
              <span />
            )}
            {p?.key_optional && (
              <label className="inline-flex items-center gap-1.5 text-muted">
                <input
                  type="checkbox"
                  checked={noKey}
                  onChange={(e) => setNoKey(e.target.checked)}
                  className="accent-accent"
                />{" "}
                {t("No key")}
              </label>
            )}
          </div>
        </Field>
      )}
      <Field
        label={t("Tool calling")}
        hint={t(
          "Auto uses the API's function calling and falls back to describing tools in the prompt when the endpoint rejects them. Prompt: for endpoints that silently ignore tools.",
        )}
      >
        <div className="flex gap-1.5">
          {["auto", "native", "prompt"].map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setToolMode(m)}
              className={cx(
                "rounded-full px-3 py-1.5 text-[13px] border",
                toolMode === m
                  ? "border-accent bg-accent/10 text-accent font-medium"
                  : "border-border text-muted",
              )}
            >
              {m}
            </button>
          ))}
        </div>
      </Field>
      {!p?.cloud && data.llm.proxy !== undefined && (
        <Field
          label={t("Proxy (optional)")}
          hint={t("Only this provider's requests go through it. nanoMuse Cloud never does.")}
        >
          <input
            className={inputCls}
            value={proxy}
            onChange={(e) => {
              setProxy(e.target.value);
              setProxyTouched(true);
            }}
            // a masked password cannot be edited in place: the field empties to be retyped
            onFocus={() => proxy.includes("••••") && !proxyTouched && setProxy("")}
            onBlur={() => !proxyTouched && setProxy(data.llm.proxy ?? "")}
            placeholder="http://host:port / socks5://host:port"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
      )}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={saving || !model.trim() || (needsUrl && !baseUrl.trim())}
          onClick={() => void save()}
          className={primaryBtn}
        >
          {saving ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Check size={16} />
          )}{" "}
          {t("Save")}
        </button>
        <button
          type="button"
          disabled={testing}
          onClick={() => void runTest()}
          className={secondaryBtn}
        >
          {testing ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Plug size={16} />
          )}{" "}
          {t("Test")}
        </button>
      </div>
      {test && (
        <TestLine
          result={test}
          okText={t('Replied "{reply}" in {ms} ms', {
            reply: test.reply ?? "",
            ms: test.ms ?? 0,
          })}
        />
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ pictures and clips
/**
 * One of the two media rows of the Models contract — *Making pictures* (`[image]`) and
 * *Making clips* (`[video]`). The value is `<provider> · <model>` as the runtime resolves it:
 * an explicit choice, else the chat provider's own model, else the account's. The picker
 * offers nanoMuse Cloud when signed in, the chat model's provider when it has the capability,
 * and every catalogue provider that has it (a key to add); nothing without it.
 */
export function MediaSlotCard({
  slot,
  data,
  onChange,
}: {
  slot: "image" | "video";
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast, state } = useStore();
  const t = useT();
  const info = data[slot]!;
  const cap: Capability = slot;
  const account = state.hub?.account ?? null;
  const signedIn = !!account?.signed_in;
  const region = regionOf(account);
  const locale = getLocale();
  const cloudBaseUrl = data.providers[CLOUD_PRESET]?.base_url ?? "";
  const choices = mediaChoices(cap, {
    signedIn,
    chat: { provider: data.llm.provider, base_url: data.llm.base_url, cloud: !!data.llm.cloud },
    region,
    locale,
  });
  const current = currentChoice(info, cloudBaseUrl);
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState(current);
  const [model, setModel] = useState(info.model);
  const [baseUrl, setBaseUrl] = useState(info.base_url);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<{ list: string[]; more: string[]; source: "live" | "catalogue" | "loading" }>({ list: [], more: [], source: "catalogue" });

  useEffect(() => {
    setChoice(current);
    setModel(info.model);
    setBaseUrl(info.base_url);
    setKey("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info]);

  const chosen = choices.find((c) => c.value === choice) ?? null;
  const entry = chosen?.entry ?? null;
  const edition = entry ? editionFor(entry, region) : null;
  const endpointUrl = choice === CLOUD_ID ? cloudBaseUrl : choice === CUSTOM_ID ? baseUrl.trim() : (edition?.base_url ?? "");
  // the key the slot would use: one typed here, the one saved for this very provider, the
  // chat model's on its own host, the account's on nanoMuse Cloud
  const keySaved = current === choice && current !== "" && (info.key_source === "vault" || info.key_source === "config");
  const needsKey = !!chosen?.needsKey && !key && !keySaved;
  const defaultModel = choice === CLOUD_ID ? (models.list[0] ?? "") : (entry?.defaults[slot] ?? "");

  // the endpoint's picture or clip models, when it lists any
  useEffect(() => {
    if (!open || !choice || (choice !== CLOUD_ID && !endpointUrl)) {
      setModels({ list: [], more: [], source: "catalogue" });
      return;
    }
    let alive = true;
    const handle = setTimeout(
      () => {
        setModels((m) => ({ ...m, source: "loading" }));
        api
          .llmModels(choice === CLOUD_ID ? { preset: CLOUD_PRESET } : { preset: entry ? presetFor(entry.id) : "", base_url: endpointUrl, api_key: key || undefined })
          .then((r) => {
            if (!alive) return;
            const list = (slot === "image" ? r.image_models : r.video_models) ?? [];
            const more = (slot === "image" ? r.image_catalog : r.video_catalog) ?? [];
            setModels({ list: list.filter((m) => !more.includes(m)), more, source: r.source });
          })
          .catch(() => alive && setModels({ list: [], more: [], source: "catalogue" }));
      },
      key ? 600 : 150,
    );
    return () => {
      alive = false;
      clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, choice, endpointUrl, key]);

  const title = slot === "image" ? t("Making pictures") : t("Making clips");
  const subtitle = slot === "image" ? t("Portraits of your Muse.") : t("Short clips of your Muse.");
  const value = slotValue(info, locale);
  const sentence = unavailableLine(t, cap, region, locale);
  const status = !info.effective_provider
    ? { text: t("Not set up"), tone: "warn" }
    : info.effective_source === "cloud"
      ? { text: t("Your account"), tone: "ok" }
      : info.effective_source === "chat"
        ? { text: t("The chat model's provider"), tone: "ok" }
        : { text: t("Your key"), tone: "ok" };
  const save = async () => {
    setSaving(true);
    try {
      if (!choice) {
        await api.setMedia(slot, { provider: "", model: "", base_url: "", api_key: "" });
      } else if (choice === CLOUD_ID) {
        await api.setMedia(slot, { provider: "openai", base_url: cloudBaseUrl, model: model.trim(), api_key: CLOUD_KEY_REF });
      } else if (choice === CUSTOM_ID) {
        await api.setMedia(slot, { provider: "openai", base_url: baseUrl.trim(), model: model.trim(), api_key: key ? key : null });
      } else {
        // the chat provider's own slot rides on the chat key: an empty key here says so
        await api.setMedia(slot, { provider: choice, base_url: "", model: model.trim(), api_key: key ? key : chosen?.group === "chat" ? "" : null });
      }
      setKey("");
      invalidateProviders();
      toast(t("Saved"));
      onChange();
      setOpen(false);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const groupTitle = (g: MediaChoice["group"]) => (g === "cloud" ? t("Your account") : g === "chat" ? t("The chat model's provider") : t("Add a provider"));
  const groups = (["cloud", "chat", "add"] as const).map((g) => ({ g, items: choices.filter((c) => c.group === g) })).filter((x) => x.items.length);
  const vaultName = slot === "image" ? "IMAGE_API_KEY" : "VIDEO_API_KEY";

  return (
    <Card
      icon={slot === "image" ? <ImageIcon size={19} /> : <Clapperboard size={19} />}
      title={title}
      summary={value || sentence}
      status={status}
      open={open}
      onToggle={() => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted">{subtitle}</p>
      <Field label={t("Provider")} hint={!value && !choice ? sentence : undefined}>
        <select
          value={choice}
          onChange={(e) => {
            setChoice(e.target.value);
            setModel("");
            setKey("");
          }}
          className={cx(inputCls, "text-fg")}
        >
          <option value="">{t("Automatic")}</option>
          {groups.map(({ g, items }) => (
            <optgroup key={g} label={groupTitle(g)}>
              {items.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.value === CUSTOM_ID ? t("Other OpenAI-compatible endpoint") : c.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {value && <p className="mt-1.5 text-[12px] text-muted">{t("Currently {value}", { value })}</p>}
        {!value && !choice && (
          <button type="button" className="mt-1.5 inline-flex items-center gap-1 text-[12.5px] text-accent" onClick={() => setChoice(choices.find((c) => c.group === "add")?.value ?? "")}>
            <Plus size={13} /> {t("Add a provider")}
          </button>
        )}
        {entry && (
          <p className="mt-1.5 text-[12px] text-muted">
            <span className="font-medium text-fg">{providerName(entry, locale)}</span> · {coversLine(t, entry.capabilities)}
            {". "}
            {locale === "zh-CN" ? entry.note_zh : entry.note}
          </p>
        )}
      </Field>
      {choice === CUSTOM_ID && (
        <Field label={t("Base URL")} hint={t("The endpoint that serves /images/generations, for example https://host/v1.")}>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className={inputCls} placeholder="https://host/v1" inputMode="url" autoCapitalize="off" />
        </Field>
      )}
      {choice && (
        <StudioModelPick
          label={slot === "image" ? t("Picture model") : t("Clip model")}
          provider={choice === CLOUD_ID ? "nanoMuse Cloud" : choice === CUSTOM_ID ? hostOf(baseUrl) || t("Other OpenAI-compatible endpoint") : (chosen?.label ?? choice)}
          value={model}
          options={models.list}
          more={models.more}
          onChange={setModel}
          other={choice !== CLOUD_ID || !!account?.any_model}
          placeholder={defaultModel || undefined}
        />
      )}
      {choice && choice !== CLOUD_ID && chosen?.group !== "chat" && (
        <Field
          label={t("API key")}
          hint={keySaved ? t("A key is in the vault. Leave blank to keep it.") : t("Stored encrypted in the vault as {name}.", { name: vaultName })}
        >
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              className={cx(inputCls, "pr-10")}
              placeholder={keySaved ? "••••••••" : (entry?.key_hint || "sk-…")}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
            />
            <button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? t("Hide key") : t("Show key")} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1.5 text-muted">
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {edition?.key_url && (
            <a href={edition.key_url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-[12px] text-accent">
              {t("Get a key from {vendor}", { vendor: entry ? providerName(entry, locale) : "" })} <ExternalLink size={12} />
            </a>
          )}
        </Field>
      )}
      {chosen?.group === "chat" && <p className="text-[12px] text-muted">{t("Uses the chat model's key.")}</p>}
      <div className="flex gap-2 pt-1">
        <button type="button" disabled={saving || needsKey || (choice === CUSTOM_ID && !baseUrl.trim())} onClick={() => void save()} className={primaryBtn}>
          {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} {t("Save")}
        </button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ recall by meaning
/**
 * Memories embedded once, the message embedded per turn, the closest fused with the keyword
 * hits — so "写邮件给房东" finds "the landlord is Bob Li". Works with the model's own endpoint
 * when it has /embeddings (OpenAI, Ollama, most gateways); DeepSeek has none, so this card is
 * where an Ollama next door gets pointed at.
 */
export function RecallCard({
  data,
  onChange,
}: {
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast } = useStore();
  const t = useT();
  const e = data.embeddings;
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState(e.mode);
  const [own, setOwn] = useState(!!e.base_url);
  const [baseUrl, setBaseUrl] = useState(e.base_url);
  const [model, setModel] = useState(e.model);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    setMode(e.mode);
    setOwn(!!e.base_url);
    setBaseUrl(e.base_url);
    setModel(e.model);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.embeddings]);

  const status =
    e.mode === "off"
      ? { text: t("Off"), tone: "off" }
      : e.available === true
        ? { text: t("On"), tone: "ok" }
        : e.available === false
          ? {
              text: e.mode === "on" ? t("Not reachable") : t("By keyword"),
              tone: "warn",
            }
          : { text: t("Not tried yet"), tone: "off" };
  const summary =
    e.mode === "off"
      ? t("Keyword recall only")
      : e.available === true
        ? t("{model} · {n} of {total} memories indexed", {
            model: e.model || e.default_model,
            n: e.indexed,
            total: e.total,
          })
        : e.available === false
          ? e.reason
          : t("{model} at {host}", {
              model: e.model || e.default_model,
              host: hostOf(e.effective_base_url),
            });

  const save = async () => {
    setSaving(true);
    setTest(null);
    try {
      await api.setEmbeddings({
        mode,
        base_url: own ? baseUrl.trim() : "",
        model: model.trim(),
        api_key: own ? (key ? key : undefined) : "",
      });
      setKey("");
      toast(t("Saved"));
      onChange();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const runTest = async () => {
    setTesting(true);
    try {
      setTest(await api.testEmbeddings());
      onChange();
    } catch (err) {
      setTest({ ok: false, error: (err as Error).message });
    } finally {
      setTesting(false);
    }
  };
  const chip = (on: boolean) =>
    cx(
      "rounded-full px-3 py-1.5 text-[13px] border",
      on
        ? "border-accent bg-accent/10 text-accent font-medium"
        : "border-border text-muted",
    );

  return (
    <Card
      icon={<BrainCircuit size={19} />}
      title={t("Recall by meaning")}
      summary={summary}
      status={status}
      open={open}
      onToggle={() => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted leading-snug">
        {t(
          "Memories are embedded once and a message finds the ones that mean the same thing, in any language: “写邮件给房东” finds “the landlord is Bob Li”. Keyword recall stays; the two are fused.",
        )}
      </p>
      <Field
        label={t("Mode")}
        hint={t(
          "Auto uses the model's endpoint when it has embeddings and falls back to keywords when it does not. On insists and warns. Off: keywords only.",
        )}
      >
        <div className="flex gap-1.5">
          {(["auto", "on", "off"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={chip(mode === m)}
            >
              {m === "auto" ? t("Auto") : m === "on" ? t("On") : t("Off")}
            </button>
          ))}
        </div>
      </Field>
      {mode !== "off" && (
        <>
          <Field
            label={t("Endpoint")}
            hint={
              own
                ? t(
                    "Any OpenAI-compatible /embeddings: Ollama with an embedding model pulled, OpenAI, a gateway.",
                  )
                : t(
                    "The model's endpoint and key. DeepSeek has no embeddings; pick another endpoint.",
                  )
            }
          >
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => setOwn(false)}
                className={chip(!own)}
              >
                {t("Same as the model")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setOwn(true);
                  if (!baseUrl) setBaseUrl("http://127.0.0.1:11434/v1");
                }}
                className={chip(own)}
              >
                {t("Another endpoint")}
              </button>
            </div>
          </Field>
          {own && (
            <>
              <Field label={t("Base URL")}>
                <input
                  value={baseUrl}
                  onChange={(ev) => setBaseUrl(ev.target.value)}
                  className={inputCls}
                  placeholder="http://127.0.0.1:11434/v1"
                  inputMode="url"
                />
              </Field>
              <Field
                label={t("API key")}
                hint={
                  e.key_source === "vault"
                    ? t("A key is in the vault. Leave blank to keep it.")
                    : t(
                        "Stored encrypted in the vault as EMBEDDINGS_API_KEY. Ollama needs none.",
                      )
                }
              >
                <input
                  type="password"
                  value={key}
                  onChange={(ev) => setKey(ev.target.value)}
                  className={inputCls}
                  placeholder={e.key_source === "vault" ? "••••••••" : "sk-…"}
                  autoComplete="off"
                />
              </Field>
            </>
          )}
          <Field
            label={t("Embedding model")}
            hint={t(
              "Blank uses the endpoint's default: {model}. On Ollama: ollama pull qwen3-embedding:0.6b (reads Chinese and English).",
              { model: e.default_model },
            )}
          >
            <input
              value={model}
              onChange={(ev) => setModel(ev.target.value)}
              className={inputCls}
              placeholder={e.default_model}
              autoComplete="off"
            />
          </Field>
        </>
      )}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={saving || (own && !/^https?:\/\//.test(baseUrl.trim()))}
          onClick={() => void save()}
          className={primaryBtn}
        >
          {saving ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Check size={16} />
          )}{" "}
          {t("Save")}
        </button>
        <button
          type="button"
          disabled={testing || e.mode === "off"}
          onClick={() => void runTest()}
          className={secondaryBtn}
        >
          {testing ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Plug size={16} />
          )}{" "}
          {t("Test")}
        </button>
      </div>
      {test && (
        <TestLine
          result={test}
          okText={t("{model} · {dims} dims · {n} memories indexed · {ms} ms", {
            model: test.model ?? "",
            dims: test.dims ?? 0,
            n: test.indexed ?? 0,
            ms: test.ms ?? 0,
          })}
        />
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ web search
/**
 * Who answers `web_search`. DuckDuckGo needs nothing and is the default but is scraped, so it
 * rate-limits now and then; Brave and Tavily take a key, SearXNG the URL of an instance you run.
 * Whatever is picked, a failed search falls back to DuckDuckGo once, with a note.
 */
export function SearchCard({
  data,
  onChange,
}: {
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast } = useStore();
  const t = useT();
  const s = data.search;
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState(s.provider);
  const [baseUrl, setBaseUrl] = useState(s.base_url);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    setProvider(s.provider);
    setBaseUrl(s.base_url);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.search]);

  const info = s.providers.find((p) => p.id === s.provider);
  const chosen = s.providers.find((p) => p.id === provider);
  const needsKey = !!chosen?.needs_key;
  const status = s.configured
    ? { text: t("On"), tone: "ok" }
    : { text: t("Not set up"), tone: "warn" };
  const summary = s.configured
    ? s.provider === "searxng"
      ? t("{provider} at {host}", {
          provider: info?.label ?? s.provider,
          host: hostOf(s.base_url),
        })
      : (info?.label ?? s.provider)
    : t("{provider} needs {what}; searches use DuckDuckGo until then", {
        provider: info?.label ?? s.provider,
        what: info?.needs_key ? t("a key") : t("an instance URL"),
      });

  const save = async () => {
    setSaving(true);
    setTest(null);
    try {
      await api.setSearch({
        provider,
        base_url: provider === "searxng" ? baseUrl.trim() : "",
        api_key: needsKey ? (key ? key : undefined) : "",
      });
      setKey("");
      toast(t("Saved"));
      onChange();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const runTest = async () => {
    setTesting(true);
    try {
      setTest(await api.testSearch());
    } catch (err) {
      setTest({ ok: false, error: (err as Error).message });
    } finally {
      setTesting(false);
    }
  };
  const chip = (on: boolean) =>
    cx(
      "rounded-full px-3 py-1.5 text-[13px] border",
      on
        ? "border-accent bg-accent/10 text-accent font-medium"
        : "border-border text-muted",
    );
  const canSave = provider !== "searxng" || /^https?:\/\//.test(baseUrl.trim());

  return (
    <Card
      icon={<Search size={19} />}
      title={t("Web search")}
      summary={summary}
      status={status}
      open={open}
      onToggle={() => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted leading-snug">
        {t(
          "DuckDuckGo needs nothing, but it is scraped and rate-limits now and then. For searches that always work, use a provider with an API. Whichever you pick, a failed search falls back to DuckDuckGo with a note.",
        )}
      </p>
      <Field label={t("Provider")}>
        <div className="flex flex-wrap gap-1.5">
          {s.providers.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setProvider(p.id as typeof provider)}
              className={chip(provider === p.id)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </Field>
      {needsKey && (
        <Field
          label={t("API key")}
          hint={
            s.key_source === "vault" && s.provider === provider
              ? t("A key is in the vault. Leave blank to keep it.")
              : t("Stored encrypted in the vault as SEARCH_API_KEY.")
          }
        >
          <input
            type="password"
            value={key}
            onChange={(ev) => setKey(ev.target.value)}
            className={inputCls}
            placeholder={
              s.key_source === "vault" && s.provider === provider
                ? "••••••••"
                : "…"
            }
            autoComplete="off"
          />
          {chosen?.keys_url && (
            <a
              href={chosen.keys_url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-block text-[12px] text-accent"
            >
              {t("Get a key from {label}", { label: chosen.label })}
            </a>
          )}
        </Field>
      )}
      {provider === "searxng" && (
        <Field
          label={t("Instance URL")}
          hint={t(
            "A SearXNG you run, with the JSON format enabled in its settings.",
          )}
        >
          <input
            value={baseUrl}
            onChange={(ev) => setBaseUrl(ev.target.value)}
            className={inputCls}
            placeholder="http://127.0.0.1:8080"
            inputMode="url"
          />
        </Field>
      )}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={saving || !canSave}
          onClick={() => void save()}
          className={primaryBtn}
        >
          {saving ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Check size={16} />
          )}{" "}
          {t("Save")}
        </button>
        <button
          type="button"
          disabled={testing}
          onClick={() => void runTest()}
          className={secondaryBtn}
        >
          {testing ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Plug size={16} />
          )}{" "}
          {t("Test")}
        </button>
      </div>
      {test && (
        <TestLine
          result={test}
          okText={t("{provider} · {n} results · {ms} ms", {
            provider: test.provider ?? "",
            n: test.results ?? 0,
            ms: test.ms ?? 0,
          })}
        />
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ email
const MAIL_PRESETS: Array<{
  id: string;
  label: string;
  imap: string;
  smtp: string;
  port: number;
  starttls: boolean;
}> = [
  {
    id: "gmail",
    label: "Gmail",
    imap: "imap.gmail.com",
    smtp: "smtp.gmail.com",
    port: 587,
    starttls: true,
  },
  {
    id: "outlook",
    label: "Outlook",
    imap: "outlook.office365.com",
    smtp: "smtp.office365.com",
    port: 587,
    starttls: true,
  },
  {
    id: "icloud",
    label: "iCloud",
    imap: "imap.mail.me.com",
    smtp: "smtp.mail.me.com",
    port: 587,
    starttls: true,
  },
  {
    id: "qq",
    label: "QQ",
    imap: "imap.qq.com",
    smtp: "smtp.qq.com",
    port: 587,
    starttls: true,
  },
  {
    id: "163",
    label: "163",
    imap: "imap.163.com",
    smtp: "smtp.163.com",
    port: 465,
    starttls: false,
  },
  {
    id: "fastmail",
    label: "Fastmail",
    imap: "imap.fastmail.com",
    smtp: "smtp.fastmail.com",
    port: 587,
    starttls: true,
  },
];

export function EmailCard({
  data,
  onChange,
  compact,
}: {
  data: ConnectionsData;
  onChange: () => void;
  compact?: boolean;
}) {
  const { toast } = useStore();
  const t = useT();
  const e = data.email;
  const [open, setOpen] = useState(!!compact);
  const [address, setAddress] = useState(e.address);
  const [password, setPassword] = useState("");
  const [imap, setImap] = useState(e.imap_host);
  const [imapPort, setImapPort] = useState(e.imap_port);
  const [smtp, setSmtp] = useState(e.smtp_host);
  const [smtpPort, setSmtpPort] = useState(e.smtp_port);
  const [starttls, setStarttls] = useState(e.smtp_starttls);
  const [busy, setBusy] = useState<"save" | "test" | "off" | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);

  useEffect(() => {
    setAddress(e.address);
    setImap(e.imap_host);
    setImapPort(e.imap_port);
    setSmtp(e.smtp_host);
    setSmtpPort(e.smtp_port);
    setStarttls(e.smtp_starttls);
  }, [e]);

  const applyPreset = (p: (typeof MAIL_PRESETS)[number]) => {
    setImap(p.imap);
    setImapPort(993);
    setSmtp(p.smtp);
    setSmtpPort(p.port);
    setStarttls(p.starttls);
  };

  const connect = async () => {
    setBusy("save");
    setTest(null);
    try {
      await api.setEmail({
        enabled: true,
        address: address.trim(),
        password: password || undefined,
        imap_host: imap.trim(),
        imap_port: imapPort,
        smtp_host: smtp.trim(),
        smtp_port: smtpPort,
        smtp_starttls: starttls,
      });
      setPassword("");
      const result = await api.testEmail();
      setTest(result);
      toast(result.ok ? t("Email connected") : t("Saved, but the test failed"));
      onChange();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("off");
    try {
      await api.disconnectEmail();
      setTest(null);
      toast(t("Email disconnected"));
      onChange();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const status =
    e.enabled && e.configured
      ? { text: t("Connected"), tone: "ok" }
      : e.enabled
        ? { text: t("Incomplete"), tone: "warn" }
        : { text: t("Not connected"), tone: "off" };

  return (
    <Card
      icon={<Mail size={19} />}
      title={t("Email")}
      summary={
        e.configured && e.enabled
          ? `${e.address} · ${t("reads and sends")}`
          : t("Read your inbox, draft and send mail")
      }
      status={status}
      open={open}
      onToggle={compact ? undefined : () => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted -mt-1">
        {t(
          "Reading is a moderate action; sending always asks you first. Use an app password where your provider offers one.",
        )}
      </p>
      <Field label={t("Provider")}>
        <div className="flex flex-wrap gap-1.5">
          {MAIL_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => applyPreset(p)}
              className={cx(
                "rounded-full px-3 py-1.5 text-[13px] border",
                imap === p.imap
                  ? "border-accent bg-accent/10 text-accent font-medium"
                  : "border-border text-muted",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </Field>
      <Field label={t("Address")}>
        <input
          value={address}
          onChange={(ev) => setAddress(ev.target.value)}
          className={inputCls}
          placeholder="you@example.com"
          inputMode="email"
          autoComplete="off"
        />
      </Field>
      <Field
        label={t("Password")}
        hint={
          e.password_set
            ? t("A password is in the vault. Leave blank to keep it.")
            : t("Stored encrypted in the vault as EMAIL_PASSWORD.")
        }
      >
        <input
          type="password"
          value={password}
          onChange={(ev) => setPassword(ev.target.value)}
          className={inputCls}
          placeholder={e.password_set ? "••••••••" : t("app password")}
          autoComplete="off"
        />
      </Field>
      <div className="grid grid-cols-[1fr_84px] gap-2">
        <Field label={t("IMAP server")}>
          <input
            value={imap}
            onChange={(ev) => setImap(ev.target.value)}
            className={inputCls}
            placeholder="imap.example.com"
          />
        </Field>
        <Field label={t("Port")}>
          <input
            type="number"
            value={imapPort}
            onChange={(ev) => setImapPort(Number(ev.target.value))}
            className={inputCls}
          />
        </Field>
        <Field label={t("SMTP server")}>
          <input
            value={smtp}
            onChange={(ev) => setSmtp(ev.target.value)}
            className={inputCls}
            placeholder="smtp.example.com"
          />
        </Field>
        <Field label={t("Port")}>
          <input
            type="number"
            value={smtpPort}
            onChange={(ev) => setSmtpPort(Number(ev.target.value))}
            className={inputCls}
          />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-[13.5px]">
        <input
          type="checkbox"
          checked={starttls}
          onChange={(ev) => setStarttls(ev.target.checked)}
          className="accent-[var(--om-accent)]"
        />{" "}
        {t("STARTTLS for SMTP (off for port 465)")}
      </label>
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={
            busy !== null ||
            !address.trim() ||
            !imap.trim() ||
            !smtp.trim() ||
            (!password && !e.password_set)
          }
          onClick={() => void connect()}
          className={primaryBtn}
        >
          {busy === "save" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Plug size={16} />
          )}{" "}
          {e.configured ? t("Save & test") : t("Connect")}
        </button>
        {e.enabled && (
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void disconnect()}
            className={secondaryBtn}
          >
            {busy === "off" ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Unplug size={16} />
            )}{" "}
            {t("Disconnect")}
          </button>
        )}
      </div>
      {test && (
        <TestLine
          result={test}
          okText={t("Signed in · {n} messages in the inbox", {
            n: test.inbox ?? "?",
          })}
        />
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ calendar
/** Where the private .ics link hides, per provider — the one thing people get stuck on. */
const CALENDAR_HINTS: Array<{ id: string; label: string; hint: string }> = [
  {
    id: "google",
    label: "Google",
    hint: "Settings → your calendar → Integrate calendar → Secret address in iCal format",
  },
  {
    id: "outlook",
    label: "Outlook",
    hint: "Settings → Calendar → Shared calendars → Publish a calendar → ICS link",
  },
  {
    id: "icloud",
    label: "iCloud",
    hint: "Share Calendar → Public Calendar → copy the webcal:// link",
  },
  {
    id: "fastmail",
    label: "Fastmail",
    hint: "Settings → Calendars → Export → Calendar URL",
  },
  {
    id: "file",
    label: ".ics file",
    hint: "A path on the machine where nanoMuse runs, for example ~/calendar.ics",
  },
];

export function CalendarCard({
  data,
  onChange,
  compact,
}: {
  data: ConnectionsData;
  onChange: () => void;
  compact?: boolean;
}) {
  const { toast } = useStore();
  const t = useT();
  const c = data.calendar;
  const [open, setOpen] = useState(!!compact);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [dayStart, setDayStart] = useState(c.day_start);
  const [dayEnd, setDayEnd] = useState(c.day_end);
  const [busy, setBusy] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);

  useEffect(() => {
    setDayStart(c.day_start);
    setDayEnd(c.day_end);
  }, [c.day_start, c.day_end]);

  const add = async () => {
    setBusy("add");
    setTest(null);
    try {
      const view = await api.addCalendarFeed(name.trim(), url.trim());
      if (view.error) {
        toast(
          t("Added, but it could not be read: {error}", { error: view.error }),
        );
      } else {
        const feed = view.feeds.find((f) => f.name === name.trim());
        toast(`${t("Calendar connected")} · ${evs(feed?.events ?? 0)}`);
        setName("");
        setUrl("");
        setAdding(false);
      }
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (n: string) => {
    setBusy(n);
    try {
      await api.removeCalendarFeed(n);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const saveHours = async () => {
    setBusy("hours");
    try {
      await api.setCalendar({ day_start: dayStart, day_end: dayEnd });
      toast(t("Saved"));
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const runTest = async () => {
    setBusy("test");
    try {
      setTest(await api.testCalendar());
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const total = c.feeds.reduce((n, f) => n + f.events, 0);
  const broken = c.feeds.filter((f) => f.error).length;
  const evs = (n: number) => (n === 1 ? t("1 event") : t("{n} events", { n }));
  const status = c.configured
    ? broken
      ? { text: t("{n} not reading", { n: broken }), tone: "warn" }
      : { text: t("Connected"), tone: "ok" }
    : { text: t("Not connected"), tone: "off" };

  return (
    <Card
      icon={<CalendarDays size={19} />}
      title={t("Calendar")}
      summary={
        !c.configured
          ? t("Your agenda, free time, and events it can draft")
          : c.feeds.length === 1
            ? `${c.feeds[0].name} · ${evs(total)}`
            : `${t("{n} calendars", { n: c.feeds.length })} · ${evs(total)}`
      }
      status={status}
      open={open}
      onToggle={compact ? undefined : () => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted -mt-1">
        {t(
          "Reads your calendar from its private .ics link; the link stays in the vault. It never changes your calendar; an event it proposes comes as a file you add with a tap.",
        )}
      </p>
      {c.feeds.length > 0 && (
        <ul className="space-y-1.5">
          {c.feeds.map((f) => (
            <li
              key={f.name}
              className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2"
            >
              <span
                className={cx(
                  "h-2 w-2 rounded-full",
                  f.error
                    ? "bg-rose-500"
                    : f.fetched_at
                      ? "bg-emerald-500"
                      : "bg-amber-500",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">
                  {f.name}
                </div>
                <div className="text-[11.5px] text-muted truncate">
                  {f.error
                    ? f.error
                    : f.fetched_at
                      ? `${evs(f.events)} · ${t("read {when}", { when: relativeTime(f.fetched_at) })}`
                      : t("not read yet")}
                  {!f.from_app && ` · ${t("from config.toml")}`}
                </div>
              </div>
              {f.from_app && (
                <button
                  type="button"
                  aria-label={t("Remove")}
                  disabled={busy === f.name}
                  onClick={() => void remove(f.name)}
                  className="p-1.5 rounded-full text-muted hover:bg-surface-2"
                >
                  {busy === f.name ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Trash2 size={15} />
                  )}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <div className="space-y-2.5 rounded-2xl border border-border/70 p-3">
          <Field label={t("Where is the link?")}>
            <div className="flex flex-wrap gap-1.5">
              {CALENDAR_HINTS.map((h) => (
                <button
                  key={h.id}
                  type="button"
                  onClick={() => setHint(hint === h.id ? null : h.id)}
                  className={cx(
                    "rounded-full px-3 py-1.5 text-[13px] border",
                    hint === h.id
                      ? "border-accent bg-accent/10 text-accent font-medium"
                      : "border-border text-muted",
                  )}
                >
                  {t(h.label)}
                </button>
              ))}
            </div>
            {hint && (
              <div className="mt-1.5 text-[11.5px] text-muted leading-snug">
                {t(CALENDAR_HINTS.find((h) => h.id === hint)!.hint)}
              </div>
            )}
          </Field>
          <Field label={t("Name")}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputCls}
              placeholder={t("Work")}
            />
          </Field>
          <Field
            label={t("Private .ics link or file path")}
            hint={
              t("Stored encrypted in the vault as CALENDAR_{name}.", {
                name:
                  name
                    .trim()
                    .toUpperCase()
                    .replace(/[^A-Z0-9]+/g, "_")
                    .replace(/^_+|_+$/g, "") || "NAME",
              }) +
              " " +
              t("nanoMuse fetches whatever address you put here, from this machine; only paste links you trust.")
            }
          >
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className={inputCls}
              placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"
              inputMode="url"
              autoComplete="off"
            />
          </Field>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy === "add" || !name.trim() || !url.trim()}
              onClick={() => void add()}
              className={primaryBtn}
            >
              {busy === "add" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Plug size={16} />
              )}{" "}
              {t("Connect")}
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className={secondaryBtn}
            >
              {t("Cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className={secondaryBtn}
        >
          <Plus size={16} /> {t("Add a calendar")}
        </button>
      )}
      {c.configured && (
        <>
          <Field
            label={t("Working hours")}
            hint={t("Free time is looked for inside these hours.")}
          >
            <div className="flex items-center gap-2">
              <input
                type="time"
                value={dayStart}
                onChange={(e) => setDayStart(e.target.value)}
                className={cx(inputCls, "w-auto")}
              />
              <span className="text-muted">–</span>
              <input
                type="time"
                value={dayEnd}
                onChange={(e) => setDayEnd(e.target.value)}
                className={cx(inputCls, "w-auto")}
              />
              {(dayStart !== c.day_start || dayEnd !== c.day_end) && (
                <button
                  type="button"
                  disabled={busy === "hours"}
                  onClick={() => void saveHours()}
                  className={cx(primaryBtn, "px-3")}
                  aria-label={t("Save")}
                >
                  {busy === "hours" ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Check size={16} />
                  )}
                </button>
              )}
            </div>
          </Field>
          <button
            type="button"
            disabled={busy === "test"}
            onClick={() => void runTest()}
            className={secondaryBtn}
          >
            {busy === "test" ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}{" "}
            {t("Read again")}
          </button>
          {test && (
            <TestLine
              result={test}
              okText={
                c.feeds.length === 1
                  ? evs(test.events ?? 0)
                  : `${evs(test.events ?? 0)} · ${t("{n} calendars", { n: c.feeds.length })}`
              }
            />
          )}
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ contacts
export function ContactsCard({
  data,
  onChange,
  compact,
}: {
  data: ConnectionsData;
  onChange: () => void;
  compact?: boolean;
}) {
  const { toast } = useStore();
  const t = useT();
  const c = data.contacts;
  const [open, setOpen] = useState(!!compact);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Contact[] | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const people = (n: number) =>
    n === 1 ? t("1 person") : t("{n} people", { n });

  const finish = (
    view: ConnectionsData["contacts"] & { error?: string },
    added: string,
  ) => {
    if (view.error) {
      toast(
        t("Added, but it could not be read: {error}", { error: view.error }),
      );
    } else {
      const src = view.sources.find((x) => x.name === added);
      toast(`${t("Address book connected")} · ${people(src?.contacts ?? 0)}`);
      setName("");
      setUrl("");
      setAdding(false);
    }
    onChange();
  };

  const add = async () => {
    setBusy("add");
    setTest(null);
    try {
      finish(await api.addContactsSource(name.trim(), url.trim()), name.trim());
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const upload = async (file: File) => {
    setBusy("upload");
    setTest(null);
    try {
      const label = (
        name.trim() ||
        file.name.replace(/\.vcf$/i, "") ||
        "Imported"
      ).slice(0, 40);
      finish(await api.importContacts(label, await file.text()), label);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const remove = async (n: string) => {
    setBusy(n);
    try {
      await api.removeContactsSource(n);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const runTest = async () => {
    setBusy("test");
    try {
      setTest(await api.testContacts());
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    if (!query.trim()) {
      setHits(null);
      return;
    }
    const handle = setTimeout(() => {
      api
        .contacts(query.trim(), 5)
        .then((r) => setHits(r.people))
        .catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  const broken = c.sources.filter((f) => f.error).length;
  const status = !c.enabled
    ? { text: t("Off"), tone: "off" }
    : c.configured
      ? broken
        ? { text: t("{n} not reading", { n: broken }), tone: "warn" }
        : { text: t("Connected"), tone: "ok" }
      : { text: t("Not connected"), tone: "off" };

  return (
    <Card
      icon={<ContactIcon size={19} />}
      title={t("Contacts")}
      summary={
        !c.configured
          ? t("Who is who, so it never guesses an address")
          : c.sources.length === 0
            ? `${people(c.count)} · ${t("told to it in chat")}`
            : `${people(c.count)} · ${c.sources.length === 1 ? c.sources[0].name : t("{n} address books", { n: c.sources.length })}`
      }
      status={status}
      open={open}
      onToggle={compact ? undefined : () => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted -mt-1">
        {t(
          "Import a .vcf export from Google Contacts, iCloud, Outlook or your phone, or paste a link to one. People you mention in chat go into its own book. It looks people up before writing to them and warns when an address is unknown.",
        )}
      </p>
      {(c.sources.length > 0 || c.own > 0) && (
        <ul className="space-y-1.5">
          {c.own > 0 && (
            <li className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">
                  {t("My contacts")}
                </div>
                <div className="text-[11.5px] text-muted truncate">{`${people(c.own)} · ${t("added in chat")}`}</div>
              </div>
            </li>
          )}
          {c.sources.map((f) => (
            <li
              key={f.name}
              className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2"
            >
              <span
                className={cx(
                  "h-2 w-2 rounded-full",
                  f.error
                    ? "bg-rose-500"
                    : f.fetched_at
                      ? "bg-emerald-500"
                      : "bg-amber-500",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">
                  {f.name}
                </div>
                <div className="text-[11.5px] text-muted truncate">
                  {f.error
                    ? f.error
                    : f.fetched_at
                      ? `${people(f.contacts)} · ${t("read {when}", { when: relativeTime(f.fetched_at) })}`
                      : t("not read yet")}
                  {!f.from_app && ` · ${t("from config.toml")}`}
                </div>
              </div>
              {f.from_app && (
                <button
                  type="button"
                  aria-label={t("Remove")}
                  disabled={busy === f.name}
                  onClick={() => void remove(f.name)}
                  className="p-1.5 rounded-full text-muted hover:bg-surface-2"
                >
                  {busy === f.name ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Trash2 size={15} />
                  )}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <div className="space-y-2.5 rounded-2xl border border-border/70 p-3">
          <Field label={t("Name")}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputCls}
              placeholder={t("iPhone")}
            />
          </Field>
          <Field
            label={t("A .vcf file from your phone or computer")}
            hint={t(
              "Google Contacts: Export → vCard. iPhone: Contacts → select all → Share → Save to Files. Outlook: People → Manage → Export.",
            )}
          >
            <input
              ref={fileInput}
              type="file"
              accept=".vcf,text/vcard,text/x-vcard"
              className="hidden"
              onChange={(e) =>
                e.target.files?.[0] && void upload(e.target.files[0])
              }
            />
            <button
              type="button"
              disabled={busy === "upload"}
              onClick={() => fileInput.current?.click()}
              className={secondaryBtn}
            >
              {busy === "upload" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Upload size={16} />
              )}{" "}
              {t("Choose a .vcf file")}
            </button>
          </Field>
          <Field
            label={t("Or a link / path to one")}
            hint={
              t("A link is stored encrypted in the vault as CONTACTS_{name}.", {
                name:
                  name
                    .trim()
                    .toUpperCase()
                    .replace(/[^A-Z0-9]+/g, "_")
                    .replace(/^_+|_+$/g, "") || "NAME",
              }) +
              " " +
              t("nanoMuse fetches whatever address you put here, from this machine; only paste links you trust.")
            }
          >
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className={inputCls}
              placeholder="https://… /contacts.vcf"
              inputMode="url"
              autoComplete="off"
            />
          </Field>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy === "add" || !name.trim() || !url.trim()}
              onClick={() => void add()}
              className={primaryBtn}
            >
              {busy === "add" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Plug size={16} />
              )}{" "}
              {t("Connect")}
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className={secondaryBtn}
            >
              {t("Cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className={secondaryBtn}
        >
          <Plus size={16} /> {t("Add an address book")}
        </button>
      )}
      {c.configured && (
        <>
          <div className="relative">
            <Search
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className={cx(inputCls, "pl-9")}
              placeholder={t("Find someone, as the agent would")}
              autoComplete="off"
            />
          </div>
          {hits !== null && (
            <ul className="space-y-1">
              {hits.length === 0 && (
                <li className="text-[12.5px] text-muted px-1">
                  {t("No one matches.")}
                </li>
              )}
              {hits.map((p) => (
                <li
                  key={p.id}
                  className="rounded-2xl bg-surface-2/60 px-3 py-2"
                >
                  <div className="text-[13.5px] font-medium">
                    {p.name}
                    {p.org && (
                      <span className="text-muted font-normal"> · {p.org}</span>
                    )}
                  </div>
                  <div className="text-[12px] text-muted break-words">
                    {[...p.emails, ...p.phones].join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {c.sources.length > 0 && (
            <button
              type="button"
              disabled={busy === "test"}
              onClick={() => void runTest()}
              className={secondaryBtn}
            >
              {busy === "test" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <RefreshCw size={16} />
              )}{" "}
              {t("Read again")}
            </button>
          )}
          {test && (
            <TestLine result={test} okText={people(test.contacts ?? 0)} />
          )}
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ browser
function BrowserCard({
  data,
  onChange,
}: {
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast } = useStore();
  const t = useT();
  const b = data.browser;
  const [busy, setBusy] = useState(false);
  const flip = async () => {
    setBusy(true);
    try {
      await api.setBrowser(!b.enabled);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      icon={<Globe size={19} />}
      title={t("Browser")}
      summary={
        b.available
          ? t("Open pages, click, fill forms, screenshot")
          : t("Playwright is not installed on the server")
      }
      status={
        b.enabled && b.available
          ? { text: t("On"), tone: "ok" }
          : b.enabled
            ? { text: t("Unavailable"), tone: "warn" }
            : { text: t("Off"), tone: "off" }
      }
      open={false}
      trailing={
        <button
          type="button"
          role="switch"
          aria-checked={b.enabled}
          disabled={busy}
          onClick={() => void flip()}
          className={cx(
            "relative h-7 w-12 shrink-0 rounded-full transition",
            b.enabled ? "bg-accent" : "bg-surface-2 border border-border",
          )}
        >
          <span
            className={cx(
              "absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition",
              b.enabled ? "left-[22px]" : "left-0.5",
            )}
          />
        </button>
      }
    >
      {!b.available && (
        <p className="text-[12.5px] text-muted">
          {t("Install it where the server runs:")}{" "}
          <code className="rounded bg-surface-2 px-1">
            pip install &quot;nanomuse[browser]&quot; &amp;&amp; playwright
            install chromium
          </code>
        </p>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ phone (GUI)
function PhoneCard({
  data,
  onChange,
}: {
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast } = useStore();
  const t = useT();
  const g = data.gui;
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState(g.model);
  const [baseUrl, setBaseUrl] = useState(g.base_url);
  const [apiKey, setApiKey] = useState("");
  const [result, setResult] = useState<TestResult | null>(null);
  useEffect(() => {
    setModel(g.model);
    setBaseUrl(g.base_url);
  }, [g.model, g.base_url]);

  const flip = async () => {
    setBusy(true);
    try {
      await api.setGui({ enabled: !g.enabled });
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    setBusy(true);
    setResult(null);
    try {
      await api.setGui({
        model: model.trim(),
        base_url: baseUrl.trim(),
        ...(apiKey ? { api_key: apiKey.trim() } : {}),
      });
      setApiKey("");
      onChange();
      setResult(await api.testGui());
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const phone = g.phone;
  // the Android app: its own accessibility service does the operating — re-read when the
  // sheet is opened again or the app comes back from Settings
  const [a11y, setA11y] = useState(accessibilityState);
  const a11yRef = useRef(a11y);
  useEffect(() => {
    if (!open) return;
    const again = () => {
      const now = accessibilityState();
      if (now !== a11yRef.current) {
        a11yRef.current = now;
        setA11y(now);
        // switched on or off in Settings: the server knows already (the app announced it),
        // so the card's header should catch up too
        setTimeout(onChange, 400);
      }
    };
    again();
    document.addEventListener("visibilitychange", again);
    window.addEventListener("focus", again);
    return () => {
      document.removeEventListener("visibilitychange", again);
      window.removeEventListener("focus", again);
    };
  }, [open, onChange]);
  const summary = phone.connected
    ? t("{name} is connected", { name: phone.device?.name ?? t("A phone") })
    : g.enabled
      ? t("No phone connected. Open the app on the phone")
      : t("Tap, type and swipe in the apps on your phone");
  return (
    <Card
      icon={<Smartphone size={19} />}
      title={t("Phone")}
      summary={summary}
      status={
        g.enabled && phone.connected
          ? { text: t("On"), tone: "ok" }
          : g.enabled
            ? { text: t("Waiting"), tone: "warn" }
            : { text: t("Off"), tone: "off" }
      }
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-[13px] leading-snug">
          <div className="font-medium">{t("Operate the phone")}</div>
          <div className="text-[12px] text-muted">
            {t(
              "When on, the agent can read the screen and act in the apps on the connected phone: 12306, WeChat, Alipay… It asks before paying, sending or deleting.",
            )}
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={g.enabled}
          disabled={busy}
          onClick={() => void flip()}
          className={cx(
            "relative h-7 w-12 shrink-0 rounded-full transition",
            g.enabled ? "bg-accent" : "bg-surface-2 border border-border",
          )}
        >
          <span
            className={cx(
              "absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition",
              g.enabled ? "left-[22px]" : "left-0.5",
            )}
          />
        </button>
      </div>
      {a11y !== null && (
        <div className="rounded-2xl bg-surface-2 px-3 py-2.5 text-[12.5px] leading-snug space-y-1.5">
          <div className="flex items-center justify-between gap-3">
            <span className="font-medium">{t("This phone")}</span>
            <span
              className={cx(
                "rounded-full px-2 py-0.5 text-[11px] font-medium",
                a11y === "on" && "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
                a11y === "off" && "bg-amber-500/15 text-amber-700 dark:text-amber-300",
                a11y === "unsupported" && "bg-surface text-muted",
              )}
            >
              {a11y === "on" ? t("Ready") : a11y === "off" ? t("Not yet") : t("Not on this Android")}
            </span>
          </div>
          {a11y === "unsupported" && (
            <div className="text-muted">
              {t("Operating the screen needs Android 11 or newer; this phone can still be used for everything else.")}
            </div>
          )}
          {a11y === "off" && (
            <>
              <div className="text-muted">
                {t(
                  "Turn on the nanoMuse accessibility service; that is how it sees the screen and taps for you, only while a task runs, with a Stop button on screen.",
                )}
              </div>
              <div className="flex flex-wrap gap-2 pt-0.5">
                <button
                  type="button"
                  onClick={() => androidApp()?.openAccessibilitySettings?.()}
                  className="rounded-full bg-accent px-3 py-1.5 text-[12.5px] font-medium text-white"
                >
                  {t("Open Accessibility settings")}
                </button>
                <button
                  type="button"
                  onClick={() => androidApp()?.openAppSettings?.()}
                  className="rounded-full border border-border px-3 py-1.5 text-[12.5px]"
                >
                  {t("App settings")}
                </button>
              </div>
              <div className="text-muted">
                {t(
                  "Greyed out with “Restricted setting”? Android 13+ does that for apps installed from a download: in App settings tap ⋮ → Allow restricted settings, then come back.",
                )}
              </div>
            </>
          )}
          {a11y === "on" && (
            <div className="text-muted">
              {t("Android may switch the service off after an update or a battery clean-up; if the phone stops answering, come back here.")}
            </div>
          )}
        </div>
      )}
      {phone.connected && phone.device && (
        <div className="rounded-2xl bg-surface-2 px-3 py-2 text-[12.5px] text-muted">
          {t("{name} ({platform}), {n} apps", {
            name: phone.device.name,
            platform: phone.device.platform,
            n: String(phone.device.apps),
          })}
          {phone.last_screen && (
            <>
              {" "}
              ·{" "}
              {t("last seen in {app}", {
                app: phone.last_screen.app_name || phone.last_screen.app,
              })}
            </>
          )}
        </div>
      )}
      <div className="text-[12px] text-muted leading-snug">
        {t(
          "The operator's model looks at screens step by step: a small, fast model that takes pictures. The Hands model row under Chat model picks one on the same endpoint and key; the fields here are for a different endpoint. Empty = {model}.",
          { model: g.default_model || t("the chat model") },
        )}
      </div>
      <Field label={t("Model")}>
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={g.default_model || t("same as the chat model")}
          className={inputCls}
        />
      </Field>
      <Field label={t("Base URL")}>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={t("same as the chat model")}
          className={inputCls}
        />
      </Field>
      <Field
        label={t("API key")}
        hint={
          g.key_source === "vault"
            ? t("A key is in the vault; leave empty to keep it.")
            : g.key_source === "config"
              ? t("Set in config.toml.")
              : t("Leave empty to use the main model's key.")
        }
      >
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-…"
          className={inputCls}
          autoComplete="off"
        />
      </Field>
      <button
        type="button"
        disabled={busy}
        onClick={() => void save()}
        className={primaryBtn}
      >
        {busy ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Check size={16} />
        )}
        {t("Save and test")}
      </button>
      {result && (
        <TestLine result={result} okText={t("The operator's model answers.")} />
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ mcp
function MCPCard({
  data,
  onChange,
}: {
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast } = useStore();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");
  const [risk, setRisk] = useState("moderate");
  const [busy, setBusy] = useState<string | null>(null);

  const add = async () => {
    setBusy("add");
    try {
      const parts = command.trim().split(/\s+/).filter(Boolean);
      await api.addMCP({
        name: name.trim(),
        command: parts[0] ?? null,
        args: parts.slice(1),
        url: url.trim() || null,
        risk,
      });
      setName("");
      setCommand("");
      setUrl("");
      setAdding(false);
      toast(t("Server connected"));
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (n: string) => {
    setBusy(n);
    try {
      await api.removeMCP(n);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const connected = data.mcp.filter((m) => m.connected).length;
  // what the account's other devices connected and this one has not (contract C3): shown
  // with the server's own sign-in as the action — the key never travels
  const elsewhere = (data.shared ?? []).filter((c) => c.enabled && !c.here);
  const prefill = (c: SharedConnector) => {
    setName(c.id);
    setUrl(c.url);
    setCommand("");
    setAdding(true);
    setOpen(true);
  };
  return (
    <Card
      icon={<Plug size={19} />}
      title={t("MCP servers")}
      summary={
        data.mcp.length
          ? t("{n} of {total} connected · {tools} tools", {
              n: connected,
              total: data.mcp.length,
              tools: data.mcp.reduce((n, m) => n + m.tools, 0),
            })
          : t("Add tools from any Model Context Protocol server")
      }
      status={
        data.mcp.length
          ? {
              text: t("{n} on", { n: connected }),
              tone: connected ? "ok" : "warn",
            }
          : { text: t("None"), tone: "off" }
      }
      open={open}
      onToggle={() => setOpen(!open)}
    >
      {data.mcp.length > 0 && (
        <ul className="space-y-1.5">
          {data.mcp.map((m) => (
            <li
              key={m.name}
              className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2"
            >
              <span
                className={cx(
                  "h-2 w-2 rounded-full",
                  m.connected ? "bg-emerald-500" : "bg-rose-500",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">
                  {m.builtin ? t("This phone") : m.name}
                </div>
                <div className="text-[11.5px] text-muted truncate">
                  {m.builtin ? t("clipboard, notifications, calendar, contacts, location, alarms, photos") : (m.url ?? [m.command, ...m.args].join(" "))} ·{" "}
                  {t("{n} tools", { n: m.tools })} · {t(m.risk)}
                  {!m.from_app && !m.builtin && ` · ${t("from config.toml")}`}
                </div>
              </div>
              {m.from_app && (
                <button
                  type="button"
                  aria-label={t("Remove")}
                  disabled={busy === m.name}
                  onClick={() => void remove(m.name)}
                  className="p-1.5 rounded-full text-muted hover:bg-surface-2"
                >
                  {busy === m.name ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Trash2 size={15} />
                  )}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {elsewhere.length > 0 && (
        <ul className="space-y-1.5">
          {elsewhere.map((c) => (
            <li
              key={`${c.device_id}:${c.id}`}
              className="flex items-center gap-2.5 rounded-2xl border border-dashed border-border/70 px-3 py-2"
            >
              <span className="h-2 w-2 rounded-full bg-border" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">{c.label || c.id}</div>
                <div className="text-[11.5px] text-muted truncate">
                  {t("Connected on {device}; sign in here to use it on this device", { device: c.device || c.device_id })}
                  {c.url ? ` · ${c.url}` : ""}
                </div>
              </div>
              {c.url && (
                <button type="button" onClick={() => prefill(c)} className={cx(secondaryBtn, "py-1.5 text-[12.5px]")}>
                  {t("Sign in here")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <div className="space-y-2.5 rounded-2xl border border-border/70 p-3">
          <Field label={t("Name")}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputCls}
              placeholder="filesystem"
            />
          </Field>
          <Field
            label={t("Command")}
            hint={t(
              "Run locally over stdio, for example: npx -y @modelcontextprotocol/server-filesystem ./workspace",
            )}
          >
            <input
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              className={inputCls}
              placeholder="npx -y @modelcontextprotocol/server-…"
            />
          </Field>
          <Field
            label={t("or URL")}
            hint={t("A remote server over Streamable HTTP.")}
          >
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className={inputCls}
              placeholder="https://host/mcp"
              inputMode="url"
            />
          </Field>
          <Field
            label={t("Risk of its tools")}
            hint={t("Decides when the Sentinel asks you before a call.")}
          >
            <div className="flex gap-1.5">
              {["safe", "moderate", "high"].map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRisk(r)}
                  className={cx(
                    "rounded-full px-3 py-1.5 text-[13px] border",
                    risk === r
                      ? "border-accent bg-accent/10 text-accent font-medium"
                      : "border-border text-muted",
                  )}
                >
                  {t(r)}
                </button>
              ))}
            </div>
          </Field>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={
                busy === "add" ||
                !name.trim() ||
                !(command.trim() || url.trim())
              }
              onClick={() => void add()}
              className={primaryBtn}
            >
              {busy === "add" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Plug size={16} />
              )}{" "}
              {t("Connect")}
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className={secondaryBtn}
            >
              {t("Cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className={secondaryBtn}
        >
          <Plus size={16} /> {t("Add a server")}
        </button>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ vault
function VaultCard({
  data,
  onChange,
}: {
  data: ConnectionsData;
  onChange: () => void;
}) {
  const { toast } = useStore();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const add = async () => {
    setBusy("add");
    try {
      await api.vaultSet(name.trim(), value);
      setName("");
      setValue("");
      toast(t("Stored in the vault"));
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const remove = async (n: string) => {
    setBusy(n);
    try {
      await api.vaultDelete(n);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      icon={<KeyRound size={19} />}
      title={t("Vault")}
      summary={
        data.vault.length
          ? t("{n} secrets · encrypted on your machine", {
              n: data.vault.length,
            })
          : t("Encrypted secrets the model never sees")
      }
      status={{ text: `${data.vault.length}`, tone: "off" }}
      open={open}
      onToggle={() => setOpen(!open)}
    >
      <p className="text-[12.5px] text-muted -mt-1">
        {t("Refer to a secret as")}{" "}
        <code className="rounded bg-surface-2 px-1">{"{{vault:NAME}}"}</code>{" "}
        {t(
          "in a tool call or config: the value is filled in after the Sentinel approves and is redacted from everything the model reads.",
        )}
      </p>
      {data.vault.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {data.vault.map((n) => (
            <li
              key={n}
              className="flex items-center gap-1 rounded-full bg-surface-2 pl-3 pr-1 py-1 text-[12.5px] font-mono"
            >
              {n}
              <button
                type="button"
                aria-label={t("Delete {name}", { name: n })}
                disabled={busy === n}
                onClick={() => void remove(n)}
                className="p-1 rounded-full text-muted hover:text-rose-500"
              >
                {busy === n ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Trash2 size={13} />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-[1fr_1fr_auto] gap-2 items-end">
        <Field label={t("Name")}>
          <input
            value={name}
            onChange={(e) =>
              setName(
                e.target.value.toUpperCase().replace(/[^A-Z0-9_.-]/g, "_"),
              )
            }
            className={cx(inputCls, "font-mono")}
            placeholder="GITHUB_TOKEN"
          />
        </Field>
        <Field label={t("Value")}>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={inputCls}
            placeholder={t("secret")}
            autoComplete="off"
          />
        </Field>
        <button
          type="button"
          disabled={busy === "add" || !name || !value}
          onClick={() => void add()}
          className={cx(primaryBtn, "px-3")}
          aria-label={t("Store")}
        >
          {busy === "add" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Plus size={16} />
          )}
        </button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ bits
/** one of the studio's two model pickers: the endpoint's candidates when it lists any, a
 *  free field otherwise; the empty choice leaves the pick to the runtime */
const OTHER_MODEL = "\u0000other";

/**
 * A model from the list, or one typed by its id when `other` (the list's last entry opens
 * the field). The list is the picker of the Models contract (`ModelPicker`): one group
 * named after the provider with its catalogue default first, or on nanoMuse Cloud the menu
 * and the account's other models as two groups; each folds past eight rows, and a search
 * field appears once the rows pass eight in all.
 */
function StudioModelPick({
  label,
  provider,
  value,
  options,
  more = [],
  onChange,
  other = true,
  placeholder,
}: {
  label: string;
  /** the provider's name, for the group's title and the button's `<provider> · <model>` */
  provider: string;
  value: string;
  options: string[];
  /** a second group — on nanoMuse Cloud, the other models under the Cloud key a member may use */
  more?: string[];
  onChange: (v: string) => void;
  other?: boolean;
  /** what "Automatic" means for this provider: the catalogue's default model */
  placeholder?: string;
}) {
  const t = useT();
  const listed = options.includes(value) || more.includes(value);
  const [typing, setTyping] = useState(false);
  const automatic = placeholder ? t("Automatic · {model}", { model: placeholder }) : t("Automatic");
  const asRows = (ids: string[]) => ids.map((id) => ({ id, name: id }));
  const groups: ModelGroup[] = more.length
    ? [
        { key: "menu", label: t("Menu"), rows: asRows(options), ...(placeholder ? { default: placeholder } : {}) },
        { key: "more", label: t("More models on your account"), rows: asRows(more) },
      ]
    : [{ key: "list", label: provider, rows: asRows(options), ...(placeholder ? { default: placeholder } : {}) }];
  const current = value && listed ? { group: options.includes(value) ? groups[0].key : "more", id: value } : undefined;
  return (
    <div className="block text-[12.5px] text-muted">
      <span className="block mb-1">{label}</span>
      {(options.length || more.length) && (listed || !value) && !typing ? (
        <ModelPicker
          label={label}
          text={value ? `${provider} · ${value}` : automatic}
          heads={[{ value: "", label: automatic }]}
          headValue={value ? undefined : ""}
          groups={groups}
          current={current}
          onHead={() => onChange("")}
          onPick={(_group, row) => onChange(row.id)}
          tail={other ? t("Other model…") : undefined}
          onTail={() => {
            setTyping(true);
            onChange("");
          }}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={automatic}
          aria-label={label}
          className={cx(inputCls, "text-fg")}
          spellCheck={false}
        />
      )}
    </div>
  );
}

/** The "(how)" at the end of an unavailable line: the guide to one's own key. */
function OwnKeyHow() {
  const t = useT();
  return (
    <a href={OWN_KEY_DOCS} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-accent">
      {t("How")} <ExternalLink size={11} />
    </a>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="text-[12px] text-muted">{label}</label>
      <div className="mt-1">{children}</div>
      {hint && (
        <div className="mt-1 text-[11.5px] text-muted leading-snug">{hint}</div>
      )}
    </div>
  );
}

/** The outcome of a connection test: the sentence in the person's language; a failed model
 * test keeps the provider's own words one tap away. */
function TestLine({ result, okText }: { result: TestResult; okText: string }) {
  const t = useT();
  const [showDetail, setShowDetail] = useState(false);
  const detail = !result.ok && result.detail && result.detail !== result.error ? result.detail : null;
  return (
    <div
      className={cx(
        "rounded-2xl px-3 py-2 text-[12.5px]",
        result.ok
          ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
          : "bg-rose-500/12 text-rose-700 dark:text-rose-300",
      )}
    >
      {result.ok ? okText : t(result.error ?? "The model provider did not answer.")}
      {detail && (
        <>
          {" "}
          <button type="button" onClick={() => setShowDetail((v) => !v)} className="underline decoration-dotted underline-offset-2 opacity-70 hover:opacity-100">
            {showDetail ? t("Hide details") : t("Details")}
          </button>
          {showDetail && <div className="mt-1.5 break-all font-mono text-[11px] opacity-80">{detail}</div>}
        </>
      )}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export { inputCls, primaryBtn, secondaryBtn };
