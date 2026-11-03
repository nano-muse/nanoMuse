package io.github.nanomuse.guard

import android.app.Activity
import android.app.Application
import android.content.Context
import android.os.Bundle
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first

/** Authentication availability is strict for access, unlike optional risk confirmations. */
object AccessAuthentication {
    fun available(context: Context) = DeviceCredential.available(context)
    fun confirm(activity: Activity, title: String, result: (Boolean) -> Unit) {
        if (!available(activity)) { result(false); return }
        DeviceCredential.confirm(activity, title, title) { success ->
            result(success && !activity.isFinishing && !activity.isDestroyed)
        }
    }
}

object AppAccess {
    private lateinit var application: Application
    private val lease = AccessLease(SystemClock::elapsedRealtime)
    private val _locked = MutableStateFlow(false)
    val locked = _locked.asStateFlow()
    private val prefs get() = application.getSharedPreferences("nanomuse_access", Context.MODE_PRIVATE)
    val enabled get() = prefs.getBoolean("app_enabled", false)
    val timeout get() = prefs.getInt("app_timeout", -1)
    private var started = 0
    private var pendingActivity: android.content.Intent? = null

    @Synchronized fun initialize(context: Context) {
        if (::application.isInitialized) return
        application = context.applicationContext as Application
        publish()
        application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityStarted(activity: Activity) {
                if (started++ == 0) { lease.foreground(timeout); publish() }
                if (activity is com.openminis.app.webapp.WebAppActivity) deferIfLocked(activity)
            }
            override fun onActivityStopped(activity: Activity) {
                started = (started - 1).coerceAtLeast(0)
                if (started == 0 && !activity.isChangingConfigurations) lease.background()
            }
            override fun onActivityCreated(activity: Activity, state: Bundle?) = Unit
            override fun onActivityResumed(activity: Activity) = Unit
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
    }

    fun authenticated(success: Boolean) { lease.authenticate(success); publish() }
    fun configure(enable: Boolean, seconds: Int, authenticated: Boolean): Boolean {
        if (!authenticated || !AccessAuthentication.available(application)) return false
        require(seconds in TIMEOUTS)
        check(prefs.edit().putBoolean("app_enabled", enable).putInt("app_timeout", seconds).commit())
        lease.authenticate(true)
        publish()
        return true
    }
    suspend fun awaitUnlocked() { locked.first { !it } }
    /** Standalone web apps are a second UI entry point; never execute their content while locked. */
    fun deferIfLocked(activity: com.openminis.app.webapp.WebAppActivity): Boolean {
        initialize(activity)
        if (!_locked.value) return false
        activity.window.decorView.visibility = android.view.View.INVISIBLE
        pendingActivity = android.content.Intent(activity.intent).setClass(application, activity.javaClass)
        activity.startActivity(android.content.Intent(activity, com.openminis.app.MainActivity::class.java))
        activity.finish()
        return true
    }
    fun takePendingActivity(): android.content.Intent? {
        if (_locked.value) return null
        return pendingActivity.also { pendingActivity = null }
    }
    private fun publish() { _locked.value = enabled && !lease.isUnlocked(0) }
    val TIMEOUTS = listOf(-1, 30, 60, 300, 600, 900, 3600, 0)
}
