package io.github.nanomuse.hands

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings
import com.openminis.app.MinisApp
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.hasImageInput
import com.openminis.app.data.repository.ProviderRepository
import io.github.nanomuse.cloud.NanoMuseCloud
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The screen as a hand (0.1.12). Off by default; when the user switches it on and the three
 * prerequisites hold, the agent gets `nanomuse-hands` — a screenshot-driven operator that taps,
 * types and swipes in the apps that have no API — as the last rung of the ladder.
 *
 * The eyes are the screenshot alone: no accessibility tree is read for perception. The
 * accessibility service is the hand (gestures, the screenshot itself, the focused field to
 * type into) and nothing more.
 */
object Hands {
    private const val PREFS = "nanomuse"
    private const val KEY_ENABLED = "hands.enabled"
    private const val KEY_MODEL = "hands.model_entry"
    const val DEEP_LINK = "minis://settings/hands"
    const val MIN_SDK = Build.VERSION_CODES.R

    private fun prefs(context: Context): SharedPreferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun enabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)
    fun setEnabled(context: Context, on: Boolean) { prefs(context).edit().putBoolean(KEY_ENABLED, on).apply() }

    /** The switch as a flow: the current value, then every change, wherever it is made. */
    fun enabledFlow(context: Context): Flow<Boolean> = callbackFlow {
        val p = prefs(context.applicationContext)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == KEY_ENABLED) trySend(p.getBoolean(KEY_ENABLED, false))
        }
        p.registerOnSharedPreferenceChangeListener(listener)
        trySend(p.getBoolean(KEY_ENABLED, false))
        awaitClose { p.unregisterOnSharedPreferenceChangeListener(listener) }
    }

    /** The chosen screen model's entry id; null means "pick one" ([screenModel]). */
    fun modelEntryId(context: Context): String? = prefs(context).getString(KEY_MODEL, null)?.takeIf { it.isNotBlank() }
    /** Null forgets the choice: the screen's model follows the automatic order again. */
    fun setModelEntryId(context: Context, id: String?) {
        prefs(context).edit().apply { if (id == null) remove(KEY_MODEL) else putString(KEY_MODEL, id) }.apply()
    }

    // ── readiness ──────────────────────────────────────────────────────────

    data class Readiness(
        val androidOk: Boolean,
        val serviceOn: Boolean,
        val overlayOk: Boolean,
        val model: ScreenModel?,
    ) {
        val ready: Boolean get() = androidOk && serviceOn && overlayOk && model != null
    }

    fun readiness(context: Context): Readiness = Readiness(
        androidOk = Build.VERSION.SDK_INT >= MIN_SDK,
        serviceOn = MinisAccessibilityService.getInstance() != null,
        overlayOk = Settings.canDrawOverlays(context),
        model = screenModel(context),
    )

    /** Usable right now: switched on and every prerequisite in place. */
    fun usable(context: Context): Boolean = enabled(context) && readiness(context).ready

    // ── the screen model ───────────────────────────────────────────────────

    /** How the screen model was arrived at, for the settings page to say. */
    enum class Why { CHOSEN, CHAT_PROVIDER, MENU, DEFAULT, CHAT, GROUP, VISION_GROUP, ANY }

    /**
     * The own-key fallback for the hands (contract C4): `qwen3.8-27b` on 阿里云百炼,
     * `qwen/qwen3.8-27b` on OpenRouter. Cloud names and recommends its screen model in the
     * menu instead. The chat model is a separate setting.
     */
    val DEFAULT_MODEL_IDS = listOf("qwen3.8-27b", "qwen/qwen3.8-27b")

    /** A model that sees pictures, with the key to call it. */
    data class ScreenModel(val instance: ProviderInstance, val entry: ModelEntry, val apiKey: String, val why: Why = Why.ANY) {
        val label: String get() = entry.model.displayName.ifBlank { entry.model.id } + " · " + instance.label.ifBlank { instance.providerType.name }
        val modelId: String get() = entry.model.id
    }

    /**
     * Every enabled model that declares image input, for the picker — of providers whose
     * vendor has vision models (contract C11, [io.github.nanomuse.cloud.Capabilities]; a
     * provider the catalogue does not know is taken at its models' word).
     */
    fun visionEntries(context: Context): List<Pair<ProviderInstance, ModelEntry>> {
        val repo = repo(context) ?: return emptyList()
        val cfg = repo.config.value
        return cfg.modelEntries.filter { !it.isHidden && it.model.hasImageInput }.mapNotNull { e ->
            cfg.instances.firstOrNull { it.id == e.providerInstanceId && it.isEnabled && sees(context, it) }?.let { it to e }
        }
    }

    /** The vendor of [inst] has models that see (C11); true for an endpoint the catalogue does not know. */
    fun sees(context: Context, inst: ProviderInstance): Boolean =
        io.github.nanomuse.cloud.Capabilities.allows(context, inst, io.github.nanomuse.cloud.ProviderCatalogue.VISION)

    /** No configured provider has a model that sees the screen: the one sentence that says so (C11), or null when one has. */
    fun unavailableLine(context: Context): String? =
        if (visionEntries(context).isEmpty()) io.github.nanomuse.cloud.Capabilities.unavailableLine(context, io.github.nanomuse.cloud.ProviderCatalogue.VISION) else null

    /**
     * The model that looks at the screen — the *hands model*, a setting of its own beside the
     * chat model (contract C4) — in the order of the Models page (0.1.41, [io.github.nanomuse.models.SlotOrder]):
     * the one chosen in Settings → Models (or → Hands); the chat provider's own model for the
     * screen (the catalogue's `defaults.hands`, else its first model that sees) when the chat
     * provider is the person's own and sees — the relay never jumps ahead of a provider the
     * person chose; nanoMuse Cloud's model for the screen (what the relay recommends
     * `for: gui`), when signed in; the own-key default (`qwen3.8-27b`
     * on 百炼, `qwen/qwen3.8-27b` on OpenRouter); then, for a set-up with none of those, the
     * chat model the person last picked when it sees, the first sighted member of the default
     * group, the Vision Group, and last any enabled vision model, preferring names that say so
     * (`vl`, `vision`) — but never one of the Cloud's catalog models the person did not pick,
     * so a member is not quietly billed for `qwen-vl-max` because its name has `vl` in it.
     * Null when none of the user's models sees. [automatic] leaves the choice aside and answers
     * what the rest of the order gives now, for the picker's *Automatic* row.
     */
    fun screenModel(context: Context, automatic: Boolean = false): ScreenModel? {
        val repo = repo(context) ?: return null
        val cfg = repo.config.value
        fun usable(inst: ProviderInstance?, entry: ModelEntry?, why: Why): ScreenModel? {
            if (inst == null || entry == null || !inst.isEnabled || !entry.model.hasImageInput || !sees(context, inst)) return null
            val key = repo.usableApiKey(inst) ?: return null
            return ScreenModel(inst, entry, key, why)
        }
        fun byEntry(entry: ModelEntry?, why: Why): ScreenModel? =
            entry?.let { e -> usable(cfg.instances.firstOrNull { it.id == e.providerInstanceId }, e, why) }
        if (!automatic) modelEntryId(context)?.let { id -> byEntry(cfg.modelEntries.firstOrNull { it.id == id }, Why.CHOSEN) }?.let { return it }
        val cloud = NanoMuseCloud.instance(context)
        // the chat provider's own model for the screen, when the chat provider is the
        // person's own and sees: `defaults.hands` of the catalogue, else its first that sees
        io.github.nanomuse.models.ModelSlots.ownChatInstance(context)?.takeIf { sees(context, it) }?.let { own ->
            val wanted = io.github.nanomuse.models.ModelSlots.defaultOf(context, own, io.github.nanomuse.models.ModelSlots.Slot.HANDS)
            val sighted = cfg.modelEntries.filter { it.providerInstanceId == own.id && !it.isHidden && it.model.hasImageInput }
            (sighted.firstOrNull { wanted != null && it.model.id.equals(wanted, ignoreCase = true) } ?: sighted.firstOrNull())
                ?.let { byEntry(it, Why.CHAT_PROVIDER) }
        }?.let { return it }
        if (cloud != null) {
            NanoMuseCloud.sightedModelId(context)?.let { sighted ->
                byEntry(cfg.modelEntries.firstOrNull { it.providerInstanceId == cloud.id && it.model.id == sighted && !it.isHidden }, Why.MENU)
            }?.let { return it }
        }
        // the hands' default under a key of the person's own (Bailian, OpenRouter, a relay of
        // their own): the entry has to be there already — nothing is added behind their back
        DEFAULT_MODEL_IDS.firstNotNullOfOrNull { wanted ->
            cfg.modelEntries.filter { !it.isHidden && it.model.id.equals(wanted, ignoreCase = true) }
                .firstNotNullOfOrNull { byEntry(it, Why.DEFAULT) }
        }?.let { return it }
        byEntry(repo.lastUsedVisibleEntry(), Why.CHAT)?.let { return it }
        val defaultGroup = cfg.modelGroups.firstOrNull { it.id == cfg.defaultPrimaryGroupId } ?: cfg.modelGroups.firstOrNull()
        defaultGroup?.memberEntryIds?.firstNotNullOfOrNull { id ->
            byEntry(cfg.modelEntries.firstOrNull { it.id == id }, Why.GROUP)
        }?.let { return it }
        repo.resolveVisionCandidates().firstNotNullOfOrNull { (inst, e) -> usable(inst, e, Why.VISION_GROUP) }?.let { return it }
        val all = visionEntries(context)
            .filter { (inst, e) -> inst.id != cloud?.id || !NanoMuseCloud.isCatalogModel(context, e.model.id) }
            .mapNotNull { (inst, e) -> usable(inst, e, Why.ANY) }
        return all.firstOrNull { Regex("vl|vision", RegexOption.IGNORE_CASE).containsMatchIn(it.modelId) } ?: all.firstOrNull()
    }

    private fun repo(context: Context): ProviderRepository? = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull

    // ── a run in progress ──────────────────────────────────────────────────

    /** True while the hands are working; the settings page and the overlay observer read it. */
    private val _active = MutableStateFlow(false)
    val active: StateFlow<Boolean> = _active.asStateFlow()
    internal fun setActive(on: Boolean) { _active.value = on }

    /**
     * Takes the hands for a run: true when they were free, false when another run holds them.
     * One atomic step, so two `nanomuse-hands run` arriving together cannot both start; the
     * run that gets them hands them back in [HandsOperator.run]'s finish.
     */
    internal fun claim(): Boolean = _active.compareAndSet(expect = false, update = true)

    /** The run in progress, so Stop can reach it from anywhere. */
    @Volatile internal var current: HandsOperator? = null

    /** Ends the run in progress after the action in flight; a no-op when none. */
    fun stopCurrent(reason: String = "stopped from the app") { current?.requestStop(reason) }

    // ── what the agent is told ─────────────────────────────────────────────

    /**
     * The system-prompt paragraph: the ladder, and the CLI when the hands are usable. English,
     * like the rest of the prompt; honest about what is off so the agent explains and links the
     * setting instead of pretending to tap.
     */
    fun promptParagraph(context: Context): String {
        val on = enabled(context)
        val r = readiness(context)
        return buildString {
            append("## Apps without an API — the ladder (nanoMuse)\n")
            append("Most everyday apps here (12306, 微信, 支付宝, 美团, 淘宝, 京东…) have no API. Climb in this order and say which rung you are on before you start: ")
            append("(1) a skill, a CLI or an MCP server; (2) the page fetched with the user's login or `browser_use`; (3) the phone's own screen, last. ")
            append("A task is rarely all screen: find the number with a command, the button with the screen, and ask before it is pressed.\n")
            if (on && r.ready) {
                append("The screen is available: `nanomuse-hands run --task \"<one clear task, with every detail the hands need>\" [--app \"<app name>\"]` ")
                append("(screen model: ${r.model?.label}). It looks at screenshots — never the accessibility tree — and taps, types and swipes; a capsule with Stop shows the user what it does. ")
                append("It never types passwords, codes or card numbers: for a login or a code it hands the phone to the user and waits. Taps that pay, send, post or delete go through the same approval card as the shell and the browser. ")
                append("It returns JSON: `outcome` is done (with `answer`), stopped (the user tapped Stop — do not restart it), needs_user (`question` — relay it and wait), infeasible or failed (with `message`); `last_screen` is a picture you can show with `![screen](<last_screen>)`. ")
                append("Keep the complete JSON result: do not pipe nanomuse-hands run through head or tail. Save it to a file or parse named fields with jq, preserving ok, outcome, steps, last_screen and the answer, message or question. ")
                append("Tell the user in one line that you are about to use the screen and which app, then run it; give one task per run, and never a payment as the task. `nanomuse-hands apps` lists the installed apps; `nanomuse-hands status` says what is set up.")
            } else if (on) {
                val missing = buildList {
                    if (!r.androidOk) add("Android 11 or newer")
                    if (!r.serviceOn) add("the accessibility service is off")
                    if (!r.overlayOk) add("no permission to draw over other apps")
                    if (r.model == null) add("no model that can see pictures")
                }.joinToString(", ")
                append("The screen is switched on but not usable yet ($missing). If a task needs it, say so in one line and give the link [Hands]($DEEP_LINK) — it opens the setting; do not try android-a11y-cli instead.")
            } else {
                append("Operating the phone's screen is switched off (the default). If a task can only be done on the screen, say so in one line and give the link [Hands]($DEEP_LINK) so the user can switch it on; do not try android-a11y-cli instead, and do not pretend.")
            }
        }
    }
}
