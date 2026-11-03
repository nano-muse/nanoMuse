package io.github.nanomuse.sync

import io.github.nanomuse.hub.Device
import org.junit.Assert.*
import org.junit.Test

class RemoteDeviceRouteTest {
    private fun device(id: String, name: String, online: Boolean = true) = Device(id, name, "computer", "Linux", "", online, listOf("task"), 0)

    @Test fun `offline mentions remain explicit destinations instead of falling through to a local model`() {
        val result = RemoteDeviceRoute.resolve("@Desk hello", listOf(device("one", "Desk", false))) as RemoteDeviceRoute.Selected
        assertFalse(result.device.online)
        assertEquals("hello", result.text)
    }

    @Test fun `ambiguous short names and duplicate full names are refused`() {
        assertEquals(RemoteDeviceRoute.Ambiguous, RemoteDeviceRoute.resolve("@desk hello", listOf(device("one", "Desktop"), device("two", "Desk PC"))))
        assertEquals(RemoteDeviceRoute.Ambiguous, RemoteDeviceRoute.resolve("@Desk hello", listOf(device("one", "Desk"), device("two", "Desk"))))
    }

    @Test fun `ordinary mentions stay local and longest full names still work`() {
        val devices = listOf(device("one", "Pixel 8"), device("two", "Pixel 8 Pro"))
        assertEquals("two", (RemoteDeviceRoute.resolve("@Pixel 8 Pro hello", devices) as RemoteDeviceRoute.Selected).device.id)
        assertEquals(RemoteDeviceRoute.None, RemoteDeviceRoute.resolve("read @Pixel 8", devices))
        assertEquals(RemoteDeviceRoute.None, RemoteDeviceRoute.resolve("@/var/minis/workspace/file", devices))
    }

    @Test fun `a qualified duplicate selects its exact id even when it is offline`() {
        val devices = listOf(device("one", "Desk", false), device("two", "Desk"))
        val result = RemoteDeviceRoute.resolve("@Desk [one] hello", devices) as RemoteDeviceRoute.Selected
        assertEquals("one", result.device.id)
        assertFalse(result.device.online)
        assertEquals("hello", result.text)
    }
}
