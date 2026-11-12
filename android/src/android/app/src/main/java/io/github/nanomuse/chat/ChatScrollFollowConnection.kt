package io.github.nanomuse.chat

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.unit.Velocity

/** Keeps transcript-follow intent separate from positions changed by streaming or layout. */
class ChatScrollFollowConnection(
    private val isNearBottom: () -> Boolean,
    private val setDetached: (Boolean) -> Unit,
) : NestedScrollConnection {
    private var flingTowardsLatest = false

    override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
        if (source == NestedScrollSource.UserInput) updateIntent(available.y)
        return Offset.Zero
    }

    override fun onPostScroll(
        consumed: Offset,
        available: Offset,
        source: NestedScrollSource,
    ): Offset {
        if (source == NestedScrollSource.UserInput) updateIntent(consumed.y)
        return Offset.Zero
    }

    override suspend fun onPreFling(available: Velocity): Velocity {
        flingTowardsLatest = available.y < 0f
        return Velocity.Zero
    }

    override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
        if (flingTowardsLatest && isNearBottom()) setDetached(false)
        flingTowardsLatest = false
        return Velocity.Zero
    }

    private fun updateIntent(deltaY: Float) {
        // A new gesture supersedes a previous fling even if its completion arrives late.
        if (deltaY != 0f) flingTowardsLatest = false
        // With reverseLayout, a downward finger movement reveals older rows.
        // Detach before the child consumes it so the next token cannot win a race.
        if (deltaY > 0f) setDetached(true)
        else if (deltaY < 0f && isNearBottom()) setDetached(false)
    }
}
