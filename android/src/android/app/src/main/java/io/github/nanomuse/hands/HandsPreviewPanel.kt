package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.TextView
import com.openminis.app.R
import java.util.concurrent.Executor

/** A read-only pane inside the existing Stop capsule. No stored frames, gestures or model calls. */
internal class HandsPreviewPanel(
    context: Context,
    private val worker: Executor,
    private val permitted: () -> Boolean,
    private val capture: () -> Bitmap?,
) : FrameLayout(context) {
    private val main = Handler(Looper.getMainLooper())
    private val screen = ImageView(context).apply {
        scaleType = ImageView.ScaleType.FIT_CENTER
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val unavailable = TextView(context).apply {
        setText(R.string.nm_hands_preview_wait)
        setTextColor(0xCCFFFFFF.toInt())
        gravity = Gravity.CENTER
        textSize = 13f
    }
    private var active = false
    private var serial = 0
    private var busy = false
    private val tick = Runnable { requestFrame() }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        addView(unavailable, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        visibility = View.GONE
    }

    fun expanded(expand: Boolean) {
        serial++
        active = expand
        visibility = if (expand) View.VISIBLE else View.GONE
        main.removeCallbacks(tick)
        clearPicture()
        if (expand) requestFrame()
    }

    private fun clearPicture() {
        screen.setImageDrawable(null)
        unavailable.visibility = View.VISIBLE
    }

    private fun requestFrame() {
        if (!active || !isAttachedToWindow || busy) return
        if (!permitted()) { expanded(false); return }
        busy = true
        val request = serial
        worker.execute {
            val bitmap = runCatching { if (permitted()) capture() else null }.getOrNull()
            main.post {
                busy = false
                if (request != serial || !active || !isAttachedToWindow || !permitted()) {
                    bitmap?.recycle() // never submitted to the renderer
                    clearPicture()
                } else if (bitmap == null) {
                    clearPicture()
                } else {
                    screen.setImageBitmap(bitmap)
                    unavailable.visibility = View.GONE
                }
                if (active && isAttachedToWindow) main.postDelayed(tick, 1000)
            }
        }
    }

    override fun onDetachedFromWindow() {
        expanded(false)
        super.onDetachedFromWindow()
    }
}
