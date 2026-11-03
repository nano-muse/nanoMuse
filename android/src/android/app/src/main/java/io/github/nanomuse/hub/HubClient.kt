package io.github.nanomuse.hub

import com.openminis.app.logging.AppLogger
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/** Another device of the account, as the hub lists it. */
data class Device(
    val id: String,
    val name: String,
    val kind: String,
    val os: String,
    val version: String,
    val online: Boolean,
    val actions: List<String>,
    val lastSeen: Long,
) {
    val isPhone: Boolean get() = kind == "phone"
    val isComputer: Boolean get() = kind == "computer"

    companion object {
        fun from(o: JSONObject): Device = Device(
            id = o.optString("id"),
            name = o.optString("name"),
            kind = o.optString("kind"),
            os = o.optString("os"),
            version = o.optString("version"),
            online = o.optBoolean("online"),
            actions = o.optJSONArray("actions")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList(),
            lastSeen = o.optLong("last_seen") * 1000,
        )
    }
}

class HubException(val code: String, message: String) : IOException(message)

/**
 * A call another device made to this phone; answer it exactly once. A frame that cannot be
 * sent because the socket dropped meanwhile is logged and lost, never thrown: the handlers run
 * on worker threads and in their own coroutines, where an exception would end the process, and
 * the relay fails the call to its caller on its own when no answer arrives.
 */
class IncomingCall internal constructor(
    val id: String,
    val from: JSONObject,
    val action: String,
    val args: JSONObject,
    private val client: HubClient,
) {
    @Volatile var answered = false
        private set

    val senderName: String get() = from.optString("name").ifBlank { from.optString("id").ifBlank { "a device" } }
    val senderKind: String get() = from.optString("kind")

    fun event(body: JSONObject) {
        if (!answered) trySend(JSONObject().put("type", "event").put("id", id).put("body", body))
    }

    fun result(body: JSONObject) {
        if (answered) return
        answered = true
        trySend(JSONObject().put("type", "result").put("id", id).put("ok", true).put("body", body))
    }

    fun fail(code: String, message: String) {
        if (answered) return
        answered = true
        trySend(JSONObject().put("type", "result").put("id", id).put("ok", false).put("error", code).put("message", message))
    }

    private fun trySend(frame: JSONObject) {
        try {
            client.send(frame)
        } catch (e: HubException) {
            AppLogger.info("HubClient", "$action for $senderName: ${frame.optString("type")} not sent, ${e.message}")
        }
    }
}

/**
 * One socket to the hub, kept up with backoff. Frames in are parsed here; calls for this
 * phone go to [onCall] on a worker thread; the answers to our own calls wake the caller.
 * Progress events for a call are pumped on their own thread, in order, so an event handler
 * may itself call through the hub (an approval, say) without blocking the reader.
 */
class HubClient(
    private val url: String,
    private val key: String,
    private val hello: () -> JSONObject,
    private val onCall: (IncomingCall) -> Unit,
    private val onDevices: (List<Device>) -> Unit,
    private val onState: (connected: Boolean, detail: String) -> Unit,
    /** the account's name and look changed on the relay: the frame, with its rev */
    private val onProfile: (JSONObject) -> Unit = {},
    /** another device pushed conversations: `{"type": "sync", "what", "cursor", "from"}` (contract C7) */
    private val onSync: (JSONObject) -> Unit = {},
    /** a turn started or ended on another device: `{"type": "working", "cid", "from", "device_name", "working", "at"}` (contract C9) */
    private val onWorking: (JSONObject) -> Unit = {},
    /** an event with no call behind it (relay 0.31): a computer's own approval card, or the word that it was answered */
    private val onPush: (JSONObject) -> Unit = {},
) {
    private class Pending(val onEvent: ((JSONObject) -> Unit)?) {
        val done = CountDownLatch(1)
        @Volatile var frame: JSONObject? = null
        val events = LinkedBlockingQueue<Any>()
    }

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(25, TimeUnit.SECONDS)
            .build()
    }
    private val workers = Executors.newCachedThreadPool { r -> Thread(r, "hub-worker").apply { isDaemon = true } }
    private val timer: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "hub-timer").apply { isDaemon = true } }
    private val pending = ConcurrentHashMap<String, Pending>()
    @Volatile private var ws: WebSocket? = null
    @Volatile private var stopped = false
    @Volatile var connected = false
        private set
    @Volatile var devices: List<Device> = emptyList()
        private set
    private var retry: ScheduledFuture<*>? = null
    private var delayMs = 1000L
    @Volatile private var frameLimit = MAX_FRAME
    private val stopSentinel = Any()

    fun start() {
        stopped = false
        connect()
    }

    fun stop() {
        stopped = true
        retry?.cancel(false)
        ws?.close(1000, "bye")
        ws = null
        connected = false
        failAll("closed", "the hub connection was closed")
        // a stopped client is never started again (Hub makes a new one): its threads go too
        timer.shutdownNow()
        workers.shutdownNow()
        http.dispatcher.executorService.shutdown()
        http.connectionPool.evictAll()
    }

    private fun connect() {
        if (stopped) return
        onState(false, "connecting")
        val req = Request.Builder().url(url).header("Authorization", "Bearer $key").header("User-Agent", "nanoMuse-Android/${Hub.VERSION}").build()
        ws = http.newWebSocket(req, listener)
    }

    /**
     * Drops the socket and tries again after the backoff (1 s doubling to 30 s), or after
     * [atLeastMs] when the relay said to wait: a paused hub, a replaced connection, a key it
     * refused at the handshake.
     */
    private fun scheduleReconnect(reason: String, atLeastMs: Long = 0L) {
        connected = false
        ws = null
        failAll("disconnected", "the hub connection dropped")
        // A stopped client says nothing more: its own close arrives here a moment after
        // stop(), when Hub may already run a new client whose state this would overwrite.
        if (stopped) return
        onState(false, reason)
        retry?.cancel(false)
        val wait = maxOf(delayMs, atLeastMs)
        retry = timer.schedule({ connect() }, wait, TimeUnit.MILLISECONDS)
        delayMs = (delayMs * 2).coerceAtMost(30_000L)
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            webSocket.send(hello().toString())
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            // a frame past the limit (the relay's own, or this phone's ceiling when the relay
            // named a larger one) is not parsed: a relay of someone else's cannot make the
            // phone build a JSON tree of tens of megabytes
            if (text.length > frameLimit) {
                AppLogger.warning(TAG, "a frame of ${text.length} characters is past the limit; closing")
                runCatching { webSocket.close(1009, "too_large") }
                return
            }
            val frame = runCatching { JSONObject(text) }.getOrNull() ?: return
            onFrame(frame)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            // Acknowledge with a normal close: echoing the relay's own code back (4003, say)
            // means nothing to it, and OkHttp refuses codes outside the ranges it knows.
            runCatching { webSocket.close(1000, null) }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            if (stopped) return // our own close after stop(); see scheduleReconnect
            if (code == 4001 || code == 4002) {
                // Bad key or bad device: the relay will say the same thing next time. Stop here
                // and say why; a new sign-in makes a new client.
                stopped = true
                connected = false
                ws = null
                failAll("bad_key", "the hub refused this device")
                onState(false, if (code == 4001) "bad_key" else "bad_device")
                return
            }
            // 4003: replaced by a newer connection of this device (wait 30 s, as the desktop
            // does), or the operator paused the hub (`hub_paused`: two minutes, as the desktop
            // and the iPhone wait); the row under Devices says which.
            if (code == 4003 && reason == "hub_paused") {
                scheduleReconnect("hub_paused", atLeastMs = HUB_PAUSED_RETRY_MS)
                return
            }
            scheduleReconnect("closed $code $reason", atLeastMs = if (code == 4003) REPLACED_RETRY_MS else 0L)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val status = response?.code
            AppLogger.info(TAG, "hub socket failed: ${t.message}" + (status?.let { " (HTTP $it)" } ?: ""))
            if (status == 401 || status == 403) {
                // The relay refused the key before the socket opened (it closes 4001 before
                // accepting, which reaches us as a failed handshake). The same key will be
                // refused again in a second; say so and try again slowly, a new sign-in makes
                // a new client.
                scheduleReconnect("bad_key", atLeastMs = REFUSED_RETRY_MS)
                return
            }
            scheduleReconnect(t.message ?: t.javaClass.simpleName)
        }
    }

    private fun onFrame(frame: JSONObject) {
        when (frame.optString("type")) {
            "welcome" -> {
                delayMs = 1000L
                connected = true
                // the relay's frame limit, within this phone's own ceiling
                frameLimit = frame.optJSONObject("server")?.optInt("frame_limit", 0)?.takeIf { it > 0 }?.coerceAtMost(MAX_FRAME) ?: MAX_FRAME
                devices = parseDevices(frame.optJSONArray("devices"))
                onState(true, frame.optString("device_id"))
                onDevices(devices)
            }
            "devices" -> {
                devices = parseDevices(frame.optJSONArray("devices"))
                onDevices(devices)
            }
            "profile" -> runCatching { onProfile(frame) }
            "sync" -> runCatching { onSync(frame) }
            "working" -> runCatching { onWorking(frame) }
            "call" -> {
                val call = IncomingCall(
                    id = frame.optString("id"),
                    from = frame.optJSONObject("from") ?: JSONObject(),
                    action = frame.optString("action"),
                    args = frame.optJSONObject("args") ?: JSONObject(),
                    client = this,
                )
                workers.execute {
                    try {
                        onCall(call)
                    } catch (t: Throwable) {
                        AppLogger.warning(TAG, "${call.action} from ${call.senderName} failed: ${t.message}")
                        call.fail("failed", "${t.javaClass.simpleName}: ${t.message}")
                    }
                    if (!call.answered) call.fail("failed", "the handler did not answer")
                }
            }
            "result", "event", "error" -> {
                val id = frame.optString("id")
                if (frame.optString("type") == "event" && id.isBlank()) { runCatching { onPush(frame) }; return }
                val p = pending[id]
                if (p == null) {
                    if (frame.optString("type") == "error" && id.isBlank()) AppLogger.warning(TAG, "hub error: ${frame.optString("code")} ${frame.optString("message")}")
                    return
                }
                if (frame.optString("type") == "event") {
                    if (p.onEvent != null) p.events.put(frame.optJSONObject("body") ?: JSONObject())
                    return
                }
                p.frame = frame
                p.done.countDown()
            }
        }
    }

    private fun parseDevices(arr: JSONArray?): List<Device> =
        arr?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map(Device::from) } ?: emptyList()

    internal fun send(frame: JSONObject) {
        val socket = ws ?: throw HubException("disconnected", "not connected to the hub")
        if (!socket.send(frame.toString())) throw HubException("disconnected", "the hub socket is closing")
    }

    private fun failAll(code: String, message: String) {
        val all = pending.values.toList()
        pending.clear()
        all.forEach { p ->
            p.frame = JSONObject().put("type", "error").put("code", code).put("message", message)
            p.done.countDown()
        }
    }

    /** Ask device [to] to carry out [action]; blocks up to [timeoutMs]. Returns the result body or throws [HubException]. */
    fun call(to: String, action: String, args: JSONObject, timeoutMs: Long, onEvent: ((JSONObject) -> Unit)? = null): JSONObject {
        val id = UUID.randomUUID().toString().replace("-", "").take(16)
        try {
            return callWithId(id, to, action, args, timeoutMs, onEvent)
        } catch (error: Exception) {
            if (action == "task" && (error is InterruptedException ||
                    error is HubException && error.code == "timeout")) {
                // The caller owns this id. A late cleanup must never stop a different task.
                val interrupted = Thread.interrupted() || error is InterruptedException
                try {
                    runCatching { call(to, "stop", JSONObject().put("call", id), TASK_STOP_TIMEOUT_MS) }
                } finally {
                    if (interrupted) Thread.currentThread().interrupt()
                }
            }
            throw error
        }
    }

    /** A caller-owned id lets Stop name this exact task without affecting another chat. */
    fun callWithId(id: String, to: String, action: String, args: JSONObject, timeoutMs: Long, onEvent: ((JSONObject) -> Unit)? = null): JSONObject {
        val p = Pending(onEvent)
        pending[id] = p
        var pump: Thread? = null
        if (onEvent != null) {
            pump = Thread({
                while (true) {
                    val body = p.events.take()
                    if (body === stopSentinel) return@Thread
                    try {
                        onEvent(body as JSONObject)
                    } catch (t: Throwable) {
                        AppLogger.warning(TAG, "event handler: ${t.message}")
                    }
                }
            }, "hub-events").apply { isDaemon = true; start() }
        }
        try {
            send(JSONObject().put("type", "call").put("id", id).put("to", to).put("action", action).put("args", args))
            if (!p.done.await(timeoutMs, TimeUnit.MILLISECONDS)) throw HubException("timeout", "no answer from the device within ${timeoutMs / 1000} s")
        } finally {
            pending.remove(id)
            if (pump != null) {
                p.events.put(stopSentinel)
                pump.join(5_000)
            }
        }
        val frame = p.frame ?: JSONObject()
        if (frame.optString("type") == "error") throw HubException(frame.optString("code").ifBlank { "error" }, frame.optString("message").ifBlank { "the hub refused the call" })
        if (!frame.optBoolean("ok")) throw HubException(frame.optString("error").ifBlank { "failed" }, frame.optString("message").ifBlank { "the device could not do it" })
        return frame.optJSONObject("body") ?: JSONObject()
    }

    fun rename(name: String) {
        runCatching { send(JSONObject().put("type", "rename").put("name", name)) }
    }

    /** Drops an offline device from the account's list; the hub refuses while it is connected. */
    fun forget(deviceId: String) {
        runCatching { send(JSONObject().put("type", "forget").put("device_id", deviceId)) }
    }

    companion object {
        private const val TAG = "HubClient"
        /** Match the relay and desktop/runtime task deadline. */
        const val TASK_TIMEOUT_MS = 15 * 60_000L
        const val TASK_STOP_TIMEOUT_MS = 15_000L
        /** After 4003 without a reason (replaced by a newer connection): what the desktop waits too. */
        private const val REPLACED_RETRY_MS = 30_000L
        /** After 4003 `hub_paused` (the operator paused the hub): what the desktop and the iPhone wait too. */
        private const val HUB_PAUSED_RETRY_MS = 120_000L
        /** After the relay refused the key at the handshake: what the runtime waits too. */
        private const val REFUSED_RETRY_MS = 60_000L
        /** The largest frame taken from the relay, in characters: the relay's default (docs/hub.md). */
        const val MAX_FRAME = 16 * 1024 * 1024
    }
}
