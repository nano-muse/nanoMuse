package io.github.nanomuse.reach

import io.github.nanomuse.guard.GateOutcome
import io.github.nanomuse.guard.GuardKind
import io.github.nanomuse.guard.RiskAssessment
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskGate
import org.json.JSONObject

/** The same scoped grants for a direct mention and a model-delegated task. */
object RemoteApprovalGate {
    fun assessment(event: JSONObject, name: String): RiskAssessment {
        val target = RemoteApprovalKey.target(event)
        return RiskAssessment(
            when (event.optString("risk").lowercase()) {
                "destructive", "delete" -> RiskClass.DESTRUCTIVE
                "outbound", "send", "network" -> RiskClass.OUTBOUND
                "money", "payment" -> RiskClass.MONEY
                "install" -> RiskClass.INSTALL
                else -> RiskClass.DESTRUCTIVE
            },
            event.optString("reason").ifBlank { "asked by $name" },
            target,
            rememberable = target != null,
            wireRisk = event.optString("risk").lowercase(),
        )
    }

    suspend fun check(
        sessionId: String?,
        deviceId: String,
        name: String,
        assessment: RiskAssessment,
        preview: String,
    ): GateOutcome =
        RiskGate.check(
            sessionId ?: "pc",
            GuardKind.COMPUTER,
            assessment.copy(
                target = assessment.target?.let {
                    RemoteApprovalKey.scoped(
                        deviceId,
                        assessment.wireRisk.orEmpty(),
                        it,
                    )
                },
            ),
            preview,
            pageUrl = name,
        )
}
