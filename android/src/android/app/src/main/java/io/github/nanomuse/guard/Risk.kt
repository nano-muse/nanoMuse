package io.github.nanomuse.guard

/**
 * What a tool call is about to do to the world. Ordered by how much it matters:
 * a command that both installs and pays is a payment.
 */
enum class RiskClass {
    /** Reads, computes, writes inside the sandbox. Runs without a word. */
    SAFE,
    /** Fetches software into the sandbox. Runs, and the user is told. */
    INSTALL,
    /** Removes the user's files or history. Asks. */
    DESTRUCTIVE,
    /** Sends something out: a message, a mail, a push, a form. Asks. */
    OUTBOUND,
    /**
     * Another device of the account running, reading or writing something on this phone over
     * the hub (0.1.31). Asks the person holding the phone; "always for that device" may be
     * remembered.
     */
    REMOTE,
    /**
     * Moves money. Asks at the moment of paying, every time — unless the user chose, on the
     * card and confirmed with the phone's screen lock, to remember it for that one app or site.
     */
    MONEY;

    /** The danger tier, which is how Settings → Permissions groups what was remembered. */
    val tier: RiskTier
        get() = when (this) {
            SAFE, INSTALL -> RiskTier.NOTICE
            DESTRUCTIVE, OUTBOUND, REMOTE -> RiskTier.CONFIRM
            MONEY -> RiskTier.HIGHEST
        }
}

/**
 * Three tiers of danger, from the user's point of view:
 * - [NOTICE]: runs, and the user is told (installs).
 * - [CONFIRM]: asks first; "for this chat" or "always for X" may be remembered from the card.
 * - [HIGHEST]: asks at the critical moment every time; remembering is a deliberate act — one
 *   object only, confirmed with the screen lock — and shows first on the permissions page.
 */
enum class RiskTier { NOTICE, CONFIRM, HIGHEST }

/** Where a request came from; the card words itself differently for each. */
enum class GuardKind {
    SHELL,
    BROWSER,
    /** A tap on the phone's own screen, by the hands (0.1.12). [RiskRequest.pageUrl] carries the app. */
    SCREEN,
    /** A shell command or a file change on a paired computer (0.1.13). [RiskRequest.pageUrl] carries its name. */
    COMPUTER,
    /** Another device doing something on this phone (0.1.31). [RiskRequest.pageUrl] carries its name. */
    DEVICE,
    /**
     * A step of a scheduled task on a computer of the account, asked here because nobody may be
     * at that computer (a pushed `approval` event, docs/hub.md). [RiskRequest.pageUrl] carries the
     * computer's name, [RiskRequest.elementText] the task's title, [RiskRequest.app] the app.
     */
    SCHEDULED,
}

/**
 * The verdict on one call. [target] is the object a standing grant would be bound to — a
 * folder, a host, a recipient — so "always allow for X" means exactly X and nothing wider.
 * [warnings] are the always-ask flags (`rm -rf /`, `curl | sh`, force push): a call that
 * carries one is never waved through by a grant and offers none.
 */
data class RiskAssessment(
    val riskClass: RiskClass,
    val reason: String,
    val target: String? = null,
    val warnings: List<String> = emptyList(),
    /** False for a legacy remote event that has no complete structured grant target. */
    val rememberable: Boolean = true,
    /** Exact remote wire class, kept only to prevent aliases from sharing a grant. */
    val wireRisk: String? = null,
) {
    val needsApproval: Boolean
        get() = warnings.isNotEmpty() || riskClass == RiskClass.DESTRUCTIVE ||
            riskClass == RiskClass.OUTBOUND || riskClass == RiskClass.REMOTE || riskClass == RiskClass.MONEY

    companion object {
        val SAFE = RiskAssessment(RiskClass.SAFE, "")

        /** The stronger of two verdicts, keeping every warning. */
        fun merge(a: RiskAssessment, b: RiskAssessment): RiskAssessment {
            val top = if (b.riskClass.ordinal > a.riskClass.ordinal) b else a
            val reasons = listOf(a, b).map { it.reason }.filter { it.isNotBlank() }.distinct()
            return top.copy(
                reason = reasons.take(3).joinToString("; "),
                warnings = (a.warnings + b.warnings).distinct(),
                rememberable = a.rememberable && b.rememberable,
                wireRisk = a.wireRisk.takeIf { it == b.wireRisk },
            )
        }
    }
}
