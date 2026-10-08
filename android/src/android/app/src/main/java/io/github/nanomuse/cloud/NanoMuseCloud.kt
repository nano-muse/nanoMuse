package io.github.nanomuse.cloud

import android.content.Context
import android.os.Build
import com.openminis.app.BuildConfig
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ModelGroup
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import com.openminis.app.data.repository.ProviderRepository
import io.github.nanomuse.avatar.ImageGen
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

/**
 * nanoMuse Cloud: the "start now" path. An e-mail address, a code, and the
 * app has a provider with a starter allowance — no key of one's own needed. The server is the
 * relay in `cloud/` of the repository; anyone can run one, and "Use a different server" on the
 * sign-in screen points the phone at it ([RelayAddress]).
 *
 * To the rest of the app the relay is an ordinary OpenAI-compatible provider: an API-key
 * [ProviderInstance] on the relay's base URL, whose key is the `nm_…` token the relay issued.
 * Chat, model listing, and the avatar's pictures all go through the paths that already exist
 * for any custom base URL. What this object adds is the sign-in itself, the provisioning of
 * that instance (models fetched, a default group, the image model), and the account meta the
 * settings page shows (how much is left).
 *
 * What the relay keeps about a person is the hashed identifier and token counts; message
 * content is forwarded to the model, not stored. See `docs/cloud.md`.
 */
object NanoMuseCloud {
    const val DEFAULT_BASE = "https://cloud.nanomuse.cn"
    const val LABEL = "nanoMuse Cloud"

    private const val PREFS = "nanomuse"
    private const val KEY_BASE = "cloud.base"
    private const val KEY_INSTANCE = "cloud.instance_id"
    private const val KEY_CHANNEL = "cloud.channel"
    /** The relay's word on where the account is from (`"cn"`, contract C5); empty when it did not say. */
    private const val KEY_REGION = "cloud.region"
    private const val KEY_HINT = "cloud.hint"
    private const val KEY_GRANTED = "cloud.granted"
    private const val KEY_USED = "cloud.used"
    private const val KEY_USED_TODAY = "cloud.used_today"
    private const val KEY_DAILY_CAP = "cloud.daily_cap"
    private const val KEY_UNLIMITED = "cloud.unlimited"
    private const val KEY_CHECKED_AT = "cloud.checked_at"
    private const val KEY_MEMBER = "cloud.member"
    private const val KEY_SPENT_TODAY = "cloud.spent_today_cny"
    private const val KEY_SPENT_TOTAL = "cloud.spent_total_cny"
    private const val KEY_USD_CNY = "cloud.usd_cny"
    // 0.1.23: the one pool (relay 0.5)
    private const val KEY_GRANT = "cloud.grant_cny"
    private const val KEY_LEFT = "cloud.left_cny"
    private const val KEY_WARN = "cloud.warn"
    private const val KEY_ALLOWANCE = "cloud.allowance_cny"
    // 0.1.27: an invitation credits both sides (relay 0.9)
    private const val KEY_INVITEE_BONUS = "cloud.invitee_bonus_cny"
    private const val KEY_OWN_KEY_DOCS = "cloud.own_key_docs"
    /** Relay 0.21, contract C11: the ways-on card as data (`spend.guidance`), kept as sent; the card reads it first. */
    private const val KEY_GUIDANCE = "cloud.guidance_json"
    private const val KEY_ACCOUNT_ID = "cloud.account_id"
    private const val KEY_CREATED_AT = "cloud.created_at"
    private const val KEY_HAS_PASSWORD = "cloud.has_password"
    private const val KEY_SESSIONS = "cloud.sessions"
    private const val KEY_VIA = "cloud.via"
    private const val KEY_USAGE = "cloud.usage_json"
    // 0.1.22: invitations (relay 0.4); 0.5 counts no clips and keeps no separate credit
    private const val KEY_INVITE_CODE = "cloud.invite_code"
    private const val KEY_INVITE_URL = "cloud.invite_url"
    private const val KEY_INVITES = "cloud.invites"
    private const val KEY_INVITE_BONUS = "cloud.invite_bonus_cny"
    private const val KEY_INVITE_EARNED = "cloud.invite_earned_cny"
    // 0.1.27: data controls (relay 0.9) — the switch, what is kept, how new accounts start
    private const val KEY_CONTRIBUTE = "cloud.contribute"
    private const val KEY_CONTRIBUTE_DEFAULT = "cloud.contribute_default"
    private const val KEY_PRIVACY_URL = "cloud.privacy_url"
    /** The code sign-in created the account: the first-run setup owes the password step. */
    private const val KEY_FRESH = "cloud.fresh_account"
    /** The relay refused the key and the phone kept the account's data aside (contract C12); the sign-in page says so until the next sign-in. */
    private const val KEY_ENDED = "cloud.sign_in_ended"
    private const val KEY_WARNED_GRANT = "cloud.warned_grant"
    private const val KEY_SAMPLES = "cloud.samples"
    /** The relay's menu and what lies beyond it, so the picker and the hands can tell them apart. */
    private const val KEY_MENU_IDS = "cloud.menu_ids"
    private const val KEY_CATALOG_IDS = "cloud.catalog_ids"
    private const val KEY_RECOMMENDED = "cloud.recommended"
    private const val KEY_SIGHTED = "cloud.sighted"
    private const val KEY_CHAT_IDS = "cloud.chat_ids"
    private const val KEY_GUI_IDS = "cloud.gui_ids"
    private const val KEY_MODELS_AT = "cloud.models_at"
    /** The two lanes' defaults (contract C4), for a relay that does not mark `for` itself. */
    const val DEFAULT_CHAT_MODEL = "deepseek-v4.1-flash"
    const val DEFAULT_GUI_MODEL = "qwen3.8-27b"
    private const val MODELS_FRESH_MS = 60 * 60 * 1000L

    /** Where the privacy policy is when the relay did not name one. */
    const val PRIVACY_URL = "https://nanomuse.cn/privacy/"

    /**
     * A refusal of the relay's: its stable [code], its own sentence, the HTTP [status]; relay
     * 0.22 adds [retryAfterS] (`provider_busy`, `too_many_in_flight`) and [paused] (the
     * refusal comes from one of the operator's switches, not from use).
     */
    class CloudException(
        val code: String,
        message: String,
        val status: Int = 0,
        val retryAfterS: Int? = null,
        val paused: Boolean = false,
    ) : IOException(message)

    /** One line of the usage breakdown: a kind (chat, image, video, realtime) or a model. */
    data class UsageRow(
        val kind: String,
        val model: String,
        val requests: Int,
        val promptTokens: Long,
        val completionTokens: Long,
        val charged: Long,
        val costCny: Double,
    ) {
        val tokens: Long get() = promptTokens + completionTokens
    }

    /** What the relay says was used, by category today and overall, and by model overall. */
    data class Usage(
        val todayByKind: List<UsageRow>,
        val totalByKind: List<UsageRow>,
        val byModel: List<UsageRow>,
        val kinds: List<String>,
    )

    /** A live sign-in of the account: one per device holding a key. */
    data class Session(
        val prefix: String,
        val device: String,
        val via: String,
        val createdAt: Long,
        val lastUsedAt: Long,
        val current: Boolean,
    )

    /** One line of the account's own history (sign-ins, password changes, refusals). */
    data class Event(val ts: Long, val kind: String, val detail: String)

    /** What the settings page shows. Cached from the last `/v1/me` (or the sign-in itself). */
    data class Account(
        val channel: String,
        val hint: String,
        val granted: Long,
        val used: Long,
        val usedToday: Long,
        val dailyCap: Long,
        val checkedAt: Long,
        /** The relay runs without a ceiling: usage is shown, nothing is refused for lack of tokens. */
        val unlimited: Boolean = false,
        /** A member of the relay (the operator's list): no daily spend cap. */
        val member: Boolean = false,
        /** Money, as the relay's operator is billed for this account, in yuan. */
        val spentTodayCny: Double = 0.0,
        val spentTotalCny: Double = 0.0,
        /**
         * The pool for the account's lifetime (relay 0.5): the allowance plus what invites and
         * the operator added; 0 = no limit (a member, or an open relay).
         */
        val grantCny: Double = 0.0,
        /** What is left of the pool; negative when there is no limit. */
        val leftCny: Double = -1.0,
        /** The relay's 80 % heads-up. */
        val warn: Boolean = false,
        /** How the pool grows, for the account page: the starting allowance. */
        val allowanceCny: Double = 0.0,
        /** The guide for bringing one's own key; empty on an older relay. */
        val ownKeyDocs: String = "",
        /** Yuan per dollar, for showing both; 0 when the relay did not say. */
        val usdCny: Double = 0.0,
        /** The relay's opaque id for the account (not the number or address). */
        val accountId: String = "",
        /** When the account was created (UNIX seconds); 0 when unknown. */
        val createdAt: Long = 0,
        /** A password is set, so signing in elsewhere needs no code. */
        val hasPassword: Boolean = false,
        /** Devices currently signed in, this one included. */
        val sessions: Int = 0,
        /** How this phone signed in: "code" or "password". */
        val via: String = "",
        /** Where the relay places the account — `"cn"` for mainland China (contract C5); empty when it did not say. */
        val region: String = "",
        /** The breakdown by kind and by model, when the relay reports one. */
        val usage: Usage? = null,
        /** This account's invite code and the link to share; empty on a relay from before 0.4. */
        val inviteCode: String = "",
        val inviteUrl: String = "",
        /** Friends who signed up with the code, what each adds, and what they added in all. */
        val invites: Int = 0,
        val inviteBonusCny: Double = 0.0,
        /** What the new account gets for signing up with a code (relay 0.9); 0 on an older relay. */
        val inviteeBonusCny: Double = 0.0,
        val inviteEarnedCny: Double = 0.0,
        /**
         * Data controls — "Help improve nanoMuse's AI models": whether the relay keeps this
         * account's chat turns for the community's model, and how many it holds so far.
         */
        val contribute: Boolean = false,
        val samples: Int = 0,
        /** How the relay starts new accounts (relay 0.9); null when it did not say. */
        val contributeDefaultOn: Boolean? = null,
        /** The relay's privacy policy; empty when it did not say. */
        val privacyUrl: String = "",
    ) {
        val remaining: Long get() = (granted - used).coerceAtLeast(0)
        /** 0..1 of the grant still unspent. */
        val fraction: Float get() = if (granted <= 0) 0f else (remaining.toFloat() / granted.toFloat()).coerceIn(0f, 1f)
        /** The relay prices requests in money (a relay from before this shows tokens only). */
        val pricesInMoney: Boolean get() = usdCny > 0
        /** The account has a pool to run out of (not a member, not an open relay). */
        val limited: Boolean get() = grantCny > 0 && leftCny >= 0
        /** 0..1 of the pool spent; 0 when there is no limit. */
        val spendFraction: Float get() = if (!limited) 0f else (spentTotalCny / grantCny).toFloat().coerceIn(0f, 1f)
        /** The pool is spent: the relay refuses model calls until it grows or the person brings a key. */
        val exhausted: Boolean get() = limited && leftCny <= 0.0
        fun toUsd(cny: Double): Double = if (usdCny > 0) cny / usdCny else 0.0
    }

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }
    private val json = "application/json; charset=utf-8".toMediaType()

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /**
     * The relay this phone talks to: nanoMuse Cloud, or the one the person named on the
     * sign-in screen ("Use a different server" — people who run their own, 0.1.38). Kept
     * across launches; the hub, the console links and the media models all read it from here.
     */
    fun baseUrl(context: Context): String =
        prefs(context).getString(KEY_BASE, null)?.takeIf { it.isNotBlank() }?.trimEnd('/')
            ?: DEFAULT_BASE

    fun setBaseUrl(context: Context, url: String?) {
        prefs(context).edit().apply {
            if (url.isNullOrBlank() || url.trim().trimEnd('/') == DEFAULT_BASE) remove(KEY_BASE) else putString(KEY_BASE, url.trim().trimEnd('/'))
        }.apply()
    }

    /** Every build may point at another relay now (0.1.38); kept for the callers that asked. */
    fun canOverrideBase(): Boolean = true

    /** Asks the relay at [url] for its `/healthz`; the version it reports. Throws [IOException]. */
    suspend fun checkRelay(url: String): RelayAddress.Health = withContext(Dispatchers.IO) { RelayAddress.check(url) }

    /** The provider instance the relay is signed in as, if it still exists. */
    fun instance(context: Context): ProviderInstance? {
        val id = prefs(context).getString(KEY_INSTANCE, null) ?: return null
        return repo(context)?.instance(id)
    }

    fun isSignedIn(context: Context): Boolean {
        val inst = instance(context) ?: return false
        return !repo(context)?.loadApiKey(inst.id).isNullOrBlank()
    }

    /**
     * Whether nanoMuse Cloud is one of the model sources: signed in and the Cloud provider
     * instance switched on (upstream's `isEnabled`, the switch Settings › Models shows as *Use
     * nanoMuse Cloud models*). Off, no automatic choice and no side call (title, memory,
     * pictures, clips) goes through the relay; only the explicit *Use nanoMuse Cloud this time*
     * button does ([io.github.nanomuse.chat.CloudRetry]). The sign-in itself is untouched:
     * sync, the hub and the account page keep working.
     */
    fun modelsOn(context: Context): Boolean {
        val inst = instance(context) ?: return false
        return inst.isEnabled && isSignedIn(context)
    }

    /**
     * Switches the Cloud provider instance on or off as a model source; the sign-in stays. Off
     * while new chats answer through the relay, the chat slot moves to the first own chat model
     * ([io.github.nanomuse.models.ModelSlots.chatLeaves]), as every client does; with no chat
     * model of the person's own the switch is refused and stays on, since nothing else could
     * answer (the 1.0.0 rule). Returns false for that refusal, which the page says in one
     * sentence (`nm_models_cloud_off_refused`); true when the state is as asked.
     */
    fun setModelsOn(context: Context, on: Boolean): Boolean {
        val inst = instance(context) ?: return false
        if (inst.isEnabled == on) return true
        if (!on && !io.github.nanomuse.models.ModelSlots.canLeave(context, inst.id)) return false
        repo(context)?.updateInstance(inst.copy(isEnabled = on))
        if (!on) io.github.nanomuse.models.ModelSlots.chatLeaves(context, inst.id)
        return true
    }

    private val _signedIn = MutableStateFlow<Boolean?>(null)

    /** Whether this phone is signed in, as a flow the home screen can follow. */
    fun signedIn(context: Context): StateFlow<Boolean?> {
        if (_signedIn.value == null) _signedIn.value = isSignedIn(context)
        return _signedIn
    }

    /** The account key this phone signed in with — the hub authenticates with it too. */
    fun apiKey(context: Context): String? {
        val inst = instance(context) ?: return null
        return repo(context)?.loadApiKey(inst.id)?.takeIf { it.isNotBlank() }
    }

    /**
     * The invite bonus as the relay states it, for the lines that mention it ("+¥5 for each
     * of you") — the relay's figure can change from its operator's page at any time, so no
     * string carries one of its own. ¥5 only until the first /v1/me.
     */
    fun inviteBonusText(context: Context): String {
        val bonus = account(context)?.inviteBonusCny?.takeIf { it > 0 } ?: 5.0
        return io.github.nanomuse.ui.cloud.money(bonus)
    }

    fun account(context: Context): Account? {
        val p = prefs(context)
        val hint = p.getString(KEY_HINT, null) ?: return null
        return Account(
            channel = p.getString(KEY_CHANNEL, "") ?: "",
            hint = hint,
            granted = p.getLong(KEY_GRANTED, 0),
            used = p.getLong(KEY_USED, 0),
            usedToday = p.getLong(KEY_USED_TODAY, 0),
            dailyCap = p.getLong(KEY_DAILY_CAP, 0),
            checkedAt = p.getLong(KEY_CHECKED_AT, 0),
            unlimited = p.getBoolean(KEY_UNLIMITED, false),
            member = p.getBoolean(KEY_MEMBER, false),
            spentTodayCny = p.getFloat(KEY_SPENT_TODAY, 0f).toDouble(),
            spentTotalCny = p.getFloat(KEY_SPENT_TOTAL, 0f).toDouble(),
            grantCny = p.getFloat(KEY_GRANT, 0f).toDouble(),
            leftCny = p.getFloat(KEY_LEFT, -1f).toDouble(),
            warn = p.getBoolean(KEY_WARN, false),
            allowanceCny = p.getFloat(KEY_ALLOWANCE, 0f).toDouble(),
            ownKeyDocs = p.getString(KEY_OWN_KEY_DOCS, "") ?: "",
            usdCny = p.getFloat(KEY_USD_CNY, 0f).toDouble(),
            accountId = p.getString(KEY_ACCOUNT_ID, "") ?: "",
            createdAt = p.getLong(KEY_CREATED_AT, 0),
            hasPassword = p.getBoolean(KEY_HAS_PASSWORD, false),
            sessions = p.getInt(KEY_SESSIONS, 0),
            via = p.getString(KEY_VIA, "") ?: "",
            region = p.getString(KEY_REGION, "") ?: "",
            usage = p.getString(KEY_USAGE, null)?.let { parseUsage(runCatching { JSONObject(it) }.getOrNull()) },
            inviteCode = p.getString(KEY_INVITE_CODE, "") ?: "",
            inviteUrl = p.getString(KEY_INVITE_URL, "") ?: "",
            invites = p.getInt(KEY_INVITES, 0),
            inviteBonusCny = p.getFloat(KEY_INVITE_BONUS, 0f).toDouble(),
            inviteeBonusCny = p.getFloat(KEY_INVITEE_BONUS, 0f).toDouble(),
            inviteEarnedCny = p.getFloat(KEY_INVITE_EARNED, 0f).toDouble(),
            contribute = p.getBoolean(KEY_CONTRIBUTE, false),
            samples = p.getInt(KEY_SAMPLES, 0),
            contributeDefaultOn = if (p.contains(KEY_CONTRIBUTE_DEFAULT)) p.getBoolean(KEY_CONTRIBUTE_DEFAULT, false) else null,
            privacyUrl = p.getString(KEY_PRIVACY_URL, "") ?: "",
        )
    }

    /**
     * The ways-on card as the relay last described it (`spend.guidance` of `/v1/me`, relay
     * 0.21, contract C11): the region's providers in order, the plans, the local servers, the
     * caveats. Null from a relay that sends none — the card falls back to the bundled catalogue.
     */
    fun guidance(context: Context): Guidance? =
        prefs(context).getString(KEY_GUIDANCE, null)?.let { Guidance.parse(it) }

    /** Whether the last sign-in created the account (until [clearFreshAccount]). */
    fun freshAccount(context: Context): Boolean = prefs(context).getBoolean(KEY_FRESH, false)
    fun clearFreshAccount(context: Context) { prefs(context).edit().remove(KEY_FRESH).apply() }

    /**
     * True after the relay refused the phone's key and the account's data was put aside
     * (contract C12) — the sign-in page tells the person so — until the next sign-in.
     */
    fun signInEnded(context: Context): Boolean = prefs(context).getBoolean(KEY_ENDED, false)

    /**
     * The 80 % heads-up is said once per pool size: true the first time it is asked for a
     * pool of [grantCny] (and records it), false afterwards — until the pool grows.
     */
    fun markWarned(context: Context, grantCny: Double): Boolean {
        val p = prefs(context)
        val key = String.format(java.util.Locale.US, "%.2f", grantCny)
        if (p.getString(KEY_WARNED_GRANT, null) == key) return false
        p.edit().putString(KEY_WARNED_GRANT, key).apply()
        return true
    }

    /**
     * Data controls — flip "Help improve nanoMuse's AI models": while on, the relay keeps this
     * account's chat turns (the training view: what was written, what was answered, the tool
     * calls) for the community's own model. Nothing about the allowance changes. Returns the
     * account as the relay now describes it.
     */
    suspend fun setContribute(context: Context, on: Boolean): Account = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        val r = call(context, "POST", "/v1/me/contribute", JSONObject().put("on", on), token = key)
        val e = prefs(context).edit()
            .putBoolean(KEY_CONTRIBUTE, r.optBoolean("on", on))
            .putInt(KEY_SAMPLES, r.optInt("samples", 0))
        if (r.has("default_on")) e.putBoolean(KEY_CONTRIBUTE_DEFAULT, r.optBoolean("default_on", false))
        r.optString("privacy_url", "").takeIf { it.isNotBlank() }?.let { e.putString(KEY_PRIVACY_URL, it) }
        e.apply()
        account(context)!!
    }

    /**
     * The agent's name and look as the account's devices share it (`rev` 0 = none yet); without
     * the face's pictures when [withFace] is false. Blocking — [ProfileSync] calls it off the
     * main thread.
     */
    fun profile(context: Context, withFace: Boolean): JSONObject {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        return call(context, "GET", if (withFace) "/v1/me/profile" else "/v1/me/profile?face=false", null, token = key)
    }

    /** This phone's name and look for the account (last writer wins); the new `rev`. Blocking. */
    fun putProfile(context: Context, body: JSONObject): JSONObject {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        return call(context, "PUT", "/v1/me/profile", body, token = key)
    }

    /** Delete every turn the relay kept from this account; returns how many went. */
    suspend fun deleteSamples(context: Context): Int = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        val n = call(context, "DELETE", "/v1/me/samples", null, token = key).optInt("deleted", 0)
        prefs(context).edit().putInt(KEY_SAMPLES, 0).apply()
        n
    }

    /**
     * What a job would cost before it is started — the avatar studio asks before a new face
     * (the candidates, the poses and, with video on, the clips). Nothing is charged.
     */
    data class Estimate(
        val cny: Double,
        /** What is left of the pool; null when there is no limit. */
        val leftCny: Double?,
        val affordable: Boolean,
        val images: Int,
        val clips: Int,
    )

    suspend fun estimate(context: Context, images: Int, clips: Int): Estimate = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        val r = call(context, "GET", "/v1/estimate?images=$images&clips=$clips", null, token = key)
        // 0.5 says `left_cny`; a 0.4 relay said `left_today_cny`
        val leftKey = if (r.has("left_cny")) "left_cny" else "left_today_cny"
        Estimate(
            cny = r.optDouble("cny", 0.0),
            leftCny = if (r.isNull(leftKey)) null else r.optDouble(leftKey, 0.0),
            affordable = r.optBoolean("affordable", true),
            images = images,
            clips = clips,
        )
    }

    /** Ask the relay to send a code. Throws [CloudException] with the relay's `code`. */
    suspend fun requestCode(context: Context, identifier: String) = withContext(Dispatchers.IO) {
        call(context, "POST", "/v1/auth/code", JSONObject().put("identifier", identifier.trim()), token = null)
        Unit
    }

    /**
     * Exchange the code for a key and make the relay a usable provider: instance, key, models,
     * a default group with the recommended chat model (only if the user has none yet), and the
     * image model for the avatar (only if none is set). Returns the account as the relay sees it.
     */
    suspend fun verify(context: Context, identifier: String, code: String, invite: String = ""): Account = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("identifier", identifier.trim())
            .put("code", code.trim())
            .put("device", deviceName())
        // a friend's code counts for a new account only; the relay ignores it otherwise
        if (invite.isNotBlank()) body.put("invite", invite.trim())
        adopt(context, call(context, "POST", "/v1/auth/verify", body, token = null))
    }

    /** The password way in — for people who set one under Account; no code to wait for. */
    suspend fun login(context: Context, identifier: String, password: String): Account = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("identifier", identifier.trim())
            .put("password", password)
            .put("device", deviceName())
        adopt(context, call(context, "POST", "/v1/auth/login", body, token = null))
    }

    /**
     * Set or change the password. [current] is needed when one is set already — except right
     * after a code sign-in, which is the "forgot it" path. An empty [password] with [current]
     * removes it.
     */
    suspend fun setPassword(context: Context, password: String, current: String?) = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        val body = JSONObject().put("password", password)
        if (current != null) body.put("current", current) else body.put("current", JSONObject.NULL)
        call(context, "POST", "/v1/auth/password", body, token = key)
        prefs(context).edit().putBoolean(KEY_HAS_PASSWORD, password.isNotEmpty()).apply()
        Unit
    }

    /** The devices signed in to this account, the current one first. */
    suspend fun sessions(context: Context): List<Session> = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: return@withContext emptyList()
        val arr = call(context, "GET", "/v1/me/sessions", null, token = key).optJSONArray("sessions") ?: JSONArray()
        (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map {
            Session(
                prefix = it.optString("prefix"),
                device = it.optString("device"),
                via = it.optString("via", "code"),
                createdAt = it.optLong("created_at"),
                lastUsedAt = it.optLong("last_used_at", 0),
                current = it.optBoolean("current"),
            )
        }
    }

    /** Sign one other device out. */
    suspend fun revokeSession(context: Context, prefix: String) = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        call(context, "DELETE", "/v1/me/sessions/$prefix", null, token = key)
        Unit
    }

    /** The account's own history, newest first. */
    suspend fun events(context: Context, limit: Int = 40): List<Event> = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: return@withContext emptyList()
        val arr = call(context, "GET", "/v1/me/events?limit=$limit", null, token = key).optJSONArray("events") ?: JSONArray()
        (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map {
            Event(ts = it.optLong("ts"), kind = it.optString("kind"), detail = it.optString("detail"))
        }
    }

    /**
     * Every other device loses its key; with [includingThis] this phone signs out too, and
     * its copy of the account's data stays only with [keep] (contract C12).
     */
    suspend fun signOutEverywhere(context: Context, includingThis: Boolean, keep: Boolean = false) = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        call(context, "POST", "/v1/auth/sign-out-all", JSONObject().put("all", includingThis), token = key)
        if (includingThis) forgetLocally(context, keep)
        Unit
    }

    /**
     * The person's own request: the account and everything about it goes at the relay, and
     * everything of it on this phone — chats, memory, feed, goals, face, the key — goes too
     * (contract C12). The next sign-in with the same address is a new account and starts empty.
     */
    suspend fun deleteAccount(context: Context) = withContext(Dispatchers.IO) {
        val key = apiKey(context) ?: throw CloudException("bad_key", "Not signed in")
        call(context, "POST", "/v1/auth/delete", null, token = key)
        forgetLocally(context, keep = false)
    }

    private fun deviceName(): String = "${Build.MANUFACTURER} ${Build.MODEL}".trim().take(80)

    /**
     * The phone forgets the account: the hub stops, the account's data leaves the fixed paths
     * (contract C12, [io.github.nanomuse.account.AccountData.leave] — put aside with [keep],
     * deleted without), the provider and the key go, and the phone's own set comes back.
     * The account's data moves while the account is still the signed-in key; the phone's set
     * returns only once the key is gone, so nothing made in the gap is filed under the account
     * that left. All of it inside the sync lock, so no push reads the gap as deletions.
     */
    private suspend fun forgetLocally(context: Context, keep: Boolean) {
        val ctx = context.applicationContext
        io.github.nanomuse.hub.Hub.stop(ctx)
        val account = io.github.nanomuse.account.AccountData.key(ctx)
        io.github.nanomuse.sync.ConversationSync.exclusive {
            if (account.isNotEmpty()) io.github.nanomuse.account.AccountData.leave(ctx, account, keep)
            instance(ctx)?.let { repo(ctx)?.removeInstance(it.id) }
            clear(ctx)
            if (account.isNotEmpty()) io.github.nanomuse.account.AccountData.enter(ctx, io.github.nanomuse.account.AccountScope.LOCAL)
        }
    }

    /**
     * A key from the relay (a code or a password sign-in) becomes a usable provider: instance,
     * key, models, a default group with the recommended chat model (only if the user has none
     * yet); the image and video models follow the Models page's order with nothing written.
     */
    private suspend fun adopt(context: Context, reply: JSONObject): Account {
        val repo = repo(context) ?: throw CloudException("no_repository", "Provider storage is not ready")
        val apiKey = reply.optString("api_key").takeIf { it.isNotBlank() }
            ?: throw CloudException("bad_reply", "The relay sent no key")
        // contract C12: who was here before the key is written — the phone's own set (signed
        // out), or an account a sign-in reached without a sign-out (nothing of it is deleted
        // without the sheet's question: it is put aside, as *Keep* would)
        val before = io.github.nanomuse.account.AccountData.key(context)
        // The host the code was sent to is the host the key is for; the relay's own idea of
        // its public address (`base_url`) is informational.
        val base = baseUrl(context)

        // One instance per relay: signing in again on the same phone refreshes the key and
        // keeps the entries, groups and the image model that already point at it.
        val existing = instance(context)
        val inst = existing?.let {
            if (it.customBaseURL == base) it else it.copy(customBaseURL = base).also(repo::updateInstance)
        } ?: ProviderInstance(
            id = UUID.randomUUID().toString(),
            label = LABEL,
            providerType = ProviderType.openAI,
            credentialType = ProviderCredential.apiKey,
            customBaseURL = base,
            appendV1Suffix = true,
        ).also { repo.addInstance(it) }
        repo.saveApiKey(inst.id, apiKey)
        prefs(context).edit().putString(KEY_INSTANCE, inst.id).remove(KEY_ENDED).apply()

        // The models the relay serves — same `/v1/models` call every provider gets; the relay
        // includes modalities so the picture model is recognised as one.
        runCatching { repo.refreshModels(inst) }
        provisionDefaults(context, repo, inst, reply.optJSONArray("models"))
        // the menu as sent with the key; the catalog beyond it comes with the first /v1/models
        rememberModels(context, reply.optJSONArray("models"), stamp = false)
        runCatching { syncModels(context, apiKey) }

        saveAccount(context, reply)
        if (reply.optBoolean("created", false)) prefs(context).edit().putBoolean(KEY_FRESH, true).apply()
        val after = io.github.nanomuse.account.AccountData.key(context)
        if (after != before) {
            io.github.nanomuse.sync.ConversationSync.exclusive {
                io.github.nanomuse.account.AccountData.leave(context, before, keep = true)
                io.github.nanomuse.account.AccountData.enter(context, after)
            }
        }
        _signedIn.value = true
        io.github.nanomuse.hub.Hub.restart(context) // the new key joins the hub
        ProfileSync.pullSoon(context) // the name and look the account's other devices wear
        io.github.nanomuse.sync.ConversationSync.signedIn(context) // the account's conversations (contract C7)
        return account(context)!!
    }

    /** Re-read the balance. Returns null (and forgets the account) when the key is gone. */
    suspend fun refresh(context: Context): Account? = withContext(Dispatchers.IO) {
        val inst = instance(context) ?: return@withContext null
        val key = repo(context)?.loadApiKey(inst.id) ?: return@withContext null
        try {
            val me = call(context, "GET", "/v1/me", null, token = key)
            saveAccount(context, me)
            // the menu and the catalog move slowly: once an hour is plenty
            if (System.currentTimeMillis() - prefs(context).getLong(KEY_MODELS_AT, 0) > MODELS_FRESH_MS) {
                runCatching { syncModels(context, key) }
            }
            account(context)
        } catch (e: CloudException) {
            if (e.status == 401) {
                // Revoked elsewhere, or the relay was reset: the provider cannot answer any
                // more. Nobody on this phone asked, so the account's data is put aside as
                // *Keep* would and comes back with the next sign-in as the same account
                // (contract C12). Only `account_deleted` — the account itself is gone at the
                // relay — leaves nothing to come back to, and the data goes.
                val keep = io.github.nanomuse.account.AccountScope.keepOnRefusedKey(e.code)
                forgetLocally(context, keep)
                if (keep) prefs(context).edit().putBoolean(KEY_ENDED, true).apply()
                null
            } else {
                account(context)
            }
        }
    }

    /**
     * Revoke this phone's key at the relay and take the provider out of the app. The account's
     * chats, memory, feed, goals and face stay on the phone — put aside for its return — only
     * with [keep] (the sign-out sheet's switch, off by default; contract C12).
     */
    suspend fun signOut(context: Context, keep: Boolean = false) = withContext(Dispatchers.IO) {
        val repo = repo(context)
        val inst = instance(context)
        val key = inst?.let { repo?.loadApiKey(it.id) }
        if (inst != null && key != null) {
            runCatching { call(context, "POST", "/v1/auth/sign-out", null, token = key) }
        }
        forgetLocally(context, keep)
    }

    /**
     * The one line for a turn refused for a spent allowance: the invitation, and the way on
     * that fits where the person is (contract C5) — 阿里云百炼 on the mainland, OpenRouter's
     * sign-in elsewhere.
     */
    fun allowanceSentence(context: Context): String = context.getString(
        if (Region.mainland(context)) R.string.nm_cloud_err_allowance else R.string.nm_cloud_err_allowance_abroad,
        inviteBonusText(context),
    )

    /**
     * A sentence for the person, from the relay's stable error codes — every code the relay
     * sends today (docs/cloud.md; the desktop's `refusals.ts` and the runtime's `failures.py`
     * say the same in their words), never a status code or the wire.
     */
    fun describe(context: Context, e: Throwable): String = when (e) {
        is CloudException -> when (e.code) {
            "bad_identifier" -> context.getString(R.string.nm_cloud_err_bad_identifier)
            "code_wrong" -> context.getString(R.string.nm_cloud_err_code_wrong)
            "code_expired" -> context.getString(R.string.nm_cloud_err_code_expired)
            "code_too_often" -> context.getString(R.string.nm_cloud_err_code_too_often)
            "not_invited" -> context.getString(R.string.nm_cloud_err_not_invited)
            "signup_closed" -> context.getString(R.string.nm_cloud_err_signup_closed)
            "send_failed" -> context.getString(R.string.nm_cloud_err_send_failed)
            "phone_region" -> context.getString(R.string.nm_cloud_sms_region) // the same sentence the sign-in screen shows before asking
            "account_disabled" -> context.getString(R.string.nm_cloud_err_disabled)
            "bad_key" -> context.getString(R.string.nm_cloud_err_bad_key)
            "account_deleted" -> context.getString(R.string.nm_cloud_err_account_deleted)
            "out_of_tokens" -> context.getString(R.string.nm_cloud_err_out_of_tokens)
            "daily_cap" -> context.getString(R.string.nm_cloud_err_daily_cap)
            // relay 0.22: the operator paused the free allowance — not used up, the same card, another lead
            "allowance_exhausted" -> if (e.paused) context.getString(R.string.nm_cloud_err_allowance_paused) else allowanceSentence(context)
            "rate_limited", "too_many_in_flight" -> context.getString(R.string.nm_cloud_err_rate_limited)
            "provider_busy" -> e.retryAfterS?.takeIf { it > 0 }
                ?.let { context.getString(R.string.nm_cloud_err_provider_busy_wait, io.github.nanomuse.ui.chat.duration(context, it)) }
                ?: context.getString(R.string.nm_cloud_err_provider_busy)
            "too_large" -> context.getString(R.string.nm_cloud_err_too_large)
            "model_not_offered" -> context.getString(R.string.nm_cloud_err_model_not_offered)
            "service_paused" -> context.getString(R.string.nm_cloud_err_service_paused)
            "sync_paused" -> context.getString(R.string.nm_cloud_err_sync_paused)
            "hub_paused" -> context.getString(R.string.nm_cloud_err_hub_paused)
            "upstream" -> context.getString(R.string.nm_cloud_err_relay_down)
            "unreachable" -> context.getString(R.string.nm_cloud_err_unreachable)
            "bad_credentials" -> context.getString(R.string.nm_cloud_err_bad_credentials)
            "no_password" -> context.getString(R.string.nm_cloud_err_no_password)
            "locked" -> context.getString(R.string.nm_cloud_err_locked)
            "password_wrong" -> context.getString(R.string.nm_cloud_err_password_wrong)
            "password_required" -> context.getString(R.string.nm_cloud_err_password_required)
            "password_short" -> context.getString(R.string.nm_cloud_err_password_short)
            "password_weak", "password_long" -> context.getString(R.string.nm_cloud_err_password_weak)
            // no code of the relay's: the status says enough for a 413 (a proxy's plain
            // "Request too large"), a 401 and a 5xx; anything else shows the relay's sentence
            else -> when {
                e.status == 413 -> context.getString(R.string.nm_cloud_err_too_large)
                e.status == 401 -> context.getString(R.string.nm_cloud_err_bad_key)
                e.status >= 500 -> context.getString(R.string.nm_cloud_err_relay_down)
                else -> e.message?.takeIf { it.isNotBlank() && !it.startsWith("HTTP ") } ?: context.getString(R.string.nm_cloud_err_generic)
            }
        }
        is IOException -> context.getString(R.string.nm_cloud_err_unreachable)
        else -> e.message ?: context.getString(R.string.nm_cloud_err_generic)
    }

    // -- internals -------------------------------------------------------------------------------

    private fun repo(context: Context): ProviderRepository? =
        (context.applicationContext as? MinisApp)?.providerRepositoryOrNull

    /**
     * After the key: a default group if the user has none. Nothing of the user's own is
     * replaced — someone who already has a key and a group keeps them and gets the relay as
     * one more provider.
     */
    private fun provisionDefaults(context: Context, repo: ProviderRepository, inst: ProviderInstance, models: JSONArray?) {
        val offered = (0 until (models?.length() ?: 0)).mapNotNull { models?.optJSONObject(it) }
        // the group opens on the chat default (deepseek-v4.1-flash, contract C4); the hands
        // model (qwen3.8-27b) is a setting of its own, read by Hands.screenModel
        val recommendedChat = recommendedChat(offered.filter { !drawsOnly(it) })?.optString("id")

        var config = repo.config.value
        var entries = config.modelEntries.filter { it.providerInstanceId == inst.id && !it.isHidden }
        if (entries.isEmpty() && offered.isNotEmpty()) {
            // The /models call failed or has not landed yet: build the entries
            // from the list the relay sent with the key, so the person is never
            // left with a provider that has no models and a group with no members.
            repo.replaceEntries(inst.id, offered.mapNotNull { modelFromRelay(it) })
            config = repo.config.value
            entries = config.modelEntries.filter { it.providerInstanceId == inst.id && !it.isHidden }
        }
        val chatEntry = entries.firstOrNull { it.model.id == recommendedChat }
            ?: entries.firstOrNull { !ImageGen.looksLikeImageModel(it.model.id) && !drawsOrFilms(it.model) }
        if (chatEntry != null) {
            // Ours already, with the recommended model or with the person's own choice
            // (a member who swapped the recommended model for another must not get a
            // second "nanoMuse Cloud" group with the old one back on signing in again).
            val already = config.modelGroups.any { chatEntry.id in it.memberEntryIds || (it.name == LABEL && it.memberEntryIds.isNotEmpty()) }
            if (!already) {
                // A group of ours left empty by an earlier sign-out is reused rather
                // than doubled; otherwise a new one.
                val empty = config.modelGroups.firstOrNull { it.name == LABEL && it.memberEntryIds.isEmpty() }
                if (empty != null) {
                    repo.updateGroup(empty.copy(memberEntryIds = (empty.memberEntryIds + chatEntry.id).toMutableList()))
                    if (repo.defaultPrimaryGroupId == null) repo.defaultPrimaryGroupId = empty.id
                } else {
                    val group = ModelGroup(name = LABEL)
                    group.memberEntryIds.add(chatEntry.id)
                    repo.addGroup(group)
                    if (repo.defaultPrimaryGroupId == null) repo.defaultPrimaryGroupId = group.id
                }
            }
            // The default group must be one that can answer.
            val default = repo.config.value.modelGroups.firstOrNull { it.id == repo.defaultPrimaryGroupId }
            if (default == null || default.memberEntryIds.isEmpty()) {
                val groups = repo.config.value.modelGroups
                repo.defaultPrimaryGroupId = (groups.firstOrNull { chatEntry.id in it.memberEntryIds } ?: groups.firstOrNull { it.name == LABEL && it.memberEntryIds.isNotEmpty() })?.id
            }
        }
        // The image model is not written here any more (0.1.41): with nothing chosen,
        // ImageGen.endpoint resolves it in the contract's order (the chat provider's own
        // image model, else the relay's, else the first own provider that draws), so a pick
        // of the person's own is never shadowed by a choice made for them at sign-in.
    }

    private fun drawsOnly(model: JSONObject): Boolean {
        val out = model.optJSONObject("architecture")?.optJSONArray("output_modalities")
        val mods = (0 until (out?.length() ?: 0)).map { out!!.optString(it) }
        return "image" in mods && "text" !in mods
    }

    /**
     * The relay's `for` on a menu entry — `["chat"]`, `["gui"]` or both (relay 0.17, under
     * `nanomuse` with its other flags; a top-level `for` is read too); null when it did not say.
     */
    private fun lanes(model: JSONObject): List<String>? {
        val arr = model.optJSONObject("nanomuse")?.optJSONArray("for") ?: model.optJSONArray("for") ?: return null
        return (0 until arr.length()).map { arr.optString(it) }
    }

    /**
     * The chat model the menu opens on (contract C4): the one the relay recommends *for chat*
     * — `deepseek-v4.1-flash` — and, on a relay from before `for`, the recommended one, then
     * the known default by name, then the first of the menu. [chats] are the menu's chat
     * models in the menu's order.
     */
    private fun recommendedChat(chats: List<JSONObject>): JSONObject? {
        fun recommended(m: JSONObject) = m.optJSONObject("nanomuse")?.optBoolean("recommended") == true
        fun forChat(m: JSONObject) = lanes(m)?.contains("chat") != false
        return chats.firstOrNull { recommended(it) && forChat(it) && lanes(it)?.contains("gui") != true }
            ?: chats.firstOrNull { recommended(it) && forChat(it) }
            ?: chats.firstOrNull { it.optString("id") == DEFAULT_CHAT_MODEL }
            ?: chats.firstOrNull { forChat(it) }
    }

    // -- the menu and the catalog ------------------------------------------------------------

    /**
     * Ask the relay for its models and remember which are the menu's and which the catalog's
     * (`nanomuse.catalog`: usable under the operator's key but not on the menu — a member may
     * name them; the relay has checked whether they take pictures). The app's own entries
     * carry none of this: OpenMinis reads `/v1/models` as any provider's list.
     */
    private suspend fun syncModels(context: Context, apiKey: String) {
        val reply = call(context, "GET", "/v1/models", null, token = apiKey)
        rememberModels(context, reply.optJSONArray("data"), stamp = true)
    }

    private fun rememberModels(context: Context, models: JSONArray?, stamp: Boolean) {
        val items = (0 until (models?.length() ?: 0)).mapNotNull { models?.optJSONObject(it) }
        if (items.isEmpty()) return
        val menu = mutableListOf<String>()
        val catalog = mutableListOf<String>()
        for (m in items) {
            val id = m.optString("id").takeIf { it.isNotBlank() } ?: continue
            val nm = m.optJSONObject("nanomuse")
            if (nm?.optBoolean("catalog") == true) catalog.add(id) else menu.add(id)
        }
        fun sees(m: JSONObject): Boolean {
            val mods = m.optJSONObject("architecture")?.optJSONArray("input_modalities")
            return (0 until (mods?.length() ?: 0)).any { mods!!.optString(it) == "image" }
        }
        val chats = items.filter { !drawsOnly(it) && it.optJSONObject("nanomuse")?.optBoolean("catalog") != true }
        val recommended = recommendedChat(chats)
        // the menu's model for the screen — the hands model, a setting apart from the chat
        // model (contract C4): what the relay marks `for: ["gui"]`, qwen3.8-27b on an older
        // relay that does not say, else the first of the menu that sees
        val sighted = (chats.firstOrNull { lanes(it)?.contains("gui") == true }
            ?: chats.firstOrNull { it.optString("id") == DEFAULT_GUI_MODEL }
            ?: chats.firstOrNull { sees(it) })?.optString("id")
        // the menu by lane (0.1.41, the Models page): `for` contains `chat` / `gui`; a relay
        // from before `for` puts every chat model in the chat lane and the sighted one in gui
        val chatLane = chats.filter { lanes(it)?.contains("chat") != false }.map { it.optString("id") }.filter { it.isNotBlank() }
        val guiLane = chats.filter { lanes(it)?.contains("gui") == true }.map { it.optString("id") }.filter { it.isNotBlank() }
            .ifEmpty { listOfNotNull(sighted) }
        prefs(context).edit().apply {
            putString(KEY_MENU_IDS, menu.joinToString(","))
            // the list sent with the key is the menu alone: it must not erase a catalog we know
            if (stamp || catalog.isNotEmpty()) putString(KEY_CATALOG_IDS, catalog.joinToString(","))
            putString(KEY_RECOMMENDED, recommended?.optString("id") ?: "")
            putString(KEY_SIGHTED, sighted ?: "")
            putString(KEY_CHAT_IDS, chatLane.joinToString(","))
            putString(KEY_GUI_IDS, guiLane.joinToString(","))
            if (stamp) putLong(KEY_MODELS_AT, System.currentTimeMillis())
        }.apply()
    }

    private fun ids(context: Context, key: String): Set<String> =
        prefs(context).getString(key, null)?.split(',')?.filter { it.isNotBlank() }?.toSet() ?: emptySet()

    /** The menu's model ids, in the menu's order (empty when the relay has not been asked yet). */
    fun menuModelIds(context: Context): List<String> =
        prefs(context).getString(KEY_MENU_IDS, null)?.split(',')?.filter { it.isNotBlank() } ?: emptyList()

    /** True for a model the relay serves beyond its menu (the catalog); false for the menu's and for the unknown. */
    fun isCatalogModel(context: Context, modelId: String): Boolean = modelId in ids(context, KEY_CATALOG_IDS)

    /** The menu's recommended chat model, if the relay said. */
    fun recommendedModelId(context: Context): String? = prefs(context).getString(KEY_RECOMMENDED, null)?.takeIf { it.isNotBlank() }

    /** The menu's model for looking at the screen: the recommended one when it sees pictures, else the first that does. */
    fun sightedModelId(context: Context): String? = prefs(context).getString(KEY_SIGHTED, null)?.takeIf { it.isNotBlank() }

    /** The menu's chat lane (`for` contains `chat`), in the menu's order; the whole menu's chat models when the relay did not say. */
    fun chatLaneIds(context: Context): List<String> =
        prefs(context).getString(KEY_CHAT_IDS, null)?.split(',')?.filter { it.isNotBlank() } ?: emptyList()

    /** The menu's lane for the screen (`for` contains `gui`), in the menu's order; the sighted model alone on an older relay. */
    fun guiLaneIds(context: Context): List<String> =
        prefs(context).getString(KEY_GUI_IDS, null)?.split(',')?.filter { it.isNotBlank() }?.ifEmpty { null }
            ?: listOfNotNull(sightedModelId(context))

    /** Is this entry served by the relay? (Null when the person is not signed in.) */
    fun owns(context: Context, entry: ModelEntry): Boolean = instance(context)?.id == entry.providerInstanceId

    // The person picked a model in the chat's picker: the next chats follow it. That used to
    // live here for the relay's models alone; since 0.1.41 it holds for every provider and is
    // io.github.nanomuse.models.ModelSlots.followPick.

    /** A picture or video model is no chat model, whatever its name says. */
    fun drawsOrFilms(model: LLMModel): Boolean {
        val out = model.outputModalities?.map { it.lowercase() } ?: return false
        return "text" !in out && ("image" in out || "video" in out)
    }

    /** One entry of the relay's `/v1/models` list (also sent with the key) as the app's model. */
    private fun modelFromRelay(item: JSONObject): LLMModel? {
        val id = item.optString("id").takeIf { it.isNotBlank() } ?: return null
        val arch = item.optJSONObject("architecture")
        fun mods(key: String): List<String>? {
            val arr = arch?.optJSONArray(key) ?: return null
            return (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotBlank() }.takeIf { it.isNotEmpty() }
        }
        return LLMModel(
            id = id,
            displayName = item.optString("name").ifBlank { id },
            provider = LABEL,
            inputModalities = mods("input_modalities"),
            outputModalities = mods("output_modalities"),
        )
    }

    private fun saveAccount(context: Context, reply: JSONObject) {
        // The nudges policy rides along in /v1/me (contract C1); the sign-in reply may carry it too.
        io.github.nanomuse.community.Nudges.accept(context, reply.optJSONObject("nudges"))
        val account = reply.optJSONObject("account") ?: JSONObject()
        val tokens = reply.optJSONObject("tokens") ?: JSONObject()
        val spend = reply.optJSONObject("spend") ?: JSONObject()
        prefs(context).edit()
            .putString(KEY_CHANNEL, account.optString("channel"))
            .putString(KEY_HINT, account.optString("hint"))
            .putLong(KEY_GRANTED, tokens.optLong("granted"))
            .putLong(KEY_USED, tokens.optLong("used"))
            .putLong(KEY_USED_TODAY, tokens.optLong("used_today"))
            .putLong(KEY_DAILY_CAP, tokens.optLong("daily_cap"))
            .putBoolean(KEY_UNLIMITED, tokens.optBoolean("unlimited", false))
            .putBoolean(KEY_MEMBER, account.optBoolean("member", false))
            .putFloat(KEY_SPENT_TODAY, spend.optDouble("today", 0.0).toFloat())
            .putFloat(KEY_SPENT_TOTAL, spend.optDouble("total", 0.0).toFloat())
            // relay 0.5: the pool and what is left; a 0.4 relay sent the day's cap under `daily_cap`
            .putFloat(KEY_GRANT, spend.optDouble("grant", spend.optDouble("daily_cap", 0.0)).toFloat())
            .putFloat(
                KEY_LEFT,
                when {
                    spend.optBoolean("unlimited", false) -> -1f
                    spend.has("left") && !spend.isNull("left") -> spend.optDouble("left", -1.0).toFloat()
                    spend.has("left_today") && !spend.isNull("left_today") -> spend.optDouble("left_today", -1.0).toFloat()
                    else -> -1f
                },
            )
            .putBoolean(KEY_WARN, spend.optBoolean("warn", false))
            .putFloat(KEY_ALLOWANCE, spend.optDouble("allowance_cny", 0.0).toFloat())
            .putFloat(KEY_INVITEE_BONUS, spend.optDouble("invitee_bonus_cny", reply.optJSONObject("invite")?.optDouble("invitee_bonus_cny", 0.0) ?: 0.0).toFloat())
            .putString(KEY_OWN_KEY_DOCS, spend.optString("own_key_docs", ""))
            // relay 0.21: the card as data; an older relay sends none and the bundled catalogue is used
            .putString(KEY_GUIDANCE, spend.optJSONObject("guidance")?.toString())
            .putFloat(KEY_USD_CNY, spend.optDouble("usd_cny", 0.0).toFloat())
            .putString(KEY_ACCOUNT_ID, account.optString("id"))
            .putLong(KEY_CREATED_AT, account.optLong("created_at", 0))
            .putBoolean(KEY_HAS_PASSWORD, account.optBoolean("has_password", false))
            .putInt(KEY_SESSIONS, account.optInt("sessions", 0))
            .putString(KEY_VIA, account.optString("signed_in_via"))
            .putString(KEY_REGION, account.optString("region", reply.optString("region", "")))
            .putString(KEY_USAGE, reply.optJSONObject("usage")?.toString())
            .putString(KEY_INVITE_CODE, reply.optJSONObject("invite")?.optString("code").orEmpty())
            .putString(KEY_INVITE_URL, reply.optJSONObject("invite")?.optString("url").orEmpty())
            .putInt(KEY_INVITES, reply.optJSONObject("invite")?.optInt("invites") ?: 0)
            .putFloat(KEY_INVITE_BONUS, (reply.optJSONObject("invite")?.optDouble("bonus_cny", 0.0) ?: 0.0).toFloat())
            .putFloat(KEY_INVITE_EARNED, (reply.optJSONObject("invite")?.optDouble("earned_cny", 0.0) ?: 0.0).toFloat())
            .putBoolean(KEY_CONTRIBUTE, reply.optJSONObject("contribute")?.optBoolean("on", false) ?: false)
            .putInt(KEY_SAMPLES, reply.optJSONObject("contribute")?.optInt("samples", 0) ?: 0)
            .putString(KEY_PRIVACY_URL, reply.optJSONObject("contribute")?.optString("privacy_url", "").orEmpty())
            .also { e ->
                // relay 0.9 says how new accounts start; an older one does not, and the page says nothing
                val ct = reply.optJSONObject("contribute")
                if (ct != null && ct.has("default_on")) e.putBoolean(KEY_CONTRIBUTE_DEFAULT, ct.optBoolean("default_on", false)) else e.remove(KEY_CONTRIBUTE_DEFAULT)
            }
            .putLong(KEY_CHECKED_AT, System.currentTimeMillis())
            .apply()
        migrateMediaModels(context, reply.optJSONArray("models"))
    }

    /**
     * The relay's menu changes between versions (0.4 draws with qwen-image-3.0 and animates with
     * wan2.2-i2v-flash instead of the Pro tier and MiniMax-H3). A phone that still points its
     * image or video model at a name the relay no longer offers is moved to what it offers now;
     * a user's own providers are never touched, and a slot that was never chosen (it follows
     * the automatic order, which already reads the relay's current menu) is left unchosen.
     */
    private fun migrateMediaModels(context: Context, models: JSONArray?) {
        val inst = instance(context) ?: return
        val offered = (0 until (models?.length() ?: 0)).mapNotNull { models?.optJSONObject(it) }
        if (offered.isEmpty()) return
        val ids = offered.map { it.optString("id") }.toSet()
        val image = ImageGen.endpoint(context)?.takeIf { ImageGen.isChosen(context) }
        if (image != null && image.instanceId == inst.id && image.model !in ids) {
            offered.firstOrNull { drawsOnly(it) }?.optString("id")?.let { ImageGen.save(context, inst.id, it) }
        }
        val video = io.github.nanomuse.media.MediaModels.videoEndpoint(context)?.takeIf { io.github.nanomuse.media.MediaModels.videoChosen(context) }
        if (video != null && video.instanceId == inst.id && video.model !in ids) {
            val offeredVideo = offered.filter { films(it) }
            val pick = offeredVideo.firstOrNull { it.optJSONObject("nanomuse")?.optBoolean("recommended") == true } ?: offeredVideo.firstOrNull()
            pick?.optString("id")?.let { io.github.nanomuse.media.MediaModels.saveVideo(context, inst.id, it) }
        }
    }

    private fun films(model: JSONObject): Boolean {
        val out = model.optJSONObject("architecture")?.optJSONArray("output_modalities")
        return (0 until (out?.length() ?: 0)).any { out!!.optString(it) == "video" }
    }

    private fun parseUsage(usage: JSONObject?): Usage? {
        usage ?: return null
        fun rows(arr: JSONArray?): List<UsageRow> = (0 until (arr?.length() ?: 0)).mapNotNull { arr?.optJSONObject(it) }.map {
            UsageRow(
                kind = it.optString("kind"),
                model = it.optString("model"),
                requests = it.optInt("requests"),
                promptTokens = it.optLong("prompt_tokens"),
                completionTokens = it.optLong("completion_tokens"),
                charged = it.optLong("charged"),
                costCny = it.optDouble("cost_cny", 0.0),
            )
        }
        val kinds = usage.optJSONArray("kinds")
        return Usage(
            todayByKind = rows(usage.optJSONObject("today")?.optJSONArray("by_kind")),
            totalByKind = rows(usage.optJSONObject("total")?.optJSONArray("by_kind")),
            byModel = rows(usage.optJSONObject("total")?.optJSONArray("by_model")),
            kinds = (0 until (kinds?.length() ?: 0)).map { kinds!!.optString(it) },
        )
    }

    private fun clear(context: Context) {
        _signedIn.value = false
        prefs(context).edit()
            .remove(KEY_INSTANCE).remove(KEY_CHANNEL).remove(KEY_HINT)
            .remove(KEY_GRANTED).remove(KEY_USED).remove(KEY_USED_TODAY).remove(KEY_DAILY_CAP).remove(KEY_UNLIMITED).remove(KEY_CHECKED_AT)
            .remove(KEY_MEMBER).remove(KEY_SPENT_TODAY).remove(KEY_SPENT_TOTAL).remove(KEY_USD_CNY)
            .remove(KEY_GRANT).remove(KEY_LEFT).remove(KEY_WARN).remove(KEY_ALLOWANCE).remove(KEY_INVITEE_BONUS)
            .remove(KEY_OWN_KEY_DOCS).remove(KEY_GUIDANCE)
            .remove(KEY_ACCOUNT_ID).remove(KEY_CREATED_AT).remove(KEY_HAS_PASSWORD).remove(KEY_SESSIONS).remove(KEY_VIA).remove(KEY_REGION).remove(KEY_USAGE)
            .remove(KEY_INVITE_CODE).remove(KEY_INVITE_URL).remove(KEY_INVITES).remove(KEY_INVITE_BONUS).remove(KEY_INVITE_EARNED)
            .remove(KEY_CONTRIBUTE).remove(KEY_SAMPLES).remove(KEY_CONTRIBUTE_DEFAULT).remove(KEY_PRIVACY_URL).remove(KEY_FRESH).remove(KEY_WARNED_GRANT)
            .remove(KEY_MENU_IDS).remove(KEY_CATALOG_IDS).remove(KEY_RECOMMENDED).remove(KEY_SIGHTED).remove(KEY_CHAT_IDS).remove(KEY_GUI_IDS).remove(KEY_MODELS_AT)
            .apply()
        ProfileSync.forget(context)
        io.github.nanomuse.sync.ConversationSync.forget(context) // the next account starts with its own ids and cursor
    }

    private fun call(context: Context, method: String, path: String, body: JSONObject?, token: String?): JSONObject {
        val builder = Request.Builder().url(baseUrl(context) + path)
        if (token != null) builder.header("Authorization", "Bearer $token")
        builder.header("User-Agent", "nanoMuse-Android/${BuildConfig.VERSION_NAME}")
        when (method) {
            "GET" -> builder.get()
            else -> builder.method(method, (body?.toString() ?: "{}").toRequestBody(json))
        }
        val response = try {
            http.newCall(builder.build()).execute()
        } catch (e: IOException) {
            throw CloudException("unreachable", e.message ?: "unreachable")
        }
        response.use { r ->
            val text = r.body?.string().orEmpty()
            if (r.isSuccessful) {
                return if (text.isBlank()) JSONObject() else runCatching { JSONObject(text) }.getOrElse { JSONObject() }
            }
            val err = runCatching { JSONObject(text).optJSONObject("error") }.getOrNull()
            throw CloudException(
                code = err?.optString("code")?.takeIf { it.isNotBlank() } ?: "http_${r.code}",
                message = err?.optString("message")?.takeIf { it.isNotBlank() } ?: "HTTP ${r.code}",
                status = r.code,
                // relay 0.22: when to come back, and whether an operator's switch is the reason
                retryAfterS = err?.optDouble("retry_after", 0.0)?.takeIf { it > 0 }?.let { kotlin.math.ceil(it).toInt() },
                paused = err?.optBoolean("paused", false) == true,
            )
        }
    }
}
