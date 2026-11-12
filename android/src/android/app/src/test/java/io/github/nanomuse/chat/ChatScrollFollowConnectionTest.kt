package io.github.nanomuse.chat

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.unit.Velocity
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatScrollFollowConnectionTest {
    private var nearBottom = true
    private var detached = false
    private val connection = ChatScrollFollowConnection({ nearBottom }) { detached = it }

    @Test
    fun `reading older content detaches before scroll consumption even within bottom threshold`() {
        assertEquals(Offset.Zero, connection.onPreScroll(Offset(0f, 1f), NestedScrollSource.UserInput))
        assertTrue(detached)
    }

    @Test
    fun `programmatic follow and content drift cannot change a reading decision`() {
        connection.onPreScroll(Offset(0f, 80f), NestedScrollSource.UserInput)
        nearBottom = false
        repeat(5) {
            connection.onPreScroll(Offset(0f, -30f), NestedScrollSource.SideEffect)
            connection.onPostScroll(Offset(0f, -30f), Offset.Zero, NestedScrollSource.SideEffect)
        }
        // Final markdown or keyboard reflow can temporarily report bottom again.
        nearBottom = true
        connection.onPostScroll(Offset.Zero, Offset.Zero, NestedScrollSource.SideEffect)
        assertTrue(detached)
    }

    @Test
    fun `scrolling towards latest only reattaches after reaching the bottom`() {
        connection.onPreScroll(Offset(0f, 80f), NestedScrollSource.UserInput)
        nearBottom = false
        connection.onPreScroll(Offset(0f, -20f), NestedScrollSource.UserInput)
        assertTrue(detached)
        nearBottom = true
        assertEquals(Offset.Zero, connection.onPostScroll(
            Offset(0f, -20f), Offset.Zero, NestedScrollSource.UserInput,
        ))
        assertFalse(detached)
    }

    @Test
    fun `a return gesture at the bottom reattaches even if there is no remaining distance`() {
        detached = true
        connection.onPreScroll(Offset(0f, -1f), NestedScrollSource.UserInput)
        connection.onPostScroll(Offset.Zero, Offset(0f, -1f), NestedScrollSource.UserInput)
        assertFalse(detached)
    }

    @Test
    fun `flinging towards latest reattaches when the fling reaches bottom`() = runTest {
        detached = true
        nearBottom = false
        assertEquals(Velocity.Zero, connection.onPreFling(Velocity(0f, -800f)))
        nearBottom = true
        assertEquals(Velocity.Zero, connection.onPostFling(Velocity(0f, -800f), Velocity.Zero))
        assertFalse(detached)
    }

    @Test
    fun `a fling away or a return fling stopping early keeps reading detached`() = runTest {
        detached = true
        connection.onPreFling(Velocity(0f, 800f))
        connection.onPostFling(Velocity(0f, 800f), Velocity.Zero)
        assertTrue(detached)
        nearBottom = false
        connection.onPreFling(Velocity(0f, -800f))
        connection.onPostFling(Velocity(0f, -800f), Velocity.Zero)
        assertTrue(detached)
    }

    @Test
    fun `an unrelated fling completion does not reuse a previous return gesture`() = runTest {
        detached = true
        connection.onPreFling(Velocity(0f, -800f))
        connection.onPostFling(Velocity(0f, -800f), Velocity.Zero)
        assertFalse(detached)
        detached = true
        connection.onPostFling(Velocity.Zero, Velocity.Zero)
        assertTrue(detached)
    }

    @Test
    fun `a fresh reading gesture takes precedence over an older return fling`() = runTest {
        detached = true
        connection.onPreFling(Velocity(0f, -800f))
        connection.onPreScroll(Offset(0f, 1f), NestedScrollSource.UserInput)
        connection.onPostFling(Velocity(0f, -800f), Velocity.Zero)
        assertTrue(detached)
    }
}
