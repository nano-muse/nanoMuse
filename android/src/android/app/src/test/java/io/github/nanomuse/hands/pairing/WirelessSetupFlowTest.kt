// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse background screen wireless setup.
package io.github.nanomuse.hands.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WirelessSetupFlowTest {
    private fun base(
        dev: Boolean = true,
        usb: Boolean = true,
        a11y: Boolean = true,
        wireless: Boolean? = true,
        status: WirelessStatus = WirelessStatus.NotPaired,
        discovery: PairingDiscovery = PairingDiscovery.Idle,
        notifications: Boolean = true,
        channel: PairingChannelHealth = PairingChannelHealth.Ready,
        repair: Boolean = false,
        a11ySkipped: Boolean = false,
        restricted: Boolean = false,
        confirmed: Set<SetupStep> = emptySet(),
        revisit: SetupStep? = null,
        wirelessMissing: Boolean = false,
        devPageMissing: Boolean = false,
    ) = SetupInputs(
        developerOptions = dev,
        wirelessDebugging = wireless,
        status = status,
        discovery = discovery,
        notificationsAllowed = notifications,
        pairingChannel = channel,
        repair = repair,
        usbDebugging = usb,
        accessibility = a11y,
        accessibilitySkipped = a11ySkipped,
        restrictedSettings = restricted,
        confirmed = confirmed,
        revisit = revisit,
        wirelessMissing = wirelessMissing,
        developerSettingsMissing = devPageMissing,
    )

    @Test
    fun guidesThroughSixStepsInOrder() {
        val step1 = WirelessSetupFlow.view(base(dev = false, usb = false, a11y = false, wireless = false))
        assertEquals(SetupPhase.Guide, step1.phase)
        assertEquals(SetupStep.DeveloperOptions, step1.current)
        assertEquals(StepMark.Current, step1.marks[SetupStep.DeveloperOptions])

        val step2 = WirelessSetupFlow.view(base(dev = true, usb = false, a11y = false, wireless = false))
        assertEquals(SetupStep.UsbDebugging, step2.current)
        assertEquals(StepMark.Done, step2.marks[SetupStep.DeveloperOptions])

        val step3 = WirelessSetupFlow.view(base(dev = true, usb = true, a11y = false, wireless = false, restricted = true))
        assertEquals(SetupStep.Accessibility, step3.current)
        assertTrue(step3.showAppInfo)

        val step4 = WirelessSetupFlow.view(base(dev = true, usb = true, a11y = true, wireless = false))
        assertEquals(SetupStep.WirelessDebugging, step4.current)

        val step5 = WirelessSetupFlow.view(base(dev = true, usb = true, a11y = true, wireless = true, discovery = PairingDiscovery.Found(37001)))
        assertEquals(SetupStep.PairingCode, step5.current)
        assertTrue(step5.autoRead)
        assertTrue(step5.portFound)

        val step6Working = WirelessSetupFlow.view(base(status = WirelessStatus.Connecting))
        assertEquals(SetupPhase.Working, step6Working.phase)
        assertNull(step6Working.current)
        assertEquals(StepMark.Current, step6Working.marks[SetupStep.Connect])

        val done = WirelessSetupFlow.view(base(status = WirelessStatus.Running))
        assertEquals(SetupPhase.Success, done.phase)
        assertTrue(done.marks.values.all { it == StepMark.Done })
    }

    @Test
    fun skippedAccessibilityMarksSkippedAndDisablesAutoRead() {
        val v = WirelessSetupFlow.view(base(a11y = false, a11ySkipped = true))
        assertEquals(SetupPhase.Guide, v.phase)
        assertEquals(SetupStep.PairingCode, v.current)
        assertEquals(StepMark.Skipped, v.marks[SetupStep.Accessibility])
        assertFalse(v.autoRead)
    }

    @Test
    fun confirmedStepAdvancesWhenSystemToggleCannotBeRead() {
        val v = WirelessSetupFlow.view(base(dev = false, confirmed = setOf(SetupStep.DeveloperOptions)))
        assertEquals(SetupStep.PairingCode, v.current)
        assertEquals(StepMark.Done, v.marks[SetupStep.DeveloperOptions])
    }

    @Test
    fun confirmedWirelessDebuggingWithHelperOffShowsSuspectInsteadOfLooping() {
        val v = WirelessSetupFlow.view(
            base(
                wireless = false,
                status = WirelessStatus.WirelessDebuggingOff,
                confirmed = setOf(SetupStep.WirelessDebugging),
            ),
        )
        assertEquals(SetupPhase.Failed, v.phase)
        assertEquals(SetupStep.Connect, v.current)
        assertEquals(SetupSuspect(SetupStep.WirelessDebugging, unreadable = false), v.suspect)
    }

    @Test
    fun revisitShowsEarlierStepAndMarksRevisiting() {
        val v = WirelessSetupFlow.view(base(revisit = SetupStep.UsbDebugging))
        assertEquals(SetupPhase.Guide, v.phase)
        assertEquals(SetupStep.UsbDebugging, v.current)
        assertTrue(v.revisiting)
        assertEquals(StepMark.Current, v.marks[SetupStep.UsbDebugging])
    }

    @Test
    fun repairModeReturnsRunningStateToPairingStep() {
        val v = WirelessSetupFlow.view(base(status = WirelessStatus.Running, repair = true))
        assertEquals(SetupPhase.Guide, v.phase)
        assertEquals(SetupStep.PairingCode, v.current)
        assertTrue(v.autoRead)

        val connecting = WirelessSetupFlow.view(base(status = WirelessStatus.Connecting, repair = true))
        assertEquals(SetupPhase.Working, connecting.phase)
    }

    @Test
    fun reportsNotificationIssuesOnlyOnPairingStep() {
        val off = WirelessSetupFlow.view(base(notifications = false))
        assertEquals(PairingNotifyIssue.NotificationsOff, off.notifyIssue)
        assertTrue(off.needsNotifications)

        val channelOff = WirelessSetupFlow.view(base(channel = PairingChannelHealth.Off))
        assertEquals(PairingNotifyIssue.ChannelOff, channelOff.notifyIssue)
        assertTrue(channelOff.needsNotifications)

        val lowered = WirelessSetupFlow.view(base(channel = PairingChannelHealth.Lowered))
        assertEquals(PairingNotifyIssue.NotHeadsUp, lowered.notifyIssue)
        assertFalse(lowered.needsNotifications)

        val onDevStep = WirelessSetupFlow.view(base(dev = false, notifications = false))
        assertNull(onDevStep.notifyIssue)
    }

    @Test
    fun failuresMapToPairingOrConnectStepWithSuspectWhenAppropriate() {
        val wrongCode = WirelessSetupFlow.view(base(status = WirelessStatus.Failed(WirelessFailure.WrongCode)))
        assertEquals(SetupPhase.Failed, wrongCode.phase)
        assertEquals(SetupStep.PairingCode, wrongCode.current)
        assertNull(wrongCode.suspect)

        val revoked = WirelessSetupFlow.view(base(status = WirelessStatus.Failed(WirelessFailure.AuthorizationRevoked)))
        assertEquals(SetupStep.PairingCode, revoked.current)

        val connectFailed = WirelessSetupFlow.view(
            base(
                wireless = null,
                status = WirelessStatus.Failed(WirelessFailure.ConnectFailed),
            ),
        )
        assertEquals(SetupStep.Connect, connectFailed.current)
        assertEquals(SetupSuspect(SetupStep.WirelessDebugging, unreadable = true), connectFailed.suspect)
    }

    @Test
    fun unavailableWhenBothDeveloperPageAndWirelessSettingMissing() {
        val v = WirelessSetupFlow.view(base(wirelessMissing = true, devPageMissing = true))
        assertEquals(SetupPhase.Unavailable, v.phase)
        assertNull(v.current)
    }
}
