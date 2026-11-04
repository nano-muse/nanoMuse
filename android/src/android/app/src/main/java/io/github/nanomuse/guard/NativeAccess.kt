package io.github.nanomuse.guard

import android.app.Activity
import android.app.Dialog
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Native diagnostic windows must follow the same access lease as Compose content. */
internal fun watchNativeAccess(locked: StateFlow<Boolean>, scope: CoroutineScope, close: () -> Unit) =
    scope.launch(start = CoroutineStart.UNDISPATCHED) { locked.first { it }; close() }

internal suspend fun awaitNativeResume(resumed: StateFlow<Lifecycle.State>) {
    resumed.first { it.isAtLeast(Lifecycle.State.RESUMED) }
}

internal suspend fun awaitNativeAccess(resumed: StateFlow<Lifecycle.State>, locked: StateFlow<Boolean>) {
    combine(resumed, locked) { state, isLocked ->
        state.isAtLeast(Lifecycle.State.RESUMED) && !isLocked
    }.first { it }
}

object NativeAccess {
    fun afterUnlock(activity: Activity, action: () -> Unit) {
        val owner = activity as? LifecycleOwner ?: return
        owner.lifecycleScope.launch {
            awaitNativeAccess(owner.lifecycle.currentStateFlow, AppAccess.locked)
            if (!activity.isFinishing && !activity.isDestroyed) action()
        }
    }

    fun protect(activity: Activity, dialog: Dialog) {
        val owner = activity as? LifecycleOwner
        if (owner == null) { dialog.dismiss(); activity.finish(); return }
        val job = watchNativeAccess(AppAccess.locked, owner.lifecycleScope) {
            dialog.dismiss()
            activity.finish()
        }
        dialog.setOnDismissListener { job.cancel() }
    }
}
