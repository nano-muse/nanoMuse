package io.github.nanomuse.hands

/** Existing scroll distances remain the default; a model can ask for a larger vertical sweep. */
object HandsScroll {
    data class Gesture(val from: Pair<Int, Int>, val to: Pair<Int, Int>)

    fun gesture(direction: String, distance: String, width: Int, height: Int): Gesture {
        require(width > 0 && height > 0)
        require(direction in setOf("up", "down", "left", "right"))
        require(distance in setOf("normal", "large"))
        val cx = width / 2
        val cy = height / 2
        val dx = width * 35 / 100
        val dy = if (distance == "large") height * 65 / 200 else {
            val old = height * 30 / 100
            old / 2 + old / 4
        }
        val (from, to) = when (direction) {
            "down" -> (cx to cy + dy) to (cx to cy - dy)
            "up" -> (cx to cy - dy) to (cx to cy + dy)
            "left" -> (cx + dx to cy) to (cx - dx to cy)
            else -> (cx - dx to cy) to (cx + dx to cy)
        }
        return Gesture(from, to)
    }
}
