package io.github.nanomuse.sync

import android.content.Context
import com.openminis.app.R
import com.openminis.app.ui.chat.AssistantBlock
import io.github.nanomuse.hub.Device
import io.github.nanomuse.hub.Hub
import io.github.nanomuse.hub.HubErrors
import io.github.nanomuse.reach.Computers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runInterruptible
import org.json.JSONObject

/** Owns a remote reply, not a local agent run. All UI callbacks run in the caller's scope. */
class RemoteTaskChat(private val context: Context, private val device: Device, text: String, val callId: String) : RemoteChatBridge.Task {
    private val task = RemoteDeviceTask(device, text, Computers.uiLanguage(context), callId)
    private val reply = RemoteTaskReply(device.id)
    private var ended = false
    override var failed = false
        private set

    override val text: String get() = context.getString(R.string.nm_sync_from, device.name) + "\n\n" + reply.text
    override val blocks: List<AssistantBlock> get() = listOf(AssistantBlock(
        id = "$callId:origin", kind = "text", content = context.getString(if (ended) R.string.nm_sync_from else R.string.nm_sync_working, device.name),
    )) + reply.blocks

    override fun stop() {
        reply.finish(context.getString(R.string.nm_coding_stopped), stopped = true)
        ended = true
    }

    override suspend fun run(sessionId: String, update: () -> Unit) {
        try {
            exchange(sessionId, update)
        } catch (e: CancellationException) {
            stop()
            throw e
        } catch (e: Exception) {
            failed = true
            reply.finish(context.getString(R.string.nm_remote_failed, device.name, HubErrors.describe(context, e)), failed = true)
        } finally {
            ended = true
            update()
        }
    }

    private suspend fun exchange(sessionId: String, update: () -> Unit): Unit = coroutineScope {
        val approvals = RemoteTaskApprovals(this, sessionId, device.name, approve = { id, allow ->
            runInterruptible(Dispatchers.IO) {
                Hub.call(device.id, "approve", JSONObject().put("approval_id", id).put("allow", allow), 30_000)
            }
        })
        try {
            update()
            val result = task.run(
                call = { id, to, action, args, event ->
                    args.put("from", Hub.name(context))
                    runInterruptible(Dispatchers.IO) {
                        Hub.callWithId(id, to, action, args, io.github.nanomuse.hub.HubClient.TASK_TIMEOUT_MS, event)
                    }
                },
                onEvent = { body -> approvals.event(body); reply.event(body); update() },
                stop = { id -> runInterruptible(Dispatchers.IO) {
                    Hub.call(device.id, "stop", JSONObject().put("call", id), io.github.nanomuse.hub.HubClient.TASK_STOP_TIMEOUT_MS)
                }; Unit },
            )
            val answer = RemoteTaskReply.answer(result)
            failed = answer == null
            val final = answer ?: context.getString(R.string.nm_remote_no_answer, device.name)
            reply.finish((listOf(final) + approvals.notices).joinToString("\n\n"), failed)
        } finally {
            approvals.close()
        }
    }
}
