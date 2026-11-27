package io.github.nanomuse.ui.cloud

import androidx.compose.ui.graphics.Color
import io.github.nanomuse.hub.Device
import org.json.JSONObject

internal fun deviceConversationLabel(row: JSONObject, device: Device?): String {
    val icon = if ((device?.kind ?: row.optString("kind")) == "phone") "📱" else "▣"
    return "$icon ${device?.name ?: row.getString("name")} · ${row.getString("device").takeLast(6)}"
}

internal fun deviceConversationColor(id: String): Color =
    Color.hsl(Math.floorMod(id.hashCode(), 360).toFloat(), 0.42f, 0.48f)
