package io.github.nanomuse.feed

import org.json.JSONObject
import org.mozilla.javascript.Context
import org.mozilla.javascript.ContextFactory
import org.mozilla.javascript.Function
import org.mozilla.javascript.Script
import java.util.concurrent.TimeUnit

/** Only the bundled rules are code. Provider responses, choices and chat input cross as strings. */
internal class PublicWatchEngine(private val source: String) {
    private val deadline = ThreadLocal<Long>()
    private val engine = object : ContextFactory() {
        override fun makeContext(): Context = super.makeContext().apply {
            optimizationLevel = -1 // interpreted on ART
            maximumInterpreterStackDepth = 256
            languageVersion = Context.VERSION_ES6
            setClassShutter { false }
            instructionObserverThreshold = 16_384
        }

        override fun observeInstructionCount(cx: Context, count: Int) {
            check(System.nanoTime() < (deadline.get() ?: return)) { "Public source processing timed out" }
        }
    }
    @Volatile private var program: Script? = null

    enum class Entry(val function: String) { LEDGER("NanoMuseWatch"), READER("NanoMusePublicRead") }

    fun run(entry: Entry, input: JSONObject): JSONObject {
        deadline.set(System.nanoTime() + TimeUnit.SECONDS.toNanos(6))
        try {
            return engine.call { cx ->
                val compiled = program ?: synchronized(this) {
                    program ?: cx.compileString(source, "public-watches.js", 1, null).also { program = it }
                }
                val scope = cx.initSafeStandardObjects()
                compiled.exec(cx, scope)
                val fn = scope.get(entry.function, scope) as Function
                JSONObject(Context.toString(fn.call(cx, scope, scope, arrayOf(input.toString()))))
            }
        } finally {
            deadline.remove()
        }
    }
}
