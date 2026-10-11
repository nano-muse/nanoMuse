package io.github.nanomuse.ui.home

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.SizeTransform
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.outlined.Call
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import dev.chrisbanes.haze.hazeSource
import dev.chrisbanes.haze.rememberHazeState
import com.openminis.app.R
import com.openminis.app.agent.SoulStore
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.data.repository.MCPRepository
import com.openminis.app.data.repository.MemoryRepository
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.data.repository.SkillRepository
import com.openminis.app.scheduled.ScheduledRepeatMode
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskManager
import com.openminis.app.ui.chat.ChatScreen
import com.openminis.app.ui.chat.ChatViewModel
import com.openminis.app.ui.chat.ChatViewModelStore
import com.openminis.app.ui.navigation.FilePreviewHolder
import com.openminis.app.ui.navigation.Routes
import com.openminis.app.ui.navigation.safeNavigate
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.ui.chat.NmHomeChrome
import io.github.nanomuse.goals.GoalCategory
import io.github.nanomuse.goals.GoalFlow
import io.github.nanomuse.home.MainChat
import io.github.nanomuse.ideas.Idea
import io.github.nanomuse.ui.avatar.rememberAgentMood
import io.github.nanomuse.ui.feed.FeedTab
import io.github.nanomuse.ui.feed.FeedUi
import io.github.nanomuse.ui.goals.GoalsTab
import io.github.nanomuse.ui.header.openSoulSettings
import io.github.nanomuse.ui.header.rememberNanoMuseStatusLine
import io.github.nanomuse.ui.ideas.IdeasTab
import io.github.nanomuse.ui.library.LibraryTab
import io.github.nanomuse.ui.onboarding.FirstRunSetup
import io.github.nanomuse.ui.onboarding.FirstRunSetupScreen
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * nanoMuse's home, in Muse's shape: the app opens on a conversation, not a list. A bottom bar
 * switches between the chat and the Ideas / Goals / Library pages, a drawer holds the main chat
 * and the side chats, and everything that used to be the OpenMinis session list is one tap
 * further in (the archive glyph in the drawer). Rendered by `Routes.SESSION_LIST` in compact
 * windows; wide windows keep the upstream list/detail split.
 *
 * The chat tab stays composed while another tab is showing (hidden under it), so switching
 * tabs never rebuilds the conversation, drops the composer text or loses the scroll position.
 */
@Composable
fun NanoMuseHome(
    navController: NavHostController,
    chatRepository: ChatRepository,
    providerRepository: ProviderRepository,
    memoryRepository: MemoryRepository?,
    skillRepository: SkillRepository?,
    mcpRepository: MCPRepository?,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val focusManager = LocalFocusManager.current

    var tab by rememberSaveable { mutableStateOf(HomeTab.CHAT) }
    var chatSessionId by rememberSaveable { mutableStateOf<String?>(null) }
    val mainSessionId by MainChat.sessionId.collectAsState()

    LaunchedEffect(Unit) {
        val main = MainChat.resolve(context, chatRepository)
        if (chatSessionId == null) chatSessionId = main
    }

    // contract C10: a sign-in made the open chat another account's — the home is this account's now
    val hiddenSessions by io.github.nanomuse.sync.ConversationSync.hidden.collectAsState()
    LaunchedEffect(hiddenSessions, mainSessionId) {
        val shown = chatSessionId ?: return@LaunchedEffect
        if (shown in hiddenSessions) chatSessionId = mainSessionId ?: MainChat.resolve(context, chatRepository)
    }

    val isMainChat = chatSessionId?.let { MainChat.isMain(context, it) } ?: true

    // Each time the home comes to the foreground: one more distinct day for the star asks'
    // day counter (StarPrompt), and the relay's nudges policy re-read when a day has passed.
    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    androidx.compose.runtime.DisposableEffect(lifecycleOwner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_START) {
                io.github.nanomuse.community.Nudges.refreshIfStale(context)
                io.github.nanomuse.community.StarPrompt.dayOpened(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    fun showSession(id: String) {
        focusManager.clearFocus(force = true)
        chatSessionId = id
        tab = HomeTab.CHAT
    }

    fun showMain() {
        val id = mainSessionId ?: return
        showSession(id)
    }

    // Requests from cards inside messages, idea sheets, etc.
    var pendingPrefill by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        HomeBus.requests.collect { req ->
            when (req) {
                is HomeBus.Request.ShowTab -> tab = req.tab
                is HomeBus.Request.ShowSession -> showSession(req.sessionId)
                is HomeBus.Request.PrefillComposer -> {
                    showMain()
                    pendingPrefill = req.text
                }
            }
            HomeBus.handled()
        }
    }

    // First run. Until the app has a model to talk to, the home is Muse's welcome screen with
    // the three steps (provider → its models → the first conversation), not a chat that cannot
    // answer. Gated on the provider config and the session list having loaded, so a returning
    // user never sees the setup flash past before their providers are read.
    val providerConfig by providerRepository.config.collectAsState()
    val configLoaded by providerRepository.configLoaded.collectAsState()
    val sessions by chatRepository.observeSessions().collectAsState(initial = null)
    // contract C12: the account left and took the open chat with it (or the chat was deleted
    // under the home) — the home shows this account's main chat, resolved afresh if need be
    LaunchedEffect(sessions, mainSessionId) {
        val shown = chatSessionId ?: return@LaunchedEffect
        val list = sessions ?: return@LaunchedEffect
        if (MainChat.isDraftId(shown) || list.any { it.id == shown }) return@LaunchedEffect
        val main = mainSessionId
        chatSessionId = if (main != null && main != shown && (MainChat.isDraftId(main) || list.any { it.id == main })) {
            main
        } else {
            MainChat.reset()
            MainChat.resolve(context, chatRepository)
        }
    }
    var setupDone by remember { mutableStateOf(FirstRunSetup.isDone(context)) }
    // A provider of the person's own that could answer: enabled and holding a credential. The
    // Cloud instance is the account, counted through `signedIn` below.
    val cloudId = io.github.nanomuse.cloud.NanoMuseCloud.instance(context)?.id
    val hasProviders = remember(providerConfig) {
        providerConfig.instances.any { it.id != cloudId && it.isEnabled && providerRepository.hasAnyCredential(it) }
    }
    val hasGroups = providerConfig.modelGroups.isNotEmpty()
    // The flow flips when the sign-in lands (or the key is revoked); signed out with a key of
    // one's own the chat stays, the sign-in is an invitation under Settings.
    val signedIn by io.github.nanomuse.cloud.NanoMuseCloud.signedIn(context).collectAsState()
    val phase = when {
        !configLoaded || sessions == null || signedIn == null -> HomePhase.LOADING
        FirstRunSetup.needed(signedIn == true, hasProviders, sessions!!.isNotEmpty(), setupDone) -> HomePhase.SETUP
        else -> HomePhase.HOME
    }
    // Once the chat has been shown the setup is over for good: an empty main chat is a draft
    // with no session row, so without this a trip to the profile page and back could bring
    // the welcome screen up again.
    LaunchedEffect(phase) {
        if (phase == HomePhase.HOME && !setupDone) {
            FirstRunSetup.markDone(context)
            setupDone = true
        }
    }

    // The main chat's ViewModel: the same instance ChatScreen uses (process-level store), so the
    // tab headers can show its mood/status and the tabs can send into it. Not created before the
    // setup is over: a ViewModel resolves its model when it is built, and one built while the
    // default group did not exist yet would keep talking to whatever entry it found first.
    val mainVm: ChatViewModel? = if (phase != HomePhase.HOME) null else mainSessionId?.let { id ->
        viewModel(
            viewModelStoreOwner = ChatViewModelStore.ownerFor(id),
            factory = ChatViewModel.factory(
                sessionId = id,
                chatRepository = chatRepository,
                providerRepository = providerRepository,
                appContext = context.applicationContext,
                memoryRepository = memoryRepository,
                skillRepository = skillRepository,
                mcpRepository = mcpRepository,
            ),
        )
    }
    // The profile page's "Change avatar": the request pre-typed, keyboard up, once the main
    // chat's ViewModel is there to take it.
    LaunchedEffect(pendingPrefill, mainVm) {
        val text = pendingPrefill ?: return@LaunchedEffect
        val vm = mainVm ?: return@LaunchedEffect
        pendingPrefill = null
        vm.nmPrefillComposer(text)
    }
    val streaming by (mainVm?.isStreaming ?: remember { kotlinx.coroutines.flow.MutableStateFlow(false) }).collectAsState()
    val error by (mainVm?.error ?: remember { kotlinx.coroutines.flow.MutableStateFlow<String?>(null) }).collectAsState()
    val mood = rememberAgentMood(streaming, error)
    // The same account of the work the chat header gives: the step, the reply arriving, or the request it is on.
    val replying by remember(mainVm) {
        mainVm?.streamingById?.let { flow ->
            flow.map { stream ->
                stream.values.any { d -> !d.isAwaitingModelResponse && d.toolBlocks.lastOrNull()?.let { it.kind == "text" && it.content.isNotEmpty() } == true }
            }.distinctUntilChanged()
        } ?: kotlinx.coroutines.flow.flowOf(false)
    }.collectAsState(initial = false)
    val homeMessages by (mainVm?.uiMessages ?: remember { kotlinx.coroutines.flow.MutableStateFlow(emptyList<com.openminis.app.ui.chat.ChatMessage>()) }).collectAsState()
    val requestBrief = remember(homeMessages) { io.github.nanomuse.ui.header.requestBrief(homeMessages.lastOrNull { it.role == "user" }?.content) }
    val statusLine = rememberNanoMuseStatusLine(streaming, mood, replying = replying, request = requestBrief)
    val soul by SoulStore.cachedMetadata.collectAsState()
    val agentName = soul.name.trim().ifEmpty { stringResource(R.string.app_name) }

    fun sendToMainChat(text: String) {
        val vm = mainVm ?: run {
            Toast.makeText(context, R.string.nm_home_not_ready, Toast.LENGTH_SHORT).show()
            return
        }
        showMain()
        vm.nmMarkPersonTurn() // an idea or goal card the person tapped: a task for StarPrompt's count
        vm.sendMessage(text)
    }

    fun startGoal(category: GoalCategory, seed: String? = null) {
        val id = mainSessionId ?: return
        val opener = GoalFlow.startCreation(context, id, category)
        sendToMainChat(if (seed.isNullOrBlank()) opener else "$opener $seed")
    }

    fun createRoutine(idea: Idea) {
        val (h, m) = idea.time?.split(":")?.takeIf { it.size == 2 }
            ?.let { (a, b) -> a.toIntOrNull()?.coerceIn(0, 23) to b.toIntOrNull()?.coerceIn(0, 59) }
            ?.takeIf { it.first != null && it.second != null }
            ?.let { it.first!! to it.second!! }
            ?: (9 to 0)
        val task = ScheduledTaskManager(context).create(
            ScheduledTask(
                label = idea.title.take(40),
                timeOfDayHour = h,
                timeOfDayMinute = m,
                repeatMode = ScheduledRepeatMode.DAILY,
                prompt = idea.prompt,
            ),
        )
        Toast.makeText(context, R.string.nm_idea_routine_created, Toast.LENGTH_SHORT).show()
        navController.safeNavigate(Routes.scheduledTaskEdit(task.id))
    }

    /** "Discuss" on a feed card: a side chat that opens on the post. */
    fun discussPost(post: io.github.nanomuse.feed.FeedPost) {
        scope.launch {
            val app = context.applicationContext as? com.openminis.app.MinisApp ?: return@launch
            val id = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                io.github.nanomuse.goals.GoalSessions.create(app, post.title.take(40))
            } ?: run {
                Toast.makeText(context, R.string.nm_feed_routine_needs_model, Toast.LENGTH_SHORT).show()
                return@launch
            }
            showSession(id)
            val opener = context.getString(R.string.nm_feed_discuss_opener, post.title, post.body.take(1200))
            com.openminis.app.debug.HeadlessChatRunner.prompt(
                context = app, sessionId = id, text = opener, wait = false, timeoutMs = 10 * 60 * 1000L,
            )
        }
    }

    val drawerState = rememberDrawerState(DrawerValue.Closed)
    fun openDrawer() {
        focusManager.clearFocus(force = true)
        scope.launch { drawerState.open() }
    }
    fun closeDrawer() = scope.launch { drawerState.close() }

    // Back: close the drawer → leave a non-chat tab → leave a side chat → (system) leave the app.
    val homeShown = phase == HomePhase.HOME
    BackHandler(enabled = homeShown && drawerState.isOpen) { closeDrawer() }
    BackHandler(enabled = homeShown && !drawerState.isOpen && tab != HomeTab.CHAT) { tab = HomeTab.CHAT }
    BackHandler(enabled = homeShown && !drawerState.isOpen && tab == HomeTab.CHAT && !isMainChat && mainSessionId != null) { showMain() }

    // The drawer + tab shell, as a local composable so it can share every piece of state above
    // and still be one branch of the phase switch below.
    // nanoMuse: the frosted pill bar blurs this shell's content — the shell is the haze source.
    val hazeState = rememberHazeState()
    val homeShell: @Composable () -> Unit = {
    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = drawerState.isOpen || tab == HomeTab.CHAT,
        drawerContent = {
            ModalDrawerSheet(
                drawerContainerColor = MuseTones.surface,
                drawerShape = androidx.compose.foundation.shape.RoundedCornerShape(topEnd = 24.dp, bottomEnd = 24.dp),
            ) {
                SideChatDrawer(
                    agentName = agentName,
                    chatRepository = chatRepository,
                    mainSessionId = mainSessionId,
                    currentSessionId = chatSessionId,
                    onOpenMain = { closeDrawer(); showMain() },
                    onOpenSession = { id -> closeDrawer(); showSession(id) },
                    onNewChat = { closeDrawer(); showSession("__new__${UUID.randomUUID()}") },
                    onAllChats = { closeDrawer(); navController.safeNavigate(ROUTE_ALL_CHATS) },
                    onSettings = { closeDrawer(); navController.safeNavigate(Routes.SETTINGS) },
                    onSetMain = { id -> MainChat.set(context, id); closeDrawer(); showSession(id) },
                    onSystemFiles = { closeDrawer(); navController.safeNavigate(io.github.nanomuse.ui.sysfiles.ROUTE_SYSTEM_FILES) },
                    onDevices = { closeDrawer(); navController.safeNavigate(io.github.nanomuse.ui.cloud.ROUTE_CLOUD_ACCOUNT) },
                    onCoding = { closeDrawer(); navController.safeNavigate(io.github.nanomuse.ui.coding.ROUTE_CODING) },
                )
            }
        },
    ) {
        Scaffold(
            containerColor = ChatColors.background,
            contentWindowInsets = WindowInsets(0),
            bottomBar = {
                MuseBottomBar(selected = tab, hazeState = hazeState, onSelect = { picked ->
                    if (picked == HomeTab.CHAT && tab == HomeTab.CHAT && !isMainChat) {
                        showMain()
                    } else {
                        focusManager.clearFocus(force = true)
                        tab = picked
                    }
                })
            },
        ) { padding ->
            val bottom = padding.calculateBottomPadding()
            // Scaffold measures the entire bar, including its floating gap and
            // navigation inset, before laying out this content. Use that same
            // inset for placement and IME consumption, without a frame-late callback.
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .hazeSource(hazeState)
                    // nanoMuse: no bottom inset — the pill bar is an overlay and the
                    // content slides behind it for the frosted blur. Each tab pads
                    // its own scrollable content above the pill.
                    .consumeWindowInsets(PaddingValues(bottom = bottom)),
            ) {
                // Chat tab — always composed, hidden while another tab is on top.
                val chatVisible = tab == HomeTab.CHAT
                // Fades a touch slower than the page above it fades in, so the switch reads as
                // one cross-fade rather than a cut to the canvas.
                val chatAlpha by animateFloatAsState(
                    targetValue = if (chatVisible) 1f else 0f,
                    animationSpec = tween(if (chatVisible) 120 else 220),
                    label = "chatAlpha",
                )
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .zIndex(0f)
                        .graphicsLayer { alpha = chatAlpha },
                ) {
                    val sid = chatSessionId
                    if (sid != null) {
                        ChatScreen(
                            sessionId = sid,
                            chatRepository = chatRepository,
                            providerRepository = providerRepository,
                            memoryRepository = memoryRepository,
                            skillRepository = skillRepository,
                            mcpRepository = mcpRepository,
                            onBack = { if (!isMainChat) showMain() },
                            onNewChat = { showSession("__new__${UUID.randomUUID()}") },
                            onOpenTerminal = { navController.safeNavigate(Routes.terminal(sessionId = sid)) },
                            onOpenTerminalWithCommand = { command ->
                                navController.safeNavigate(Routes.terminal(initCommand = command, sessionId = sid))
                            },
                            onMoveToSession = { targetId -> showSession(targetId) },
                            onBrowseChatFiles = { navController.safeNavigate(Routes.chatFiles(sid)) },
                            onPreviewAttachment = { item ->
                                FilePreviewHolder.currentItem = item
                                navController.safeNavigate(Routes.FILE_PREVIEW)
                            },
                            onModelGroupsClick = { navController.safeNavigate(Routes.MODEL_GROUPS) },
                            nmHome = NmHomeChrome(isMainChat = isMainChat, onOpenDrawer = { openDrawer() }),
                            // nanoMuse: preserve the full-size blur source, but keep
                            // the chat footer above the bar measured by Scaffold.
                            nmBottomOverlay = bottom,
                        )
                    }
                }

                val holder = rememberSaveableStateHolder()
                // The page that is (or was last) on top of the chat. Keeping it while the
                // sheet fades back to the chat means the content does not blink to empty.
                var pageTab by remember { mutableStateOf(if (tab == HomeTab.CHAT) HomeTab.FEED else tab) }
                if (tab != HomeTab.CHAT) pageTab = tab
                AnimatedVisibility(
                    visible = !chatVisible,
                    enter = fadeIn(tween(160)),
                    exit = fadeOut(tween(120)),
                    modifier = Modifier.fillMaxSize().zIndex(1f),
                ) {
                    Surface(
                        color = ChatColors.background,
                        // nanoMuse: no bottom padding — tab content flows behind
                        // the pill overlay like the chat does. Tabs handle their
                        // own bottom contentPadding internally.
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        // Pages cross-fade; the header sits at the same spot on every page,
                        // so only the content below it appears to change.
                        AnimatedContent(
                            targetState = pageTab,
                            transitionSpec = {
                                (fadeIn(tween(160)) togetherWith fadeOut(tween(120)))
                                    .using(SizeTransform(clip = false))
                            },
                            label = "nmTab",
                        ) { page ->
                        holder.SaveableStateProvider(page.name) {
                            val header: @Composable () -> Unit = {
                                TabHeader(
                                    tab = page,
                                    mood = mood,
                                    name = agentName,
                                    statusLine = statusLine,
                                    onAvatarClick = { navController.safeNavigate(io.github.nanomuse.ui.profile.ROUTE_AGENT_PROFILE) },
                                    onNameClick = { navController.safeNavigate(io.github.nanomuse.ui.profile.ROUTE_AGENT_PROFILE) },
                                    onOpenDrawer = { openDrawer() },
                                    navController = navController,
                                    mainSessionId = mainSessionId,
                                )
                            }
                            when (page) {
                                HomeTab.FEED -> FeedTab(
                                    header = header,
                                    onDiscuss = { discussPost(it) },
                                    onEditRoutine = { navController.safeNavigate(Routes.scheduledTaskEdit(it)) },
                                )
                                HomeTab.IDEAS -> IdeasTab(
                                    header = header,
                                    onSendToChat = { sendToMainChat(it) },
                                    onCreateRoutine = { createRoutine(it) },
                                    onStartGoal = { category, seed -> startGoal(category, seed) },
                                )
                                HomeTab.GOALS -> GoalsTab(
                                    header = header,
                                    onStartGoal = { startGoal(it) },
                                    onOpenSession = { showSession(it) },
                                    onEditRoutine = { navController.safeNavigate(Routes.scheduledTaskEdit(it)) },
                                    onRoutineRuns = { navController.safeNavigate(Routes.scheduledTaskRuns(it)) },
                                    onAllRoutines = { navController.safeNavigate(Routes.SCHEDULED_TASKS) },
                                )
                                HomeTab.LIBRARY -> LibraryTab(
                                    header = header,
                                    chatRepository = chatRepository,
                                    onPreview = { item ->
                                        FilePreviewHolder.currentItem = item
                                        navController.safeNavigate(Routes.FILE_PREVIEW)
                                    },
                                    onOpenSession = { showSession(it) },
                                )
                                HomeTab.CHAT -> Unit
                            }
                        }
                        }
                    }
                }
            }
        }
    }
    } // homeShell

    AnimatedContent(
        targetState = phase,
        transitionSpec = { fadeIn(tween(220)) togetherWith fadeOut(tween(160)) },
        label = "nmHomePhase",
    ) { current ->
        when (current) {
            HomePhase.LOADING -> Surface(color = MuseTones.surface, modifier = Modifier.fillMaxSize()) {}
            HomePhase.SETUP -> FirstRunSetupScreen(
                agentName = agentName,
                signedIn = signedIn == true,
                hasGroups = hasGroups,
                hasProviders = hasProviders,
                onSignIn = { navController.safeNavigate(io.github.nanomuse.ui.cloud.ROUTE_CLOUD_SIGN_IN) },
                onAddProvider = { navController.safeNavigate(Routes.ADD_PROVIDER) },
                onSelectModels = { navController.safeNavigate(Routes.ONBOARDING_MODELS) },
                onStart = { FirstRunSetup.markDone(context); setupDone = true },
                onSettings = { navController.safeNavigate(Routes.SETTINGS) },
            )
            HomePhase.HOME -> homeShell()
        }
    }
}

private enum class HomePhase { LOADING, SETUP, HOME }

/** The big-face header on the four pages, with Muse's round hamburger and "•••" (sliders on the feed). */
@Composable
private fun TabHeader(
    tab: HomeTab,
    mood: io.github.nanomuse.ui.avatar.AgentMood,
    name: String,
    statusLine: String?,
    onAvatarClick: () -> Unit,
    onNameClick: () -> Unit,
    onOpenDrawer: () -> Unit,
    navController: NavHostController,
    mainSessionId: String?,
) {
    var menu by remember { mutableStateOf(false) }
    MuseHeader(
        mood = mood,
        name = name,
        statusLine = statusLine,
        onAvatarClick = onAvatarClick,
        onNameClick = onNameClick,
        leading = {
            MuseRoundButton(
                icon = Icons.Filled.Menu,
                contentDescription = stringResource(R.string.nm_open_drawer),
                onClick = onOpenDrawer,
            )
        },
        trailing = {
            if (tab == HomeTab.FEED) {
                MuseRoundButton(
                    icon = Icons.Outlined.Tune,
                    contentDescription = stringResource(R.string.nm_feed_settings_title),
                    onClick = { FeedUi.settingsOpen.value = true },
                )
            } else Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box {
                MuseRoundButton(
                    icon = Icons.Filled.MoreHoriz,
                    contentDescription = stringResource(R.string.nm_more),
                    onClick = { menu = true },
                )
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    if (tab == HomeTab.CHAT) {
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.nm_coding_title)) },
                            onClick = { menu = false; navController.safeNavigate(io.github.nanomuse.ui.coding.ROUTE_CODING) },
                        )
                    }
                    when (tab) {
                        HomeTab.GOALS -> {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_routine_all)) },
                                onClick = { menu = false; navController.safeNavigate(Routes.SCHEDULED_TASKS) },
                            )
                        }
                        HomeTab.LIBRARY -> {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_library_menu_shared_folders)) },
                                onClick = { menu = false; navController.safeNavigate(Routes.SHARED_FOLDERS) },
                            )
                            if (mainSessionId != null && !MainChat.isDraftId(mainSessionId)) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.chat_menu_browse_chat_files)) },
                                    onClick = { menu = false; navController.safeNavigate(Routes.chatFiles(mainSessionId)) },
                                )
                            }
                        }
                        else -> Unit
                    }
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.nm_sysfiles_title)) },
                        onClick = { menu = false; navController.safeNavigate(io.github.nanomuse.ui.sysfiles.ROUTE_SYSTEM_FILES) },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.nm_drawer_settings)) },
                        onClick = { menu = false; navController.safeNavigate(Routes.SETTINGS) },
                    )
                }
                }
            }
        },
    )
}
