package io.github.nanomuse.hands

import android.animation.ValueAnimator
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.SweepGradient
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewOutlineProvider
import android.view.VelocityTracker
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.compose.ui.graphics.asAndroidBitmap
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.ui.avatar.AgentMood
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Foreground runs use the capsule over the operated app: the face in a slowly turning
 * three-hue ring, activity bars, the current step and **Stop**. Background runs omit that top
 * capsule and automatically open a secure, draggable, read-only screen window with Stop,
 * pause and handover controls. When the hands need the user, either presentation becomes an
 * approval or handover card. These are plain views in a `TYPE_APPLICATION_OVERLAY` window, so
 * they live outside any Activity; every call is safe from any thread.
 *
 * The capsule hides itself for the instant a screenshot is taken ([hideForCapture]), so the
 * screen model never sees it and cannot tap its own Stop button. The model still cannot see
 * what is under it, so a gesture it asks for may land where the capsule is: for the length of
 * every injected gesture the window lets touches through ([passThrough]), and when the target
 * is under the capsule it first moves to the other end of the screen ([dodge]) so the ring
 * drawn there ([stage]) can be seen.
 *
 * The [stage] — the glow along the edges and the ring at the point about to be tapped — is a
 * second, full-screen window that never takes a touch, added first so the capsule stays on top.
 */
class HandsCapsule(private val context: Context, showStage: Boolean = true) {
    private val main = Handler(Looper.getMainLooper())
    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val backgroundPreview = !showStage
    private var root: LinearLayout? = null
    private var params: WindowManager.LayoutParams? = null
    private var titleView: TextView? = null
    private var detailView: TextView? = null
    private var continueBtn: TextView? = null
    private var openBtn: TextView? = null
    private var allowBtn: TextView? = null
    private var denyBtn: TextView? = null
    private var ring: RingView? = null
    private var bars: BarsView? = null
    private var pane: HandsPreviewPanel? = null
    private var togglePreview: TextView? = null
    private var pauseButton: TextView? = null
    private var phoneButton: TextView? = null
    var canHandOff: () -> Boolean = { false }
    var onPhone: (() -> Unit)? = null
    private var controls: LinearLayout? = null
    private var paused = false
    private var workingTitle = ""
    private var windowAnimator: ValueAnimator? = null
    var previewAllowed: () -> Boolean = { false }
    internal var capturePreview: () -> PreviewCapture<Bitmap> = { PreviewCapture.Pending }
    var togglePause: () -> Boolean = { false }

    private fun collapsePreview() {
        pane?.expanded(false)
        controls?.visibility = View.GONE
        togglePreview?.setText(R.string.nm_hands_preview_show)
    }


    /** What the hands draw on the screen while they work. */
    val stage = if (showStage) HandsStage(context) else null

    var onStop: (() -> Unit)? = null
    var onContinue: (() -> Unit)? = null
    var onOpenApp: (() -> Unit)? = null
    /** The approval answered on the capsule itself, where the person already is (0.1.33). */
    var onAllow: (() -> Unit)? = null
    var onDeny: (() -> Unit)? = null

    private fun dp(v: Int): Int = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), context.resources.displayMetrics).toInt()

    /** A background task must expose Stop before it launches its app. */
    fun showBeforeBackgroundRun(): Boolean {
        val shown = java.util.concurrent.FutureTask {
            working(0, context.getString(R.string.nm_hands_looking))
            root?.parent != null
        }
        if (Looper.myLooper() == Looper.getMainLooper()) shown.run() else main.post(shown)
        return runCatching { shown.get(3, TimeUnit.SECONDS) }.getOrDefault(false)
    }

    /** Shows (or updates) the working state. */
    fun working(step: Int, detail: String) = onMain {
        ensure()
        stage?.mood(HandsStage.Mood.WORKING)
        togglePreview?.visibility = View.VISIBLE
        pauseButton?.isEnabled = true
        pauseButton?.visibility = View.VISIBLE
        phoneButton?.isEnabled = canHandOff()
        ring?.turning(!paused)
        bars?.visibility = if (paused) View.GONE else View.VISIBLE
        workingTitle = if (step > 0) context.getString(R.string.nm_hands_step, step)
        else context.getString(R.string.nm_hands_background_screen)
        titleView?.text = if (paused) context.getString(R.string.nm_goal_status_paused) else workingTitle
        detailView?.text = detail
        continueBtn?.visibility = View.GONE
        openBtn?.visibility = View.GONE
        allowBtn?.visibility = View.GONE
        denyBtn?.visibility = View.GONE
        if (backgroundPreview) {
            pane?.expanded(true)
            controls?.visibility = View.VISIBLE
        }
    }

    /** The hands wait for the user to do something on the phone. */
    fun takeOver(reason: String) = onMain {
        ensure()
        stage?.mood(HandsStage.Mood.WAITING)
        stage?.clear()
        ring?.turning(false)
        bars?.visibility = View.GONE
        titleView?.text = context.getString(R.string.nm_hands_your_turn)
        detailView?.text = reason.ifBlank { context.getString(R.string.nm_hands_your_turn_detail) }
        continueBtn?.visibility = View.VISIBLE
        openBtn?.visibility = View.GONE
        allowBtn?.visibility = View.GONE
        denyBtn?.visibility = View.GONE
    }

    /** An explicit choice before the selected app can replace what the user is doing. */
    fun offerPhone(reason: String) = onMain {
        if (ended) return@onMain
        collapsePreview()
        takeOver(reason)
        continueBtn?.visibility = View.GONE
        togglePreview?.visibility = View.GONE
        pauseButton?.visibility = View.GONE
        controls?.visibility = View.VISIBLE
        phoneButton?.isEnabled = canHandOff()
    }

    /**
     * A tap waits for approval. [decidable]: Allow once / Deny right here on the capsule — the
     * person is in the operated app, not in nanoMuse. Money is confirmed with the screen lock,
     * which only the card in the chat can do: then the capsule offers Open instead.
     */
    fun approval(what: String, decidable: Boolean = false) = onMain {
        ensure()
        collapsePreview()
        togglePreview?.visibility = View.GONE
        pauseButton?.isEnabled = false
        stage?.mood(HandsStage.Mood.WAITING)
        ring?.turning(false)
        bars?.visibility = View.GONE
        titleView?.text = context.getString(R.string.nm_hands_approval_title)
        detailView?.text = what
        continueBtn?.visibility = View.GONE
        openBtn?.visibility = if (decidable) View.GONE else View.VISIBLE
        allowBtn?.visibility = if (decidable) View.VISIBLE else View.GONE
        denyBtn?.visibility = if (decidable) View.VISIBLE else View.GONE
    }

    fun hide() = onMain {
        ended = true
        windowAnimator?.cancel()
        windowAnimator = null
        collapsePreview()
        pane = null; controls = null; togglePreview = null; pauseButton = null; phoneButton = null
        val v = root
        root = null; params = null; titleView = null; detailView = null; continueBtn = null; openBtn = null; allowBtn = null; denyBtn = null
        ring?.turning(false); ring = null
        bars?.stop(); bars = null
        if (v != null) {
            val exitY = if (backgroundPreview) 0f else -dp(20).toFloat()
            v.animate().alpha(0f).translationY(exitY).scaleX(0.96f).scaleY(0.96f)
                .setDuration(200L).setInterpolator(DecelerateInterpolator())
                .withEndAction { runCatching { wm.removeView(v) } }.start()
        }
        stage?.hide()
    }

    /** Hides the capsule and the stage for a screenshot and waits until the frame is gone; [restore] brings them back. */
    fun hideForCapture() {
        val latch = CountDownLatch(1)
        main.post {
            root?.visibility = View.INVISIBLE
            stage?.setVisible(false)
            latch.countDown()
        }
        latch.await(300, TimeUnit.MILLISECONDS)
        // One more frame so the compositor has dropped it.
        Thread.sleep(80)
    }

    fun restore() = onMain {
        root?.visibility = View.VISIBLE
        stage?.setVisible(true)
    }

    /**
     * Runs [gesture] with the capsule letting touches through, so an injected tap or swipe that
     * crosses it reaches the app underneath instead of Stop. Waits for the window manager to
     * apply the flag before the gesture and puts it back after.
     */
    fun <T> passThrough(gesture: () -> T): T {
        setPassThrough(true)
        try {
            return gesture()
        } finally {
            setPassThrough(false)
        }
    }

    private fun setPassThrough(on: Boolean) {
        val latch = CountDownLatch(1)
        main.post {
            try {
                val v = root ?: return@post
                val p = params ?: return@post
                val flags = if (on) p.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                else p.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
                if (flags != p.flags) {
                    p.flags = flags
                    wm.updateViewLayout(v, p)
                }
            } catch (t: Throwable) {
                AppLogger.warning(TAG, "pass-through: ${t.message}")
            } finally {
                latch.countDown()
            }
        }
        latch.await(300, TimeUnit.MILLISECONDS)
        // The touchable region follows the next relayout.
        if (on) Thread.sleep(60)
    }

    /**
     * When ([x], [y]) is under the capsule, moves it to the other end of the screen and waits
     * for the move, so the ring drawn at the target is not hidden behind it. The touch itself
     * would pass through anyway ([passThrough]).
     */
    fun dodge(x: Int, y: Int) {
        val latch = CountDownLatch(1)
        var moved = false
        main.post {
            try {
                val v = root ?: return@post
                val p = params ?: return@post
                val loc = IntArray(2)
                v.getLocationOnScreen(loc)
                val margin = dp(8)
                val inside = x >= loc[0] - margin && x <= loc[0] + v.width + margin &&
                    y >= loc[1] - margin && y <= loc[1] + v.height + margin
                if (!inside) return@post
                val atTop = p.gravity and Gravity.BOTTOM != Gravity.BOTTOM
                p.gravity = (if (atTop) Gravity.BOTTOM else Gravity.TOP) or Gravity.CENTER_HORIZONTAL
                p.y = (if (atTop) navigationBarHeight() else statusBarHeight()) + dp(6)
                wm.updateViewLayout(v, p)
                moved = true
            } catch (t: Throwable) {
                AppLogger.warning(TAG, "dodge: ${t.message}")
            } finally {
                latch.countDown()
            }
        }
        latch.await(300, TimeUnit.MILLISECONDS)
        if (moved) Thread.sleep(120)
    }

    // ── building ───────────────────────────────────────────────────────────

    private fun onMain(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) runCatching(block).onFailure { AppLogger.warning(TAG, "capsule: ${it.message}") }
        else main.post { runCatching(block).onFailure { AppLogger.warning(TAG, "capsule: ${it.message}") } }
    }

    @Volatile private var ended = false

    private fun ensure() {
        if (root != null || ended) return
        stage?.show() // first, so the capsule's window sits above it
        val radius = dp(26).toFloat()
        val pill = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(7), dp(10), dp(7))
            // the desktop pill's ink: dark, a little translucent, a hairline of light round it
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = radius
                setColor(INK)
                setStroke(dp(1), EDGE)
            }
            elevation = dp(8).toFloat()
            clipToOutline = true
            outlineProvider = object : ViewOutlineProvider() {
                override fun getOutline(v: View, outline: Outline) {
                    outline.setRoundRect(0, 0, v.width, v.height, radius)
                }
            }
            if (!backgroundPreview) {
                // slides in from the top the way the desktop pill does
                alpha = 0f
                translationY = -dp(28).toFloat()
                scaleX = 0.96f
                scaleY = 0.96f
            }
        }
        val faceBox = FrameLayout(context).apply {
            val s = dp(36)
            layoutParams = LinearLayout.LayoutParams(s, s)
        }
        val ringView = RingView(context).apply {
            layoutParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        }
        val face = ImageView(context).apply {
            val s = dp(26)
            layoutParams = FrameLayout.LayoutParams(s, s, Gravity.CENTER)
            scaleType = ImageView.ScaleType.CENTER_CROP
            clipToOutline = true
            outlineProvider = object : ViewOutlineProvider() {
                override fun getOutline(v: View, outline: Outline) { outline.setOval(0, 0, v.width, v.height) }
            }
            faceBitmap()?.let { setImageBitmap(it) } ?: setImageResource(R.drawable.nm_avatar_working)
        }
        faceBox.addView(ringView); faceBox.addView(face)
        val barsView = BarsView(context).apply {
            layoutParams = LinearLayout.LayoutParams(dp(20), dp(14)).apply { marginStart = dp(8) }
        }
        val texts = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(10); marginEnd = dp(8) }
        }
        val title = TextView(context).apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13.5f)
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            maxLines = 1
        }
        val detail = TextView(context).apply {
            setTextColor(0xCCFFFFFF.toInt())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            maxLines = 2
        }
        texts.addView(title); texts.addView(detail)
        val cont = button(context.getString(R.string.nm_hands_continue), ACCENT) { onContinue?.invoke() }.apply { visibility = View.GONE }
        val open = button(context.getString(R.string.nm_hands_open), ACCENT) { onOpenApp?.invoke() }.apply { visibility = View.GONE }
        val allow = button(context.getString(R.string.nm_hands_allow_once), ACCENT) { onAllow?.invoke() }.apply { visibility = View.GONE }
        val deny = button(context.getString(R.string.nm_hands_deny), STOP_RED) { onDeny?.invoke() }.apply { visibility = View.GONE }
        val stop = button(context.getString(R.string.nm_hands_stop), STOP_RED) { onStop?.invoke() }
        if (!backgroundPreview) {
            pill.addView(faceBox)
            pill.addView(barsView)
        }
        pill.addView(texts)
        val panelRoot = if (backgroundPreview) {
            val container = LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                background = GradientDrawable().apply {
                    cornerRadius = dp(18).toFloat()
                    setColor(INK)
                    setStroke(dp(1), EDGE)
                }
                clipToOutline = true
                elevation = dp(10).toFloat()
            }
            val preview = HandsPreviewPanel(context, java.util.concurrent.ForkJoinPool.commonPool(),
                { previewAllowed() }, { capturePreview() })
            val decisions = LinearLayout(context).apply {
                gravity = Gravity.CENTER
                setPadding(dp(6), 0, dp(6), dp(6))
            }
            val actions = LinearLayout(context).apply { gravity = Gravity.CENTER; visibility = View.GONE }
            val pause = button(context.getString(R.string.nm_hands_preview_pause), ACCENT) {
                if (previewAllowed()) {
                    paused = togglePause()
                    pauseButton?.setText(if (paused) R.string.nm_hands_preview_resume else R.string.nm_hands_preview_pause)
                    ring?.turning(!paused)
                    bars?.visibility = if (paused) View.GONE else View.VISIBLE
                    titleView?.text = if (paused) context.getString(R.string.nm_goal_status_paused) else workingTitle
                }
            }
            val phone = button(context.getString(R.string.nm_hands_handoff_phone), ACCENT) {
                if (canHandOff()) onPhone?.invoke()
            }.apply { filterTouchesWhenObscured = true }
            pane = preview
            controls = actions
            togglePreview = null
            pauseButton = pause
            phoneButton = phone
            pill.addView(stop)
            decisions.addView(cont)
            decisions.addView(open)
            decisions.addView(allow)
            decisions.addView(deny)
            actions.addView(pause)
            actions.addView(phone)
            container.addView(pill)
            container.addView(decisions)
            val height = minOf((context.resources.displayMetrics.heightPixels * 0.38f).toInt(), dp(320))
            container.addView(preview, LinearLayout.LayoutParams(-1, height))
            container.addView(actions)
            container
        } else pill
        if (!backgroundPreview) {
            pill.addView(cont)
            pill.addView(open)
            pill.addView(allow)
            pill.addView(deny)
            pill.addView(stop)
        }

        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        val dm = context.resources.displayMetrics
        val backgroundWidth = minOf(dm.widthPixels - dp(24), dp(220))
        val params = WindowManager.LayoutParams(
            if (backgroundPreview) backgroundWidth else minOf((dm.widthPixels * 0.94f).toInt(), dp(420)),
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            if (backgroundPreview) {
                gravity = Gravity.TOP or Gravity.START
                x = dm.widthPixels - backgroundWidth - dp(12)
                y = statusBarHeight() + dp(12)
            } else {
                gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
                y = statusBarHeight() + dp(6)
            }
        }
        if (backgroundPreview) {
            panelRoot.alpha = 0f
            panelRoot.scaleX = 0.96f
            panelRoot.scaleY = 0.96f
        }
        try {
            if (backgroundPreview) params.flags = params.flags or WindowManager.LayoutParams.FLAG_SECURE
            wm.addView(panelRoot, params)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "addView failed: ${t.message}")
            return
        }
        val animated = if (backgroundPreview) panelRoot else pill
        animated.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
            .setDuration(320L).setInterpolator(DecelerateInterpolator(1.6f)).start()
        root = panelRoot; this.params = params; titleView = title; detailView = detail; continueBtn = cont; openBtn = open; allowBtn = allow; denyBtn = deny
        if (backgroundPreview) {
            ring = null
            bars = null
            installBackgroundDrag(preview = checkNotNull(pane), window = panelRoot, params = params)
        } else {
            ringView.turning(true)
            barsView.start()
            ring = ringView
            bars = barsView
        }
    }

    /**
     * The background display is a small screen, not a second top capsule. Dragging its picture
     * moves the whole secure window; release projects the gesture and snaps to Mika's nearest
     * safe corner. Buttons stay ordinary taps because the preview alone is the drag handle.
     */
    private fun installBackgroundDrag(
        preview: View,
        window: View,
        params: WindowManager.LayoutParams,
    ) {
        var corner = HandsPipPhysics.Corner.BOTTOM_END
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var dragging = false
        var velocity: VelocityTracker? = null
        var lastWidth = 0
        var lastHeight = 0
        val slop = ViewConfiguration.get(context).scaledTouchSlop

        fun bounds(): HandsPipPhysics.Bounds {
            val dm = context.resources.displayMetrics
            return HandsPipPhysics.Bounds(
                width = dm.widthPixels.toFloat(),
                height = dm.heightPixels.toFloat(),
                pipWidth = window.width.toFloat(),
                pipHeight = window.height.toFloat(),
                margin = dp(12).toFloat(),
                top = statusBarHeight().toFloat(),
                bottom = navigationBarHeight().toFloat(),
            )
        }

        fun place(targetX: Float, targetY: Float, animate: Boolean) {
            val (safeX, safeY) = bounds().clamp(targetX, targetY)
            windowAnimator?.cancel()
            if (!animate || stillMotion(context)) {
                params.x = safeX.toInt()
                params.y = safeY.toInt()
                runCatching { wm.updateViewLayout(window, params) }
                return
            }
            val fromX = params.x
            val fromY = params.y
            windowAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = 220L
                interpolator = DecelerateInterpolator(1.4f)
                addUpdateListener {
                    val t = it.animatedValue as Float
                    params.x = (fromX + (safeX - fromX) * t).toInt()
                    params.y = (fromY + (safeY - fromY) * t).toInt()
                    runCatching { wm.updateViewLayout(window, params) }
                }
                start()
            }
        }

        window.addOnLayoutChangeListener { _, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom ->
            val width = right - left
            val height = bottom - top
            if (width <= 0 || height <= 0 ||
                (width == lastWidth && height == lastHeight &&
                    right - left == oldRight - oldLeft && bottom - top == oldBottom - oldTop)
            ) {
                return@addOnLayoutChangeListener
            }
            lastWidth = width
            lastHeight = height
            val (x, y) = bounds().position(corner)
            place(x, y, animate = false)
        }
        preview.setOnTouchListener { _, event ->
            val tracked = MotionEvent.obtain(event).apply { setLocation(event.rawX, event.rawY) }
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    windowAnimator?.cancel()
                    velocity?.recycle()
                    velocity = VelocityTracker.obtain().also { it.addMovement(tracked) }
                    downX = event.rawX
                    downY = event.rawY
                    startX = params.x
                    startY = params.y
                    dragging = false
                }
                MotionEvent.ACTION_MOVE -> {
                    velocity?.addMovement(tracked)
                    val dx = event.rawX - downX
                    val dy = event.rawY - downY
                    if (!dragging && (kotlin.math.abs(dx) > slop || kotlin.math.abs(dy) > slop)) {
                        dragging = true
                    }
                    if (dragging) place(startX + dx, startY + dy, animate = false)
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    velocity?.addMovement(tracked)
                    velocity?.computeCurrentVelocity(1000)
                    val vx = velocity?.xVelocity ?: 0f
                    val vy = velocity?.yVelocity ?: 0f
                    velocity?.recycle()
                    velocity = null
                    if (dragging) {
                        val safe = bounds()
                        corner = HandsPipPhysics.snapCorner(
                            params.x.toFloat(),
                            params.y.toFloat(),
                            vx,
                            vy,
                            safe,
                        )
                        val (x, y) = safe.position(corner)
                        place(x, y, animate = true)
                    }
                }
            }
            tracked.recycle()
            true
        }
    }

    private fun navigationBarHeight(): Int {
        val id = context.resources.getIdentifier("navigation_bar_height", "dimen", "android")
        return if (id > 0) context.resources.getDimensionPixelSize(id) else dp(48)
    }

    private fun button(text: String, color: Int, onClick: () -> Unit): TextView = TextView(context).apply {
        this.text = text
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setPadding(dp(12), dp(7), dp(12), dp(7))
        background = GradientDrawable().apply { cornerRadius = dp(16).toFloat(); setColor(color) }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(6) }
        setOnClickListener { onClick() }
    }

    /**
     * The ring round the face: the stage's three hues, breathing while the hands work — one
     * breath in 4.8 s, 1 → 1.06 in size and a shade brighter at the top, the desktop capsule's
     * `.ring` (#236.4.6: every working light breathes, none runs) — a still pale ring while
     * they wait. One small view, one sweep gradient — nothing full-screen animates, and
     * nothing at all under the system's reduce-motion setting.
     */
    private class RingView(context: Context) : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        private val rect = RectF()
        private var shader: SweepGradient? = null
        private var breath = 0f
        private var working = false
        private var animator: ValueAnimator? = null

        fun turning(on: Boolean) {
            if (working == on && (animator != null) == (on && !stillMotion(context))) return
            working = on
            animator?.cancel(); animator = null
            breath = if (stillMotion(context)) 0.5f else 0f
            if (on && !stillMotion(context)) {
                animator = ValueAnimator.ofFloat(0f, 1f).apply {
                    duration = BREATH_MS
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = null
                    addUpdateListener { breath = breathe(it.animatedValue as Float); invalidate() }
                    start()
                }
            }
            invalidate()
        }

        override fun onDetachedFromWindow() {
            animator?.cancel(); animator = null
            super.onDetachedFromWindow()
        }

        override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
            val stroke = resources.displayMetrics.density * 1.5f
            paint.strokeWidth = stroke
            rect.set(stroke, stroke, w - stroke, h - stroke)
            shader = SweepGradient(w / 2f, h / 2f, intArrayOf(ACCENT, VIOLET, CYAN, ACCENT), floatArrayOf(0f, 0.38f, 0.72f, 1f))
        }

        override fun onDraw(canvas: Canvas) {
            if (working) {
                paint.shader = shader
                // brightness 0.9 → 1.1 on the desktop; on a canvas, the alpha 0.86 → 1
                paint.alpha = (255 * (0.86f + 0.14f * breath)).toInt()
                val scale = 1f + 0.06f * breath
                canvas.save()
                canvas.scale(scale, scale, width / 2f, height / 2f)
                canvas.drawOval(rect, paint)
                canvas.restore()
            } else {
                paint.shader = null
                paint.color = 0x59FFFFFF
                canvas.drawOval(rect, paint)
            }
        }
    }

    /**
     * Four thin bars breathing in turn — the desktop pill's sign that something is happening:
     * each 35 % → 100 % tall and 0.6 → 1 opaque over the same 4.8 s breath, each 0.6 s behind
     * the last. Still, full height, under reduce-motion.
     */
    private class BarsView(context: Context) : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private var t = 0f
        private var animator: ValueAnimator? = null

        fun start() {
            if (animator != null || stillMotion(context)) { invalidate(); return }
            animator = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = BREATH_MS
                repeatCount = ValueAnimator.INFINITE
                interpolator = null
                addUpdateListener { t = it.animatedValue as Float; invalidate() }
                start()
            }
        }

        fun stop() {
            animator?.cancel(); animator = null
        }

        override fun onDetachedFromWindow() {
            stop()
            super.onDetachedFromWindow()
        }

        override fun onDraw(canvas: Canvas) {
            val d = resources.displayMetrics.density
            val barW = 3f * d
            val gap = 2.5f * d
            val total = 4 * barW + 3 * gap
            var x = (width - total) / 2f
            val still = stillMotion(context)
            for (i in 0 until 4) {
                // each bar 0.6 s behind the last (desktop: animation-delay 0.6 s · i)
                val phase = ((t - i * BAR_LAG) % 1f + 1f) % 1f
                val eased = if (still) 1f else breathe(phase)
                val h = height * (0.35f + 0.65f * eased)
                paint.shader = null
                paint.color = if (i % 2 == 0) CYAN else ACCENT
                paint.alpha = (255 * (0.6f + 0.4f * eased)).toInt()
                canvas.drawRoundRect(x, height - h, x + barW, height.toFloat(), barW / 2f, barW / 2f, paint)
                x += barW + gap
            }
        }
    }

    private fun faceBitmap(): Bitmap? = runCatching { AvatarStore.bitmap(AgentMood.WORKING) }.getOrNull()

    private fun statusBarHeight(): Int {
        val id = context.resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (id > 0) context.resources.getDimensionPixelSize(id) else dp(24)
    }

    /** Brings nanoMuse's chat back to the front. */
    fun bringAppToFront(sessionId: String?) {
        try {
            val intent = Intent(context, Class.forName("com.openminis.app.MainActivity")).apply {
                if (!sessionId.isNullOrBlank()) data = android.net.Uri.parse("minis://session/$sessionId")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            context.startActivity(intent)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "bring to front failed: ${t.message}")
        }
    }

    companion object {
        private const val TAG = "HandsCapsule"
        /** The stage's three hues (HandsStage, the desktop stage's --accent / --violet / --cyan). */
        private const val ACCENT = 0xFF0A66E4.toInt()
        private const val VIOLET = 0xFF7C5CFF.toInt()
        private const val CYAN = 0xFF06B6D4.toInt()
        /** The pill's ink and its hairline edge, as on the desktop: rgba(17,18,24,.82) and white at 10 %. */
        private const val INK = 0xD1111218.toInt()
        private const val EDGE = 0x1AFFFFFF
        /** Stop: a low-saturation red, not an alarm. */
        private const val STOP_RED = 0xFF9B3B3B.toInt()
        /** One breath: 2.4 s in, 2.4 s out — the rhythm of every working light on every client. */
        private const val BREATH_MS = 4800L
        /** Each bar 0.6 s behind the last, as a share of the breath. */
        private const val BAR_LAG = 600f / BREATH_MS

        /** 0 → 1 → 0 over one cycle, eased at both ends (CSS ease-in-out, near enough). */
        private fun breathe(phase: Float): Float = 0.5f - 0.5f * kotlin.math.cos(phase * 2f * Math.PI.toFloat())

        /** The system's reduce-motion setting: animator scale 0 → every light holds still. */
        private fun stillMotion(context: Context): Boolean =
            android.provider.Settings.Global.getFloat(context.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
}
