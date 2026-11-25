package com.openminis.app.provider

import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.provider.anthropic.AnthropicProvider
import com.openminis.app.provider.gemini.GeminiProvider
import com.openminis.app.provider.openai.OpenAIProvider
import io.github.nanomuse.net.awaitBlockedBodyReader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okio.BufferedSource
import okio.buffer
import okio.source
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException

@RunWith(Parameterized::class)
class VisionRequestCancellationTest(private val protocol: String, private val bodyStarted: Boolean) {
    companion object {
        @JvmStatic @Parameterized.Parameters(name = "{0}, body started={1}")
        fun cases() = listOf("OpenAI", "Anthropic", "Gemini").flatMap { protocol ->
            listOf(false, true).map { bodyStarted -> arrayOf(protocol, bodyStarted) }
        }
    }

    // A real HTTP/1.1 peer lets the test see the socket close while the server is still holding
    // the reply. Waiting for the coroutine alone would miss an abandoned network call.
    @Test fun cancellingOneDecisionDisconnectsOnlyThatRequest() = runBlocking {
        ServerSocket(0, 8, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 5_000
            val base = "http://127.0.0.1:${server.localPort}"
            val provider: LLMProvider = when (protocol) {
                "OpenAI" -> OpenAIProvider(apiKey = "fixture", model = LLMModel.gpt4oMini, basePath = base)
                "Anthropic" -> AnthropicProvider(apiKey = "fixture", model = LLMModel.claudeHaiku45, basePath = base)
                else -> GeminiProvider(apiKey = "fixture", model = LLMModel.gemini25Flash, basePath = base)
            }
            fun request() = async(Dispatchers.IO) {
                provider.sendMessage(listOf(LLMMessage(LLMMessage.Role.USER, "Read the screen")), systemPrompt = null, maxTokens = 64)
            }
            val first = request()
            server.accept().use { stalled ->
                val incoming = readRequest(stalled)
                if (bodyStarted) {
                    writeHead(stalled, 4096)
                    stalled.getOutputStream().write(' '.code)
                    stalled.getOutputStream().flush()
                    val reading = if (protocol == "OpenAI") {
                        awaitBlockedBodyReader("OpenAIProvider.kt", "readLine", "java.io.BufferedReader")
                    } else {
                        awaitBlockedBodyReader("${protocol}Provider.kt", "string", "okhttp3.")
                    }
                    assertTrue("the real provider must be blocked reading the response body", reading)
                }
                val other = request()
                server.accept().use { sibling ->
                    readRequest(sibling)
                    first.cancel()
                    val closed = try { incoming.exhausted() } catch (failure: SocketException) {
                        if (failure.message?.contains("reset", ignoreCase = true) == true) true else throw failure
                    }
                    assertTrue("peer must observe EOF before it releases any reply", closed)
                    withTimeout(3_000) { first.join() }
                    val answer = when (protocol) {
                        "OpenAI" -> "data: " + """{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}""" + "\n\ndata: [DONE]\n\n"
                        "Anthropic" -> """{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn"}"""
                        else -> """{"candidates":[{"content":{"parts":[{"text":"ok"}]},"finishReason":"STOP"}]}"""
                    }.toByteArray()
                    writeHead(sibling, answer.size)
                    sibling.getOutputStream().write(answer)
                    sibling.getOutputStream().flush()
                    assertEquals("ok", withTimeout(5_000) { other.await() }.text)
                }
            }
        }
    }

    private fun writeHead(socket: Socket, length: Int) {
        val type = if (protocol == "OpenAI") "text/event-stream" else "application/json"
        val headers = "HTTP/1.1 200 OK\r\nContent-Type: $type\r\nContent-Length: $length\r\nConnection: close\r\n\r\n"
        socket.getOutputStream().write(headers.toByteArray())
        socket.getOutputStream().flush()
    }

    private fun readRequest(socket: Socket): BufferedSource {
        socket.soTimeout = 3_000
        val source = socket.source().buffer()
        assertTrue(source.readUtf8LineStrict().startsWith("POST "))
        val headers = generateSequence { source.readUtf8LineStrict().takeIf(String::isNotEmpty) }.toList()
        val length = headers.single { it.startsWith("Content-Length:", ignoreCase = true) }.substringAfter(':').trim().toLong()
        source.skip(length)
        return source
    }
}
