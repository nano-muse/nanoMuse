package io.github.nanomuse.hands

import android.content.Context
import io.github.nanomuse.account.AccountData
import io.github.nanomuse.guard.AppAccess
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Revokes outstanding reads across sign-out, including leaving and returning to the same account. */
object HandsReplayAccess {
    data class Ticket(val owner: String, val generation: Long)
    private val epoch = MutableStateFlow(0L)
    val changes = epoch.asStateFlow()
    private var changing = false

    @Synchronized fun accountChanging(leaving: Boolean) { changing = leaving; invalidate() }
    @Synchronized fun invalidate() { epoch.value++ }
    @Synchronized fun ticket(context: Context): Ticket? =
        if (changing || AppAccess.locked.value) null else Ticket(AccountData.key(context), epoch.value)
    fun current(context: Context, ticket: Ticket): Boolean = this.ticket(context) == ticket
}
