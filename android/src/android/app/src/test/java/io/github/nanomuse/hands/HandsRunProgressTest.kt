package io.github.nanomuse.hands

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HandsRunProgressTest {
    @Test
    fun aNewOwnerRejectsLateUpdatesFromThePreviousRun() {
        val first = HandsRunProgress.begin("chat-a", "run-a", background = true, appLabel = "Maps")
        assertTrue(HandsRunProgress.update(first, HandsRunProgress.Phase.LOOKING, step = 1))

        val second = HandsRunProgress.begin("chat-b", "run-b", background = true, appLabel = "Mail")
        assertFalse(HandsRunProgress.update(first, HandsRunProgress.Phase.ACTING, step = 9))
        assertEquals("run-b", HandsRunProgress.state.value?.runId)
        assertEquals(HandsRunProgress.Phase.STARTING, HandsRunProgress.state.value?.phase)

        HandsRunProgress.clear(second)
        assertNull(HandsRunProgress.state.value)
    }

    @Test
    fun terminalStateCannotBeReopenedByALateAction() {
        val token = HandsRunProgress.begin("chat", "run", background = true, appLabel = null)
        assertTrue(HandsRunProgress.update(
            token,
            HandsRunProgress.Phase.ACTING,
            step = 3,
            action = HandsRunProgress.Action.TYPE,
        ))
        assertTrue(HandsRunProgress.finish(token, HandsRunProgress.Phase.STOPPED, step = 3))
        assertFalse(HandsRunProgress.update(token, HandsRunProgress.Phase.LOOKING, step = 4))
        assertFalse(HandsRunProgress.state.value?.active ?: true)
        assertNull(HandsRunProgress.state.value?.action)
        HandsRunProgress.clear(token)
    }
}
