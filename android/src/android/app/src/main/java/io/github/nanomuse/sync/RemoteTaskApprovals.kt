package io.github.nanomuse.sync

import io.github.nanomuse.guard.GateOutcome
import io.github.nanomuse.reach.RemoteApprovalGate
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Cards belong to this call. Closing it or receiving a remote result withdraws them. */
class RemoteTaskApprovals(
    private val scope: CoroutineScope,
    private val sessionId: String,
    private val name: String,
    private val approve: suspend (String, Boolean) -> Unit,
    private val decide: suspend (JSONObject) -> GateOutcome = { body ->
        val preview = body.optString("preview").ifBlank { body.optString("summary") }
        RemoteApprovalGate.check(sessionId, name, RemoteApprovalGate.assessment(body, name), "$name: $preview")
    },
) {
    private val pending = mutableMapOf<String, Job>()
    private var closed = false
    val notices = mutableListOf<String>()

    fun event(body: JSONObject) {
        if (closed) return
        val id = body.optString("approval_id").takeIf { it.isNotBlank() } ?: return
        when (body.optString("stage")) {
            "approval" -> if (id !in pending) {
                pending[id] = scope.launch {
                    val outcome = decide(body)
                    when (outcome) {
                        is GateOutcome.Allowed -> outcome.notice?.let { notices += it }
                        is GateOutcome.Denied -> notices += outcome.message
                    }
                    approve(id, outcome is GateOutcome.Allowed)
                }
            }
            "approval_result" -> pending.remove(id)?.cancel()
        }
    }

    fun close() { closed = true; pending.values.forEach(Job::cancel); pending.clear() }
}
