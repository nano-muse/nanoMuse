package io.github.nanomuse.hub

import android.content.Context
import android.util.AtomicFile
import io.github.nanomuse.cloud.NanoMuseCloud
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.util.concurrent.ConcurrentHashMap

internal class PersistentTaskEndpoint(private val journal: PersistentTurns) {
    private val calls = ConcurrentHashMap<Pair<TurnOwner, String>, LiveTurn>()

    fun status(owner: TurnOwner, turn: String): JSONObject {
        val result = journal.status(owner, turn) ?: return PersistentTurns.state("unknown")
        if (result.optString("state") == "accepted") calls[owner to turn]?.let { result.put("events", it.events()) }
        return result
    }

    fun callId(owner: TurnOwner, turn: String): String? =
        calls[owner to turn]?.callId?.takeIf { journal.status(owner, turn)?.optString("state") == "accepted" }

    fun run(
        owner: TurnOwner, turn: String, call: IncomingCall, create: () -> String,
        execute: (String, (JSONObject) -> Unit) -> JSONObject,
    ): JSONObject {
        val reservation = journal.accept(owner, turn, create)
        if (!reservation.accepted) return reservation.result
        val key = owner to turn
        val live = LiveTurn(call.id)
        calls[key] = live
        val emit: (JSONObject) -> Unit = { event ->
            live.record(event)
            call.event(event)
        }
        try {
            val result = try {
                emit(JSONObject().put("stage", "accepted").put("turn_id", turn))
                PersistentTurns.state("completed").put("text", execute(reservation.session, emit).optString("text"))
            } catch (failure: HubActions.Refused) {
                if (failure.code == "cancelled") PersistentTurns.state("cancelled")
                else PersistentTurns.state("failed").put("error", failure.code).put("message", failure.message)
            } catch (_: Exception) {
                PersistentTurns.state("failed").put("error", "failed").put("message", "The execution device could not finish the turn")
            }
            journal.finish(owner, turn, result)
            return result
        } finally {
            calls.remove(key)
        }
    }

    companion object {
        @Volatile private var instance: PersistentTaskEndpoint? = null

        fun owner(context: Context, call: IncomingCall): TurnOwner {
            val account = NanoMuseCloud.account(context)?.accountId?.takeIf { it.isNotBlank() }
                ?: throw HubActions.Refused("not_allowed", "Sign in to use persistent conversations")
            return TurnOwner(account, call.from.optString("id"), call.args.optString("conversation"))
        }

        @Synchronized fun get(context: Context): PersistentTaskEndpoint {
            instance?.let { return it }
            val file = AtomicFile(File(context.noBackupFilesDir, "hub-turns.json"))
            val initial = try {
                file.readFully().toString(Charsets.UTF_8)
            } catch (_: FileNotFoundException) {
                "{}"
            }
            val journal = PersistentTurns(initial) { snapshot ->
                val stream = file.startWrite()
                try {
                    stream.write(snapshot.toByteArray(Charsets.UTF_8))
                    stream.fd.sync()
                    file.finishWrite(stream)
                } catch (error: Exception) {
                    file.failWrite(stream)
                    throw error
                }
            }
            return PersistentTaskEndpoint(journal).also { instance = it }
        }
    }
}
