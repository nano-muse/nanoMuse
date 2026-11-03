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
import android.view.View
import android.view.ViewOutlineProvider
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
 * The capsule that sits over the operated app while the hands work: the face in a slowly
 * turning three-hue ring, four activity bars, what is being done, and **Stop**. When the hands
 * need the user it grows into a card — *Your turn* with **Continue** for a login or a code,
 * *Waiting for your approval* with **Open** for a tap that needs the card in the chat — and the
 * ring stands still. The same pill the desktop stage shows (desktop/app/src/renderer/stage):
 * dark and translucent with a hairline edge, sliding in from the top. Plain views on a
 * `TYPE_APPLICATION_OVERLAY` window, so it lives outside any Activity; every call is safe from
 * any thread.
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
class HandsCapsule(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
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

    /** What the hands draw on the screen while they work. */
    val stage = HandsStage(context)

    var onStop: (() -> Unit)? = null
    var onContinue: (() -> Unit)? = null
    var onOpenApp: (() -> Unit)? = null
    /** The approval answered on the capsule itself, where the person already is (0.1.33). */
    var onAllow: (() -> Unit)? = null
    var onDeny: (() -> Unit)? = null

    private fun dp(v: Int): Int = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), context.resources.displayMetrics).toInt()

    /** Shows (or updates) the working state. */
    fun working(step: Int, detail: String) = onMain {
        ensure()
        stage.mood(HandsStage.Mood.WORKING)
        ring?.turning(true)
        bars?.visibility = View.VISIBLE
        titleView?.text = context.getString(R.string.nm_hands_step, step)
        detailView?.text = detail
        continueBtn?.visibility = View.GONE
        openBtn?.visibility = View.GONE
        allowBtn?.visibility = View.GONE
        denyBtn?.visibility = View.GONE
    }

    /** The hands wait for the user to do something on the phone. */
    fun takeOver(reason: String) = onMain {
        ensure()
        stage.mood(HandsStage.Mood.WAITING)
        stage.clear()
        ring?.turning(false)
        bars?.visibility = View.GONE
        titleView?.text = context.getString(R.string.nm_hands_your_turn)
        detailView?.text = reason.ifBlank { context.getString(R.string.nm_hands_your_turn_detail) }
        continueBtn?.visibility = View.VISIBLE
        openBtn?.visibility = View.GONE
        allowBtn?.visibility = View.GONE
        denyBtn?.visibility = View.GONE
    }

    /**
     * A tap waits for approval. [decidable]: Allow once / Deny right here on the capsule — the
     * person is in the operated app, not in nanoMuse. Money is confirmed with the screen lock,
     * which only the card in the chat can do: then the capsule offers Open instead.
     */
    fun approval(what: String, decidable: Boolean = false) = onMain {
        ensure()
        stage.mood(HandsStage.Mood.WAITING)
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
        val v = root
        root = null; params = null; titleView = null; detailView = null; continueBtn = null; openBtn = null; allowBtn = null; denyBtn = null
        ring?.turning(false); ring = null
        bars?.stop(); bars = null
        if (v != null) {
            // slide back up the way it came, then let go of the window
            v.animate().alpha(0f).translationY(-dp(20).toFloat()).scaleX(0.96f).scaleY(0.96f)
                .setDuration(200L).setInterpolator(DecelerateInterpolator())
                .withEndAction { runCatching { wm.removeView(v) } }.start()
        }
        stage.hide()
    }

    /** Hides the capsule and the stage for a screenshot and waits until the frame is gone; [restore] brings them back. */
    fun hideForCapture() {
        val latch = CountDownLatch(1)
        main.post {
            root?.visibility = View.INVISIBLE
            stage.setVisible(false)
            latch.countDown()
        }
        latch.await(300, TimeUnit.MILLISECONDS)
        // One more frame so the compositor has dropped it.
        Thread.sleep(80)
    }

    fun restore() = onMain {
        root?.visibility = View.VISIBLE
        stage.setVisible(true)
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

    private fun ensure() {
        if (root != null) return
        stage.show() // first, so the capsule's window sits above it
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
            // slides in from the top the way the desktop pill does
            alpha = 0f
            translationY = -dp(28).toFloat()
            scaleX = 0.96f; scaleY = 0.96f
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
        pill.addView(faceBox); pill.addView(barsView); pill.addView(texts); pill.addView(cont); pill.addView(open); pill.addView(allow); pill.addView(deny); pill.addView(stop)

        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        val dm = context.resources.displayMetrics
        val params = WindowManager.LayoutParams(
            minOf((dm.widthPixels * 0.94f).toInt(), dp(420)),
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = statusBarHeight() + dp(6)
        }
        try {
            wm.addView(pill, params)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "addView failed: ${t.message}")
            return
        }
        pill.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f).setDuration(320L).setInterpolator(DecelerateInterpolator(1.6f)).start()
        ringView.turning(true)
        barsView.start()
        root = pill; this.params = params; titleView = title; detailView = detail; continueBtn = cont; openBtn = open; allowBtn = allow; denyBtn = deny
        ring = ringView; bars = barsView
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
