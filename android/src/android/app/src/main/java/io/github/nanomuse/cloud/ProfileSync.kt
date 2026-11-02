package io.github.nanomuse.cloud

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.util.Base64
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ProcessLifecycleOwner
import com.openminis.app.agent.SoulStore
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.avatar.AvatarMotion
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.connectors.SharedConnectors
import io.github.nanomuse.ui.avatar.AgentMood
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import org.json.JSONObject

/**
 * The agent's name and look, the same on every device of the account.
 *
 * The relay keeps one profile per account (`/v1/me/profile`: the name, which face, and a drawn
 * face's five stills as WebP) and says `{"type": "profile", "rev"}` on the hub when it changes.
 * Here: **pull** on sign-in, on app start and on that frame, worn when the relay's `rev` is
 * newer than the one last seen on this phone; **push** a moment after the name (SOUL.md) or
 * the face ([AvatarStore]) changes here. The pictures ride along only when the face itself
 * changed. Never a key, never a message — the runtime does the same in `nanomuse/hub/profile.py`.
 *
 * The phone keeps the face it drew — the clips, the prompt — when the account's pictures are
 * the ones it already wears: the relay names them with `face_id` (the hash of the idle still),
 * older relays are checked against the downloaded still. So a rename on the desktop changes
 * the name here and nothing else.
 *
 * An emoji look chosen on another device is kept beside the drawn face and worn here too.
 *
 * The same profile carries which device connected which service (`connectors`, contract C3,
 * [SharedConnectors]): this phone's entries ride along with every push — names, addresses,
 * kinds, never a token — and the other devices' entries are read on every pull, whatever the
 * `rev`, since the relay merges them per device rather than versioning them with the look.
 */
object ProfileSync {
    private const val TAG = "ProfileSync"
    private const val PREFS = "nanomuse_profile_sync"
    private const val KEY_REV = "rev"
    private const val KEY_PUSHED_FACE = "pushed_face"
    private const val KEY_PUSHED_NAME = "pushed_name"
    /** The hash of the idle still as the relay holds it (what it reports as `face_id`). */
    private const val KEY_FACE_HASH = "face_hash"
    /** This phone's connector entries as last sent, so a push with nothing new is skipped. */
    private const val KEY_PUSHED_CONNECTORS = "pushed_connectors"
    /** The face's clips as the account lists them (`{mood: {sha256, mime, bytes}}`, relay 0.29), to add this phone's to. */
    private const val KEY_CLIPS = "account_clips"
    private const val PUSH_DELAY_MS = 2_500L
    private const val DRAGON = "dragon"

    private val moods = mapOf(
        "idle" to AgentMood.IDLE,
        "working" to AgentMood.WORKING,
        "waiting" to AgentMood.WAITING,
        "happy" to AgentMood.HAPPY,
        "error" to AgentMood.ERROR,
    )

    private val worker = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "nm-profile-sync").apply { isDaemon = true } }
    private var app: Context? = null
    @Volatile private var pending: ScheduledFuture<*>? = null
    /** Set while a pulled profile is being worn, so the change does not push back. */
    @Volatile private var applying = false

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** App start: remember the context for the stores' callbacks and fetch what the account wears. */
    fun init(context: Context) {
        app = context.applicationContext
        pullSoon(context)
        // The hub's `profile` frame is missed while the app is in the background: a pull on
        // the way back to the front picks up a name or a face another device wrote meanwhile,
        // instead of waiting for the next cold start.
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_START) pullSoon(context)
            },
        )
        // what this phone connected changes → the account's other devices hear about it
        SharedConnectors.watch(context.applicationContext) { changed() }
    }

    /** Signed out: the next account starts from its own profile. */
    fun forget(context: Context) {
        prefs(context).edit().clear().apply()
        SharedConnectors.forget(context)
    }

    // -- the frame, the pull --------------------------------------------------------------

    fun onFrame(context: Context, frame: JSONObject) {
        val rev = frame.optInt("rev", 0)
        if (frame.optString("device") == io.github.nanomuse.hub.Hub.deviceId(context)) {
            // our own write coming back
            if (rev > prefs(context).getInt(KEY_REV, 0)) prefs(context).edit().putInt(KEY_REV, rev).apply()
            return
        }
        pullSoon(context)
    }

    fun pullSoon(context: Context) {
        val ctx = context.applicationContext
        if (!NanoMuseCloud.isSignedIn(ctx)) return
        worker.execute {
            try {
                pull(ctx)
            } catch (e: Exception) {
                AppLogger.info(TAG, "pull: ${e.message}")
            }
        }
    }

    /**
     * The account a read or a write is for, taken before the network and checked after it:
     * a sign-out or a sign-in that lands while the relay answers moves the stores to another
     * set (contract C12), and what came back must not be worn or recorded as that set's.
     */
    private fun account(context: Context): String = io.github.nanomuse.account.AccountData.key(context)

    private fun still(context: Context, account: String): Boolean =
        NanoMuseCloud.isSignedIn(context) && account(context) == account

    /** Fetch the relay's profile and wear it when it is newer. */
    private fun pull(context: Context) {
        val account = account(context)
        val light = NanoMuseCloud.profile(context, withFace = false)
        if (!still(context, account)) { AppLogger.info(TAG, "pull: the account changed meanwhile, nothing worn"); return }
        val rev = light.optInt("rev", 0)
        val known = prefs(context).getInt(KEY_REV, 0)
        // the other devices' connections come with every read, whatever the rev
        SharedConnectors.absorb(context, light)
        if (rev == 0) {
            // the relay has nothing for this account yet: this phone's look seeds it, unless
            // it is the plain default (nothing worth telling the other devices) — and so do
            // its connections, if it has any
            val name = SoulStore.load(context)?.metadata?.name.orEmpty()
            if (AvatarStore.current.value != null || AvatarStore.emoji.value != null || (name.isNotBlank() && name != "nanoMuse") || SharedConnectors.mine(context).length() > 0) push(context)
            return
        }
        if (rev <= known) {
            // the look is current; this phone's connections may still be unsaid
            if (connectorsStamp(context) != prefs(context).getString(KEY_PUSHED_CONNECTORS, null)) push(context)
            return
        }
        val name = light.optString("name").trim()
        val avatar = light.optString("avatar")
        applying = true
        try {
            if (name.isNotBlank()) {
                val cur = SoulStore.load(context)
                if (cur != null && cur.metadata.name != name) {
                    SoulStore.save(context, cur.copy(metadata = cur.metadata.copy(name = name)))
                }
            }
            val knownHash = prefs(context).getString(KEY_FACE_HASH, "").orEmpty()
            when {
                avatar == "emoji" -> {
                    io.github.nanomuse.avatar.EmojiLook.fromProfile(light)?.let(AvatarStore::adoptEmoji)
                    rememberClips(context, null)
                }
                avatar == "face" && light.optBoolean("has_face") -> {
                    val remote = light.optString("face_id")
                    if (AvatarStore.current.value == null || remote.isEmpty() || remote != knownHash) {
                        val full = NanoMuseCloud.profile(context, withFace = true)
                        if (!still(context, account)) { AppLogger.info(TAG, "pull: the account changed meanwhile, the face not worn"); return }
                        wearFace(context, full, knownHash)
                    }
                    // else: the pictures this phone already wears — only the name changed
                    // the clips another device made of this face (relay 0.29): taken instead of drawn
                    rememberClips(context, light.optJSONObject("clips"))
                    adoptClips(context, account)
                }
                // A reset from another device removes either kind of custom still.
                AvatarStore.current.value != null || AvatarStore.emoji.value != null -> { AvatarStore.reset(); rememberClips(context, null) }
                else -> rememberClips(context, null)
            }
        } finally {
            applying = false
        }
        prefs(context).edit()
            .putInt(KEY_REV, rev)
            .putString(KEY_PUSHED_FACE, faceStamp())
            .putString(KEY_PUSHED_NAME, name)
            .apply()
        AppLogger.info(TAG, "wearing rev $rev from the account ($avatar)")
    }

    private fun wearFace(context: Context, full: JSONObject, knownHash: String) {
        val face = full.optJSONObject("face") ?: return
        val idleBytes = bytes(face.optString("idle")) ?: return
        val hash = sha1(idleBytes)
        if (AvatarStore.current.value != null && hash == knownHash) return
        val idle = BitmapFactory.decodeByteArray(idleBytes, 0, idleBytes.size) ?: return
        AvatarStore.adopt(idle, full.optString("description"), full.optString("style"), "account")
        for ((key, mood) in moods) {
            if (mood == AgentMood.IDLE) continue
            val pic = decode(face.optString(key)) ?: continue
            AvatarStore.putMood(mood, pic)
        }
        prefs(context).edit().putString(KEY_FACE_HASH, hash).apply()
    }

    private fun bytes(b64: String): ByteArray? {
        if (b64.isBlank()) return null
        return runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull()
    }

    private fun sha1(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-1").digest(bytes).joinToString("") { "%02x".format(java.util.Locale.ROOT, it) }.take(12)

    private fun decode(b64: String): Bitmap? {
        val bytes = bytes(b64) ?: return null
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
    }

    // -- the push ---------------------------------------------------------------------------

    /** The name or the face changed on this phone (SOUL.md saved, a face adopted or reset). */
    fun changed() {
        val ctx = app ?: return
        if (applying || !NanoMuseCloud.isSignedIn(ctx)) return
        pending?.cancel(false)
        pending = worker.schedule({
            try {
                push(ctx)
            } catch (e: Exception) {
                AppLogger.warning(TAG, "push: ${e.message}")
            }
        }, PUSH_DELAY_MS, TimeUnit.MILLISECONDS)
    }

    /** What identifies the face worn here, so a rename does not resend the pictures. */
    private fun faceStamp(): String {
        val cur = AvatarStore.current.value ?: return AvatarStore.emoji.value?.let { "emoji:${it.emoji}:${it.color}" }.orEmpty()
        return "${cur.createdAt}:${cur.moods.keys.sortedBy { it.ordinal }.joinToString(",") { it.name }}"
    }

    /** This phone's connector entries, as a string, to tell a push with nothing new. */
    private fun connectorsStamp(context: Context): String = SharedConnectors.mine(context).toString()

    private fun push(context: Context) {
        val account = account(context)
        val name = SoulStore.load(context)?.metadata?.name?.takeIf { it.isNotBlank() } ?: "nanoMuse"
        val p = prefs(context)
        val stamp = faceStamp()
        // A phone that never pushed or pulled and wears no face has nothing to say about the
        // look: its first write must not put the dragon over a face the account already has.
        val sameFace = stamp == p.getString(KEY_PUSHED_FACE, null).orEmpty()
        val connectors = SharedConnectors.mine(context)
        val sameConnectors = connectors.toString() == p.getString(KEY_PUSHED_CONNECTORS, null)
        if (sameFace && sameConnectors && name == p.getString(KEY_PUSHED_NAME, null)) return
        val body = JSONObject()
            .put("device", io.github.nanomuse.hub.Hub.deviceId(context))
            .put("name", name.take(60))
            // which services this phone connected (contract C3): the relay keeps the other
            // devices' entries and replaces only ours; never a token
            .put("connectors", connectors)
        val cur = AvatarStore.current.value
        var sentHash: String? = null
        if (cur == null) {
            // The dragon goes up only when this phone took a face off (a reset): a rename or a
            // connector change on a phone without a face leaves the look as the relay has it
            // (relay 0.25 keeps a field that is absent). Before, every such write carried the
            // dragon and the account's face vanished from the other devices.
            io.github.nanomuse.avatar.EmojiLook.writeProfile(body, AvatarStore.emoji.value, changed = !sameFace)
        } else {
            body.put("avatar", "face")
                .put("style", cur.style.take(20))
                .put("description", cur.prompt.take(200))
            if (!sameFace) {
                val face = JSONObject()
                AvatarStore.decodeBitmap(AvatarStore.baseFile())?.let {
                    val idle = webp(it)
                    face.put("idle", Base64.encodeToString(idle, Base64.NO_WRAP))
                    sentHash = sha1(idle)
                }
                for ((key, mood) in moods) {
                    if (mood == AgentMood.IDLE) continue
                    AvatarStore.decodeBitmap(AvatarStore.moodFile(mood))?.let {
                        face.put(key, Base64.encodeToString(webp(it), Base64.NO_WRAP))
                    }
                }
                if (face.has("idle")) {
                    body.put("face", face)
                } else {
                    // a face with no picture on disk cannot be shared: the others keep theirs
                    body.remove("avatar")
                    body.remove("style")
                    body.remove("description")
                }
            }
        }
        val out = NanoMuseCloud.putProfile(context, body)
        if (!still(context, account)) { AppLogger.info(TAG, "push: the account changed meanwhile, nothing recorded"); return }
        // the reply is the merged profile: the other devices' connections, fresh
        SharedConnectors.absorb(context, out)
        val editor = p.edit()
            .putInt(KEY_REV, out.optInt("rev", p.getInt(KEY_REV, 0)))
            .putString(KEY_PUSHED_FACE, stamp)
            .putString(KEY_PUSHED_NAME, name)
            .putString(KEY_PUSHED_CONNECTORS, connectors.toString())
        if (body.has("avatar") && body.optString("avatar") != "face") editor.putString(KEY_FACE_HASH, "")
        else if (sentHash != null) editor.putString(KEY_FACE_HASH, sentHash)
        // new pictures, or no face: the relay drops the clips of the old face with them
        if (body.has("face") || (body.has("avatar") && body.optString("avatar") != "face")) editor.putString(KEY_CLIPS, "")
        editor.apply()
        AppLogger.info(TAG, "shared with the account as rev ${out.optInt("rev")}")
        // clips this phone drew of the face before the account knew the face: up they go now
        if (body.has("face")) for ((mood, file) in AvatarMotion.clips.value) shareClip(context, mood, file.readBytes())
    }

    // -- the face's clips (relay 0.29) ----------------------------------------------------

    private fun rememberClips(context: Context, clips: JSONObject?) {
        prefs(context).edit().putString(KEY_CLIPS, clips?.toString().orEmpty()).apply()
    }

    private fun accountClips(context: Context): JSONObject =
        prefs(context).getString(KEY_CLIPS, null)?.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() } ?: JSONObject()

    /**
     * The clips the account lists for the worn face, downloaded for the moods this phone has
     * none of: the file by its hash, checked against it, written whole and then put in place.
     * A bad file (another type, a hash that does not match) is left out; the mood is drawn here
     * as before when a video model allows.
     */
    private fun adoptClips(context: Context, account: String) {
        val listed = accountClips(context)
        if (listed.length() == 0 || AvatarStore.current.value == null) return
        var taken = 0
        for ((key, mood) in moods) {
            val clip = listed.optJSONObject(key) ?: continue
            if (mood !in AvatarMotion.animated) continue
            val target = AvatarMotion.clipFile(mood)
            if (target.exists() && target.length() > 0) continue
            val sha = clip.optString("sha256").lowercase()
            if (!sha.matches(Regex("[0-9a-f]{64}"))) continue
            val got = try { NanoMuseCloud.getBlob(context, sha) } catch (e: Exception) { AppLogger.warning(TAG, "clip $key: ${e.message}"); continue } ?: continue
            if (!still(context, account)) return
            val (mime, bytes) = got
            if (!mime.startsWith("video/") && !clip.optString("mime").startsWith("video/")) continue
            if (sha256(bytes) != sha) { AppLogger.warning(TAG, "clip $key: the file does not match its hash"); continue }
            val tmp = File(target.parentFile, target.name + ".tmp")
            tmp.parentFile?.mkdirs()
            tmp.writeBytes(bytes)
            if (!tmp.renameTo(target)) { target.delete(); tmp.renameTo(target) }
            taken++
        }
        if (taken > 0) {
            AvatarMotion.rescan()
            AppLogger.info(TAG, "$taken clip(s) of the face taken from the account")
        }
    }

    /**
     * A clip drawn here goes to the account for its other devices (relay 0.29): the file by its
     * hash, then the profile's `clips` with this mood added to what the account already lists.
     * Signed out, or on a relay that keeps no files, nothing is sent; the clip stays here.
     */
    fun shareClip(context: Context, mood: AgentMood, bytes: ByteArray) {
        val ctx = context.applicationContext
        if (!NanoMuseCloud.isSignedIn(ctx) || AvatarStore.current.value == null) return
        if (NanoMuseCloud.account(ctx)?.record?.on != true) return
        val key = moods.entries.firstOrNull { it.value == mood }?.key ?: return
        val account = account(ctx)
        val stamp = faceStamp()
        worker.execute {
            try {
                val sha = sha256(bytes)
                if (!NanoMuseCloud.hasBlob(ctx, sha)) NanoMuseCloud.putBlob(ctx, sha, "video/mp4", bytes)
                // the face may have moved on while the clip was drawn: then it is not this face's clip any more
                if (!still(ctx, account) || faceStamp() != stamp) return@execute
                val clips = accountClips(ctx).put(key, JSONObject().put("sha256", sha).put("mime", "video/mp4").put("bytes", bytes.size))
                val out = NanoMuseCloud.putProfile(ctx, JSONObject().put("device", io.github.nanomuse.hub.Hub.deviceId(ctx)).put("clips", clips))
                if (!still(ctx, account)) return@execute
                prefs(ctx).edit().putString(KEY_CLIPS, clips.toString()).putInt(KEY_REV, out.optInt("rev", prefs(ctx).getInt(KEY_REV, 0))).apply()
                AppLogger.info(TAG, "the $key clip shared with the account")
            } catch (e: Exception) {
                AppLogger.warning(TAG, "clip $key not shared: ${e.message}")
            }
        }
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    /** A still as WebP bytes, small enough for the relay (512 px, lossy). */
    private fun webp(bitmap: Bitmap): ByteArray {
        val out = ByteArrayOutputStream()
        @Suppress("DEPRECATION")
        val format = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Bitmap.CompressFormat.WEBP_LOSSY else Bitmap.CompressFormat.WEBP
        bitmap.compress(format, 82, out)
        return out.toByteArray()
    }
}
