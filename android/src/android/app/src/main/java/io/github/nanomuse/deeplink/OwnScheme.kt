package io.github.nanomuse.deeplink

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * The two names of the app's own links.
 *
 * Inside the app a link is `minis://…`: that is upstream's vocabulary, shared with the sandbox
 * and with the model (`minis://attachments/x.png`, `minis://settings/soul`, the system prompt,
 * every saved conversation), and it stays. What the app registers with Android is `nanomuse`
 * (`AndroidManifest.xml`), so a phone that also has OpenMinis installed never sees a chooser
 * for the other app's links, and ours never land there. A `nanomuse://…` link coming in from
 * outside means the same as its `minis://…` form; a link the app opens on itself goes to its own
 * activity by name, never through the system's resolution of a scheme.
 */
object OwnScheme {
    /** What the manifest registers: the name other apps and web pages can address. */
    const val SYSTEM = "nanomuse"

    /** Upstream's in-app vocabulary; never registered with the system. */
    const val INTERNAL = "minis"

    /** The activity that takes every deep link, named so no scheme resolution is involved. */
    const val ACTIVITY = "com.openminis.app.MainActivity"

    /** Whether [scheme] is one of the app's own two names. */
    fun isOwn(scheme: String?): Boolean {
        val s = scheme?.lowercase() ?: return false
        return s == INTERNAL || s == SYSTEM
    }

    /** `nanomuse://x` read as `minis://x`; any other scheme is left as written. */
    fun internal(scheme: String?): String? = if (scheme?.lowercase() == SYSTEM) INTERNAL else scheme

    /** The `minis://…` form of [url] when it is a `nanomuse://…` link; otherwise [url] itself. */
    fun internalUrl(url: String): String {
        val prefix = "$SYSTEM://"
        return if (url.regionMatches(0, prefix, 0, prefix.length, ignoreCase = true)) {
            "$INTERNAL://" + url.substring(prefix.length)
        } else {
            url
        }
    }

    /** A VIEW intent for [uri] addressed to the app's own activity; [flags] as the caller needs. */
    fun intent(context: Context, uri: Uri, flags: Int = Intent.FLAG_ACTIVITY_NEW_TASK): Intent =
        Intent(Intent.ACTION_VIEW, uri).apply {
            setClassName(context.packageName, ACTIVITY)
            addFlags(flags)
        }
}
