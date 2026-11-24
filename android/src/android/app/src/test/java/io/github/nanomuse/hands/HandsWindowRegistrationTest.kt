package io.github.nanomuse.hands

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class HandsWindowRegistrationTest {
    private val w = 120
    private val h = 99
    private val sw = w + 19
    private val sh = h + 15
    private val x0 = 4
    private val y0 = 12

    private fun content(x: Int, y: Int): Int {
        val r = (x * x * 17 + y * 71) and 255
        val g = (x * 101 + y * y * 31) and 255
        val b = (x * 7 + y * 59) and 255
        return (255 shl 24) or (r shl 16) or (g shl 8) or b
    }

    private fun match(source: IntArray, read: (Int, Int) -> Int): HandsWindowRegistration.Offset? {
        val evidence = HandsWindowRegistration.sample(w, h, read = read) ?: return null
        return HandsWindowRegistration.match(w, h, sw, sh, source, evidence)
    }

    private fun source(read: (Int, Int) -> Int) =
        IntArray(sw * sh) { i -> read(i % sw - x0, i / sw - y0) }

    @Test fun findsAsymmetricInsetsAndExcludesTheSurroundingPixels() {
        val image = source { x, y -> if (x in 0 until w && y in 0 until h) content(x, y) else 0 }
        assertEquals(HandsWindowRegistration.Offset(x0, y0), match(image, ::content))
    }

    @Test fun flatImageSingleEdgeAndRepeatingTilesCannotEstablishUniqueGeometry() {
        assertNull(HandsWindowRegistration.sample(w, h) { _, _ -> -1 })
        assertNull(HandsWindowRegistration.sample(w, h) { x, _ -> if (x < 50) -1 else -16777216 })
        // More than one perfect crop is compatible with this detailed but periodic pattern.
        val tiled = { x: Int, y: Int -> content(x and 3, y and 7) }
        assertNull(match(source(tiled), tiled))
    }

    @Test fun transparentCornersAreExcludedEvenWhenTheDisplayHasDifferentPixelsThere() {
        val image = source { x, y ->
            if (x < 36 && y < 35) 0 else content(x, y)
        }
        val visible = { x: Int, y: Int ->
            if (x < 36 && y < 35) content(x + 20, y - 3) else content(x, y)
        }
        assertEquals(HandsWindowRegistration.Offset(x0, y0), match(image, visible))
    }

    @Test fun aNearMatchAlsoDisqualifiesAnOtherwiseExactCrop() {
        // Repeating every twelve pixels with a small color drift. The correct crop is exact,
        // but the display cannot reliably distinguish its neighbor across color conversions.
        val subtleTiles = { x: Int, y: Int ->
            val tile = Math.floorDiv(x, 12)
            val local = Math.floorMod(x, 12)
            val original = content(local, y)
            (original and 0xFF00FFFF.toInt()) or ((80 + 5 * tile) shl 16)
        }
        assertNull(match(source(subtleTiles), subtleTiles))
    }

    @Test fun changedPixelsAndTransparentWitnessesDoNotAuthorizeAnOffset() {
        val changed = source { x, y -> content(x, y) xor 0x003077A1 }
        assertNull(match(changed, ::content))
        val transparent = source { x, y -> content(x, y) and 0x00FFFFFF }
        assertNull(match(transparent, ::content))
    }

    @Test fun rejectsOversizedCropsAndWeakSpatialEvidence() {
        assertFalse(HandsWindowRegistration.supported(600, 800, 899, 820))
        assertFalse(HandsWindowRegistration.supported(10, 10, 20, 20))
        val smallIcon = { x: Int, y: Int -> if (x in 20..24 && y in 15..20) content(x, y) else -1 }
        assertNull(HandsWindowRegistration.sample(w, h, read = smallIcon))
    }
}
