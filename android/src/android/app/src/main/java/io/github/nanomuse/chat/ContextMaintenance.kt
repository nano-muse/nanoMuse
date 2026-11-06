package io.github.nanomuse.chat

/** A run's bounded summary attempts, independent of the provider's performance target. */
class ContextMaintenance(private val maxCompactions: Int = 3) {
    enum class Action { PROCEED, COMPACTED, STOP }

    var attempts: Int = 0
        private set
    var softDeferred: Boolean = false
        private set
    private var usedCalibrationProbe = false
    var calibrationProbeGranted: Boolean = false
        private set

    init { require(maxCompactions > 0) }

    fun reset() {
        attempts = 0
        softDeferred = false
        usedCalibrationProbe = false
        calibrationProbeGranted = false
    }

    /**
     * The caller trims locally before this check and remeasures after installing a summary.
     * A failed early summary must not block an input that still leaves output space. At most
     * one request may probe a calibration-only overflow; actual oversized inputs still stop.
     * Cancellation propagates, including while preparing the replacement request.
     */
    suspend fun check(
        budget: ContextBudget.Plan,
        measure: () -> Int,
        measureUncalibrated: () -> Int = measure,
        compact: suspend (tokens: Int, attempt: Int) -> Boolean,
    ): Action {
        calibrationProbeGranted = false
        if (budget.window <= 0) return Action.PROCEED
        val tokens = measure()
        if (tokens <= 0 || tokens < budget.compactThreshold) return Action.PROCEED
        val atHardLimit = tokens >= budget.hardLimit
        if (!atHardLimit && softDeferred) return Action.PROCEED
        if (attempts >= maxCompactions || budget.window < 32_000) {
            softDeferred = true
            return capacityAction(budget, tokens, measureUncalibrated())
        }

        attempts += 1
        val installed = compact(tokens, attempts)
        val afterTokens = measure()
        if (!installed || afterTokens >= tokens) {
            softDeferred = true
            val action = capacityAction(budget, afterTokens, measureUncalibrated())
            return if (installed && action == Action.PROCEED) Action.COMPACTED else action
        }
        // A reduced but still large request gets another bounded check before being sent.
        // A partial reduction below the capacity reserve resumes without another soft attempt.
        softDeferred = afterTokens >= budget.compactThreshold
        return Action.COMPACTED
    }

    private fun capacityAction(budget: ContextBudget.Plan, measured: Int, raw: Int): Action {
        if (measured < budget.hardLimit) return Action.PROCEED
        if (!usedCalibrationProbe && raw < budget.hardLimit) {
            usedCalibrationProbe = true
            calibrationProbeGranted = true
            return Action.PROCEED
        }
        return Action.STOP
    }
}
