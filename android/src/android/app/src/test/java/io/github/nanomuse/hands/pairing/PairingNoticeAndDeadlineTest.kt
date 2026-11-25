// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse background screen wireless setup.
package io.github.nanomuse.hands.pairing

import android.app.NotificationManager
import io.github.nanomuse.ui.hands.ChannelPlan
import io.github.nanomuse.ui.hands.ChannelSnapshot
import io.github.nanomuse.ui.hands.PairingChannel
import io.github.nanomuse.ui.hands.PairingNotice
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingNoticeAndDeadlineTest {
    private fun noticeOf(status: WirelessStatus, discovery: PairingDiscovery) =
        PairingNotice.of(status, discovery, retryReason = { "retry:$it" }, failureTitle = { "fail:$it" })

    @Test
    fun pairingNoticeStateTransitionsMatchMikaPolicy() {
        assertNull(noticeOf(WirelessStatus.NotPaired, PairingDiscovery.Idle))
        assertEquals(
            PairingNotice.EnterCode(port = null, quiet = true),
            noticeOf(WirelessStatus.NotPaired, PairingDiscovery.Searching),
        )
        assertEquals(
            PairingNotice.EnterCode(port = 37001, quiet = false),
            noticeOf(WirelessStatus.NotPaired, PairingDiscovery.Found(37001)),
        )
        assertEquals(PairingNotice.Working, noticeOf(WirelessStatus.Connecting, PairingDiscovery.Idle))
        assertEquals(PairingNotice.Done, noticeOf(WirelessStatus.Running, PairingDiscovery.Idle))
        assertEquals(
            PairingNotice.EnterCode(port = 37001, error = "retry:WrongCode"),
            noticeOf(WirelessStatus.Failed(WirelessFailure.WrongCode), PairingDiscovery.Found(37001)),
        )
        assertEquals(
            PairingNotice.Problem("fail:ConnectFailed"),
            noticeOf(WirelessStatus.Failed(WirelessFailure.ConnectFailed), PairingDiscovery.Idle),
        )
    }

    @Test
    fun delayBeforeAndRealertIntervalsRespectAutoReadAndQuietFlag() {
        val alert = PairingNotice.EnterCode(port = 37001, quiet = false)
        val quiet = PairingNotice.EnterCode(port = null, quiet = true)

        assertEquals(PairingNotice.AUTO_READ_GRACE_MS, PairingNotice.delayBefore(alert, autoRead = true))
        assertEquals(0L, PairingNotice.delayBefore(alert, autoRead = false))
        assertEquals(0L, PairingNotice.delayBefore(quiet, autoRead = true))

        assertEquals(8_000L, PairingNotice.realertAfter(alert, 0))
        assertEquals(20_000L, PairingNotice.realertAfter(alert, 1))
        assertEquals(40_000L, PairingNotice.realertAfter(alert, 2))
        assertNull(PairingNotice.realertAfter(alert, 3))
        assertNull(PairingNotice.realertAfter(quiet, 0))
        assertNull(PairingNotice.realertAfter(PairingNotice.Working, 0))
    }

    @Test
    fun followHandlesSubmittedAndRepairingFlags() {
        val submitted = PairingNotice.follow(
            status = WirelessStatus.Running,
            discovery = PairingDiscovery.Idle,
            repairing = false,
            submitted = true,
            retryReason = { "" },
            failureTitle = { "" },
        )
        assertEquals(PairingNotice.Working to false, submitted)

        val repairing = PairingNotice.follow(
            status = WirelessStatus.Running,
            discovery = PairingDiscovery.Found(37001),
            repairing = true,
            submitted = false,
            retryReason = { "" },
            failureTitle = { "" },
        )
        assertEquals(PairingNotice.EnterCode(37001) to false, repairing)

        val done = PairingNotice.follow(
            status = WirelessStatus.Running,
            discovery = PairingDiscovery.Idle,
            repairing = false,
            submitted = false,
            retryReason = { "" },
            failureTitle = { "" },
        )
        assertEquals(PairingNotice.Done to true, done)
    }

    @Test
    fun pairingChannelPlanUpgradesUneditedLegacyChannelAndRespectsUserOverride() {
        assertEquals(ChannelPlan.Create(PairingChannel.IDS.last()), PairingChannel.plan(emptyList()))

        val legacyLowered = listOf(
            ChannelSnapshot(PairingChannel.IDS.first(), NotificationManager.IMPORTANCE_DEFAULT, userSet = false),
        )
        assertEquals(ChannelPlan.Create(PairingChannel.IDS.last()), PairingChannel.plan(legacyLowered))

        val userLowered = listOf(
            ChannelSnapshot(PairingChannel.IDS.first(), NotificationManager.IMPORTANCE_DEFAULT, userSet = true),
        )
        assertEquals(
            ChannelPlan.Use(PairingChannel.IDS.first(), PairingChannelHealth.Lowered),
            PairingChannel.plan(userLowered),
        )

        val disabled = listOf(
            ChannelSnapshot(PairingChannel.IDS.last(), NotificationManager.IMPORTANCE_NONE, userSet = true),
        )
        assertEquals(
            ChannelPlan.Use(PairingChannel.IDS.last(), PairingChannelHealth.Off),
            PairingChannel.plan(disabled),
        )
    }

    @Test
    fun slidingDeadlineExtendsWindowAndReturnsTrueWhenJobFinishes() = runBlocking {
        var clock = 0L
        val deadline = SlidingDeadline(lengthMs = 80L, now = { clock })
        deadline.extend()
        val gate = CompletableDeferred<Unit>()
        val job = launch { gate.await() }
        val extender = launch {
            delay(30)
            clock = 50L
            deadline.extend()
            delay(30)
            gate.complete(Unit)
        }
        assertTrue(deadline.await(job))
        extender.join()
    }

    @Test
    fun slidingDeadlineReturnsFalseWhenExpired() = runBlocking {
        var clock = 100L
        val deadline = SlidingDeadline(lengthMs = 20L, now = { clock })
        deadline.extend()
        val never = CompletableDeferred<Unit>()
        val job = launch { never.await() }
        val advancer = launch {
            delay(25)
            clock = 200L
        }
        assertFalse(deadline.await(job))
        job.cancel()
        advancer.join()
    }
}
