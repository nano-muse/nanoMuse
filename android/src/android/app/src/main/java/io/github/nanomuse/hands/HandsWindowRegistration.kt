package io.github.nanomuse.hands

import kotlin.math.abs

/** Finds a crop inside an Android window capture, using only interior samples from its known
 * footprint on our non-mirroring display. Android can supply arbitrary asymmetric surface insets. */
internal object HandsWindowRegistration {
    data class Offset(val x: Int, val y: Int)
    data class Point(val x: Int, val y: Int, val color: Int)
    data class Edge(val first: Point, val second: Point)
    data class Evidence(val grid: List<Point>, val edges: List<Edge>)

    // Bound both memory and work. A request outside these limits needs a human handoff.
    fun supported(w: Int, h: Int, sw: Int, sh: Int): Boolean =
        w >= 24 && h >= 24 && sw - w in 0..192 && sh - h in 0..192 &&
            sw.toLong() * sh <= 2_000_000 && (sw != w || sh != h)

    private fun difference(a: Int, b: Int): Int = maxOf(
        abs((a ushr 16 and 255) - (b ushr 16 and 255)),
        abs((a ushr 8 and 255) - (b ushr 8 and 255)),
        abs((a and 255) - (b and 255)),
    )

    /** read is strictly relative to the inside of the on-screen window. Keep two orthogonal edge
     * witnesses per sector so a single icon, a solid surface or one straight edge is inadequate. */
    fun sample(w: Int, h: Int, read: (Int, Int) -> Int): Evidence? {
        if (w < 24 || h < 24) return null
        val grid = ArrayList<Point>()
        val edges = arrayOfNulls<Edge>(128)
        val strengths = IntArray(128)
        for (y in 4 until h - 5 step maxOf(1, h / 64)) {
            for (x in 4 until w - 5 step maxOf(1, w / 64)) {
                val p = Point(x, y, read(x, y))
                if (p.color ushr 24 != 255) continue
                grid.add(p)
                val cell = ((y * 8 / h) * 8 + x * 8 / w) * 2
                for (axis in 0..1) {
                    val nx = x + if (axis == 0) 1 else 0
                    val ny = y + if (axis == 1) 1 else 0
                    val next = read(nx, ny)
                    val delta = difference(p.color, next)
                    if (next ushr 24 == 255 && delta >= 24 && delta > strengths[cell + axis]) {
                        edges[cell + axis] = Edge(p, Point(nx, ny, next))
                        strengths[cell + axis] = delta
                    }
                }
            }
        }
        if (edges.indices.count { it % 2 == 0 && edges[it] != null } < 2 ||
            edges.indices.count { it % 2 == 1 && edges[it] != null } < 2 ||
            (0 until 64).count { edges[2 * it] != null || edges[2 * it + 1] != null } < 3) return null
        val witnesses = edges.indices.sortedByDescending { strengths[it] }.mapNotNull { edges[it] }
        return if (witnesses.size >= 5) Evidence(grid, witnesses) else null
    }

    /** A successful offset agrees exactly (within color rounding) at every selected edge.
     * Even another nearly matching offset makes the result ambiguous. */
    fun match(w: Int, h: Int, sw: Int, sh: Int, source: IntArray, evidence: Evidence): Offset? {
        if (!supported(w, h, sw, sh) || source.size != sw * sh) return null
        var plausible: Offset? = null
        var exact = false
        var fullChecks = 0
        val tolerated = maxOf(1, evidence.edges.size / 10)
        fun matches(p: Point, base: Int, tolerance: Int): Boolean {
            val color = source[base + p.y * sw + p.x]
            return color ushr 24 == 255 && difference(color, p.color) <= tolerance
        }
        for (dy in 0..sh - h) for (dx in 0..sw - w) {
            val base = dy * sw + dx
            var missed = 0
            var strict = true
            var checkedEdges = 0
            var horizontal = 0
            var vertical = 0
            var sectors = 0
            for (edge in evidence.edges) {
                // The compositor blends partially transparent pixels with the app behind the
                // dialog. Those pixels cannot testify to the position of the target window.
                if (source[base + edge.first.y * sw + edge.first.x] ushr 24 != 255 ||
                    source[base + edge.second.y * sw + edge.second.x] ushr 24 != 255) continue
                checkedEdges++
                if (edge.first.y == edge.second.y) horizontal++ else vertical++
                sectors = sectors or (1 shl ((edge.first.y * 4 / h) * 4 + edge.first.x * 4 / w))
                if (!matches(edge.first, base, 3) || !matches(edge.second, base, 3)) {
                    strict = false
                    if ((!matches(edge.first, base, 8) || !matches(edge.second, base, 8)) && ++missed > tolerated) break
                }
            }
            if (missed > maxOf(1, checkedEdges / 10) || checkedEdges < 6 ||
                horizontal < 2 || vertical < 2 || Integer.bitCount(sectors) < 3) continue
            // Repetitive textures should hand off rather than consuming a preview interval
            // scanning thousands of plausible crops against every point in the grid.
            if (++fullChecks > 32) return null
            var opaque = 0
            var matching = 0
            for (point in evidence.grid) {
                val color = source[base + point.y * sw + point.x]
                if (color ushr 24 != 255) continue
                opaque++
                if (difference(color, point.color) <= 5) matching++
            }
            if (opaque < maxOf(32, evidence.grid.size / 3) || matching * 100 < opaque * 97) continue
            if (plausible != null) return null
            plausible = Offset(dx, dy)
            exact = strict && matching * 100 >= opaque * 99
        }
        return if (exact) plausible else null
    }
}
