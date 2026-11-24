package io.github.nanomuse.ui.hands

import android.app.KeyguardManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.RemoteInput
import com.openminis.app.R
import io.github.nanomuse.hands.HandsReplayAccess
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID

internal class HandsPairingReply(val code: String, val port: Int?) {
    companion object {
        fun parse(input: CharSequence?): HandsPairingReply? {
            if (input == null || input.length > 24) return null
            val match = Regex("(?:(\\d{1,5})[ \\t]+)?([0-9]{6})").matchEntire(input.trim()) ?: return null
            val rawPort = match.groupValues[1]
            val port = rawPort.takeIf(String::isNotEmpty)?.toIntOrNull()
            if (rawPort.isNotEmpty() && (port == null || port !in 1..65535)) return null
            return HandsPairingReply(match.groupValues[2], port)
        }
    }
}

/** The reply is delivered to the already-open settings coroutine. No code or job survives
 * process death, leaving setup, cancellation, or an account change. */
internal object HandsPairingNotice {
    class Unavailable : Exception()
    private const val CHANNEL = "nanomuse-hands-pairing"
    private const val REPLY = "io.github.nanomuse.hands.PAIRING_REPLY"
    private const val CANCEL = "io.github.nanomuse.hands.PAIRING_CANCEL"
    private const val INPUT = "pair"
    private const val WINDOW_MS = 120_000L
    private class Request(val ticket: HandsReplayAccess.Ticket, ttl: Long) {
        val nonce = UUID.randomUUID().toString()
        val expires = SystemClock.elapsedRealtime() + ttl
        val response = CompletableDeferred<HandsPairingReply?>()
    }
    private var current: Request? = null

    suspend fun await(context: Context, timeoutMillis: Long = WINDOW_MS, onPosted: () -> Unit): HandsPairingReply? {
        val ttl = timeoutMillis.coerceIn(1, WINDOW_MS)
        val app = context.applicationContext
        val manager = app.getSystemService(NotificationManager::class.java)
        if (!manager.areNotificationsEnabled()) throw Unavailable()
        manager.createNotificationChannel(NotificationChannel(CHANNEL, app.getString(R.string.nm_hands_wireless_title),
            NotificationManager.IMPORTANCE_HIGH).apply { lockscreenVisibility = NotificationCompat.VISIBILITY_SECRET })
        if (manager.getNotificationChannel(CHANNEL)?.importance == NotificationManager.IMPORTANCE_NONE) throw Unavailable()
        val request = Request(HandsReplayAccess.ticket(app) ?: throw Unavailable(), ttl)
        synchronized(this) {
            current?.response?.complete(null)
            current = request
        }
        fun intent(action: String, flag: Int) = PendingIntent.getBroadcast(app, 0,
            Intent(app, HandsPairingReplyReceiver::class.java).setAction(action)
                .setData(Uri.fromParts("nanomuse-hands-pair", request.nonce, null)),
            PendingIntent.FLAG_ONE_SHOT or flag)
        val reply = intent(REPLY, PendingIntent.FLAG_MUTABLE)
        val cancel = intent(CANCEL, PendingIntent.FLAG_IMMUTABLE)
        try {
            val label = app.getString(R.string.nm_hands_wireless_code)
            val explanation = app.getString(R.string.nm_hands_wireless_notification_help)
            val action = NotificationCompat.Action.Builder(0, label, reply)
                .setAuthenticationRequired(true).setAllowGeneratedReplies(false)
                .addRemoteInput(RemoteInput.Builder(INPUT).setLabel(label).build()).build()
            val notification = NotificationCompat.Builder(app, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_nanomuse).setContentTitle(app.getString(R.string.nm_hands_wireless_pair))
                .setContentText(explanation).setStyle(NotificationCompat.BigTextStyle().bigText(explanation))
                .setVisibility(NotificationCompat.VISIBILITY_SECRET).setLocalOnly(true)
                .setAllowSystemGeneratedContextualActions(false).setOnlyAlertOnce(true)
                .setDeleteIntent(cancel).setTimeoutAfter(ttl).addAction(action).build()
            try { manager.notify(request.nonce, 1, notification) }
            catch (_: SecurityException) { throw Unavailable() }
            onPosted()
            return withTimeoutOrNull(ttl) { request.response.await() }
        } finally {
            synchronized(this) { if (current === request) current = null }
            reply.cancel()
            cancel.cancel()
            manager.cancel(request.nonce, 1)
        }
    }

    @Synchronized fun receive(context: Context, intent: Intent) {
        val request = current ?: return
        if (intent.data?.schemeSpecificPart != request.nonce || intent.action !in listOf(REPLY, CANCEL)) return
        current = null
        val allowed = intent.action == REPLY && SystemClock.elapsedRealtime() < request.expires &&
            !context.getSystemService(KeyguardManager::class.java).isDeviceLocked &&
            HandsReplayAccess.current(context, request.ticket)
        val input = if (allowed) RemoteInput.getResultsFromIntent(intent)?.getCharSequence(INPUT) else null
        request.response.complete(HandsPairingReply.parse(input))
    }
}

class HandsPairingReplyReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = HandsPairingNotice.receive(context, intent)
}
