// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse local wireless pairing.
package io.github.nanomuse.ui.hands

import android.content.Context
import android.os.SystemClock
import android.util.Log
import com.openminis.app.R
import com.openminis.app.accessibility.MinisAccessibilityService
import io.github.nanomuse.hands.pairing.HandsWireless
import io.github.nanomuse.hands.pairing.PairingCode
import io.github.nanomuse.hands.pairing.PairingCodeReader
import io.github.nanomuse.hands.pairing.SlidingDeadline
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.transformWhile
import kotlinx.coroutines.launch

/**
 * Process-level coordinator for wireless pairing: discovers the system pairing dialog via mDNS,
 * reads the 6-digit code automatically via [PairingCodeReader] when accessibility is on,
 * posts heads-up RemoteInput notifications as fallback, submits the code to [HandsWireless],
 * and keeps running while the user switches to Android Settings.
 */
internal object HandsPairingCoordinator {
    private const val TAG = "HandsPairing"
    private const val WINDOW_MS = 10 * 60_000L

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private var watch: Job? = null
    private val deadline = SlidingDeadline(WINDOW_MS) { SystemClock.elapsedRealtime() }

    @Volatile
    private var shown: PairingNotice? = null

    private val _repairing = MutableStateFlow(false)
    val repairing: StateFlow<Boolean> = _repairing.asStateFlow()

    @Volatile
    private var submitted = false

    fun startRepair() {
        _repairing.value = true
    }

    fun cancelRepair() {
        _repairing.value = false
    }

    /**
     * Runs one pairing attempt. Uses UNDISPATCHED so [HandsWireless.startPairing] transitions
     * status to Connecting before clearing [_repairing] and [submitted].
     */
    suspend fun pair(context: Context, code: String, port: Int?) = coroutineScope {
        val app = context.applicationContext
        Log.i(TAG, "starting wireless pairing with ${if (port != null) "port $port" else "discovered port"}")
        val job = launch(start = CoroutineStart.UNDISPATCHED) {
            HandsWireless.startPairing(app, code, port)
        }
        _repairing.value = false
        submitted = false
        job.join()
    }

    /** Starts watching for pairing, or extends the 10-minute deadline if already watching. */
    @Synchronized
    fun begin(context: Context) {
        val app = context.applicationContext
        deadline.extend()
        HandsWireless.startDiscovery(app)
        if (watch?.isActive == true) {
            Log.i(TAG, "pairing watch already active; deadline extended")
            return
        }
        Log.i(
            TAG,
            "watching for pairing (status=${HandsWireless.status.value}, accessibility=${MinisAccessibilityService.getInstance() != null})",
        )
        watch = scope.launch {
            val reader = launch {
                PairingCodeReader.run(
                    context = app,
                    isRepairing = { _repairing.value },
                    onAttempt = { code, port -> pair(app, code, port) },
                )
            }
            val notices = launch {
                combine(HandsWireless.status, HandsWireless.pairingDiscovery, _repairing) { _, _, _ ->
                    val discovery = HandsWireless.pairingDiscovery.value
                    val pending = submitted
                    val repairingNow = _repairing.value
                    PairingNotice.follow(
                        status = HandsWireless.status.value,
                        discovery = discovery,
                        repairing = repairingNow,
                        submitted = pending,
                        retryReason = { HandsPairingNotice.retryReason(app, it) },
                        failureTitle = { HandsPairingNotice.failureTitle(app, it) },
                    )
                }
                    .distinctUntilChanged()
                    .transformWhile {
                        emit(it.first)
                        !it.second
                    }
                    .collectLatest { notice ->
                        notice?.let { post(app, it) }
                    }
            }
            if (!deadline.await(notices)) {
                Log.i(TAG, "stopped watching after ${WINDOW_MS / 60_000} min without pairing")
                notices.cancel()
                cancelNotice(app)
            }
            reader.cancel()
            HandsWireless.stopDiscovery()
        }
    }

    private suspend fun post(app: Context, notice: PairingNotice) {
        delay(PairingNotice.delayBefore(notice, autoRead = MinisAccessibilityService.getInstance() != null))
        show(app, notice)
        var sent = 0
        while (true) {
            delay(PairingNotice.realertAfter(notice, sent) ?: return)
            if (shown != notice) return
            show(app, notice)
            sent++
        }
    }

    private fun show(app: Context, notice: PairingNotice) {
        shown = notice
        HandsPairingNotice.show(app, notice)
    }

    private fun cancelNotice(app: Context) {
        shown = null
        HandsPairingNotice.cancel(app)
    }

    @Synchronized
    fun end(context: Context) {
        watch?.cancel()
        watch = null
        _repairing.value = false
        submitted = false
        HandsWireless.stopDiscovery()
        cancelNotice(context.applicationContext)
    }

    /**
     * Submits a pairing code entered from the notification or the manual fallback form.
     * Invalid codes show an inline prompt in the notification and return null.
     */
    fun submit(context: Context, raw: String, port: Int?): Job? {
        val app = context.applicationContext
        val code = PairingCode.normalize(raw)
        if (code == null) {
            show(app, PairingNotice.EnterCode(port, app.getString(R.string.nm_hands_wireless_notify_code_invalid)))
            return null
        }
        submitted = true
        begin(app)
        show(app, PairingNotice.Working)
        return scope.launch { pair(app, code, port) }
    }
}
