package io.github.nanomuse.reach

import io.github.nanomuse.guard.GateOutcome
import io.github.nanomuse.guard.GuardKind
import io.github.nanomuse.guard.RiskAssessment
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskGate
import org.json.JSONObject

/** The same scoped grants for a direct mention and a model-delegated task. */
object RemoteApprovalGate {
    fun assessment(event: JSONObject, name: String): RiskAssessment = RiskAssessment(
        when (event.optString("risk").lowercase()) {
            "destructive", "delete" -> RiskClass.DESTRUCTIVE
            "outbound", "send", "network" -> RiskClass.OUTBOUND
            "money", "payment" -> RiskClass.MONEY
            "install" -> RiskClass.INSTALL
            else -> RiskClass.DESTRUCTIVE
        },
        event.optString("reason").ifBlank { "asked by $name" },
        RemoteApprovalKey.target(event),
    )

    suspend fun check(sessionId: String?, name: String, assessment: RiskAssessment, preview: String): GateOutcome =
        RiskGate.check(sessionId ?: "pc", GuardKind.COMPUTER,
            assessment.copy(target = assessment.target?.let { "pc:$it" }), preview, pageUrl = name)
}
