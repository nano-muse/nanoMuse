import { Check, Loader2, MoreHorizontal, RefreshCw, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, fileUrl } from "../api";
import { DRAGON, dragonClipUrl, dragonUrl, isDragon, studioClipUrl, studioUrl } from "../avatars";
import { AVATAR_STYLES } from "../components/AvatarPicker";
import { PageBar } from "../components/BackBar";
import { MuseRoundButton } from "../components/MuseHeader";
import { primaryBtn, secondaryBtn } from "../components/Form";
import { StarNudgeOnce } from "../components/StarNudge";
import { useMenuKeys } from "../components/useMenuKeys";
import { getLocale, useT } from "../i18n";
import { regionOf, unavailableLine } from "../providers";
import { useStore } from "../store";
import type { StudioSession, StudioView } from "../types";
import { cx } from "../util";

const MOODS = ["idle", "working", "waiting", "happy", "error"] as const;
type Mood = (typeof MOODS)[number];
const MOOD_LABEL: Record<Mood, string> = { idle: "Idle", working: "Working", waiting: "Waiting for you", happy: "Done", error: "Something went wrong" };
const CLIP_MOODS = 4;
/** the dragon's own description, as the placeholder — the phone's too */
const DEFAULT_DESCRIPTION = "a round, custard-yellow baby dragon with small orange horns and folded little wings";
const PRESETS = [
  { id: "moss-courier", name: "Moss Courier", description: "a tiny moss-covered courier with leaf ears and an unmarked canvas satchel", style: "muse" },
  { id: "tide-tinker", name: "Tide Tinker", description: "a seafoam axolotl tinkerer with coral frills and a plain tool pouch", style: "clay" },
  { id: "dusk-moth", name: "Dusk Moth", description: "a thoughtful indigo moth with peach wing spots, a cream collar and round glasses", style: "watercolor" },
  { id: "copper-acorn", name: "Copper Acorn", description: "a small acorn-shaped copper automaton with sage panels and a muted-blue scarf", style: "line" },
] as const;

/**
 * The avatar studio, the phone's screen (`AvatarStudioScreen.kt`) for the web and the desktop:
 * the face as it is, cycling through its moods; a description and a style, four drawn to
 * choose from, *Use this one*, the poses drawn in the background; and the menu — name and
 * style, the image model, the poses drawn again, back to the built-in look. The runtime runs
 * the session (`/api/avatar/*`) and reports it over the socket (`studio`); the same session
 * also starts from a sentence in the chat, where a card follows it instead.
 */
export function AvatarStudioScreen() {
  const { state, setTab, toast, draft, refreshSettings } = useStore();
  const t = useT();
  const profile = state.profile;
  const name = profile?.name ?? "nanoMuse";
  const [view, setView] = useState<StudioView | null>(null);
  const [description, setDescription] = useState("");
  const [style, setStyle] = useState("muse");
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useMenuKeys(menuRef, menu, () => setMenu(false));
  const [error, setError] = useState("");

  // the session: the socket's word, else what the first fetch found under way
  const session: StudioSession | null = state.studio ?? view?.current ?? null;
  const stage = session?.stage ?? "";
  const drawing = stage === "drawing";
  const candidates = session?.candidates ?? [];
  const haveCandidates = (stage === "drawing" || stage === "choose") && candidates.length > 0;

  // the model and the connections can both change while a view is on its way: a slower
  // earlier answer must not land over a newer one's view
  const loadGen = useRef(0);
  const active = useRef(false);
  const load = () => {
    if (!active.current) return Promise.resolve();
    const mine = ++loadGen.current;
    return api.avatarView().then(
      (d) => {
        if (loadGen.current !== mine) return;
        setView(d);
      },
      (e: Error) => {
        if (loadGen.current !== mine) return;
        toast(e.message);
      },
    );
  };
  useEffect(() => {
    active.current = true;
    void load();
    return () => {
      active.current = false;
      loadGen.current += 1;
    };
    // the face's record (face.json) and the endpoint are re-read when the look changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.avatar, state.settings?.llm.model, state.connectionsVersion]);
  useEffect(() => {
    setSelected(null);
  }, [stage, session?.session]);

  const act = async (what: string, run: () => Promise<unknown>) => {
    setBusy(what);
    setError("");
    try {
      await run();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const draw = () =>
    act("draw", async () => {
      const desc = description.trim() || DEFAULT_DESCRIPTION;
      const begun = await api.avatarBegin(desc, "", style);
      // no provider with image models: the one sentence (contract C11), never the runtime's raw reason
      if (begun.available === false) throw new Error(unavailableLine(t, "image", regionOf(state.hub?.account), getLocale()));
      // the account's model is priced and confirmed first; a key of one's own is not asked
      if (begun.cost?.cloud === false && begun.session) await api.avatarStart(begun.session);
    });

  const reset = () =>
    act("reset", async () => {
      await api.updateSettings({ profile: { avatar: DRAGON } });
      await refreshSettings();
      toast(t("Back to the built-in look."));
    });

  const drawn = view?.face ?? null;
  const wearsDrawn = !!profile?.avatar && !isDragon(profile.avatar);
  const posing = session && (stage === "posing" || stage === "animating" || stage === "done") && session.face === profile?.avatar;
  const moodsDone = posing ? Object.keys(session.moods ?? {}).length : 0;
  const clipsDone = posing ? Object.keys(session.clips ?? {}).length : 0;
  const poseErrors = posing ? (session.errors ?? []).filter((e) => !/clip/.test(e)).length : 0;

  const cost = session?.cost ?? {};
  const what = cost.clips ? t("{n} pictures and {c} clips", { n: cost.pictures ?? 8, c: cost.clips }) : t("{n} pictures", { n: cost.pictures ?? 8 });
  const costLine = (() => {
    if (cost.error) return t("The cost could not be checked: {error}", { error: cost.error });
    if (typeof cost.cny !== "number") return t("Checking the cost…");
    if (cost.unlimited) return t("About ¥{cny} for {what}; your account has no limit.", { cny: cost.cny.toFixed(2), what });
    const left = typeof cost.left_cny === "number" ? cost.left_cny.toFixed(2) : "?";
    return cost.affordable === false
      ? t("About ¥{cny} for {what}, more than the ¥{left} left in your allowance.", { cny: cost.cny.toFixed(2), what, left })
      : t("About ¥{cny} for {what}; ¥{left} left in your allowance.", { cny: cost.cny.toFixed(2), what, left });
  })();

  const styleLabel = (id: string | null | undefined) => AVATAR_STYLES.find((s) => s.id === id)?.label;
  const provider = view?.cloud ? "nanoMuse Cloud" : providerName(view?.host ?? "", t);

  return (
    <div className="flex h-full flex-col">
      <PageBar
        title={t("Avatar studio")}
        description={t("Draw a look with your image model; it moves with what it is doing.")}
        actions={
          <div ref={menuRef} className="relative">
            <MuseRoundButton small onClick={() => setMenu((v) => !v)} label={t("More")} expanded={menu}>
              <MoreHorizontal size={20} />
            </MuseRoundButton>
            {menu && (
              <div role="menu" className="absolute right-0 z-20 mt-1 w-56 overflow-hidden rounded-2xl border border-border/70 bg-surface py-1 text-[14px] shadow-lg">
                <MenuItem
                  label={t("Name & style")}
                  onClick={() => {
                    setMenu(false);
                    setTab("you");
                  }}
                />
                <MenuItem
                  label={t("Image model")}
                  onClick={() => {
                    setMenu(false);
                    setTab("connections");
                  }}
                />
                {wearsDrawn && (
                  <>
                    <MenuItem
                      label={t("Redraw the poses")}
                      onClick={() => {
                        setMenu(false);
                        void act("moods", () => api.avatarMoods());
                      }}
                    />
                    <MenuItem
                      label={t("Back to the built-in look")}
                      danger
                      onClick={() => {
                        setMenu(false);
                        void reset();
                      }}
                    />
                  </>
                )}
              </div>
            )}
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-5">
        {/* the face as it is */}
        <div className="flex flex-col items-center pt-2 text-center">
          <FacePreview avatar={profile?.avatar} emoji={profile?.emoji} color={profile?.color} name={name} />
          {drawn && (
            <div className="mt-0.5 max-w-sm text-[12.5px] text-muted">
              {[drawn.description, styleLabel(drawn.style) && t(styleLabel(drawn.style) as string)].filter(Boolean).join(" · ")}
            </div>
          )}
          {posing && (
            <div className="mt-2.5 flex items-center gap-2 text-[13px] text-muted">
              {stage === "posing" && (
                <>
                  <Loader2 size={14} className="animate-spin text-accent" />
                  <span>{t("Drawing the poses… {done}/{total}", { done: moodsDone, total: MOODS.length })}</span>
                </>
              )}
              {stage === "animating" && (
                <>
                  <Loader2 size={14} className="animate-spin text-accent" />
                  <span>{t("The new look is on; making the clips… {done}/{total}", { done: clipsDone, total: CLIP_MOODS })}</span>
                </>
              )}
              {stage === "done" && (
                <>
                  <span>
                    {poseErrors === 0
                      ? t("All five poses are in.")
                      : t("{done} of {total} poses are in; the rest show the main picture.", { done: MOODS.length - poseErrors, total: MOODS.length })}
                  </span>
                  {poseErrors > 0 && (
                    <button type="button" onClick={() => void act("moods", () => api.avatarMoods())} className="font-medium text-accent">
                      {t("Retry")}
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* the face is done: a moment of delight, and the one fair ask for a star here (once) */}
        {stage === "done" && poseErrors === 0 && <StarNudgeOnce moment="new_look" />}

        {/* describe a new one */}
        <section className="rounded-3xl border border-border/70 bg-surface p-4 shadow-sm space-y-3">
          <div>
            <h2 className="text-[17px] font-semibold">{t("Describe a new look")}</h2>
            <p className="mt-0.5 text-[13px] leading-snug text-muted">
              {t("One sentence is enough: what it is, what it wears, its air. Pick a style and your image model draws four to choose from.")}
            </p>
          </div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted">{t("AI-generated inspiration")}</p>
          <div className="grid grid-cols-4 gap-2">
            {PRESETS.map((preset, index) => (
              <button
                key={preset.id}
                type="button"
                aria-label={`${t("Candidate {n}", { n: index + 1 })}: ${t(preset.name)}, ${t(styleLabel(preset.style) ?? preset.style)}`}
                onClick={() => {
                  setDescription(t(preset.description));
                  setStyle(preset.style);
                }}
                className={cx(
                  "overflow-hidden rounded-2xl bg-[#f1efeb] text-left transition hover:ring-2 hover:ring-accent/60",
                  description === t(preset.description) ? "ring-[3px] ring-accent" : "",
                )}
              >
                <img
                  src={`/avatar-presets/${preset.id}-idle.webp`}
                  alt=""
                  className="aspect-square w-full object-cover"
                />
                <span className="block truncate px-2 pt-1.5 text-[11px] font-medium text-fg">{t(preset.name)}</span>
                <span className="block truncate px-2 pb-1.5 text-[10px] text-muted">{t(styleLabel(preset.style) ?? preset.style)}</span>
              </button>
            ))}
          </div>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            maxLength={200}
            placeholder={t(DEFAULT_DESCRIPTION)}
            aria-label={t("Describe a new look")}
            className="w-full resize-none rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14.5px] outline-none focus:ring-2 focus:ring-accent/40"
          />
          <div className="flex flex-wrap gap-1.5">
            {AVATAR_STYLES.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setStyle(s.id)}
                className={cx("rounded-full px-3 py-1.5 text-[13px] font-medium transition", style === s.id ? "bg-fg text-bg" : "bg-surface-2 text-fg hover:bg-border/60")}
              >
                {t(s.label)}
              </button>
            ))}
          </div>
          <button type="button" disabled={busy !== null || drawing || view?.available === false} onClick={() => void draw()} className={cx(primaryBtn, "w-full rounded-full py-3")}>
            {drawing || busy === "draw" ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {drawing ? t("Drawing…") : haveCandidates || stage === "choose" ? t("Draw four more") : t("Draw four")}
          </button>
          <button type="button" onClick={() => setTab("connections")} className="flex w-full items-center justify-between gap-3 py-1 text-left text-[12.5px] text-muted">
            <span className="min-w-0 flex-1">
              {view === null
                ? "…"
                : view.available
                  ? t("Drawn by {provider} · {model}", { provider, model: view.image_model || t("default model") })
                  : unavailableLine(t, "image", regionOf(state.hub?.account), getLocale())}
            </span>
            <span className="shrink-0 font-medium text-accent">{t("Change model")}</span>
          </button>
          {error && <p className="text-[13px] text-rose-600 dark:text-rose-300">{error}</p>}
        </section>

        {/* the account's model: the cost first */}
        {stage === "estimate" && session && (
          <section className="rounded-3xl border border-accent/50 bg-surface p-4 shadow-sm space-y-3">
            <div>
              <h2 className="text-[15px] font-semibold">{t("A new look for {name}", { name })}</h2>
              <p className="mt-0.5 text-[13px] text-muted">{session.description}</p>
            </div>
            <p className="text-[12.5px] text-muted">{costLine}</p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy !== null || (typeof cost.cny !== "number" && !cost.error)}
                onClick={() => void act("start", () => api.avatarStart(session.session))}
                className={cx(primaryBtn, "rounded-full")}
              >
                {busy === "start" ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} {t("Draw")}
              </button>
              <button type="button" disabled={busy !== null} onClick={() => void act("cancel", () => api.avatarCancel(session.session))} className={cx(secondaryBtn, "rounded-full")}>
                <X size={14} /> {t("Not now")}
              </button>
            </div>
          </section>
        )}

        {/* four to choose from */}
        {haveCandidates && session && (
          <section className="space-y-3 px-1">
            <div>
              <h2 className="text-[17px] font-semibold">{t("Pick one")}</h2>
              <p className="mt-0.5 text-[13px] leading-snug text-muted">{t("Draw four more any time; the old ones stay until you do.")}</p>
            </div>
            <div className="grid grid-cols-2 gap-3 wide:grid-cols-4">
              {candidates.map((c, i) => (
                <button
                  key={i}
                  type="button"
                  disabled={!c || stage !== "choose"}
                  onClick={() => setSelected((cur) => (cur === i ? null : i))}
                  aria-label={t("Candidate {n}", { n: i + 1 })}
                  aria-pressed={selected === i}
                  className={cx(
                    "relative aspect-square overflow-hidden rounded-[20px] bg-[#f1efeb] transition",
                    selected === i ? "ring-[3px] ring-accent" : c && stage === "choose" ? "hover:ring-2 hover:ring-accent/60" : "",
                  )}
                >
                  {c ? (
                    <img src={fileUrl(c)} alt="" draggable={false} className="h-full w-full object-cover" />
                  ) : (
                    <span className="absolute inset-0 flex items-center justify-center text-muted">
                      {drawing ? <Loader2 size={22} className="animate-spin" /> : <X size={18} className="opacity-50" />}
                    </span>
                  )}
                  {selected === i && (
                    <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-accent text-accent-fg shadow">
                      <Check size={16} />
                    </span>
                  )}
                </button>
              ))}
            </div>
            {session.errors && session.errors.length > 0 && stage === "choose" && <p className="text-[12.5px] text-rose-600 dark:text-rose-300">{t(session.errors[0])}</p>}
            {selected !== null && stage === "choose" && (
              <div className="space-y-1.5 pt-1">
                <button type="button" disabled={busy !== null} onClick={() => void act("choose", () => api.avatarChoose(session.session, selected))} className={cx(primaryBtn, "w-full rounded-full py-3")}>
                  {busy === "choose" ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} {t("Use this one")}
                </button>
                <p className="text-center text-[12px] leading-snug text-muted">{t("Next, its poses are drawn from it in the background: working, waiting for you, done, something wrong.")}</p>
              </div>
            )}
            {stage === "choose" && (
              <button type="button" disabled={busy !== null} onClick={() => void act("cancel", () => api.avatarCancel(session.session))} className="w-full py-1 text-center text-[13px] text-muted">
                {t("Keep the current look")}
              </button>
            )}
          </section>
        )}

        {stage === "failed" && session && (
          <section className="rounded-3xl border border-border/70 bg-surface p-4 shadow-sm space-y-2">
            <h2 className="text-[15px] font-semibold">{t("That did not work")}</h2>
            <p className="text-[13px] text-muted">{t(session.message || "Nothing came back.")}</p>
            <button type="button" disabled={busy !== null} onClick={() => void act("retry", () => api.avatarStart(session.session))} className={cx(secondaryBtn, "rounded-full")}>
              <RefreshCw size={14} /> {t("Try again")}
            </button>
          </section>
        )}

        <p className="px-1 text-[12px] leading-snug text-muted">
          {t("The pictures stay in this computer's workspace under avatar/. Each new look asks your provider for eight pictures (four to choose from and four poses) and four short clips where there is a video model.")}
        </p>
        <p className="px-1 text-[12px] leading-snug text-muted">
          <button
            type="button"
            onClick={() => {
              draft(t("Change your avatar to "));
              setTab("chat");
            }}
            className="font-medium text-accent"
          >
            {t("Or just say it in the chat: “change your avatar to a corgi”.")}
          </button>
        </p>
      </div>
    </div>
  );
}

/** The provider behind a host, by the name people know it by; the host itself otherwise. */
function providerName(host: string, t: (s: string) => string): string {
  if (!host) return t("your provider");
  if (/dashscope|aliyuncs/.test(host)) return t("Alibaba Cloud Bailian");
  if (/openai\.com/.test(host)) return "OpenAI";
  if (/deepseek/.test(host)) return "DeepSeek";
  if (/moonshot/.test(host)) return "Moonshot";
  if (/bigmodel|zhipu/.test(host)) return t("Zhipu");
  if (/siliconflow/.test(host)) return "SiliconFlow";
  if (/volces|ark/.test(host)) return t("Volcano Ark");
  if (/openrouter/.test(host)) return "OpenRouter";
  if (/googleapis/.test(host)) return "Gemini";
  if (/x\.ai/.test(host)) return "xAI";
  if (/^(127\.0\.0\.1|localhost)/.test(host)) return t("this computer");
  return host;
}

function MenuItem({ label, onClick, danger = false }: { label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" role="menuitem" onClick={onClick} className={cx("block w-full px-4 py-2.5 text-left hover:bg-surface-2", danger ? "text-rose-600 dark:text-rose-300" : "")}>
      {label}
    </button>
  );
}

/**
 * The face, large, cycling through its moods so you see what you have — idle a little
 * longer, the others two seconds each; a clip where the face has one, the still otherwise.
 */
function FacePreview({ avatar, emoji, color, name }: { avatar?: string; emoji?: string; color?: string; name: string }) {
  const t = useT();
  const [index, setIndex] = useState(0);
  const mood = MOODS[index % MOODS.length];
  const timer = useRef<number>(0);
  useEffect(() => {
    timer.current = window.setTimeout(() => setIndex((i) => (i + 1) % MOODS.length), mood === "idle" ? 2600 : 2000);
    return () => window.clearTimeout(timer.current);
  }, [index, mood]);
  const dragon = isDragon(avatar);
  const studio = !dragon && avatar ? avatar : null;
  const still = dragon ? dragonUrl(mood) : studio ? studioUrl(studio, mood) : "";
  const clip = dragon ? dragonClipUrl(mood) : studio ? studioClipUrl(studio, mood) : null;
  const [broken, setBroken] = useState<Set<string>>(() => new Set());
  const playable = clip && !broken.has(clip) ? clip : null;
  return (
    <>
      <div
        key={avatar}
        className="avatar-pop h-[148px] w-[148px] overflow-hidden rounded-full"
        style={still ? { background: "#f1efeb" } : { background: `linear-gradient(135deg, ${color ?? "#0064d4"}, color-mix(in srgb, ${color ?? "#0064d4"} 60%, #ffffff))` }}
      >
        {playable ? (
          <video
            key={playable}
            src={playable}
            poster={still}
            autoPlay
            loop
            muted
            playsInline
            disablePictureInPicture
            onError={() => setBroken((s) => new Set(s).add(playable))}
            className="h-full w-full object-cover"
          />
        ) : still ? (
          <img src={still} alt="" draggable={false} className="h-full w-full object-cover" />
        ) : (
          <span className="flex h-full w-full items-center justify-center text-[64px] leading-none">{emoji ?? "✨"}</span>
        )}
      </div>
      <div className="mt-3 text-[20px] font-semibold tracking-tight">{name}</div>
      <div className="mt-1 text-[13px] text-muted">{t(MOOD_LABEL[mood])}</div>
    </>
  );
}
