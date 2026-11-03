package io.github.nanomuse.sync

import com.openminis.app.data.FileMentionIndex
import io.github.nanomuse.hub.Device

object DeviceMentionMenu {
    fun entries(text: String, anchor: Int, filter: String, devices: List<Device>, files: List<FileMentionIndex.Entry>): List<FileMentionIndex.Entry> {
        if (anchor !in text.indices || text[anchor] !in listOf('@', '＠') || text.substring(0, anchor).isNotBlank()) return files
        val named = devices.filter { it.kind != "web" && it.name.isNotBlank() }
        val rows = named.filter { it.online && "task" in it.actions && it.name.contains(filter, ignoreCase = true) }
            .sortedWith(compareBy<Device> { !it.name.startsWith(filter, ignoreCase = true) }.thenBy(String.CASE_INSENSITIVE_ORDER) { it.name }.thenBy { it.id })
            .map { device ->
                val duplicate = named.count { it.name.equals(device.name, ignoreCase = true) } > 1
                FileMentionIndex.Entry(
                    linuxPath = if (duplicate) "${device.name} [${device.id}]" else device.name,
                    scope = FileMentionIndex.Scope.MOUNT,
                    mountName = null,
                    modifiedAt = device.lastSeen,
                    isDirectory = false,
                    nmDevice = device,
                )
            }
        return (rows + files).take(50)
    }
}
