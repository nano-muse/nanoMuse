package io.github.nanomuse.hands

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Path
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import com.openminis.app.R
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.ThinkingLevel
import com.openminis.app.logging.AppLogger
import com.openminis.app.provider.ProviderFactory
import com.openminis.app.sandbox.PRootKernel
import com.openminis.app.service.SessionActivityTracker
import io.github.nanomuse.guard.GateOutcome
import io.github.nanomuse.guard.GuardKind
import io.github.nanomuse.guard.RiskAssessment
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskDecision
import io.github.nanomuse.guard.RiskGate
import io.github.nanomuse.guard.RiskRequest
import io.github.nanomuse.guard.TapWords
import io.github.nanomuse.status.KeepAwake
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * One task on the phone's screen, start to finish: screenshot → screen model → one action →
 * again, until the model says it is done, the user says stop, or the step budget runs out.
 *
 * Perception is the screenshot alone. The accessibility service performs the gestures and
 * takes the screenshot; the only node it ever touches is the field that has the cursor, to
 * type into it — and to refuse when that field is a password field.
 *
 * Runs on the sandbox worker thread that carries the `nanomuse-hands` call, so everything here
 * blocks; the capsule's buttons arrive from the main thread through flags and latches.
 */
class HandsOperator(private val context: Context) {

    data class Options(
        val task: String,
        val appHint: String? = null,
        /** A cap on steps for callers that want one; 0 (the default) means the run goes on until the task is done, the person stops it, or the time limit. */
        val maxSteps: Int = DEFAULT_MAX_STEPS,
        val sessionId: String? = null,
        val agentName: String = "nanoMuse",
        val language: String = "the user's language",
    )

    sealed class Outcome(val code: String) {
        data class Done(val answer: String) : Outcome("done")
        data class Infeasible(val message: String) : Outcome("infeasible")
        data class Stopped(val message: String) : Outcome("stopped")
        data class NeedsUser(val question: String) : Outcome("needs_user")
        data class Failed(val message: String) : Outcome("failed")
    }

    data class Result(
        val outcome: Outcome,
        val steps: Int,
        val runId: String,
        /** `minis://attachments/hands/<run>/step-N.jpg` of the last screen, if any. */
        val lastScreen: String?,
        val tracePath: String?,
        /** One line per step, for the tool result. */
        val log: List<String>,
        val model: String?,
    )

    private class Turn(val userText: String, val image: ByteArray?, var assistant: String)

    private val stop = AtomicBoolean(false)
    private val stopReason = AtomicReference<String?>(null)
    private val userSignal = AtomicReference<CountDownLatch?>(null)
    private val capsule = HandsCapsule(context)

    /** The session this run's approval cards are filed under; see [ownPendingRequest]. */
    @Volatile private var gateSession: String? = null

    /**
     * The approval card waiting on this run, if the one on top is ours: a tap or an Enter the
     * hands asked about, not a shell or browser request of some other conversation.
     */
    private fun ownPendingRequest(): RiskRequest? =
        RiskGate.pending.value?.takeIf { it.kind == GuardKind.SCREEN && it.sessionId == gateSession }

    /**
     * Ends the run after the action in flight; from the capsule, the chat or the settings page.
     * A card the run is waiting on is answered with Deny, so Stop takes effect at once.
     */
    fun requestStop(reason: String = "the user tapped Stop") {
        stopReason.compareAndSet(null, reason)
        stop.set(true)
        ownPendingRequest()?.let { RiskGate.decide(it.id, RiskDecision.DENY) }
        userSignal.get()?.countDown()
    }

    fun run(opts: Options): Result {
        val runId = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        val log = mutableListOf<String>()
        val traceDir = traceDir(opts.sessionId, runId)
        var lastScreen: String? = null
        var steps = 0
        val model = Hands.screenModel(context)
        Hands.setActive(true)
        Hands.current = this
        gateSession = opts.sessionId ?: "hands"
        SessionActivityTracker.setCameraSuppressActive(true) // one capsule at a time: ours, not OpenMinis'
        capsule.onStop = { requestStop() }
        capsule.onContinue = { userSignal.get()?.countDown() }
        capsule.onOpenApp = { capsule.bringAppToFront(opts.sessionId) }
        // the approval answered where the person is: the same request the chat card shows,
        // and only ours (a shell or browser card of another conversation is not the capsule's to answer)
        capsule.onAllow = { ownPendingRequest()?.let { RiskGate.decide(it.id, RiskDecision.ALLOW_ONCE) } }
        capsule.onDeny = { ownPendingRequest()?.let { RiskGate.decide(it.id, RiskDecision.DENY) } }
        val started = System.currentTimeMillis()
        try {
            val svc = MinisAccessibilityService.getInstance()
                ?: return finish(Outcome.Failed("the accessibility service is not running"), steps, runId, lastScreen, traceDir, log, model?.label)
            if (Build.VERSION.SDK_INT < Hands.MIN_SDK) {
                return finish(Outcome.Failed("screenshots need Android 11"), steps, runId, lastScreen, traceDir, log, model?.label)
            }
            if (model == null) return finish(Outcome.Failed("no model that can see pictures is configured"), steps, runId, lastScreen, traceDir, log, null)
            val provider = ProviderFactory.create(model.instance, model.apiKey, model.entry.model, context)
            val apps = HandsApps.launchable(context)
            val system = HandsPrompt.system(opts.task, apps.map { it.label }.take(MAX_APPS_IN_PROMPT), opts.agentName, opts.language)
            val turns = mutableListOf<Turn>()
            var lastResult: String? = null
            var formatErrors = 0
            var blackScreens = 0
            var modelErrors = 0
            // the same action on an unchanged screen: a note at the third, a stop at the sixth
            val watch = HandsLoopWatch()
            var loopNote: String? = null

            // The app the caller named comes first, before the model looks.
            opts.appHint?.takeIf { it.isNotBlank() }?.let { hint ->
                val app = HandsApps.resolve(context, hint)
                lastResult = if (app != null && HandsApps.open(context, app)) {
                    Thread.sleep(OPEN_APP_SETTLE_MS); "opened ${app.label}."
                } else "no installed app matches “$hint”; open the one you need yourself."
                log += "open $hint → $lastResult"
            }

            while (opts.maxSteps <= 0 || steps < opts.maxSteps) {
                if (stop.get()) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                if (System.currentTimeMillis() - started > MAX_RUN_MS) {
                    return finish(Outcome.Stopped("the run hit its time limit"), steps, runId, lastScreen, traceDir, log, model.label)
                }
                steps++
                KeepAwake.a11yTouched()
                capsule.working(steps, context.getString(com.openminis.app.R.string.nm_hands_looking))

                // ── look ──
                val shot = screenshot(svc) ?: return finish(Outcome.Failed("could not take a screenshot"), steps, runId, lastScreen, traceDir, log, model.label)
                val screenW = shot.width
                val screenH = shot.height
                val jpeg = encode(shot)
                shot.recycle()
                lastScreen = save(traceDir, steps, jpeg, runId)
                if (jpeg.black) {
                    blackScreens++
                    if (blackScreens > 2) return finish(Outcome.Infeasible("the screen stays protected (black screenshot); the app does not allow it to be read"), steps, runId, lastScreen, traceDir, log, model.label)
                    log += "step $steps: protected screen — handed to the user"
                    val cont = waitForUser(context.getString(com.openminis.app.R.string.nm_hands_protected_screen))
                    if (!cont) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                    lastResult = "the screen was protected (payment or banking); the user did that part and says to continue."
                    continue
                }
                blackScreens = 0

                // ── think ──
                val messages = buildMessages(turns, HandsPrompt.turnText(steps, lastResult), jpeg.bytes)
                val reply = try {
                    runBlocking {
                        withTimeout(MODEL_TIMEOUT_MS) {
                            provider.sendMessage(messages, system, maxTokens = 1024, temperature = 0.0, thinkingLevel = ThinkingLevel.OFF).text
                        }
                    }
                } catch (t: Throwable) {
                    modelErrors++
                    AppLogger.warning(TAG, "model call failed: ${t.message}")
                    if (modelErrors >= 3) return finish(Outcome.Failed("the screen model failed three times: ${t.message}"), steps, runId, lastScreen, traceDir, log, model.label)
                    steps--
                    Thread.sleep(1500)
                    continue
                }
                if (stop.get()) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                val turn = Turn(HandsPrompt.turnText(steps, lastResult), jpeg.bytes, reply)
                turns += turn
                val parsed = try {
                    HandsAction.parse(reply)
                } catch (e: HandsAction.Companion.FormatError) {
                    formatErrors++
                    if (formatErrors >= 3) return finish(Outcome.Failed("the screen model did not answer in the action format (${e.message})"), steps, runId, lastScreen, traceDir, log, model.label)
                    lastResult = "your reply could not be read (${e.message}); answer with `Thought:` and one JSON `Action:` only."
                    log += "step $steps: unreadable reply"
                    trace(traceDir, steps, "", reply, lastResult, lastScreen)
                    continue
                }
                formatErrors = 0
                val action = parsed.action
                capsule.working(steps, parsed.thought.ifBlank { action.describe() }.take(140))
                log += "step $steps: ${action.describe()}" + (parsed.thought.takeIf { it.isNotBlank() }?.let { " — ${it.take(100)}" } ?: "")

                // ── the same thing again on the same screen? ──
                when (watch.step(jpeg.print, action)) {
                    HandsLoopWatch.Verdict.STOP -> {
                        val why = HandsLoopWatch.stopReason(action)
                        log += "step $steps: $why"
                        trace(traceDir, steps, parsed.thought, reply, why, lastScreen)
                        return finish(Outcome.Infeasible(why), steps, runId, lastScreen, traceDir, log, model.label)
                    }
                    HandsLoopWatch.Verdict.NOTE -> {
                        log += "step $steps: the same action on an unchanged screen, ${watch.streak} times running"
                        loopNote = HandsLoopWatch.NOTE
                    }
                    HandsLoopWatch.Verdict.FINE -> loopNote = null
                }

                // ── act ──
                when (action) {
                    is HandsAction.Status -> {
                        trace(traceDir, steps, parsed.thought, reply, "finished", lastScreen)
                        return finish(
                            if (action.complete) Outcome.Done(action.answer.ifBlank { parsed.thought }) else Outcome.Infeasible(action.answer.ifBlank { parsed.thought }),
                            steps, runId, lastScreen, traceDir, log, model.label,
                        )
                    }
                    is HandsAction.AskUser -> {
                        trace(traceDir, steps, parsed.thought, reply, "asked the user", lastScreen)
                        return finish(Outcome.NeedsUser(action.question.ifBlank { parsed.thought }), steps, runId, lastScreen, traceDir, log, model.label)
                    }
                    is HandsAction.TakeOver -> {
                        val cont = waitForUser(action.reason.ifBlank { parsed.thought })
                        if (!cont) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                        lastResult = "the user did it themselves and says to continue; look at the screen as it is now."
                    }
                    is HandsAction.Click, is HandsAction.DoubleTap, is HandsAction.LongPress -> {
                        val (px, py) = when (action) {
                            is HandsAction.Click -> action.at.toPixels(screenW, screenH)
                            is HandsAction.DoubleTap -> action.at.toPixels(screenW, screenH)
                            is HandsAction.LongPress -> action.at.toPixels(screenW, screenH)
                            else -> 0 to 0
                        }
                        // the label the model gave, read next to what the screen itself says is there
                        val target = action.tapTarget.orEmpty()
                        val gate = approveTap(svc, opts.sessionId, target, ScreenWords.at(svc, px, py))
                        if (gate.denied != null) {
                            trace(traceDir, steps, parsed.thought, reply, "refused: ${gate.denied}", lastScreen)
                            return finish(Outcome.Infeasible("the user did not allow the tap “${gate.shown.take(40)}” — ${gate.denied}"), steps, runId, lastScreen, traceDir, log, model.label)
                        }
                        // A remembered approval, or a payment that ran on one: the chat model
                        // sees it in the log and tells the user where it lives.
                        gate.notice?.let { log += it }
                        if (stop.get()) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                        // The ring first, where the finger is about to land; the capsule steps
                        // aside when it is in the way and lets the touch through while it lands.
                        capsule.dodge(px, py)
                        capsule.stage.aim(px, py, fxLabel(action))
                        Thread.sleep(AIM_MS)
                        val ok = capsule.passThrough {
                            when (action) {
                                is HandsAction.LongPress -> { capsule.stage.hold(LONG_PRESS_MS); tap(svc, px, py, LONG_PRESS_MS) }
                                is HandsAction.DoubleTap -> tap(svc, px, py, 50).also { capsule.stage.ripple(px, py); Thread.sleep(90) } && tap(svc, px, py, 50)
                                else -> tap(svc, px, py, 60)
                            }
                        }
                        capsule.stage.ripple(px, py)
                        lastResult = if (ok) "${action.describe()} at ($px, $py) was performed." else "the gesture at ($px, $py) was rejected by the system; try again or another way."
                        Thread.sleep(TAP_SETTLE_MS)
                    }
                    is HandsAction.Swipe -> {
                        val (x1, y1) = action.from.toPixels(screenW, screenH)
                        val (x2, y2) = action.to.toPixels(screenW, screenH)
                        val ok = sweep(svc, x1, y1, x2, y2, SWIPE_MS, fxLabel(action))
                        lastResult = if (ok) "swiped from ($x1, $y1) to ($x2, $y2)." else "the swipe was rejected by the system."
                        Thread.sleep(SWIPE_SETTLE_MS)
                    }
                    is HandsAction.Scroll -> {
                        val cx = screenW / 2
                        val cy = screenH / 2
                        val dx = screenW * 35 / 100
                        val dy = screenH * 30 / 100
                        val (from, to) = when (action.direction) {
                            "down" -> (cx to cy + dy / 2 + dy / 4) to (cx to cy - dy / 2 - dy / 4)
                            "up" -> (cx to cy - dy / 2 - dy / 4) to (cx to cy + dy / 2 + dy / 4)
                            "left" -> (cx + dx to cy) to (cx - dx to cy)
                            else -> (cx - dx to cy) to (cx + dx to cy)
                        }
                        val ok = sweep(svc, from.first, from.second, to.first, to.second, SCROLL_MS, fxLabel(action))
                        lastResult = if (ok) "scrolled ${action.direction}." else "the scroll was rejected by the system."
                        Thread.sleep(SWIPE_SETTLE_MS)
                    }
                    is HandsAction.InputText -> {
                        if (!TapWords.looksSecret(action.field)) capsule.stage.say(fxLabel(action))
                        lastResult = typeText(svc, action)
                        if (lastResult == HANDOFF) {
                            val cont = waitForUser(context.getString(com.openminis.app.R.string.nm_hands_secret_field))
                            if (!cont) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                            lastResult = "that field is a password or code field, which you never type; the user filled it in and says to continue."
                        }
                        Thread.sleep(TAP_SETTLE_MS)
                    }
                    HandsAction.KeyboardEnter -> {
                        // Enter in a messenger's field *is* the send button: the same card a tap on “Send” gets.
                        val gate = approveEnter(svc, opts.sessionId)
                        if (gate.denied != null) {
                            trace(traceDir, steps, parsed.thought, reply, "refused: ${gate.denied}", lastScreen)
                            return finish(Outcome.Infeasible("the user did not allow sending with Enter — ${gate.denied}"), steps, runId, lastScreen, traceDir, log, model.label)
                        }
                        gate.notice?.let { log += it }
                        if (stop.get()) return finish(Outcome.Stopped(stopReason.get() ?: "stopped"), steps, runId, lastScreen, traceDir, log, model.label)
                        capsule.stage.say(fxLabel(action))
                        lastResult = pressEnter(svc)
                        Thread.sleep(TAP_SETTLE_MS)
                    }
                    is HandsAction.OpenApp -> {
                        val app = HandsApps.resolve(context, action.appName)
                        lastResult = if (app != null && HandsApps.open(context, app)) {
                            capsule.stage.say(context.getString(com.openminis.app.R.string.nm_hands_fx_open, app.label))
                            Thread.sleep(OPEN_APP_SETTLE_MS); "opened ${app.label}."
                        } else {
                            "no installed app matches “${action.appName}”. Installed: " + apps.take(40).joinToString(", ") { it.label } + ". Open it from the home screen if you must."
                        }
                    }
                    HandsAction.Back -> {
                        capsule.stage.say(fxLabel(action))
                        svc.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                        lastResult = "pressed Back."
                        Thread.sleep(TAP_SETTLE_MS)
                    }
                    HandsAction.Home -> {
                        capsule.stage.say(fxLabel(action))
                        svc.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
                        lastResult = "went to the home screen."
                        Thread.sleep(TAP_SETTLE_MS)
                    }
                    is HandsAction.Wait -> {
                        capsule.stage.say(fxLabel(action))
                        Thread.sleep(action.seconds * 1000L)
                        lastResult = "waited ${action.seconds}s."
                    }
                }
                loopNote?.let { note -> lastResult = listOfNotNull(lastResult, note).joinToString(" ") }
                trace(traceDir, steps, parsed.thought, reply, lastResult ?: "", lastScreen)
            }
            return finish(Outcome.Infeasible("the step limit (${opts.maxSteps}) was reached before the task was done"), steps, runId, lastScreen, traceDir, log, model.label)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "run failed: ${t.javaClass.simpleName} ${t.message}")
            return finish(Outcome.Failed("${t.javaClass.simpleName}: ${t.message}"), steps, runId, lastScreen, traceDir, log, model?.label)
        } finally {
            capsule.hide()
            Hands.current = null
            Hands.setActive(false)
            SessionActivityTracker.setCameraSuppressActive(false)
            capsule.bringAppToFront(opts.sessionId)
        }
    }

    private fun finish(outcome: Outcome, steps: Int, runId: String, lastScreen: String?, traceDir: File?, log: List<String>, model: String?): Result =
        Result(outcome, steps, runId, lastScreen, traceDir?.let { "/var/minis/attachments/hands/$runId/trace.jsonl" }, log, model)

    // ── the user's turn ────────────────────────────────────────────────────

    /** Shows the take-over card and waits for Continue; false when Stop was tapped or nobody came. */
    private fun waitForUser(reason: String): Boolean {
        val latch = CountDownLatch(1)
        userSignal.set(latch)
        capsule.takeOver(reason)
        val came = latch.await(TAKE_OVER_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        userSignal.set(null)
        if (!came) requestStop("nobody continued within ${TAKE_OVER_TIMEOUT_MS / 60_000} minutes")
        if (stop.get()) return false
        capsule.working(0, context.getString(com.openminis.app.R.string.nm_hands_looking))
        Thread.sleep(600)
        return true
    }

    /** Null [denied] when the tap may go ahead; [notice] is what the chat model should pass on. */
    private data class TapGate(val denied: String? = null, val notice: String? = null, val shown: String = "")

    /**
     * The approval for a tap whose label says pay, send, post or delete. The person is in the
     * operated app, so the capsule takes the answer itself (Allow once / Deny); the card in the
     * chat and the notification show the same request. Money needs the screen lock, which only
     * the card can ask for: the capsule then offers Open.
     */
    private fun approveTap(svc: MinisAccessibilityService, sessionId: String?, target: String, onScreen: String?): TapGate {
        val shown = TapWords.shown(target, onScreen)
        val cls = TapWords.classify(target, onScreen) ?: return TapGate(shown = shown)
        val (pkg, _) = svc.foregroundPackage()
        val appLabel = HandsApps.labelOf(context, pkg)
        val short = shown.take(40)
        val assessment = RiskAssessment(cls, TapWords.reason(cls, short, appLabel), appLabel?.let { "app:$it" })
        val decidable = cls != RiskClass.MONEY
        capsule.approval(context.getString(if (decidable) com.openminis.app.R.string.nm_hands_approval_here else com.openminis.app.R.string.nm_hands_approval_detail, short), decidable)
        val outcome = runBlocking {
            RiskGate.check(sessionId ?: "hands", GuardKind.SCREEN, assessment, preview = "Tap “$short”", pageUrl = appLabel, elementText = short)
        }
        // The user may have opened nanoMuse to answer; put the operated app back in front.
        val (nowPkg, _) = svc.foregroundPackage()
        if (nowPkg == context.packageName && pkg != null && pkg != context.packageName) {
            HandsApps.launchable(context).firstOrNull { it.packageName == pkg }?.let { HandsApps.open(context, it) }
            Thread.sleep(OPEN_APP_SETTLE_MS)
        }
        capsule.working(0, context.getString(com.openminis.app.R.string.nm_hands_looking))
        return when (outcome) {
            is GateOutcome.Allowed -> TapGate(notice = outcome.notice, shown = shown)
            is GateOutcome.Denied -> TapGate(denied = outcome.message, shown = shown)
        }
    }

    /**
     * Enter with the cursor in a message field sends the message (0.1.31): in a messenger, or
     * when the field's hint says so, it takes the outbound card a tap on “Send” would. Enter in
     * a search box, a form or a terminal is an ordinary key.
     */
    private fun approveEnter(svc: MinisAccessibilityService, sessionId: String?): TapGate {
        val node = focusedField(svc) ?: return TapGate()
        val hint = listOfNotNull(node.hintText?.toString(), node.contentDescription?.toString()).joinToString(" ")
        val (pkg, _) = svc.foregroundPackage()
        if (!TapWords.entersSend(pkg, hint)) return TapGate()
        val appLabel = HandsApps.labelOf(context, pkg)
        val where = appLabel ?: context.getString(com.openminis.app.R.string.nm_hands_this_phone)
        val assessment = RiskAssessment(RiskClass.OUTBOUND, "presses Enter in a message field, which sends it ($where)", appLabel?.let { "app:$it" })
        capsule.approval(context.getString(com.openminis.app.R.string.nm_hands_approval_here, context.getString(com.openminis.app.R.string.nm_hands_fx_enter)), decidable = true)
        val outcome = runBlocking {
            RiskGate.check(sessionId ?: "hands", GuardKind.SCREEN, assessment, preview = "Enter → send", pageUrl = appLabel, elementText = context.getString(com.openminis.app.R.string.nm_hands_fx_enter))
        }
        val (nowPkg, _) = svc.foregroundPackage()
        if (nowPkg == context.packageName && pkg != null && pkg != context.packageName) {
            HandsApps.launchable(context).firstOrNull { it.packageName == pkg }?.let { HandsApps.open(context, it) }
            Thread.sleep(OPEN_APP_SETTLE_MS)
        }
        capsule.working(0, context.getString(com.openminis.app.R.string.nm_hands_looking))
        return when (outcome) {
            is GateOutcome.Allowed -> TapGate(notice = outcome.notice, shown = "Enter")
            is GateOutcome.Denied -> TapGate(denied = outcome.message, shown = "Enter")
        }
    }

    // ── the hand ───────────────────────────────────────────────────────────

    private fun tap(svc: MinisAccessibilityService, x: Int, y: Int, durationMs: Long): Boolean {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()); lineTo(x + 0.5f, y + 0.5f) }
        return svc.dispatchSimpleGesture(path, 0L, durationMs)
    }

    private fun swipe(svc: MinisAccessibilityService, x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long): Boolean {
        val path = Path().apply { moveTo(x1.toFloat(), y1.toFloat()); lineTo(x2.toFloat(), y2.toFloat()) }
        return svc.dispatchSimpleGesture(path, 0L, durationMs)
    }

    /** A swipe with its picture: the ring waits [AIM_MS] at the start, then travels with the finger. */
    private fun sweep(svc: MinisAccessibilityService, x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long, label: String): Boolean {
        capsule.dodge(x1, y1)
        capsule.stage.sweep(x1, y1, x2, y2, AIM_MS, durationMs, label)
        Thread.sleep(AIM_MS)
        return capsule.passThrough { swipe(svc, x1, y1, x2, y2, durationMs) }
    }

    /** The action's name for the ring's label, in the user's language. */
    private fun fxLabel(action: HandsAction): String {
        fun target(plain: Int, withTarget: Int, t: String) =
            if (t.isBlank()) context.getString(plain) else context.getString(withTarget, t.take(24))
        return when (action) {
            is HandsAction.Click -> target(R.string.nm_hands_fx_tap, R.string.nm_hands_fx_tap_target, action.target)
            is HandsAction.DoubleTap -> target(R.string.nm_hands_fx_double_tap, R.string.nm_hands_fx_double_tap_target, action.target)
            is HandsAction.LongPress -> target(R.string.nm_hands_fx_hold, R.string.nm_hands_fx_hold_target, action.target)
            is HandsAction.Swipe -> context.getString(R.string.nm_hands_fx_swipe)
            is HandsAction.Scroll -> context.getString(
                when (action.direction) {
                    "up" -> R.string.nm_hands_fx_scroll_up
                    "left" -> R.string.nm_hands_fx_scroll_left
                    "right" -> R.string.nm_hands_fx_scroll_right
                    else -> R.string.nm_hands_fx_scroll_down
                },
            )
            is HandsAction.InputText -> context.getString(R.string.nm_hands_fx_type, action.text.take(24))
            HandsAction.KeyboardEnter -> context.getString(R.string.nm_hands_fx_enter)
            HandsAction.Back -> context.getString(R.string.nm_hands_fx_back)
            HandsAction.Home -> context.getString(R.string.nm_hands_fx_home)
            is HandsAction.OpenApp -> context.getString(R.string.nm_hands_fx_open, action.appName)
            is HandsAction.Wait -> context.getString(R.string.nm_hands_fx_wait, action.seconds)
            else -> ""
        }
    }

    private fun focusedField(svc: MinisAccessibilityService): AccessibilityNodeInfo? =
        svc.rootNodes().firstNotNullOfOrNull { root -> runCatching { root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }.getOrNull() }

    /** Types into the field with the cursor; [HANDOFF] when that field is a secret. */
    private fun typeText(svc: MinisAccessibilityService, action: HandsAction.InputText): String {
        if (TapWords.looksSecret(action.field)) return HANDOFF
        val node = focusedField(svc) ?: return "no text field has the cursor; tap the field first, then type in the next turn."
        if (node.isPassword) return HANDOFF
        val hint = listOfNotNull(node.hintText?.toString(), node.contentDescription?.toString()).joinToString(" ")
        if (hint.isNotBlank() && TapWords.looksSecret(hint)) return HANDOFF
        val ok = svc.setNodeText(node, action.text)
        return if (ok) "typed “${action.text.take(60)}” into the field." else "the field did not accept text (ACTION_SET_TEXT failed); tap it and try again."
    }

    private fun pressEnter(svc: MinisAccessibilityService): String {
        val node = focusedField(svc) ?: return "no text field has the cursor, so there is nothing to submit; tap the search or send button instead."
        val ok = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
        } else false
        return if (ok) "pressed Enter." else "Enter is not available for this field; tap the search or send button on the screen instead."
    }

    // ── the eyes ───────────────────────────────────────────────────────────

    private fun screenshot(svc: MinisAccessibilityService): Bitmap? {
        capsule.hideForCapture()
        try {
            repeat(2) { attempt ->
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    val shot = svc.captureScreenshot(timeoutMs = 6_000)
                    shot.bitmap?.let { return it }
                    AppLogger.warning(TAG, "screenshot failed (${shot.errorCode}): ${shot.errorMessage}")
                }
                if (attempt == 0) Thread.sleep(400)
            }
            return null
        } finally {
            capsule.restore()
        }
    }

    /** [print]: the grey level of each sampled cell, the fingerprint [HandsLoopWatch] compares. */
    private class Jpeg(val bytes: ByteArray, val black: Boolean, val print: IntArray)

    /** Down to [SHOT_WIDTH] px wide (the grid is relative, so nothing is lost for tapping) and JPEG. */
    private fun encode(shot: Bitmap): Jpeg {
        val scale = SHOT_WIDTH.toFloat() / shot.width
        val scaled = if (scale < 1f) Bitmap.createScaledBitmap(shot, SHOT_WIDTH, (shot.height * scale).toInt().coerceAtLeast(1), true) else shot
        val print = sample(scaled)
        val black = looksBlack(print)
        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
        if (scaled !== shot) scaled.recycle()
        return Jpeg(out.toByteArray(), black, print)
    }

    /** A grid of 12 × 20 pixels, each as a grey level 0–255: enough to tell a black frame and an unchanged screen. */
    private fun sample(b: Bitmap): IntArray {
        val out = ArrayList<Int>(240)
        val stepX = (b.width / 12).coerceAtLeast(1)
        val stepY = (b.height / 20).coerceAtLeast(1)
        var y = stepY / 2
        while (y < b.height) {
            var x = stepX / 2
            while (x < b.width) {
                val c = b.getPixel(x, y)
                out += (Color.red(c) * 299 + Color.green(c) * 587 + Color.blue(c) * 114) / 1000
                x += stepX
            }
            y += stepY
        }
        return out.toIntArray()
    }

    /** A FLAG_SECURE page comes back as a black frame: nearly every sampled cell is dark. */
    private fun looksBlack(print: IntArray): Boolean {
        if (print.isEmpty()) return false
        val dark = print.count { it < 12 }
        return dark * 100 / print.size >= 98
    }

    private fun buildMessages(turns: List<Turn>, currentText: String, current: ByteArray): List<LLMMessage> {
        val out = mutableListOf<LLMMessage>()
        val withImage = turns.size - HISTORY_IMAGES
        turns.forEachIndexed { i, t ->
            val parts = mutableListOf<AgentContentPart>(AgentContentPart.Text(t.userText))
            if (i >= withImage && t.image != null) parts += AgentContentPart.ImageData(t.image, "image/jpeg")
            else parts += AgentContentPart.Text(HandsPrompt.OLDER_SCREEN)
            out += LLMMessage(LLMMessage.Role.USER, content = t.userText, contentParts = parts)
            out += LLMMessage(LLMMessage.Role.ASSISTANT, content = t.assistant)
        }
        out += LLMMessage(
            LLMMessage.Role.USER,
            content = currentText,
            contentParts = listOf(AgentContentPart.Text(currentText), AgentContentPart.ImageData(current, "image/jpeg")),
        )
        return out
    }

    // ── the trace ──────────────────────────────────────────────────────────

    private fun traceDir(sessionId: String?, runId: String): File? {
        val base = if (sessionId != null) File(context.filesDir, "minis-sessions/$sessionId/attachments")
        else PRootKernel.resolveHostPath("/var/minis/attachments")
        val hands = base?.let { File(it, "hands") } ?: return null
        // the person's screen is not kept without bound: older runs keep their trace and last screen
        runCatching { HandsTraces.prune(hands) }
        return File(hands, runId).apply { mkdirs() }
    }

    private fun save(dir: File?, step: Int, jpeg: Jpeg, runId: String): String? {
        dir ?: return null
        return runCatching {
            File(dir, "step-$step.jpg").writeBytes(jpeg.bytes)
            "minis://attachments/hands/$runId/step-$step.jpg"
        }.getOrNull()
    }

    private fun trace(dir: File?, step: Int, thought: String, reply: String, result: String, screen: String?) {
        dir ?: return
        runCatching {
            val line = JSONObject()
                .put("step", step).put("at", System.currentTimeMillis())
                .put("thought", thought).put("reply", reply).put("result", result).put("screen", screen ?: JSONObject.NULL)
            File(dir, "trace.jsonl").appendText(line.toString() + "\n")
        }
    }

    companion object {
        private const val TAG = "Hands"
        /** No step cap: a task takes as many steps as it takes (the time limit and the Stop button remain). */
        const val DEFAULT_MAX_STEPS = 0
        private const val MAX_APPS_IN_PROMPT = 120
        private const val SHOT_WIDTH = 720
        private const val JPEG_QUALITY = 78
        private const val HISTORY_IMAGES = 1
        private const val MODEL_TIMEOUT_MS = 90_000L
        private const val TAKE_OVER_TIMEOUT_MS = 5 * 60_000L
        private const val MAX_RUN_MS = 30 * 60_000L
        private const val TAP_SETTLE_MS = 900L
        private const val SWIPE_SETTLE_MS = 1100L
        private const val OPEN_APP_SETTLE_MS = 1800L
        /** The ring shows this long before the finger lands, so the eye gets there first. */
        private const val AIM_MS = 260L
        private const val LONG_PRESS_MS = 900L
        private const val SWIPE_MS = 350L
        private const val SCROLL_MS = 400L
        private const val HANDOFF = "\u0000handoff"
    }
}
