package io.github.nanomuse.testing

import android.app.UiAutomation
import androidx.test.runner.AndroidJUnitRunner

/** Keep configured accessibility services active while instrumentation drives the app. */
class AccessibilityPreservingRunner : AndroidJUnitRunner() {
    override fun getUiAutomation(): UiAutomation? =
        super.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)

    override fun getUiAutomation(flags: Int): UiAutomation? =
        super.getUiAutomation(flags or UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
}
