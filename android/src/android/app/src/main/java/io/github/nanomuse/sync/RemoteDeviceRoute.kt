package io.github.nanomuse.sync

import io.github.nanomuse.hub.Device

sealed interface RemoteDeviceRoute {
    data object None : RemoteDeviceRoute
    data object Ambiguous : RemoteDeviceRoute
    data class Selected(val device: Device, val text: String) : RemoteDeviceRoute
    companion object {
        fun resolve(text: String, devices: List<Device>): RemoteDeviceRoute {
            val input = text.trimStart()
            if (!input.startsWith("@")) return None
            val known = devices.filter { it.kind != "web" && it.name.isNotBlank() }
            val addressed = DeviceMention.parse(input, known.map { DeviceMention.Target(it.id, it.name) })
            if (addressed != null) {
                val qualified = "@${addressed.target.name} [${addressed.target.id}]"
                if (input.startsWith(qualified, ignoreCase = true)) {
                    return Selected(known.single { it.id == addressed.target.id }, addressed.text)
                }
            }
            val candidates = known.mapNotNull { device ->
                DeviceMention.parse(input, listOf(DeviceMention.Target(device.id, device.name)))?.let { device to it }
            }
            if (candidates.isEmpty()) return None
            val body = input.drop(1)
            // A full name beats a shorter prefix, as in @Pixel 8 Pro versus @Pixel 8.
            val exact = candidates.filter { (device, _) ->
                body.startsWith(device.name, ignoreCase = true) &&
                    (body.length == device.name.length || !body[device.name.length].isLetterOrDigit())
            }
            val ranked = if (exact.isNotEmpty()) exact.filter { it.first.name.length == exact.maxOf { it.first.name.length } } else candidates
            if (ranked.size != 1) return Ambiguous
            val (device, match) = ranked.single()
            return Selected(device, match.text)
        }
    }
}
