package io.github.nanomuse.hub

import android.content.Context
import android.os.Build
import com.openminis.app.BuildConfig
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.cloud.NanoMuseCloud
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * This phone on the nanoMuse hub: one outbound socket to the cloud the account is signed in
 * to, so the user's other devices — computers running nanoMuse Desktop, other phones, the web
 * console — can reach it wherever it is, and it can reach them. What they may do here is
 * decided here ([HubActions]); what this phone asks of them is judged before it is sent
 * (`nanomuse-pc`).
 */
object Hub {
    const val VERSION = BuildConfig.VERSION_NAME
    const val DEEP_LINK = "minis://settings/devices"

    private const val PREFS = "nanomuse"
    private const val KEY_ENABLED = "hub.enabled"
    private const val KEY_DEVICE_ID = "hub.device_id"
    private const val KEY_NAME = "hub.name"
    private const val KEY_REMOTE_CONTROL = "hub.remote_control"

    val ACTIONS = listOf("info", "shell", "files", "file.get", "file.put", "open", "screen", "notify", "task", "task.status", "approve", "stop", "approve.any")

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Whether this phone joins the hub at all (default on once signed in). */
    fun enabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, true)
    fun setEnabled(context: Context, on: Boolean) {
        prefs(context).edit().putBoolean(KEY_ENABLED, on).apply()
        if (on) autoStart(context) else stop(context)
    }

    /** Whether the other devices may drive this phone (shell, files, screen, tasks); `info` always answers. */
    fun remoteControl(context: Context): Boolean = prefs(context).getBoolean(KEY_REMOTE_CONTROL, true)
    fun setRemoteControl(context: Context, on: Boolean) = prefs(context).edit().putBoolean(KEY_REMOTE_CONTROL, on).apply()

    fun deviceId(context: Context): String {
        val p = prefs(context)
        p.getString(KEY_DEVICE_ID, null)?.let { return it }
        val id = "phone-" + UUID.randomUUID().toString().replace("-", "").take(12)
        p.edit().putString(KEY_DEVICE_ID, id).apply()
        return id
    }

    fun name(context: Context): String = prefs(context).getString(KEY_NAME, null)?.takeIf { it.isNotBlank() } ?: defaultName()

    fun setName(context: Context, name: String) {
        prefs(context).edit().putString(KEY_NAME, name.trim().take(60)).apply()
        client?.rename(name(context))
    }

    /** "Xiaomi 2211133C", "OnePlus PJZ110", "Samsung SM-S9180": the maker's name capitalised, the model as it is. */
    fun defaultName(): String {
        val maker = Build.MANUFACTURER.orEmpty().trim().replaceFirstChar { it.uppercase() }
        val model = Build.MODEL.orEmpty().trim()
        val raw = if (model.startsWith(maker, ignoreCase = true)) model else "$maker $model"
        return raw.trim().ifBlank { "Phone" }.take(60)
    }

    fun webConsoleUrl(context: Context): String = NanoMuseCloud.baseUrl(context).trimEnd('/') + "/app/"

    // ── the connection ─────────────────────────────────────────────────────

    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()
    private val _devices = MutableStateFlow<List<Device>>(emptyList())
    val devices: StateFlow<List<Device>> = _devices.asStateFlow()
    private val _detail = MutableStateFlow("")
    val detail: StateFlow<String> = _detail.asStateFlow()

    @Volatile private var client: HubClient? = null
    @Volatile private var appContext: Context? = null

    /** Joins the hub when the account is signed in and the switch is on; a no-op otherwise. */
    @Synchronized
    fun autoStart(context: Context) {
        if (!enabled(context) || !NanoMuseCloud.isSignedIn(context)) return
        start(context)
    }

    @Synchronized
    fun start(context: Context) {
        if (client != null) return
        val app = context.applicationContext
        val key = NanoMuseCloud.apiKey(app) ?: return
        val base = NanoMuseCloud.baseUrl(app).trimEnd('/')
        val url = base.replaceFirst("https://", "wss://").replaceFirst("http://", "ws://") + "/v1/hub"
        appContext = app
        val c = HubClient(
            url = url,
            key = key,
            hello = { hello(app) },
            onCall = { call -> HubActions.handle(app, call) },
            onDevices = { list -> _devices.value = list },
            onState = { on, detail -> _connected.value = on; _detail.value = detail },
            onProfile = { frame -> io.github.nanomuse.cloud.ProfileSync.onFrame(app, frame) },
            onSync = { frame -> io.github.nanomuse.sync.ConversationSync.onFrame(app, frame) },
            onWorking = { frame -> io.github.nanomuse.sync.ConversationSync.onWorkingFrame(app, frame) },
            onPush = { frame -> ComputerCards.onPush(app, frame) },
        )
        client = c
        c.start()
        HubService.start(app)
        AppLogger.info(TAG, "joining the hub at $url as ${deviceId(app)}")
    }

    @Synchronized
    fun stop(context: Context) {
        client?.stop()
        client = null
        _connected.value = false
        _devices.value = emptyList()
        HubService.stop(context.applicationContext)
    }

    /** Sign-out or a key change: leave, then join again if it still makes sense. */
    fun restart(context: Context) {
        stop(context)
        autoStart(context)
    }

    private fun hello(context: Context): JSONObject = JSONObject()
        .put("type", "hello")
        .put(
            "device",
            JSONObject()
                .put("id", deviceId(context))
                .put("name", name(context))
                .put("kind", "phone")
                .put("os", "Android ${Build.VERSION.RELEASE}")
                .put("version", VERSION)
                .put("actions", JSONArray(ACTIONS))
                .also { d -> helloLlm(context)?.let { d.put("llm", it) } },
        )

    /** `[A-Za-z0-9._:/-]{1,80}` and no scheme: what the hello's `llm` ids may be (docs/hub.md). */
    private val LLM_ID = Regex("^[A-Za-z0-9._:/-]{1,80}$")

    /**
     * Relay 0.28, optional: the ids this phone runs its chats under — `cloud` for the relay's
     * models, else the catalogue id of the person's own key (nothing for an endpoint the
     * catalogue does not know) — and the model id. Plain ids only; never a key or a URL. The
     * operator's console counts them in aggregate. Null when either id is missing or not plain.
     */
    private fun helloLlm(context: Context): JSONObject? {
        val entry = io.github.nanomuse.models.ModelSlots.chatEntry(context) ?: return null
        val inst = io.github.nanomuse.models.ModelSlots.chatInstance(context) ?: return null
        val provider = if (io.github.nanomuse.models.ModelSlots.isCloud(context, inst)) "cloud"
        else io.github.nanomuse.models.ModelSlots.catalogueOf(context, inst)?.id ?: return null
        val model = entry.model.id
        if (!LLM_ID.matches(provider) || !LLM_ID.matches(model) || "://" in provider || "://" in model) return null
        return JSONObject().put("provider", provider).put("model", model)
    }

    // ── calls out ──────────────────────────────────────────────────────────

    val isConnected: Boolean get() = client?.connected == true

    @Throws(HubException::class)
    fun call(to: String, action: String, args: JSONObject = JSONObject(), timeoutMs: Long = 120_000L, onEvent: ((JSONObject) -> Unit)? = null): JSONObject {
        val c = client ?: throw HubException("disconnected", "this phone is not on the hub; sign in to nanoMuse Cloud and turn on Devices")
        return c.call(to, action, args, timeoutMs, onEvent)
    }

    fun callWithId(id: String, to: String, action: String, args: JSONObject, timeoutMs: Long, onEvent: ((JSONObject) -> Unit)? = null): JSONObject {
        val c = client ?: throw HubException("disconnected", "the hub is not connected")
        return c.callWithId(id, to, action, args, timeoutMs, onEvent)
    }

    fun forget(deviceId: String) = client?.forget(deviceId)

    /** The other devices of the account — never this phone, never a browser tab. */
    fun others(context: Context): List<Device> {
        val me = deviceId(context)
        return _devices.value.filter { it.id != me && it.kind != "web" }
    }

    /** By name (case-insensitive), by id, by a unique substring, or by kind words (phone/pc/电脑/手机). */
    fun find(context: Context, query: String?): Device? {
        val all = others(context)
        val q = query?.trim()?.lowercase().orEmpty()
        if (q.isEmpty()) return all.filter { it.online }.singleOrNull()
        all.firstOrNull { it.name.lowercase() == q || it.id == query }?.let { return it }
        all.filter { it.name.lowercase().contains(q) }.singleOrNull()?.let { return it }
        val kind = when (q) {
            "pc", "computer", "desktop", "电脑", "mac", "windows" -> "computer"
            "phone", "手机" -> "phone"
            else -> null
        }
        return kind?.let { k -> all.filter { it.online && it.kind == k }.singleOrNull() }
    }

    private const val TAG = "Hub"
}
