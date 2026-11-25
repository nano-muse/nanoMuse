// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse background screen wireless setup.
package io.github.nanomuse.hands.pairing

/** Current state of the built-in wireless background screen helper. */
internal sealed interface WirelessStatus {
    /** No saved pairing yet (or pairing was forgotten). */
    data object NotPaired : WirelessStatus

    /** Paired before, but wireless debugging is currently off. */
    data object WirelessDebuggingOff : WirelessStatus

    /** Pairing, connecting, or starting the display helper. */
    data object Connecting : WirelessStatus

    /** Connected and ready for background screen runs. */
    data object Running : WirelessStatus

    /** Failed with a user-actionable category and recovery route. */
    data class Failed(
        val reason: WirelessFailure,
        val fix: WirelessFix = reason.defaultFix,
    ) : WirelessStatus
}

/** Failure category for wireless pairing and connection. */
internal enum class WirelessFailure(val defaultFix: WirelessFix, val duringPairing: Boolean) {
    /** Wrong or expired 6-digit pairing code. */
    WrongCode(WirelessFix.RePair, duringPairing = true),

    /** Pairing dialog closed before pairing completed, or pairing port could not be found. */
    PairingWindowClosed(WirelessFix.RePair, duringPairing = true),

    /** Wi-Fi is disconnected so local wireless debugging is unreachable. */
    NoWifi(WirelessFix.OpenWifi, duringPairing = false),

    /** Could not reach the local wireless debugging connection port. */
    ConnectFailed(WirelessFix.Retry, duringPairing = false),

    /** Device rejected the saved key (revoked or removed in Android settings). */
    AuthorizationRevoked(WirelessFix.RePair, duringPairing = false),

    /** Connected to wireless debugging, but the display helper did not hand over. */
    HelperStartFailed(WirelessFix.Retry, duringPairing = false),

    Unknown(WirelessFix.Retry, duringPairing = false),
}

internal enum class WirelessFix {
    Retry,
    RePair,
    OpenWifi,
    OpenWirelessDebugging,
}

/** Discovery state of the system "Pair device with pairing code" dialog via local mDNS. */
internal sealed interface PairingDiscovery {
    data object Idle : PairingDiscovery
    data object Searching : PairingDiscovery
    data class Found(val port: Int) : PairingDiscovery
}

/** Normalizes 6-digit pairing codes and port inputs, including spaces, dashes and full-width digits. */
internal object PairingCode {
    const val LENGTH = 6
    private const val DASHES = "-－‐‑–—"

    private fun toAsciiDigits(text: String): String =
        text.map { c -> if (c in '０'..'９') '0' + (c - '０') else c }.joinToString("")

    fun normalize(input: String): String? {
        val digits = toAsciiDigits(input.filterNot { it.isWhitespace() || it in DASHES })
        return digits.takeIf { it.length == LENGTH && it.all { c -> c in '0'..'9' } }
    }

    /** Manual port input: 1..65535. */
    fun port(input: String): Int? = toAsciiDigits(input.trim()).toIntOrNull()?.takeIf { it in 1..65535 }

    /**
     * Parses a connection port from the Wireless debugging main page. Accepts plain port numbers
     * as well as pasted "IP:port" or "IP：port" strings with whitespace or full-width digits.
     */
    fun parseConnectPort(input: String): Int? {
        val tail = input.substringAfterLast(':').substringAfterLast('：')
        return port(tail.filterNot { it.isWhitespace() })
    }

    /**
     * Parses notification reply input: either a 6-digit code ("123456" / "123 456" / "123-456")
     * or an explicit pairing port followed by whitespace and a 6-digit code ("37001 123456").
     */
    fun parseReply(input: CharSequence?): Pair<String, Int?>? {
        if (input == null || input.length > 32) return null
        val trimmed = input.toString().trim()
        normalize(trimmed)?.let { return it to null }
        val parts = trimmed.split(Regex("\\s+"), limit = 2)
        if (parts.size != 2) return null
        val parsedPort = port(parts[0]) ?: return null
        val parsedCode = normalize(parts[1]) ?: return null
        return parsedCode to parsedPort
    }
}

/** Pairing code and port read from a single system Settings window; null when absent or ambiguous. */
internal data class PairingScreenReading(val code: String?, val port: Int?)

/** Pairing attempt extracted from the screen; [port] is null when relying on mDNS discovery. */
internal data class PairingAttempt(val code: String, val port: Int?)

/**
 * Pure text parser for the Android "Pair device with pairing code" dialog.
 * Matches only the shape of the text (exact 6 digits ignoring whitespace; IPv4:port or [IPv6]:port)
 * without relying on view IDs or locale strings. Ambiguous windows return null so we fall back
 * cleanly instead of trying the wrong value.
 */
internal object PairingScreen {
    private val CODE = Regex("""\d{6}""")
    private val IPV4_PORT = Regex("""(?<![\w.:])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3}):(\d{1,5})(?![\w.:])""")
    private val IPV6_PORT = Regex("""\[[0-9A-Fa-f]*:[0-9A-Fa-f:.]*(?:%[\w.]+)?]:(\d{1,5})(?![\w.:])""")

    fun read(texts: List<String>): PairingScreenReading {
        val codes = texts.mapNotNull { t -> t.filterNot { it.isWhitespace() }.takeIf { CODE.matches(it) } }.toSet()
        val ports = texts.flatMap(::ports).toSet()
        return PairingScreenReading(codes.singleOrNull(), ports.singleOrNull())
    }

    private fun ports(text: String): List<Int> {
        val v4 = IPV4_PORT.findAll(text)
            .filter { m -> (1..4).all { m.groupValues[it].toInt() <= 255 } }
            .map { it.groupValues[5] }
        val v6 = IPV6_PORT.findAll(text).map { it.groupValues[1] }
        return (v4 + v6).mapNotNull { p -> p.toIntOrNull()?.takeIf { it in 1..65535 } }.toList()
    }

    /**
     * Decides whether [reading] should trigger an automatic pairing attempt:
     * a 6-digit code is present and untried, a port is available (from the same window or mDNS),
     * and the wireless helper is waiting to pair.
     */
    fun attempt(
        reading: PairingScreenReading,
        portFound: Boolean,
        status: WirelessStatus,
        tried: Set<String>,
    ): PairingAttempt? {
        val code = reading.code ?: return null
        if (code in tried) return null
        if (reading.port == null && !portFound) return null
        val waiting = when (status) {
            WirelessStatus.NotPaired, WirelessStatus.WirelessDebuggingOff -> true
            is WirelessStatus.Failed -> status.reason.duringPairing || status.fix == WirelessFix.RePair
            WirelessStatus.Connecting, WirelessStatus.Running -> false
        }
        return if (waiting) PairingAttempt(code, reading.port) else null
    }
}

/** Six guided steps in order, matching Mika's on-device wireless setup flow. */
internal enum class SetupStep {
    DeveloperOptions,
    UsbDebugging,
    Accessibility,
    WirelessDebugging,
    PairingCode,
    Connect,
}

internal enum class StepMark { Done, Current, Todo, Failed, Skipped }

internal enum class SetupPhase {
    Guide,
    Working,
    Success,
    Failed,
    Unavailable,
}

internal enum class PairingChannelHealth { Ready, Lowered, Off }

internal enum class PairingNotifyIssue {
    NotificationsOff,
    ChannelOff,
    NotHeadsUp,
}

internal data class SetupInputs(
    val developerOptions: Boolean,
    val wirelessDebugging: Boolean?,
    val status: WirelessStatus,
    val discovery: PairingDiscovery = PairingDiscovery.Idle,
    val notificationsAllowed: Boolean = true,
    val pairingChannel: PairingChannelHealth = PairingChannelHealth.Ready,
    val repair: Boolean = false,
    val usbDebugging: Boolean = true,
    val accessibility: Boolean = true,
    val accessibilitySkipped: Boolean = false,
    val restrictedSettings: Boolean = false,
    val confirmed: Set<SetupStep> = emptySet(),
    val revisit: SetupStep? = null,
    val wirelessMissing: Boolean = false,
    val developerSettingsMissing: Boolean = false,
)

internal data class SetupSuspect(val step: SetupStep, val unreadable: Boolean)

internal data class SetupView(
    val phase: SetupPhase,
    val marks: Map<SetupStep, StepMark>,
    val current: SetupStep?,
    val failure: WirelessStatus.Failed? = null,
    val portFound: Boolean = false,
    val notifyIssue: PairingNotifyIssue? = null,
    val autoRead: Boolean = false,
    val showAppInfo: Boolean = false,
    val suspect: SetupSuspect? = null,
    val revisiting: Boolean = false,
) {
    val needsNotifications: Boolean
        get() = notifyIssue == PairingNotifyIssue.NotificationsOff || notifyIssue == PairingNotifyIssue.ChannelOff
}

/**
 * Pure state machine for the six-step background screen setup flow.
 * Every input change recomputes the full view with no hidden intermediate state.
 */
internal object WirelessSetupFlow {
    private val SWITCH_RELATED = setOf(
        WirelessFailure.PairingWindowClosed,
        WirelessFailure.ConnectFailed,
        WirelessFailure.Unknown,
    )

    val REVISITABLE: Set<SetupStep> = SetupStep.entries.toSet() - SetupStep.Connect

    val CONFIRMABLE: Set<SetupStep> = setOf(
        SetupStep.DeveloperOptions,
        SetupStep.UsbDebugging,
        SetupStep.WirelessDebugging,
    )

    fun view(i: SetupInputs): SetupView {
        if (unavailable(i)) {
            return SetupView(SetupPhase.Unavailable, SetupStep.entries.associateWith { StepMark.Todo }, null)
        }
        return steps(i)
    }

    fun unavailable(i: SetupInputs): Boolean =
        i.developerSettingsMissing && i.wirelessMissing &&
            i.status != WirelessStatus.Running && i.status != WirelessStatus.Connecting

    private fun steps(i: SetupInputs): SetupView {
        val status = effectiveStatus(i.status, i.repair)
        if (status == WirelessStatus.Running) {
            return SetupView(SetupPhase.Success, marks(SetupStep.entries.size, i), null)
        }
        val natural = natural(i, status)
        val back = i.revisit?.takeIf { it in REVISITABLE && status != WirelessStatus.Connecting } ?: return natural
        val earlier = natural.phase == SetupPhase.Guide && natural.current != null && natural.current < back
        if (earlier) return natural
        val marks = natural.marks.mapValues { (_, m) -> if (m == StepMark.Current) StepMark.Todo else m } + (back to StepMark.Current)
        return guide(back, i).copy(marks = marks, revisiting = true)
    }

    private fun natural(i: SetupInputs, status: WirelessStatus): SetupView {
        if (blocks(SetupStep.DeveloperOptions, i)) return guide(SetupStep.DeveloperOptions, i)
        if (blocks(SetupStep.UsbDebugging, i)) return guide(SetupStep.UsbDebugging, i)
        if (blocks(SetupStep.Accessibility, i)) return guide(SetupStep.Accessibility, i)
        if (status == WirelessStatus.Connecting) return working(i)
        val wirelessConfirmed = SetupStep.WirelessDebugging in i.confirmed
        val wirelessOff = !wirelessConfirmed &&
            (i.wirelessDebugging == false || (i.wirelessDebugging == null && status == WirelessStatus.WirelessDebuggingOff))
        if (wirelessOff) return guide(SetupStep.WirelessDebugging, i)
        if (status == WirelessStatus.WirelessDebuggingOff && wirelessConfirmed && i.wirelessDebugging != true) {
            return SetupView(
                SetupPhase.Failed,
                marks(SetupStep.Connect.ordinal, i, current = SetupStep.Connect, mark = StepMark.Failed),
                SetupStep.Connect,
                suspect = SetupSuspect(SetupStep.WirelessDebugging, unreadable = i.wirelessDebugging == null),
            )
        }
        return when (status) {
            WirelessStatus.Running -> error("handled above")
            WirelessStatus.Connecting -> error("handled above")
            WirelessStatus.WirelessDebuggingOff -> working(i)
            WirelessStatus.NotPaired -> guide(SetupStep.PairingCode, i)
            is WirelessStatus.Failed -> {
                val step = if (status.reason.duringPairing || status.fix == WirelessFix.RePair) {
                    SetupStep.PairingCode
                } else {
                    SetupStep.Connect
                }
                SetupView(
                    SetupPhase.Failed,
                    marks(step.ordinal, i, current = step, mark = StepMark.Failed),
                    step,
                    failure = status,
                    portFound = step == SetupStep.PairingCode && i.discovery is PairingDiscovery.Found,
                    notifyIssue = notifyIssue(step, i),
                    autoRead = step == SetupStep.PairingCode && i.accessibility,
                    suspect = if (status.reason in SWITCH_RELATED) suspect(i) else null,
                )
            }
        }
    }

    private fun working(i: SetupInputs) = SetupView(
        SetupPhase.Working,
        marks(SetupStep.Connect.ordinal, i, current = SetupStep.Connect),
        null,
    )

    private fun blocks(step: SetupStep, i: SetupInputs): Boolean =
        detected(step, i) == false && step !in i.confirmed && !(step == SetupStep.Accessibility && i.accessibilitySkipped)

    fun detected(step: SetupStep, i: SetupInputs): Boolean? = when (step) {
        SetupStep.DeveloperOptions -> i.developerOptions
        SetupStep.UsbDebugging -> i.usbDebugging
        SetupStep.Accessibility -> i.accessibility
        SetupStep.WirelessDebugging -> i.wirelessDebugging
        SetupStep.PairingCode, SetupStep.Connect -> null
    }

    private fun suspect(i: SetupInputs): SetupSuspect? = when {
        !i.developerOptions -> SetupSuspect(SetupStep.DeveloperOptions, unreadable = false)
        i.wirelessDebugging != true -> SetupSuspect(SetupStep.WirelessDebugging, unreadable = i.wirelessDebugging == null)
        else -> null
    }

    private fun guide(step: SetupStep, i: SetupInputs) = SetupView(
        SetupPhase.Guide,
        marks(step.ordinal, i, current = step),
        step,
        portFound = step == SetupStep.PairingCode && i.discovery is PairingDiscovery.Found,
        notifyIssue = notifyIssue(step, i),
        autoRead = step == SetupStep.PairingCode && i.accessibility,
        showAppInfo = step == SetupStep.Accessibility && i.restrictedSettings,
    )

    private fun notifyIssue(step: SetupStep, i: SetupInputs): PairingNotifyIssue? = when {
        step != SetupStep.PairingCode -> null
        !i.notificationsAllowed -> PairingNotifyIssue.NotificationsOff
        i.pairingChannel == PairingChannelHealth.Off -> PairingNotifyIssue.ChannelOff
        i.pairingChannel == PairingChannelHealth.Lowered -> PairingNotifyIssue.NotHeadsUp
        else -> null
    }

    private fun marks(
        done: Int,
        i: SetupInputs,
        current: SetupStep? = null,
        mark: StepMark = StepMark.Current,
    ): Map<SetupStep, StepMark> = SetupStep.entries.associateWith { s ->
        when {
            s.ordinal < done && s == SetupStep.Accessibility && !i.accessibility && s !in i.confirmed -> StepMark.Skipped
            s.ordinal < done -> StepMark.Done
            s == current -> mark
            else -> StepMark.Todo
        }
    }

    /** During re-pairing, treat an already running or paired state as NotPaired until Connecting begins. */
    fun effectiveStatus(status: WirelessStatus, repair: Boolean): WirelessStatus =
        if (repair && status !is WirelessStatus.Connecting) WirelessStatus.NotPaired else status
}
