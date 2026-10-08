package io.github.nanomuse.models

import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * A provider switched off while new chats answered through it (nanoMuse Cloud under Settings ›
 * Models, or a provider of the person's own on its page): the chat slot moves to the first row
 * of the picker that is not the leaving provider's, in the picker's order.
 */
class ChatLeavesTest {
    private fun inst(id: String) = ProviderInstance(id = id, label = id, providerType = ProviderType.openAI, credentialType = ProviderCredential.apiKey)

    private val cloud = inst("cloud")
    private val bailian = inst("bailian")
    private val deepseek = inst("deepseek")

    private fun group(i: ProviderInstance, cloud: Boolean, vararg models: String) =
        ModelSlots.Group(i, cloud, models.mapIndexed { n, m -> ModelSlots.Option(i, m, entryId = "${i.id}:$m", recommended = cloud && n == 0) })

    @Test fun `the Cloud leaves, the first own provider's first row takes the chat`() {
        // the relay is off, so it is not among the groups any more
        val groups = listOf(group(bailian, false, "qwen-plus", "qwen-max"), group(deepseek, false, "deepseek-chat"))
        val next = ModelSlots.nextChat(groups, leaving = cloud.id)
        assertEquals("bailian", next?.instance?.id)
        assertEquals("qwen-plus", next?.modelId)
    }

    @Test fun `an own provider leaves while the relay is on, the relay's recommended model takes the chat`() {
        val groups = listOf(group(cloud, true, "deepseek-v4.1-flash", "qwen3.8-27b"), group(deepseek, false, "deepseek-chat"))
        val next = ModelSlots.nextChat(groups, leaving = bailian.id)
        assertEquals("cloud", next?.instance?.id)
        assertEquals("deepseek-v4.1-flash", next?.modelId)
    }

    @Test fun `the leaving provider's own rows are skipped even when they are still listed`() {
        val groups = listOf(group(bailian, false, "qwen-plus"), group(deepseek, false, "deepseek-chat"))
        val next = ModelSlots.nextChat(groups, leaving = bailian.id)
        assertEquals("deepseek", next?.instance?.id)
    }

    @Test fun `nothing left to talk to, nothing moves`() {
        assertNull(ModelSlots.nextChat(emptyList(), leaving = cloud.id))
        assertNull(ModelSlots.nextChat(listOf(group(bailian, false, "qwen-plus")), leaving = bailian.id))
    }
}
