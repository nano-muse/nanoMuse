package io.github.nanomuse.models

import android.content.Context
import com.openminis.app.MinisApp
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ModelGroup
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.hasImageInput
import com.openminis.app.data.repository.ProviderRepository
import io.github.nanomuse.avatar.ImageGen
import io.github.nanomuse.cloud.Capabilities
import io.github.nanomuse.cloud.CatalogueProvider
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.cloud.ProviderCatalogue
import io.github.nanomuse.hands.Hands
import io.github.nanomuse.home.MainChat
import io.github.nanomuse.media.MediaModels
import io.github.nanomuse.media.VideoGen
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch

/**
 * The four model slots of Settings → Models (0.1.41 "Choice"): chat, the hands (operating the
 * screen), pictures and clips. Each slot keeps its value where it always was — the default
 * model group for chat (`defaultPrimaryGroupId`), `hands.model_entry`, `avatar.provider_id /
 * avatar.model`, `media.video.*` — so the upstream Model groups screen, Settings → Hands and
 * Settings → Image & video models stay consistent with the page. This object is the one place
 * that lists what a slot can be set to, says what it is now, and sets it; the order for a slot
 * nobody chose is [SlotOrder].
 */
object ModelSlots {
    enum class Slot(val capability: String, val defaultsKey: String) {
        CHAT(ProviderCatalogue.CHAT, "chat"),
        HANDS(ProviderCatalogue.VISION, "hands"),
        IMAGE(ProviderCatalogue.IMAGE, "image"),
        VIDEO(ProviderCatalogue.VIDEO, "video");

        companion object {
            fun byKey(key: String?): Slot? = values().firstOrNull { it.defaultsKey == key }
        }
    }

    /**
     * One choice in a slot's picker: a model of a provider; [entryId] for chat and hands, where
     * the app binds entries; [displayName] when the provider gave the model one (the search
     * field matches it too).
     */
    data class Option(
        val instance: ProviderInstance,
        val modelId: String,
        val entryId: String? = null,
        val recommended: Boolean = false,
        val displayName: String? = null,
    )

    /** One group of the picker: nanoMuse Cloud first when signed in, then each configured own provider. */
    data class Group(val instance: ProviderInstance, val cloud: Boolean, val options: List<Option>)

    /** What a row shows: `<provider> · <model>`. */
    data class Value(val instance: ProviderInstance, val modelId: String, val why: SlotOrder.Why? = null) {
        fun label(context: Context): String = providerLabel(context, instance) + " · " + modelId
    }

    /** The slot last changed from the page, so it can say what a chat pick applies to under the chat row. */
    val lastChanged = MutableStateFlow<Slot?>(null)

    /**
     * The chat slot was written: the group that now leads with the pick, and the pick. The main
     * chat's view-model, alive as long as the app, listens and moves (ChatViewModel); the row in
     * the database is written here, for the next launch. See [MainChatFollow].
     */
    private val _chatSlotWritten = MutableSharedFlow<MainChatFollow.Pick>(extraBufferCapacity = 1)
    val chatSlotWritten: SharedFlow<MainChatFollow.Pick> = _chatSlotWritten
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private fun repo(context: Context): ProviderRepository? = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull

    /** The provider's name as the rows show it: `nanoMuse Cloud` for the relay, the person's label otherwise. */
    fun providerLabel(context: Context, inst: ProviderInstance): String =
        if (isCloud(context, inst)) NanoMuseCloud.LABEL else inst.label.ifBlank { inst.providerType.name }

    fun isCloud(context: Context, inst: ProviderInstance): Boolean = NanoMuseCloud.instance(context)?.id == inst.id

    /** The catalogue's entry for [inst], when it knows the vendor. */
    fun catalogueOf(context: Context, inst: ProviderInstance): CatalogueProvider? =
        ProviderCatalogue.match(ProviderCatalogue.load(context), inst)

    /** The catalogue's `defaults.<slot>` for [inst]'s vendor, or null. */
    fun defaultOf(context: Context, inst: ProviderInstance, slot: Slot): String? =
        catalogueOf(context, inst)?.defaults?.get(slot.defaultsKey)?.takeIf { it.isNotBlank() }

    // ── the chat provider ───────────────────────────────────────────────

    /** The entry new chats start from: the first member of the default group. */
    fun chatEntry(context: Context): ModelEntry? {
        val cfg = repo(context)?.config?.value ?: return null
        val group = cfg.modelGroups.firstOrNull { it.id == cfg.defaultPrimaryGroupId } ?: return null
        return group.memberEntryIds.firstNotNullOfOrNull { id -> cfg.modelEntries.firstOrNull { it.id == id && !it.isHidden } }
    }

    /** The provider new chats talk to; the other slots lean on it when nothing was chosen. */
    fun chatInstance(context: Context): ProviderInstance? {
        val entry = chatEntry(context) ?: return null
        return repo(context)?.config?.value?.instances?.firstOrNull { it.id == entry.providerInstanceId && it.isEnabled }
    }

    /** The chat provider when it is the person's own (not the relay), for [SlotOrder]'s second rung. */
    fun ownChatInstance(context: Context): ProviderInstance? = chatInstance(context)?.takeIf { !isCloud(context, it) }

    // ── what each slot is now ───────────────────────────────────────────

    fun current(context: Context, slot: Slot): Value? = when (slot) {
        // a provider switched off (the Cloud switch above all) answers nothing: the row says so
        // rather than naming a model that will not run
        Slot.CHAT -> chatEntry(context)?.let { e ->
            repo(context)?.config?.value?.instances?.firstOrNull { it.id == e.providerInstanceId && it.isEnabled }?.let { Value(it, e.model.id) }
        }
        Slot.HANDS -> Hands.screenModel(context)?.let { m ->
            Value(m.instance, m.modelId, when (m.why) {
                Hands.Why.CHOSEN -> SlotOrder.Why.CHOSEN
                Hands.Why.CHAT_PROVIDER -> SlotOrder.Why.CHAT_PROVIDER
                Hands.Why.MENU -> SlotOrder.Why.CLOUD
                else -> SlotOrder.Why.FIRST_OWN
            })
        }
        Slot.IMAGE -> ImageGen.endpoint(context)?.takeIf { it.model.isNotBlank() }?.let { Value(it.instance, it.model) }
        Slot.VIDEO -> MediaModels.videoEndpoint(context)?.let { Value(it.instance, it.model) }
    }

    /** True when the video slot was switched off on purpose (a value of its own, not "nothing chosen"). */
    fun videoOff(context: Context): Boolean = MediaModels.videoSwitchedOff(context)

    /**
     * Whether the person chose for [slot] (a stored choice; for clips, Off counts), or the slot
     * follows the automatic order. Chat has no automatic row: it is the anchor the other three
     * lean on, so it always counts as chosen.
     */
    fun isChosen(context: Context, slot: Slot): Boolean = when (slot) {
        Slot.CHAT -> true
        Slot.HANDS -> Hands.modelEntryId(context) != null
        Slot.IMAGE -> ImageGen.isChosen(context)
        Slot.VIDEO -> MediaModels.videoChosen(context)
    }

    /** What the automatic order gives [slot] right now, the choice left aside; null when nothing can serve it. */
    fun automatic(context: Context, slot: Slot): Value? = when (slot) {
        Slot.CHAT -> current(context, slot)
        Slot.HANDS -> Hands.screenModel(context, automatic = true)?.let { m ->
            Value(m.instance, m.modelId, when (m.why) {
                Hands.Why.CHAT_PROVIDER -> SlotOrder.Why.CHAT_PROVIDER
                Hands.Why.MENU -> SlotOrder.Why.CLOUD
                else -> SlotOrder.Why.FIRST_OWN
            })
        }
        Slot.IMAGE -> ImageGen.endpoint(context, automatic = true)?.takeIf { it.model.isNotBlank() }?.let { Value(it.instance, it.model) }
        Slot.VIDEO -> MediaModels.videoEndpoint(context, automatic = true)?.let { Value(it.instance, it.model) }
    }

    /**
     * *Automatic*: forgets the choice for [slot] (for clips, Off too) and changes nothing else,
     * so the slot follows the order again: the chat provider when it can, nanoMuse Cloud when
     * signed in, the first own model that can. Chat is left alone.
     */
    fun clear(context: Context, slot: Slot) {
        when (slot) {
            Slot.CHAT -> return
            Slot.HANDS -> Hands.setModelEntryId(context, null)
            Slot.IMAGE -> ImageGen.clear(context)
            Slot.VIDEO -> MediaModels.clearVideo(context)
        }
        lastChanged.value = slot
    }

    // ── what each slot can be ───────────────────────────────────────────

    /** The person's own providers that are switched on and hold a credential, in the order they were added; never the relay. */
    fun ownInstances(context: Context): List<ProviderInstance> {
        val repo = repo(context) ?: return emptyList()
        val cloudId = NanoMuseCloud.instance(context)?.id
        return repo.config.value.instances.filter { it.isEnabled && it.id != cloudId && repo.hasAnyCredential(it) }
    }

    /** Models of [inst] that answer in text: the chat lane. For the relay, its menu's chat lane. */
    fun chatEntriesOf(context: Context, inst: ProviderInstance): List<ModelEntry> {
        val cfg = repo(context)?.config?.value ?: return emptyList()
        val all = cfg.modelEntries.filter {
            it.providerInstanceId == inst.id && !it.isHidden && it.model.isTextOutput &&
                !ImageGen.looksLikeImageModel(it.model.id) && !VideoGen.looksLikeVideoModel(it.model.id)
        }
        if (!isCloud(context, inst)) return all
        val lane = NanoMuseCloud.chatLaneIds(context)
        return if (lane.isEmpty()) all.filter { !NanoMuseCloud.isCatalogModel(context, it.model.id) }
        else lane.mapNotNull { id -> all.firstOrNull { it.model.id == id } }
    }

    /** Models of [inst] that see the screen. For the relay, its menu's lane for the screen. */
    fun handsEntriesOf(context: Context, inst: ProviderInstance): List<ModelEntry> {
        if (!Hands.sees(context, inst)) return emptyList()
        val cfg = repo(context)?.config?.value ?: return emptyList()
        val all = cfg.modelEntries.filter { it.providerInstanceId == inst.id && !it.isHidden && it.model.hasImageInput && it.model.isTextOutput }
        if (!isCloud(context, inst)) return all
        val lane = NanoMuseCloud.guiLaneIds(context)
        return if (lane.isEmpty()) all.filter { !NanoMuseCloud.isCatalogModel(context, it.model.id) }
        else lane.mapNotNull { id -> all.firstOrNull { it.model.id == id } }
    }

    /**
     * The picker's groups for [slot]: the relay first when signed in, then each own provider
     * with the capability; a provider without it is left out. Within a group the rows take
     * [PickerList.order]: the catalogue's default for the slot (the relay's recommended model)
     * first, then what the slot is set to when that is in the group, then the rest as the
     * provider listed them, so a collapsed group shows the rows that matter.
     */
    fun groups(context: Context, slot: Slot): List<Group> {
        val cloud = NanoMuseCloud.instance(context)?.takeIf { NanoMuseCloud.modelsOn(context) }
        val own = ownInstances(context)
        val now = if (isChosen(context, slot)) current(context, slot) else null
        fun ordered(opts: List<Option>): List<Option> = PickerList.order(
            opts,
            isDefault = { it.recommended },
            isCurrent = { now != null && now.instance.id == it.instance.id && now.modelId == it.modelId },
        )
        val out = mutableListOf<Group>()
        // the relay's recommended model first and marked; a provider of the person's own lists
        // its models as they are, the mark is nanoMuse Cloud's word alone
        cloud?.let { options(context, slot, it, cloud = true) }?.takeIf { it.isNotEmpty() }
            ?.let { out += Group(cloud, true, ordered(it)) }
        for (inst in own) {
            val opts = ordered(options(context, slot, inst, cloud = false)).map { it.copy(recommended = false) }
            if (opts.isNotEmpty()) out += Group(inst, false, opts)
        }
        return out
    }

    private fun options(context: Context, slot: Slot, inst: ProviderInstance, cloud: Boolean): List<Option> = when (slot) {
        Slot.CHAT -> {
            val rec = if (cloud) NanoMuseCloud.recommendedModelId(context) else defaultOf(context, inst, slot)
            chatEntriesOf(context, inst).map {
                Option(inst, it.model.id, it.id, recommended = it.model.id.equals(rec, ignoreCase = true), displayName = it.model.displayName)
            }
        }
        Slot.HANDS -> {
            val rec = if (cloud) NanoMuseCloud.sightedModelId(context) else defaultOf(context, inst, slot)
            handsEntriesOf(context, inst).map {
                Option(inst, it.model.id, it.id, recommended = it.model.id.equals(rec, ignoreCase = true), displayName = it.model.displayName)
            }
        }
        Slot.IMAGE -> {
            if (inst !in ImageGen.eligibleInstances(context)) emptyList()
            else {
                val listed = ImageGen.availableModels(context, inst)
                val rec = if (cloud) listed.firstOrNull() else ImageGen.recommendedModel(context, inst).takeIf { it.isNotBlank() }
                val ids = listed.ifEmpty { listOfNotNull(rec) }
                ids.map { Option(inst, it, recommended = it.equals(rec, ignoreCase = true)) }
            }
        }
        Slot.VIDEO -> {
            if (inst !in MediaModels.eligibleVideoInstances(context)) emptyList()
            else {
                val rec = MediaModels.defaultVideoModel(context, inst)
                val ids = MediaModels.availableVideoModels(context, inst)
                    ?: repo(context)?.config?.value?.modelEntries
                        ?.filter { it.providerInstanceId == inst.id && !it.isHidden && VideoGen.looksLikeVideoModel(it.model.id) }
                        ?.map { it.model.id }.orEmpty().ifEmpty { listOf(rec) }
                ids.map { Option(inst, it, recommended = it.equals(rec, ignoreCase = true)) }
            }
        }
    }

    // ── choosing ────────────────────────────────────────────────────────

    /** Sets [slot] to [option]; for chat this changes the default for new chats and moves the main chat. */
    fun choose(context: Context, slot: Slot, option: Option) {
        when (slot) {
            Slot.CHAT -> option.entryId?.let { followPick(context, it) }
            Slot.HANDS -> Hands.setModelEntryId(context, option.entryId)
            Slot.IMAGE -> ImageGen.save(context, option.instance.id, option.modelId)
            Slot.VIDEO -> MediaModels.saveVideo(context, option.instance.id, option.modelId)
        }
        lastChanged.value = slot
    }

    /**
     * A provider switched off while new chats answered through it — nanoMuse Cloud above all
     * (Settings › Models › *Use nanoMuse Cloud models*; the desktop's `setCloudModels` does the
     * same) — hands the chat slot to the first source that still talks: the relay's recommended
     * chat model when the relay is on, else the first own provider with a chat model, its
     * catalogue default first ([groups]' order). So the Models page names what answers, and new
     * chats do not fall through upstream's last-used chain without a word. Nothing moves when
     * the slot was elsewhere, or when nothing is left to serve it; then the row says *Not set*.
     * Call after the instance was written off. Returns what the slot moved to.
     */
    fun chatLeaves(context: Context, instanceId: String): Option? {
        if (!chatRunsOn(context, instanceId)) return null
        val option = nextChat(groups(context, Slot.CHAT), instanceId) ?: return null
        choose(context, Slot.CHAT, option)
        return option
    }

    /** Whether new chats answer through [instanceId] right now (the chat default's entry is its). */
    fun chatRunsOn(context: Context, instanceId: String): Boolean = chatEntry(context)?.providerInstanceId == instanceId

    /**
     * Whether [instanceId] may be switched off as far as the chat slot is concerned: new chats
     * do not run on it, or another source could take them ([nextChat]). False is the refusal
     * the Cloud switch shows as one sentence: with nothing else to answer, the switch stays on
     * rather than leaving the slot empty. Ask before the instance is written off.
     */
    fun canLeave(context: Context, instanceId: String): Boolean =
        !chatRunsOn(context, instanceId) || nextChat(groups(context, Slot.CHAT), instanceId) != null

    /** The first row of the picker's [groups] that is not [leaving]'s: the relay's recommended model, else the first own provider's default. */
    fun nextChat(groups: List<Group>, leaving: String): Option? =
        groups.firstNotNullOfOrNull { g -> g.options.firstOrNull { it.instance.id != leaving } }

    /**
     * New chats and the main chat follow [entryId]: the entry leads a group named after its
     * provider (the relay's `nanoMuse Cloud` group, or one called what the person called the
     * provider) and that group becomes the default; the main chat is bound to it
     * ([mainChatFollows]). A group with another name of the person's own is never edited; when
     * such a group is the default and already leads with the pick, the groups do not move.
     * False for a picture or video model, which is no chat model. True when the chats follow.
     */
    fun followPick(context: Context, entryId: String): Boolean {
        val repo = repo(context) ?: return false
        val config = repo.config.value
        val entry = config.modelEntries.firstOrNull { it.id == entryId } ?: return false
        val inst = config.instances.firstOrNull { it.id == entry.providerInstanceId } ?: return false
        if (NanoMuseCloud.drawsOrFilms(entry.model) || ImageGen.looksLikeImageModel(entry.model.id)) return false
        val name = providerLabel(context, inst)
        val default = config.modelGroups.firstOrNull { it.id == config.defaultPrimaryGroupId }
        if (default != null && default.memberEntryIds.firstOrNull() == entryId) {
            mainChatFollows(context, MainChatFollow.Pick(default.id, entryId))
            return true
        }
        val group = default?.takeIf { it.name == name } ?: config.modelGroups.firstOrNull { it.name == name }
        if (group == null) {
            val fresh = ModelGroup(name = name)
            fresh.memberEntryIds.add(entryId)
            repo.addGroup(fresh)
            repo.defaultPrimaryGroupId = fresh.id
            mainChatFollows(context, MainChatFollow.Pick(fresh.id, entryId))
            return true
        }
        repo.updateGroup(group.copy(memberEntryIds = SlotOrder.leadWith(group.memberEntryIds, entryId).toMutableList()))
        if (repo.defaultPrimaryGroupId != group.id) repo.defaultPrimaryGroupId = group.id
        mainChatFollows(context, MainChatFollow.Pick(group.id, entryId))
        return true
    }

    /**
     * The main chat follows the chat slot ([MainChatFollow]): its row gets the group binding
     * the chat view-model would write for the same pick, unless it already says so, and the
     * open view-model is told through [chatSlotWritten]. Side chats are not touched; a draft
     * main chat has no row and resolves to the default group when it is first written to.
     */
    fun mainChatFollows(context: Context, pick: MainChatFollow.Pick) {
        val app = context.applicationContext as? MinisApp ?: return
        val sid = MainChatFollow.target(MainChat.persisted(context)) ?: return
        val chats = app.chatRepositoryOrNull ?: return
        scope.launch {
            val session = runCatching { chats.getSession(sid) }.getOrNull() ?: return@launch
            if (!MainChatFollow.alreadySays(session.modelBinding, pick)) {
                val modelId = repo(context)?.config?.value?.modelEntries?.firstOrNull { it.id == pick.entryId }?.model?.id ?: session.modelId
                chats.updateSessionBinding(sid, MainChatFollow.binding(pick), modelId)
            }
            _chatSlotWritten.tryEmit(pick)
        }
    }

    // ── the "Use it for" card ───────────────────────────────────────────

    /**
     * The slots the card offers for [inst]: what the catalogue says the vendor covers under
     * the way it signed in; for a vendor the catalogue does not know, what its models show
     * (chat always; the screen when one sees; pictures and clips when the app can drive them).
     */
    fun offeredSlots(context: Context, inst: ProviderInstance): List<Slot> {
        val known = Capabilities.of(context, inst)
        if (known != null) return Slot.values().filter { it.capability in known }
        return buildList {
            add(Slot.CHAT)
            if (handsEntriesOf(context, inst).isNotEmpty()) add(Slot.HANDS)
            if (inst in ImageGen.eligibleInstances(context)) add(Slot.IMAGE)
            if (inst in MediaModels.eligibleVideoInstances(context)) add(Slot.VIDEO)
        }
    }

    /**
     * `Use it`: every slot in [slots] switches to [inst], model = the catalogue's
     * `defaults.<slot>`, or the first model of the list with that capability. The provider's
     * list is fetched first when the app has none yet (the form fetches it in the background).
     * Returns the slots that were set; one the provider turned out to have no model for is
     * left as it was.
     */
    suspend fun applyProvider(context: Context, inst: ProviderInstance, slots: Set<Slot>): Set<Slot> {
        val repo = repo(context) ?: return emptySet()
        if (repo.entriesFor(inst.id).none { !it.isHidden }) runCatching { repo.refreshModels(inst) }
        val done = mutableSetOf<Slot>()
        for (slot in Slot.values()) {
            if (slot !in slots) continue
            val option = when (slot) {
                Slot.CHAT -> pickEntry(chatEntriesOf(context, inst), defaultOf(context, inst, slot))?.let { Option(inst, it.model.id, it.id) }
                Slot.HANDS -> pickEntry(handsEntriesOf(context, inst), defaultOf(context, inst, slot))?.let { Option(inst, it.model.id, it.id) }
                Slot.IMAGE -> if (inst !in ImageGen.eligibleInstances(context)) null else {
                    SlotOrder.defaultModel(ImageGen.recommendedModel(context, inst).takeIf { it.isNotBlank() }, ImageGen.availableModels(context, inst))
                        ?.let { Option(inst, it) }
                }
                Slot.VIDEO -> if (inst !in MediaModels.eligibleVideoInstances(context)) null else {
                    SlotOrder.defaultModel(MediaModels.defaultVideoModel(context, inst), MediaModels.availableVideoModels(context, inst).orEmpty())
                        ?.let { Option(inst, it) }
                }
            } ?: continue
            choose(context, slot, option)
            done += slot
        }
        return done
    }

    private fun pickEntry(entries: List<ModelEntry>, wanted: String?): ModelEntry? {
        val id = SlotOrder.defaultModel(wanted, entries.map { it.model.id }) ?: return null
        return entries.firstOrNull { it.model.id.equals(id, ignoreCase = true) }
    }
}
