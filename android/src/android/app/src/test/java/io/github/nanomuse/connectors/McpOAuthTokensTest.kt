package io.github.nanomuse.connectors

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.fail
import org.junit.Test

class McpOAuthTokensTest {
    @Test
    fun `exchange requests JSON while keeping form encoded request body`() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"access_token":"fixture-access"}"""))
            val form = "grant_type=authorization_code&code=a%2Bb"
            OkHttpClient().newCall(McpOAuthTokens.request(server.url("/token").toString(), form))
                .execute().use { response ->
                    assertEquals("fixture-access", McpOAuthTokens.parse(response.code, response.body!!.string()).accessToken)
                }
            val sent = server.takeRequest()
            assertEquals("application/json", sent.getHeader("Accept"))
            assertEquals("application/x-www-form-urlencoded; charset=utf-8", sent.getHeader("Content-Type"))
            assertEquals(form, sent.body.readUtf8())
        }
    }

    @Test
    fun `invalid endpoint errors do not expose the URL or form`() {
        try {
            McpOAuthTokens.request("invalid fixture endpoint", "code=fixture-code")
            fail("Expected invalid endpoint rejection")
        } catch (error: McpOAuthTokens.Failure) {
            assertEquals("invalid_token_endpoint", error.code)
            assertEquals("invalid_token_endpoint", error.message)
            assertNull(error.cause)
        }
    }

    @Test
    fun `JSON tokens preserve refresh and expiry`() {
        val tokens = McpOAuthTokens.parse(200, """{"access_token":"fixture-access","refresh_token":"fixture-refresh","expires_in":3600}""")
        assertEquals("fixture-refresh", tokens.refreshToken)
        assertEquals(3600L, tokens.expiresIn)
        assertNull(McpOAuthTokens.parse(200, """{"access_token":"fixture-access","refresh_token":null}""").refreshToken)
    }

    @Test
    fun `HTTP 200 OAuth errors win over any token and redact description`() {
        assertFailure("incorrect_client_credentials", 200,
            """{"error":"incorrect_client_credentials","error_description":"private response","access_token":"fixture-access"}""")
        assertFailure("invalid_grant", 400, """{"error":"invalid_grant"}""")
        assertFailure("oauth_error", 200, """{"error":"private response"}""")
        assertFailure("oauth_error", 200, """{"error":null,"access_token":"fixture-access"}""")
    }

    @Test
    fun `non JSON and malformed tokens are rejected without leaking body`() {
        for (body in listOf("error=incorrect_client_credentials&error_description=private", "<html>private</html>",
            "[]", "{}", """{"access_token":42}""", """{"access_token":"  "}""")) {
            assertFailure("invalid_token_response", 200, body)
        }
        assertFailure("HTTP 500", 500, "private server response")
        assertFailure("HTTP 302", 302, """{"access_token":"fixture-access"}""")
    }

    private fun assertFailure(code: String, status: Int, body: String) {
        try {
            McpOAuthTokens.parse(status, body)
            fail("Expected token response rejection")
        } catch (error: McpOAuthTokens.Failure) {
            assertEquals(code, error.code)
            assertEquals(code, error.message)
        }
    }
}
