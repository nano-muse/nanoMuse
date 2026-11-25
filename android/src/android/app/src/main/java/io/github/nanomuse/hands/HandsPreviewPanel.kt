package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView
import java.util.concurrent.Executor

internal sealed interface PreviewCapture<out T> {
    data class Frame<T>(val value: T) : PreviewCapture<T>
    data object Pending : PreviewCapture<Nothing>
    data object Clear : PreviewCapture<Nothing>
}

internal data class PreviewFrameUpdate<T>(val displayed: T?, val retired: T?, val clear: Boolean)

/** Pending keeps the last safe frame. Security and ownership failures explicitly clear it. */
internal fun <T> retainPreviewFrame(
    current: T?,
    capture: PreviewCapture<T>,
): PreviewFrameUpdate<T> = when (capture) {
    PreviewCapture.Pending -> PreviewFrameUpdate(current, null, clear = false)
    PreviewCapture.Clear -> PreviewFrameUpdate(null, current, clear = true)
    is PreviewCapture.Frame -> when {
        capture.value === current -> PreviewFrameUpdate(current, null, clear = false)
        else -> PreviewFrameUpdate(capture.value, current, clear = false)
    }
}

/** A read-only pane inside the existing Stop window. No gestures or model calls. */
internal class HandsPreviewPanel(
    context: Context,
    private val worker: Executor,
    private val permitted: () -> Boolean,
    private val capture: () -> PreviewCapture<Bitmap>,
) : FrameLayout(context) {
    private val main = Handler(Looper.getMainLooper())
    private val screen = ImageView(context).apply {
        scaleType = ImageView.ScaleType.FIT_CENTER
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private var active = false
    private var serial = 0
    private var busy = false
    private var displayed: Bitmap? = null
    private val tick = Runnable { requestFrame() }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        visibility = View.GONE
    }

    fun expanded(expand: Boolean) {
        if (active == expand) {
            if (expand) requestFrame()
            return
        }
        serial++
        active = expand
        visibility = if (expand) View.VISIBLE else View.GONE
        main.removeCallbacks(tick)
        if (!expand) clearPicture()
        if (expand) requestFrame()
    }

    private fun clearPicture() {
        screen.setImageDrawable(null)
        displayed?.recycle()
        displayed = null
    }

    private fun requestFrame() {
        if (!active || !isAttachedToWindow || busy) return
        if (!permitted()) {
            clearPicture()
            scheduleNext()
            return
        }
        busy = true
        val request = serial
        worker.execute {
            val capture = runCatching {
                if (permitted()) capture() else PreviewCapture.Clear
            }.getOrDefault(PreviewCapture.Clear)
            main.post {
                busy = false
                if (request != serial || !active || !isAttachedToWindow || !permitted()) {
                    (capture as? PreviewCapture.Frame)?.value?.recycle()
                    clearPicture()
                } else {
                    val update = retainPreviewFrame(displayed, capture)
                    when {
                        update.clear -> clearPicture()
                        capture is PreviewCapture.Frame -> {
                            displayed = update.displayed
                            screen.setImageBitmap(update.displayed)
                            update.retired?.recycle()
                        }
                    }
                }
                scheduleNext()
            }
        }
    }

    private fun scheduleNext() {
        main.removeCallbacks(tick)
        if (active && isAttachedToWindow) main.postDelayed(tick, 1000)
    }

    override fun onDetachedFromWindow() {
        expanded(false)
        super.onDetachedFromWindow()
    }
}
