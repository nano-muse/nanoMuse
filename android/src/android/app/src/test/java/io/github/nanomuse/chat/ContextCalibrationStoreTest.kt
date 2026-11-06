package io.github.nanomuse.chat

import android.content.SharedPreferences
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.mockito.ArgumentMatchers.anyString
import org.mockito.ArgumentMatchers.isNull
import org.mockito.Mockito

class ContextCalibrationStoreTest {
    private class Fixture {
        val values = mutableMapOf<String, String>()
        val preferences = Mockito.mock(SharedPreferences::class.java)
        private val editor = Mockito.mock(SharedPreferences.Editor::class.java)
        val store = ContextCalibrationStore(preferences)

        init {
            Mockito.`when`(preferences.getString(anyString(), isNull())).thenAnswer {
                values[it.getArgument<String>(0)]
            }
            Mockito.`when`(preferences.edit()).thenReturn(editor)
            Mockito.`when`(editor.putString(anyString(), anyString())).thenAnswer {
                values[it.getArgument<String>(0)] = it.getArgument(1)
                editor
            }
        }
    }

    @Test
    fun `calibration survives a new store but never crosses provider or model routes`() {
        val fixture = Fixture()
        val calibration = fixture.store.load("route-a", "model-a")
        calibration.observe(20_000, 10_000)
        fixture.store.save("route-a", "model-a", calibration)
        val reloaded = ContextCalibrationStore(fixture.preferences)
        assertEquals(calibration.snapshot(), reloaded.load("route-a", "model-a").snapshot())
        assertEquals(ContextEstimate.Snapshot(), reloaded.load("route-b", "model-a").snapshot())
        assertEquals(ContextEstimate.Snapshot(), reloaded.load("route-a", "model-b").snapshot())
        assertFalse(fixture.values.keys.single().contains("route-a"))
        assertFalse(fixture.values.values.single().contains("model-a"))
    }

    @Test
    fun `identity encoding cannot mix ambiguous provider model pairs`() {
        val fixture = Fixture()
        val calibration = ContextEstimate.Calibration()
        calibration.observe(20_000, 10_000)
        fixture.store.save("a", "bc", calibration)
        assertEquals(ContextEstimate.Snapshot(), fixture.store.load("ab", "c").snapshot())
    }

    @Test
    fun `unknown versions and malformed preferences fall back without failing a chat`() {
        val fixture = Fixture()
        fixture.store.save("route", "model", ContextEstimate.Calibration())
        val key = fixture.values.keys.single()
        for (corrupt in listOf(
            "broken json",
            JSONObject().put("version", -1).put("scale", 2.0).put("samples", 3).toString(),
            JSONObject().put("version", ContextEstimate.CALIBRATION_VERSION)
                .put("scale", 100.0).put("samples", 3).toString(),
            JSONObject().put("version", ContextEstimate.CALIBRATION_VERSION)
                .put("scale", "NaN").put("samples", 3).toString(),
        )) {
            fixture.values[key] = corrupt
            assertEquals(ContextEstimate.Snapshot(), fixture.store.load("route", "model").snapshot())
        }
    }
}
