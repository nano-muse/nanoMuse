package io.github.nanomuse.sync

import com.openminis.app.ui.chat.AssistantBlock
import io.github.nanomuse.hub.Device
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

/** The small host adapter keeps task lifecycle out of the upstream chat view model. */
class RemoteChatBridge(
    private val scope: CoroutineScope,
    private val host: Host,
    private val newTask: (Device, String, String) -> Task,
) {
    enum class Issue { AMBIGUOUS, OFFLINE, ATTACHMENTS, BUSY, FAILED }
    interface Task {
        val text: String
        val blocks: List<AssistantBlock>
        val failed: Boolean
        val stopped: Boolean get() = false
        suspend fun run(sessionId: String, update: () -> Unit)
        fun stop()
    }
    interface Host {
        val busy: Boolean
        fun setBusy(value: Boolean)
        fun error(issue: Issue, device: String = "")
        fun clearDraft()
        fun restoreDraft(text: String)
        suspend fun session(): String
        suspend fun user(sessionId: String, text: String)
        fun started(sessionId: String) {}
        fun ended(sessionId: String, completed: Boolean) {}
        fun show(id: String, task: Task)
        suspend fun finish(sessionId: String, id: String, task: Task)
        fun afterTurn()
    }
    private class Active(val id: String, val task: Task) { var job: Job? = null }
    private var active: Active? = null

    private fun refuse(text: String, issue: Issue, device: String = ""): Boolean {
        // The composer clears its field before dispatch; a refusal must put it back.
        host.restoreDraft(text)
        host.error(issue, device)
        return true
    }

    /** True means addressed here, including a refusal. It must not fall into the local model. */
    fun send(text: String, devices: List<Device>, attachments: Boolean, compacting: Boolean): Boolean {
        val route = RemoteDeviceRoute.resolve(text, devices)
        if (route == RemoteDeviceRoute.None) return false
        if (route !is RemoteDeviceRoute.Selected) return refuse(text, Issue.AMBIGUOUS)
        if (host.busy || compacting) return refuse(text, Issue.BUSY)
        if (!route.device.online) return refuse(text, Issue.OFFLINE, route.device.name)
        if (attachments) return refuse(text, Issue.ATTACHMENTS)
        if (route.text.isBlank()) { host.restoreDraft(text); return true }
        val id = UUID.randomUUID().toString()
        val run = Active(id, newTask(route.device, route.text, id))
        active = run
        host.setBusy(true)
        host.clearDraft()
        run.job = scope.launch(start = CoroutineStart.UNDISPATCHED) {
            var sessionId: String? = null
            var userShown = false
            var taskReturned = false
            try {
                sessionId = host.session()
                host.user(sessionId, text)
                userShown = true
                host.started(sessionId)
                host.show(id, run.task)
                run.task.run(sessionId) { if (active === run) host.show(id, run.task) }
                taskReturned = true
            } catch (e: CancellationException) {
                run.task.stop()
                throw e
            } catch (_: Exception) {
                host.error(Issue.FAILED, route.device.name)
            } finally {
                withContext(NonCancellable) {
                    var saved = false
                    try {
                        if (userShown && sessionId != null) {
                            host.finish(sessionId, id, run.task)
                            saved = true
                        }
                        else host.restoreDraft(text)
                    } catch (_: Exception) {
                        host.error(Issue.FAILED, route.device.name)
                    } finally {
                        if (userShown && sessionId != null) {
                            host.ended(sessionId, saved && taskReturned && !run.task.failed && !run.task.stopped)
                        }
                        if (active === run) {
                            active = null
                            host.setBusy(false)
                            host.afterTurn()
                        }
                    }
                }
            }
        }
        return true
    }

    fun cancel(): Boolean {
        val run = active ?: return false
        run.task.stop()
        host.show(run.id, run.task)
        run.job?.cancel()
        return true
    }
}
