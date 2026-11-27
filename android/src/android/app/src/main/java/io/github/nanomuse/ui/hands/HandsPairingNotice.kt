// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse local wireless pairing.
package io.github.nanomuse.ui.hands

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.openminis.app.MainActivity
import com.openminis.app.R
import io.github.nanomuse.hands.HandsReplayAccess
import io.github.nanomuse.hands.pairing.PairingChannelHealth
import io.github.nanomuse.hands.pairing.PairingCode
import io.github.nanomuse.hands.pairing.PairingDiscovery
import io.github.nanomuse.hands.pairing.WirelessFailure
import io.github.nanomuse.hands.pairing.WirelessFix
import io.github.nanomuse.hands.pairing.WirelessSetupFlow
import io.github.nanomuse.hands.pairing.WirelessStatus
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** State of the wireless pairing notification at a point in time. */
internal sealed interface PairingNotice {
    /**
     * Inline-reply notification asking for the 6-digit pairing code.
     * When [quiet] is true, it is posted silently to the shade before the pairing dialog is found
     * so it remains available even if Android freezes the background app after switching to Settings.
     */
    data class EnterCode(
        val port: Int?,
        val error: String? = null,
        val quiet: Boolean = false,
    ) : PairingNotice

    data object Working : PairingNotice
    data object Done : PairingNotice
    data class Problem(val title: String) : PairingNotice

    companion object {
        /** Grace window before popping up the notification while accessibility auto-read is active. */
        const val AUTO_READ_GRACE_MS = 5_000L

        /** Re-alert intervals if the user has not replied yet (at most [MAX_REALERTS] times). */
        val REALERT_MS = listOf(8_000L, 20_000L, 40_000L)
        val MAX_REALERTS = REALERT_MS.size

        fun of(
            status: WirelessStatus,
            discovery: PairingDiscovery,
            retryReason: (WirelessFailure) -> String,
            failureTitle: (WirelessFailure) -> String,
        ): PairingNotice? {
            val port = (discovery as? PairingDiscovery.Found)?.port
            return when (status) {
                WirelessStatus.Running -> Done
                WirelessStatus.Connecting -> Working
                is WirelessStatus.Failed -> when {
                    status.reason.duringPairing -> EnterCode(port, retryReason(status.reason))
                    status.fix == WirelessFix.RePair && port != null -> EnterCode(port)
                    status.fix == WirelessFix.RePair && discovery == PairingDiscovery.Searching -> EnterCode(null, quiet = true)
                    else -> Problem(failureTitle(status.reason))
                }
                WirelessStatus.NotPaired, WirelessStatus.WirelessDebuggingOff -> when (discovery) {
                    is PairingDiscovery.Found -> EnterCode(discovery.port)
                    PairingDiscovery.Searching -> EnterCode(null, quiet = true)
                    PairingDiscovery.Idle -> null
                }
            }
        }

        fun delayBefore(notice: PairingNotice, autoRead: Boolean): Long =
            if (notice is EnterCode && autoRead && !notice.quiet) AUTO_READ_GRACE_MS else 0L

        fun realertAfter(notice: PairingNotice, sent: Int): Long? =
            if (notice is EnterCode && !notice.quiet) REALERT_MS.getOrNull(sent) else null

        fun follow(
            status: WirelessStatus,
            discovery: PairingDiscovery,
            repairing: Boolean,
            submitted: Boolean,
            retryReason: (WirelessFailure) -> String,
            failureTitle: (WirelessFailure) -> String,
        ): Pair<PairingNotice?, Boolean> =
            if (submitted) {
                Working to false
            } else {
                of(WirelessSetupFlow.effectiveStatus(status, repairing), discovery, retryReason, failureTitle) to
                    (status == WirelessStatus.Running && !repairing)
            }
    }
}

/** Snapshot of an existing Android notification channel. */
internal data class ChannelSnapshot(val id: String, val importance: Int, val userSet: Boolean)

/** Decision for creating or reusing the high-priority wireless pairing notification channel. */
internal sealed interface ChannelPlan {
    val id: String
    val health: PairingChannelHealth

    data class Create(override val id: String) : ChannelPlan {
        override val health: PairingChannelHealth get() = PairingChannelHealth.Ready
    }

    data class Use(override val id: String, override val health: PairingChannelHealth) : ChannelPlan
}

/**
 * Pure channel selector: creates a high-priority channel for heads-up pairing prompts,
 * upgrades unedited legacy channels by rotating the channel ID, and respects user overrides.
 */
internal object PairingChannel {
    val IDS = listOf("nanomuse-hands-pairing", "nanomuse-hands-pairing-alert")

    fun plan(existing: List<ChannelSnapshot>): ChannelPlan {
        val current = existing.filter { it.id in IDS }.maxByOrNull { IDS.indexOf(it.id) }
            ?: return ChannelPlan.Create(IDS.last())
        val newer = IDS.getOrNull(IDS.indexOf(current.id) + 1)
        return when {
            current.importance == NotificationManager.IMPORTANCE_NONE -> ChannelPlan.Use(current.id, PairingChannelHealth.Off)
            current.importance >= NotificationManager.IMPORTANCE_HIGH -> ChannelPlan.Use(current.id, PairingChannelHealth.Ready)
            current.userSet -> ChannelPlan.Use(current.id, PairingChannelHealth.Lowered)
            newer != null -> ChannelPlan.Create(newer)
            else -> ChannelPlan.Use(current.id, PairingChannelHealth.Lowered)
        }
    }
}

/** Posts and clears wireless pairing notifications with inline RemoteInput reply. */
internal object HandsPairingNotice {
    const val KEY_CODE = "pairing_code"
    const val EXTRA_PORT = "pairing_port"
    private const val NOTIFICATION_ID = 4401
    private const val DONE_TIMEOUT_MS = 8_000L
    private const val INPUT_TIMEOUT_MS = 10 * 60_000L
    private const val QUIET_GROUP = "nanomuse_hands_pairing_quiet"
    private const val TAG = "HandsPairing"

    fun ensureChannel(context: Context): ChannelPlan {
        val app = context.applicationContext
        val nm = app.getSystemService(NotificationManager::class.java)
        val existing = PairingChannel.IDS.mapNotNull { id ->
            nm.getNotificationChannel(id)?.let { ChannelSnapshot(id, it.importance, it.hasUserSetImportance()) }
        }
        val plan = PairingChannel.plan(existing)
        if (plan is ChannelPlan.Create) {
            nm.createNotificationChannel(
                NotificationChannel(
                    plan.id,
                    app.getString(R.string.nm_hands_wireless_channel_name),
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    enableVibration(true)
                    setShowBadge(false)
                },
            )
        }
        PairingChannel.IDS.filter { it != plan.id }.forEach { id ->
            if (nm.getNotificationChannel(id) != null) nm.deleteNotificationChannel(id)
        }
        return plan
    }

    fun notificationsEnabled(context: Context): Boolean =
        context.applicationContext.getSystemService(NotificationManager::class.java).areNotificationsEnabled()

    fun show(context: Context, notice: PairingNotice) {
        val app = context.applicationContext
        val nm = app.getSystemService(NotificationManager::class.java)
        val channel = ensureChannel(app).id
        val open = PendingIntent.getActivity(
            app,
            0,
            Intent(app, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = Notification.Builder(app, channel)
            .setSmallIcon(R.drawable.ic_stat_nanomuse)
            .setCategory(Notification.CATEGORY_STATUS)
            .setLocalOnly(true)
            .setContentIntent(open)
        when (notice) {
            is PairingNotice.EnterCode -> {
                val input = RemoteInput.Builder(KEY_CODE)
                    .setLabel(app.getString(R.string.nm_hands_wireless_notify_input))
                    .setAllowFreeFormInput(true)
                    .build()
                val replyIntent = Intent(app, HandsPairingReplyReceiver::class.java).apply {
                    notice.port?.let { putExtra(EXTRA_PORT, it) }
                }
                val reply = PendingIntent.getBroadcast(
                    app,
                    1,
                    replyIntent,
                    PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
                val action = Notification.Action.Builder(
                    null,
                    app.getString(R.string.nm_hands_wireless_notify_action),
                    reply,
                )
                    .addRemoteInput(input)
                    .setAllowGeneratedReplies(false)
                    .setSemanticAction(Notification.Action.SEMANTIC_ACTION_REPLY)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    action.setAuthenticationRequired(false)
                }
                val text = notice.error ?: app.getString(R.string.nm_hands_wireless_notify_enter_text)
                builder
                    .setContentTitle(app.getString(R.string.nm_hands_wireless_notify_enter_title))
                    .setContentText(text)
                    .setStyle(Notification.BigTextStyle().bigText(text))
                    .setOngoing(true)
                    .setOnlyAlertOnce(false)
                    .setTimeoutAfter(INPUT_TIMEOUT_MS)
                    .addAction(action.build())
                if (notice.port != null) {
                    builder.setSubText(app.getString(R.string.nm_hands_wireless_notify_window_found))
                }
            }
            PairingNotice.Working -> builder
                .setContentTitle(app.getString(R.string.nm_hands_wireless_notify_working))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setProgress(0, 0, true)
            PairingNotice.Done -> builder
                .setContentTitle(app.getString(R.string.nm_hands_wireless_notify_done_title))
                .setContentText(app.getString(R.string.nm_hands_wireless_notify_done_text))
                .setAutoCancel(true)
                .setOnlyAlertOnce(true)
                .setTimeoutAfter(DONE_TIMEOUT_MS)
            is PairingNotice.Problem -> builder
                .setContentTitle(notice.title)
                .setContentText(app.getString(R.string.nm_hands_wireless_notify_problem))
                .setAutoCancel(true)
        }
        if (notice is PairingNotice.EnterCode && notice.quiet) {
            builder
                .setOnlyAlertOnce(true)
                .setGroup(QUIET_GROUP)
                .setGroupAlertBehavior(Notification.GROUP_ALERT_SUMMARY)
        }
        runCatching { nm.notify(NOTIFICATION_ID, builder.build()) }
            .onFailure { Log.w(TAG, "pairing notification not posted", it) }
    }

    fun cancel(context: Context) {
        context.applicationContext.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
    }

    fun retryReason(context: Context, reason: WirelessFailure): String = when (reason) {
        WirelessFailure.WrongCode -> context.getString(R.string.nm_hands_wireless_notify_retry_code)
        WirelessFailure.PairingWindowClosed -> context.getString(R.string.nm_hands_wireless_notify_retry_window)
        else -> failureTitle(context, reason)
    }

    fun failureTitle(context: Context, reason: WirelessFailure): String = when (reason) {
        WirelessFailure.WrongCode -> context.getString(R.string.nm_hands_wireless_fail_wrong_code)
        WirelessFailure.PairingWindowClosed -> context.getString(R.string.nm_hands_wireless_fail_window_closed)
        WirelessFailure.NoWifi -> context.getString(R.string.nm_hands_wireless_fail_no_wifi)
        WirelessFailure.ConnectFailed -> context.getString(R.string.nm_hands_wireless_fail_connect)
        WirelessFailure.AuthorizationRevoked -> context.getString(R.string.nm_hands_wireless_fail_revoked)
        WirelessFailure.HelperStartFailed -> context.getString(R.string.nm_hands_wireless_fail_helper)
        WirelessFailure.Unknown -> context.getString(R.string.nm_hands_wireless_fail_unknown)
    }
}

/**
 * Receiver for the inline RemoteInput action on the pairing notification.
 * Uses [goAsync] up to [HOLD_MS] so Android does not freeze the background process mid-pairing.
 */
class HandsPairingReplyReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val raw = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(HandsPairingNotice.KEY_CODE) ?: return
        if (HandsReplayAccess.ticket(context) == null) return
        val extraPort = intent.getIntExtra(HandsPairingNotice.EXTRA_PORT, -1).takeIf { it in 1..65535 }
        val parsed = PairingCode.parseReply(raw)
        val job = if (parsed != null) {
            HandsPairingCoordinator.submit(context, parsed.first, parsed.second ?: extraPort)
        } else {
            HandsPairingCoordinator.submit(context, raw.toString(), extraPort)
        } ?: return
        val pending = goAsync()
        HandsPairingCoordinator.scope.launch {
            try {
                withTimeoutOrNull(HOLD_MS) { job.join() }
            } finally {
                pending.finish()
            }
        }
    }

    private companion object {
        const val HOLD_MS = 8_000L
    }
}
