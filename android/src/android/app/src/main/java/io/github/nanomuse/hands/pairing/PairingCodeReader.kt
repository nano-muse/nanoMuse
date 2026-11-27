// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse local wireless pairing.
package io.github.nanomuse.hands.pairing

import android.content.Context
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import com.openminis.app.accessibility.MinisAccessibilityService
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.merge
import kotlinx.coroutines.flow.onStart

/**
 * Reads the 6-digit pairing code and port directly from Android's system pairing dialog while
 * wireless pairing setup is active, so the user does not have to type the code manually.
 *
 * Runs only while [HandsPairingCoordinator] is watching, inspects only the resolved system
 * Settings app on the default display, and never logs the pairing code. If the accessibility
 * service is off, this does nothing and pairing falls back to the notification input.
 */
internal object PairingCodeReader {
    private const val SETTLE_MS = 300L
    private const val MAX_NODES = 400
    private const val TAG = "HandsPairing"

    suspend fun run(
        context: Context,
        isRepairing: () -> Boolean,
        onAttempt: suspend (code: String, port: Int?) -> Unit,
    ) {
        val settings = DeveloperSettings.settingsPackage(context.packageManager) ?: run {
            Log.w(TAG, "no system settings app found; skipping automatic code reading")
            return
        }
        val tried = mutableSetOf<String>()
        var lastSummary: String? = null
        MinisAccessibilityService.instanceFlow.collectLatest { service ->
            if (service == null) {
                Log.i(TAG, "accessibility service not running; pairing code goes through notification")
                return@collectLatest
            }
            Log.i(TAG, "watching system settings pairing window for $settings")
            merge(
                settingsEvents(service, settings),
                HandsWireless.pairingDiscovery.filter { it is PairingDiscovery.Found }.map { Unit },
            )
                .onStart { emit(Unit) }
                .conflate()
                .collect {
                    delay(SETTLE_MS)
                    val portFound = HandsWireless.pairingDiscovery.value is PairingDiscovery.Found
                    val status = WirelessSetupFlow.effectiveStatus(HandsWireless.status.value, isRepairing())
                    val readings = readSettingsWindows(service, settings)
                    val summary = "${readings.size} window(s), code=${readings.any { it.code != null }}, " +
                        "port=${readings.firstNotNullOfOrNull { it.port }}, portFound=$portFound, status=$status"
                    if (summary != lastSummary) {
                        Log.i(TAG, "saw $summary")
                        lastSummary = summary
                    }
                    val attempt = readings.firstNotNullOfOrNull {
                        PairingScreen.attempt(it, portFound, status, tried)
                    } ?: return@collect
                    Log.i(TAG, "read pairing code from system dialog; starting automatic pairing")
                    tried += attempt.code
                    onAttempt(attempt.code, attempt.port)
                }
        }
    }

    private fun settingsEvents(service: MinisAccessibilityService, settingsPackage: String) = callbackFlow {
        val listener: (MinisAccessibilityService.RecordedEvent) -> Unit = { event ->
            if (event.packageName == settingsPackage) {
                trySend(Unit)
            }
        }
        service.addEventListener(listener)
        awaitClose { service.removeEventListener(listener) }
    }

    /**
     * Reads each system Settings window separately so the pairing code and IP:port must come from
     * the same dialog window rather than mixing the pairing dialog with the underlying settings page.
     */
    private fun readSettingsWindows(
        service: MinisAccessibilityService,
        settingsPackage: String,
    ): List<PairingScreenReading> = service.defaultDisplayWindows().mapNotNull { window ->
        val root = runCatching { window.root }.getOrNull() ?: return@mapNotNull null
        if (root.packageName?.toString() != settingsPackage) return@mapNotNull null
        PairingScreen.read(collectTexts(root))
    }

    private fun collectTexts(root: AccessibilityNodeInfo): List<String> {
        val out = mutableListOf<String>()
        val queue = ArrayDeque(listOf(root))
        var seen = 0
        while (queue.isNotEmpty() && seen++ < MAX_NODES) {
            val node = queue.removeFirst()
            node.text?.toString()?.takeIf { it.isNotBlank() }?.let(out::add)
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let(queue::add)
            }
        }
        return out
    }
}
