package io.github.nanomuse.reach

import org.json.JSONObject
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class RemoteApprovalKeyTest {
    @Test
    fun aCompleteStructuredTargetCanBeRemembered() {
        val event = event("resource", "sha256:" + "a".repeat(64))
        assertNotNull(RemoteApprovalKey.target(event))
    }

    @Test
    fun twoActionsWithTheSameFirstSixtyCharactersDoNotShareAnAnswer() {
        val prefix = "x".repeat(60)
        val one = event(prefix + "one", "sha256:" + "a".repeat(64))
        val two = event(prefix + "two", "sha256:" + "b".repeat(64))
        assertNotEquals(RemoteApprovalKey.target(one), RemoteApprovalKey.target(two))
        assertNotEquals(
            RemoteApprovalKey.wire("screen", "app:Mail", prefix + "one").getString("action"),
            RemoteApprovalKey.wire("screen", "app:Mail", prefix + "two").getString("action"),
        )
    }

    @Test
    fun aLegacyOrMalformedEventCannotBeRemembered() {
        assertNull(RemoteApprovalKey.target(JSONObject().put("grant_key", "shell:git")))
        assertNull(RemoteApprovalKey.target(event("resource", "not-a-digest")))
        val stringVersion = event("resource", "sha256:" + "a".repeat(64))
        stringVersion.getJSONObject("grant_target").put("version", "1")
        assertNull(RemoteApprovalKey.target(stringVersion))
    }

    @Test
    fun devicesHaveSeparateCapabilities() {
        val target = requireNotNull(RemoteApprovalKey.target(
            event("resource", "sha256:" + "a".repeat(64)),
        ))
        assertNotEquals(
            RemoteApprovalKey.scoped("device-one", "destructive", target),
            RemoteApprovalKey.scoped("device-two", "destructive", target),
        )
        assertNotEquals(
            RemoteApprovalKey.scoped("device-one", "destructive", target),
            RemoteApprovalKey.scoped("device-one", "sensitive", target),
        )
    }

    private fun event(resource: String, action: String): JSONObject = JSONObject().put(
        "grant_target",
        JSONObject()
            .put("version", 1)
            .put("tool", "shell")
            .put("resource", resource)
            .put("action", action),
    )
}
