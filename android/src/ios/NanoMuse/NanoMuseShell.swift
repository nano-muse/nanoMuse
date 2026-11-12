//
//  NanoMuseShell.swift
//  nanoMuse
//
//  The Muse shell on iPhone and iPad: one main chat pinned to the Chat tab,
//  a bottom bar for Chat / Feed / Ideas / Goals / Library, and a side
//  drawer with the other chats. The upstream split layout (ContentView)
//  stays reachable from the drawer and from the Settings switch. The first
//  run (NanoMuseFirstRun) shows in front of it all until the account and a
//  model are in. Android: ui/home/*.
//

import SwiftUI
import Combine

// MARK: - Preferences

enum NanoMuseShellPrefs {
    private static let shellKey = "nanomuse.shell.enabled"
    private static let headerKey = "nanomuse.header.enabled"

    /// The Muse shell on phones (off → the upstream OpenMinis layout).
    static var shell: Bool {
        get { UserDefaults.standard.object(forKey: shellKey) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: shellKey) }
    }

    /// The face · name · status header in the chat's navigation bar.
    static var museHeader: Bool {
        get { UserDefaults.standard.object(forKey: headerKey) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: headerKey) }
    }
}

// MARK: - Tabs

enum NanoMuseTab: String, CaseIterable, Identifiable {
    case chat, feed, ideas, goals, library
    var id: String { rawValue }

    var title: String {
        switch self {
        case .chat: return AppLocalized("tab.chat") // its own key: 聊天 as on Android, not upstream's 闲聊
        case .feed: return AppLocalized("Feed")
        case .ideas: return AppLocalized("Ideas")
        case .goals: return AppLocalized("Goals")
        case .library: return AppLocalized("Library")
        }
    }

    var symbol: String {
        switch self {
        case .chat: return "bubble.left"
        case .feed: return "doc.text"
        case .ideas: return "lightbulb"
        case .goals: return "checkmark.square"
        case .library: return "square.grid.2x2"
        }
    }

    var selectedSymbol: String {
        switch self {
        case .chat: return "bubble.left.fill"
        case .feed: return "doc.text.fill"
        case .ideas: return "lightbulb.fill"
        case .goals: return "checkmark.square.fill"
        case .library: return "square.grid.2x2.fill"
        }
    }
}

// MARK: - Root

/// What MinisApp shows: the Muse shell on phones, the upstream split
/// layout elsewhere. Also hosts the avatar studio sheet when the shell is
/// not around to do it.
struct NanoMuseRoot: View {
    @AppStorage("nanomuse.shell.enabled") private var shellEnabled = true
    @ObservedObject private var store = ProviderConfigStore.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var hasSessions: Bool?
    @State private var setupDone = NanoMuseFirstRun.isDone
    @State private var showSetupSettings = false
    @State private var showClassicSettings = false

    /// The Muse shell on iPhone and iPad alike; off → the upstream layout.
    private var usesShell: Bool { shellEnabled }

    /// The setup in front of everything until the account or a model of one's own is in (see NanoMuseFirstRun.needed).
    /// `nil` while the answer still hangs on the session list, so a fresh install never shows the
    /// shell for a frame before the welcome page.
    private var needsSetup: Bool? {
        let cloudId = NanoMuseCloud.instance?.id
        let providers = store.instances.contains { $0.isEnabled && $0.hasAnyCredential && $0.id != cloudId }
        if let hasSessions {
            return NanoMuseFirstRun.needed(signedIn: NanoMuseCloud.isSignedIn, hasProviders: providers, hasSessions: hasSessions, done: setupDone)
        }
        // Without the sessions: an app with neither a sign-in nor a key of its own needs the setup
        // whatever the list says; a finished setup never does; the one case between waits.
        if !NanoMuseCloud.isSignedIn && !providers { return true }
        return setupDone ? false : nil
    }

    var body: some View {
        Group {
            if needsSetup == nil {
                Color.clear
            } else if needsSetup == true {
                NanoMuseFirstRunView(
                    onStart: { setupDone = true },
                    onSettings: { showSetupSettings = true }
                )
                // The gear opens Muse's settings page; the OpenMinis list is under "All settings".
                .sheet(isPresented: $showSetupSettings) {
                    NavigationStack {
                        NanoMuseSettingsHomeView(onAllSettings: {
                            showSetupSettings = false
                            showClassicSettings = true
                        })
                    }
                }
                .sheet(isPresented: $showClassicSettings) {
                    NanoMuseClassicCover(wantsSettings: true)
                }
            } else if usesShell {
                NanoMuseHomeView()
            } else {
                ContentView()
                    .nanoMuseStudioPresenter(enabled: true)
                    .nanoMuseAgentPagePresenter(enabled: true, onOpenSession: { id in
                        NotificationCenter.default.post(name: .openSessionFromIntent, object: nil, userInfo: ["sessionId": id])
                    }, onPrefillChat: { text in
                        NotificationCenter.default.post(name: .nanoMuseComposerPrefill, object: nil, userInfo: ["text": text])
                    }, onOpenRoutines: nil)
            }
        }
        // The card for a step another device's Muse asks about, over the shell and the upstream layout alike.
        .nanoMuseRemoteApprovalPresenter()
        .onAppear {
            NanoMuseProfileSync.shared.start()
            NanoMuseAccountData.shared.start() // C12: whose chat is whose; the reinstall sweep
            NanoMuseSync.shared.start() // C7: conversations between the account's devices
            NanoMuseClientEvents.start() // what happened around a turn, as codes, to the account's record (relay 0.31)
            NanoMuseStarWatch.shared.start()
            NanoMuseStar.shared.dayOpened()
        }
        .nmOnChange(of: scenePhase) { phase in
            // C1: one more day with the app, counted when it comes to the front; C2: the release check, when stale.
            guard phase == .active else { return }
            NanoMuseStar.shared.dayOpened()
            NanoMuseUpdateCheck.shared.checkIfStale()
        }
        .task {
            hasSessions = !NanoMuseSync.shared.visible(await ChatStore.shared.listSessions()).isEmpty // C12: another account's chats do not count
            // The feed's daily routine exists from the start, as on Android (a no-op without a model).
            if needsSetup == false { await NanoMuseFeedFlow.ensureRoutine() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .sessionDidCreate)) { _ in
            hasSessions = true
        }
    }
}

/// Presents the agent's page when the header's face is tapped.
struct NanoMuseAgentPagePresenter: ViewModifier {
    var enabled: Bool
    var onOpenSession: (String) -> Void
    var onPrefillChat: (String) -> Void
    /// nil → the page's "Manage routines" opens the routines list in place.
    var onOpenRoutines: (() -> Void)?
    @State private var shown = false
    @State private var showRoutines = false

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .nanoMuseOpenAgentPage)) { _ in
                guard enabled else { return }
                shown = true
            }
            .sheet(isPresented: $shown) {
                NanoMuseAgentPage(
                    onOpenSession: { id in shown = false; onOpenSession(id) },
                    onPrefillChat: { text in shown = false; onPrefillChat(text) },
                    onOpenRoutines: {
                        shown = false
                        if let onOpenRoutines { onOpenRoutines() } else { showRoutines = true }
                    }
                )
            }
            .sheet(isPresented: $showRoutines) {
                NavigationStack {
                    NanoMuseRoutinesView()
                        .toolbar { ToolbarItem(placement: .cancellationAction) { Button(AppLocalized("Done")) { showRoutines = false } } }
                }
            }
    }
}

extension View {
    func nanoMuseAgentPagePresenter(enabled: Bool, onOpenSession: @escaping (String) -> Void, onPrefillChat: @escaping (String) -> Void, onOpenRoutines: (() -> Void)?) -> some View {
        modifier(NanoMuseAgentPagePresenter(enabled: enabled, onOpenSession: onOpenSession, onPrefillChat: onPrefillChat, onOpenRoutines: onOpenRoutines))
    }
}

/// Presents the avatar studio when the header's face is tapped.
struct NanoMuseStudioPresenter: ViewModifier {
    var enabled: Bool
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .nanoMuseOpenAvatarStudio)) { _ in
                guard enabled else { return }
                shown = true
            }
            .sheet(isPresented: $shown) {
                NanoMuseAvatarStudioView()
            }
    }
}

extension View {
    func nanoMuseStudioPresenter(enabled: Bool) -> some View {
        modifier(NanoMuseStudioPresenter(enabled: enabled))
    }
}

// MARK: - Main chat

/// The one conversation the Chat tab always shows. Remembered across
/// launches (UserDefaults); resolved as: the remembered session when it
/// still exists → the most recent session → a fresh draft.
@MainActor
final class NanoMuseMainChat: ObservableObject {
    static let key = "nanomuse.main_chat.session"
    static let draftPrefix = "__new__"

    @Published private(set) var chatId: String?
    @Published private(set) var isDraft = false
    /// The id the view model is cached under: the session, or nil while a draft has not been sent yet.
    @Published private(set) var liveId: String?

    private var cancellables: Set<AnyCancellable> = []

    init() {
        NotificationCenter.default.publisher(for: .sessionDidCreate)
            .receive(on: RunLoop.main)
            .sink { [weak self] note in self?.sessionCreated(note) }
            .store(in: &cancellables)
        // C10: another account signed in — its own main chat, or a fresh draft; never the
        // conversation the previous account left pinned here.
        NotificationCenter.default.publisher(for: .nanoMuseAccountSwitched)
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.accountSwitched() }
            .store(in: &cancellables)
    }

    func resolve() {
        Task { @MainActor [self] in
            let remembered = UserDefaults.standard.string(forKey: Self.key)
            // C10: a remembered chat of another account is not shown (NanoMuseSync.shows)
            if let remembered, NanoMuseSync.shared.shows(remembered), await ChatStore.shared.sessionExists(id: remembered) {
                set(remembered, draft: false)
                return
            }
            let sessions = NanoMuseSync.shared.visible(await ChatStore.shared.listSessions())
            if let latest = sessions.filter({ !$0.isRemote }).max(by: { $0.updatedAt < $1.updatedAt }) {
                UserDefaults.standard.set(latest.id, forKey: Self.key)
                set(latest.id, draft: false)
                return
            }
            set(Self.draftPrefix + UUID().uuidString, draft: true)
        }
    }

    /// C10: the account changed under the tab. The chat it showed for the account that came
    /// back is pinned again when it is still there; otherwise the tab resolves as on a first
    /// launch — the account's own conversations, or a draft the account's synced main adopts.
    private func accountSwitched() {
        Task { @MainActor [self] in
            if let remembered = NanoMuseSync.shared.rememberedMainSession, NanoMuseSync.shared.shows(remembered), await ChatStore.shared.sessionExists(id: remembered) {
                pin(remembered)
                return
            }
            UserDefaults.standard.removeObject(forKey: Self.key)
            resolve()
        }
    }

    /// Pin another conversation to the Chat tab.
    func pin(_ id: String) {
        UserDefaults.standard.set(id, forKey: Self.key)
        set(id, draft: false)
    }

    /// C7: a synced main conversation takes the place of a draft that has not been sent yet.
    func adoptIfDraft(_ id: String) {
        guard isDraft else { return }
        pin(id)
    }

    /// Start the main chat over with an empty draft.
    func startFresh() {
        UserDefaults.standard.removeObject(forKey: Self.key)
        set(Self.draftPrefix + UUID().uuidString, draft: true)
    }

    private func set(_ id: String, draft: Bool) {
        isDraft = draft
        chatId = id
        liveId = draft ? nil : id
    }

    private func sessionCreated(_ note: Notification) {
        guard isDraft, let realId = note.object as? String else { return }
        let draftId = (note.userInfo as? [String: String])?["draftId"]
        guard draftId == chatId else { return }
        // The draft became a real session: remember it, keep the view as is
        // (the view model is already cached under the real id).
        UserDefaults.standard.set(realId, forKey: Self.key)
        liveId = realId
    }
}

// MARK: - Keyboard

/// Hides the bottom bar while the keyboard is up, as Android's IME does.
@MainActor
final class NanoMuseKeyboardWatcher: ObservableObject {
    @Published private(set) var visible = false
    private var cancellables: Set<AnyCancellable> = []

    init() {
        NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.visible = true }
            .store(in: &cancellables)
        NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.visible = false }
            .store(in: &cancellables)
    }
}

// MARK: - Home

struct NanoMuseHomeView: View {
    @StateObject private var main = NanoMuseMainChat()
    @ObservedObject private var deviceChats = NanoMuseDeviceConversations.shared
    @ObservedObject private var hub = NanoMuseHub.shared
    @State private var chooseChatDestination = false
    @State private var deviceChatError: String?
    private let deviceChatPrefix = "__device__"
    @StateObject private var keyboard = NanoMuseKeyboardWatcher()
    @ObservedObject private var star = NanoMuseStar.shared
    @ObservedObject private var allowance = NanoMuseAllowance.shared
    /// The composer's voice panel stands in for the keyboard: the bottom bar leaves the same way.
    @ObservedObject private var voiceMode = VoiceModePreference.shared
    /// "Rename chat" from the main chat's ••• menu.
    @StateObject private var rename = NanoMuseRenamePrompt()

    @State private var tab: NanoMuseTab = .chat
    @State private var drawerOpen = false
    @State private var chatPath: [String] = []
    /// The Muse header's measured height over the main chat (`nmTopOverlay`), without the status bar.
    @State private var chatHeaderHeight: CGFloat = 0
    @State private var showClassic = false
    @State private var classicWantsSettings = false
    @State private var showNanoMuseSettings = false
    @State private var showCoding = false
    @State private var showRoutines = false
    /// The routine an idea just became, while its editor is up (the Ideas room has no sheet of its own).
    @State private var editingRoutine: NanoMuseRoutine?
    @State private var showSystemFiles = false
    @State private var showSharedFolders = false
    @State private var showChatFiles = false
    @State private var showDevices = false
    @State private var agentName = NanoMuseHomeView.currentAgentName()
    /// Reduce Motion on: the bottom bar fades out for the keyboard instead of sliding down.
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// The agent's name from SOUL.md, "nanoMuse" until it has one.
    static func currentAgentName() -> String {
        let n = SoulStore.cachedMetadata.name
        return n.isEmpty ? "nanoMuse" : n
    }

    /// Hidden while the keyboard is up (Android's IME) and while the chat's voice panel is
    /// open: the panel's own row — keyboard button, read-aloud, send — would otherwise sit
    /// under the bar with no way back to typing.
    private var bottomBarHidden: Bool {
        keyboard.visible || (tab == .chat && voiceMode.isVoiceActive)
    }

    private var roomsAndDrawer: some View {
        // The chat never gets the bottom bar as a `safeAreaInset`. 0.1.36 to 0.1.39 had it as
        // one, and an inset on the NavigationStack's ancestor reaches the chat inside it through
        // UIKit's safe area. What the device showed (iPad, 0.1.39; the maintainer's iPhone,
        // 0.1.36 to 0.1.38): the chat respected the bar's 56 pt at launch, and once the bar had
        // left for the keyboard and come back it no longer did: the chat ran under the bar and
        // its composer, bottom-aligned, sat behind it ("the input field shows until I dismiss
        // the keyboard, then never again"; the sliver of a composer's top edge above the bar in
        // the 0.1.36 screenshot). 0.1.40 made the bar a VStack row under the rooms, plain layout:
        // the chat is as tall as what is left over the bar, and over the keyboard, whether the
        // bar is there or not. The floating pill kept that for the chat as bottom padding of
        // the bar's height up to 1.0.3, which left a plain canvas behind the glass. Now the chat
        // gets the bar's height as an environment value instead (`nmBottomOverlay`): the chat
        // keeps its full height, its composer column stands above the bar and its rows scroll
        // under the column and the bar (NanoMuseComposerHost), so the pill blurs the transcript
        // the way it blurs the rooms. The rooms are plain SwiftUI scroll views with no
        // NavigationStack, so they take the bar's height as a safe-area inset: their content
        // scrolls under the pill too. The pill itself lies over both, aligned to the bottom,
        // inside the safe area.
        ZStack(alignment: .bottom) {
            ZStack {
                chatLayer
                    .environment(\.nmBottomOverlay, bottomBarHidden ? 0 : NanoMuseBottomBar.height)
                    .background(ChatColors.background.ignoresSafeArea())
                    .opacity(tab == .chat ? 1 : 0)
                    .allowsHitTesting(tab == .chat)
                    .accessibilityHidden(tab != .chat)
                if tab != .chat {
                    roomLayer
                        .safeAreaInset(edge: .bottom, spacing: 0) {
                            Color.clear
                                .frame(height: bottomBarHidden ? 0 : NanoMuseBottomBar.height)
                                .allowsHitTesting(false)
                        }
                        .transition(.opacity)
                }
            }
            .animation(.easeInOut(duration: 0.15), value: tab)
            if !bottomBarHidden {
                NanoMuseBottomBar(selected: $tab) { picked in
                    if picked == tab, picked != .chat { return }
                    tab = picked
                }
                .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeOut(duration: 0.2), value: bottomBarHidden)
        .overlay {
            NanoMuseDrawer(
                isOpen: $drawerOpen,
                agentName: agentName,
                currentId: chatPath.last ?? main.chatId,
                mainId: main.chatId,
                onOpenMain: {
                    chatPath.removeAll()
                    tab = .chat
                },
                onOpenSession: { id in openSideChat(id) },
                onNewChat: { chooseNewChat() },
                deviceChats: deviceChats,
                deviceChatPrefix: deviceChatPrefix,
                onPinMain: { id in
                    chatPath.removeAll()
                    main.pin(id)
                    tab = .chat
                },
                onDevices: { showDevices = true },
                onCoding: { showCoding = true },
                onSystemFiles: { showSystemFiles = true },
                onAllChats: { showClassic = true },
                onSettings: { showNanoMuseSettings = true }
            )
        }
    }

    var body: some View {
        roomsAndDrawer
        .nanoMuseStudioPresenter(enabled: !showClassic)
        .nanoMuseAgentPagePresenter(
            enabled: !showClassic,
            onOpenSession: { id in openSideChat(id) },
            onPrefillChat: { text in prefillMainChat(text) },
            onOpenRoutines: { showRoutines = true }
        )
        .sheet(isPresented: $showClassic) {
            NanoMuseClassicCover(wantsSettings: classicWantsSettings)
                .onDisappear { classicWantsSettings = false }
        }
        .sheet(isPresented: $showCoding) {
            NanoMusePageSheet(title: AppLocalized("Coding agents")) { NanoMuseCodingView() }
        }
        .sheet(isPresented: $showRoutines) {
            NanoMusePageSheet(title: AppLocalized("All routines")) { NanoMuseRoutinesView() }
        }
        .sheet(item: $editingRoutine) { routine in
            NanoMuseRoutineEditor(routine: routine)
        }
        .sheet(isPresented: $showSystemFiles) {
            NanoMusePageSheet(title: AppLocalized("System files")) { NanoMuseSystemFilesView() }
        }
        .sheet(isPresented: $showSharedFolders) {
            NanoMusePageSheet(title: AppLocalized("Shared Folders")) { SharedFoldersSettingsView() }
        }
        .sheet(isPresented: $showChatFiles) {
            NanoMusePageSheet(title: AppLocalized("Chat files")) {
                let base = RootfsManager.shared.dataPath
                FileBrowserView(rootPath: base, initialPath: base.appendingPathComponent("var/minis"), rootLabel: "/")
            }
        }
        .sheet(isPresented: $showDevices) {
            NanoMusePageSheet(title: AppLocalized("Computers")) {
                NanoMuseComputersView(onDeviceChat: deviceChats.available ? startDeviceChat : nil)
            }
        }
        .sheet(isPresented: $chooseChatDestination) {
            NanoMusePageSheet(title: AppLocalized("New Chat")) {
                NanoMuseDeviceChatPicker(onLocal: startLocalChat, onDevice: startDeviceChat)
            }
        }
        .alert(AppLocalized("Device chat"), isPresented: Binding(
            get: { deviceChatError != nil }, set: { if !$0 { deviceChatError = nil } }
        )) {
            Button(AppLocalized("OK"), role: .cancel) {}
        } message: {
            Text(deviceChatError ?? "")
        }
        .sheet(isPresented: $showNanoMuseSettings) {
            NavigationStack {
                NanoMuseSettingsHomeView(onAllSettings: {
                    showNanoMuseSettings = false
                    classicWantsSettings = true
                    showClassic = true
                })
            }
        }
        .onAppear {
            deviceChats.load()
            if main.chatId == nil { main.resolve() }
            // A notification tap that launched the app cold: the conversation it named.
            if let id = NotificationNavigationStore.shared.takePending() { openSideChat(id) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseAccountSwitched)) { _ in
            deviceChats.load()
            if let id = chatPath.last, id.hasPrefix(deviceChatPrefix),
               !deviceChats.chats.contains(where: { deviceChatPrefix + $0.id == id }) {
                chatPath.removeAll()
            }
        }
        .nmOnChange(of: hub.connected) { _ in deviceChats.load() }
        .onReceive(NotificationCenter.default.publisher(for: .soulMdChanged)) { _ in
            agentName = Self.currentAgentName()
        }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseHomeAction)) { note in
            // The Muse header's ••• menu on the rooms, and the rooms' own shortcuts.
            switch note.object as? String {
            case "settings": showNanoMuseSettings = true
            case "coding": showCoding = true
            case "routines": showRoutines = true
            case "systemFiles": showSystemFiles = true
            case "sharedFolders": showSharedFolders = true
            case "chatFiles": showChatFiles = true
            case "askDevice":
                // C7: "Ask this device" in the Devices list — the main chat with "@<name> " in the composer.
                guard let text = note.userInfo?["text"] as? String else { return }
                showDevices = false
                showNanoMuseSettings = false
                prefillMainChat(text)
            default: break
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseMainChatAdopt)) { note in
            // C7: the account's main chat arrived while ours was still an empty draft.
            guard let id = note.object as? String else { return }
            main.adoptIfDraft(id)
        }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseOpenChat)) { note in
            guard let id = note.object as? String else { return }
            openSideChat(id)
        }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseOpenRoom)) { note in
            // A fence card's "See in Goals" / "Open the feed".
            switch note.object as? String {
            case "goals": tab = .goals
            case "feed": tab = .feed
            case "ideas": tab = .ideas
            case "library": tab = .library
            default: break
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseOpenRoutines)) { _ in
            tab = .goals
        }
        .onReceive(NotificationCenter.default.publisher(for: .openSessionFromIntent)) { note in
            // A notification tap ("Check-in: … — open to run it") or a Shortcut: show that conversation.
            guard let id = note.userInfo?["sessionId"] as? String, !id.isEmpty else { return }
            openSideChat(id)
        }
        .onReceive(NotificationCenter.default.publisher(for: .newChatRequested)) { note in
            // *New Chat* in the ••• menu, ⌘N, the *Context Full* alert and the relay's refusal
            // cards all post this; upstream's ContentView answers it, and in this layout that view
            // is only on screen under the classic cover, so the tap did nothing (#392). A fresh
            // draft side chat here, as the drawer's new chat button opens one; with the classic
            // cover up, ContentView handles it inside the sheet.
            guard !showClassic else { return }
            if note.object as? String == "menu" { chooseNewChat() }
            else { startLocalChat() }
        }
        .onReceive(NanoMuseVoicePrompt.shared.$pending) { request in
            // The Action Button's voice prompt with no chat named (#296): the main chat, on
            // screen, is the one to listen. Aimed at it by id, so a side chat pushed over it
            // does not take the press; the id follows once the main chat has resolved.
            guard let request, request.session == nil else { return }
            drawerOpen = false
            tab = .chat
            chatPath.removeAll()
            if let id = main.chatId { NanoMuseVoicePrompt.shared.aim(at: id) }
        }
        .onReceive(main.$chatId) { id in
            if let id, NanoMuseVoicePrompt.shared.pending?.session == nil { NanoMuseVoicePrompt.shared.aim(at: id) }
        }
    }

    /// Words in the main chat's composer ("Change your avatar to "), with the chat on screen.
    private func prefillMainChat(_ text: String) {
        chatPath.removeAll()
        tab = .chat
        NotificationCenter.default.post(name: .nanoMuseComposerPrefill, object: main.chatId, userInfo: ["text": text])
    }

    /// A message sent in the main chat on the person's behalf (a goal's opener, as Android's sendToMainChat).
    private func sendToMainChat(_ text: String) {
        chatPath.removeAll()
        tab = .chat
        if let id = main.chatId, !main.isDraft, let vm = ViewModelCache.shared.get(for: id) {
            vm.nmSendNow(text)
        } else {
            NotificationCenter.default.post(name: .nanoMuseComposerPrefill, object: main.chatId, userInfo: ["text": text, "send": true])
        }
    }

    private func chooseNewChat() {
        deviceChats.load()
        if deviceChats.storageError {
            deviceChatError = AppLocalized("Could not open the saved device chats.")
        }
        if deviceChats.available, !hub.others.isEmpty {
            chooseChatDestination = true
        } else {
            startLocalChat()
        }
    }

    private func startLocalChat() {
        chooseChatDestination = false
        openSideChat(NanoMuseMainChat.draftPrefix + UUID().uuidString)
    }

    private func startDeviceChat(_ device: HubDevice) {
        do {
            let id = try deviceChats.create(device)
            chooseChatDestination = false
            showDevices = false
            openSideChat(deviceChatPrefix + id)
        } catch let failure as HubError {
            deviceChatError = NanoMuseHubErrors.describe(failure)
        } catch {
            deviceChatError = AppLocalized("Could not save the device chat.")
        }
    }

    private func openSideChat(_ id: String) {
        drawerOpen = false
        tab = .chat
        if id == main.chatId {
            chatPath.removeAll()
            return
        }
        chatPath = [id]
    }

    // MARK: Chat layer

    private var chatLayer: some View {
        NavigationStack(path: $chatPath) {
            Group {
                if let id = main.chatId {
                    AIChatView(sessionId: main.isDraft ? nil : id, draftId: main.isDraft ? id : nil)
                        .id(id)
                } else {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            // Android: the header floats over the transcript, which scrolls under it. The header
            // is a safe-area inset with its measured height handed to the chat as `nmTopOverlay`:
            // the chat lets its message list extend under the header and gives the list that
            // much top content inset (AIChatView.messagesArea), so the rows pass under the face
            // the way they pass under the composer and the bottom bar. Behind the header a scrim
            // of the canvas colour fading to clear, not a blur and not a bar, and there is no
            // divider line (NanoMuseHeaderScrim). Up to 1.0.4 the inset alone shortened the
            // list, a UIKit view, and the rows stopped at a hard edge under the face.
            .environment(\.nmTopOverlay, chatHeaderHeight)
            .safeAreaInset(edge: .top, spacing: 0) {
                VStack(spacing: 0) {
                    // MuseHeader over the main chat — the face, the name pill, the drawer and ••• discs.
                    NanoMuseChatHeaderHost(
                        liveId: main.liveId,
                        name: agentName,
                        onFace: { NotificationCenter.default.post(name: .nanoMuseOpenAgentPage, object: main.liveId ?? main.chatId) },
                        leading: { drawerDisc },
                        trailing: { chatMenu }
                    )
                    // C1: the ask for a star, when NanoMuseStar's gate raises one; under the header, over the chat.
                    if let ask = star.pending {
                        NanoMuseStarCard(text: ask.text) {
                            star.dismiss()
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .padding(.horizontal, 12)
                        .padding(.bottom, 6)
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                    // C11 / parity #33: a turn refused for the free allowance — the ways on, pinned like the star card.
                    if let refused = allowance.pending {
                        ScrollView(showsIndicators: false) {
                            NanoMuseAllowanceCard(
                                refused: refused,
                                onTryAgain: { allowance.retry(session: main.liveId ?? main.chatId) },
                                onDismiss: { allowance.dismiss() }
                            )
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                        }
                        .frame(maxHeight: 360)
                        .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .padding(.horizontal, 12)
                        .padding(.bottom, 6)
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
                .onGeometryChange(for: CGFloat.self) { proxy in
                    proxy.size.height
                } action: { height in
                    if abs(height - chatHeaderHeight) > 0.5 { chatHeaderHeight = height }
                }
                .background {
                    NanoMuseChatScrimHost(liveId: main.liveId)
                        .ignoresSafeArea(edges: .top)
                }
            }
            .background(ChatColors.background.ignoresSafeArea())
            // Android: a swipe in from the leading edge opens the drawer on the Chat tab; here too,
            // on the main chat (a pushed side chat keeps the system's back swipe).
            .background(NanoMuseEdgeSwipe(enabled: tab == .chat && chatPath.isEmpty && !drawerOpen) { drawerOpen = true })
            .nmRenameAlert(rename)
            // The system bar stays out of the main chat; side chats pushed from here keep theirs.
            .toolbar(.hidden, for: .navigationBar)
            .animation(.easeInOut(duration: 0.25), value: star.pending)
            .animation(.easeInOut(duration: 0.25), value: allowance.pending)
            .navigationDestination(for: String.self) { id in
                if id.hasPrefix(deviceChatPrefix) {
                    NanoMuseDeviceChatView(conversations: deviceChats, id: String(id.dropFirst(deviceChatPrefix.count)))
                        .id(id)
                } else {
                    let draft = id.hasPrefix(NanoMuseMainChat.draftPrefix)
                    AIChatView(sessionId: draft ? nil : id, draftId: draft ? id : nil)
                        .id(id)
                        // The side chat keeps the system bar and no Muse header over its list.
                        .environment(\.nmSystemBarScrim, true)
                        .environment(\.nmTopOverlay, 0)
                }
            }
        }
    }

    /// The round hamburger: the drawer with the side chats.
    private var drawerDisc: some View {
        NanoMuseRoundButton(symbol: "line.3.horizontal", label: AppLocalized("Chats and settings")) {
            drawerOpen = true
        }
    }

    /// Android: the Chat room's ••• menu — this chat's own entries, then the shared rows.
    private var chatMenu: some View {
        Menu {
            Button { chatAction(.newChat) } label: { Label(AppLocalized("New Chat"), systemImage: "square.and.pencil") }
            // Android: rename from the room's menu; a chat that has not been sent yet has no row to name.
            if let id = main.chatId, !main.isDraft {
                Button { rename.open(id) } label: { Label(AppLocalized("Rename chat"), systemImage: "pencil") }
            }
            if !NanoMuseAppearance.shared.headerModel {
                Button { chatAction(.model) } label: { Label(AppLocalized("Model"), systemImage: "cpu") }
            }
            Button(role: .destructive) { chatAction(.clearChat) } label: { Label(AppLocalized("Clear Chat"), systemImage: "trash") }
            Divider()
            Button { chatAction(.terminal) } label: { Label(AppLocalized("Open Terminal"), systemImage: "terminal") }
            Button { chatAction(.browser) } label: { Label(AppLocalized("Open Browser"), systemImage: "safari") }
            Button { chatAction(.files) } label: { Label(AppLocalized("Browse Chat Files"), systemImage: "folder") }
            Button { chatAction(.tokenUsage) } label: { Label(AppLocalized("Token Usage"), systemImage: "chart.bar") }
            Divider()
            Button { showCoding = true } label: { Label(AppLocalized("Coding agents"), systemImage: "chevron.left.forwardslash.chevron.right") }
            Button { showRoutines = true } label: { Label(AppLocalized("All routines"), systemImage: "clock") }
            Button { showSystemFiles = true } label: { Label(AppLocalized("System files"), systemImage: "doc.text") }
            Divider()
            Button { showNanoMuseSettings = true } label: { Label(AppLocalized("Settings"), systemImage: "gearshape") }
        } label: {
            NanoMuseRoundDisc(symbol: "ellipsis")
        }
        .accessibilityLabel(Text(AppLocalized("More")))
    }

    /// One of this chat's own menu entries: AIChatView acts on it (see its `// nanoMuse:` hook).
    private func chatAction(_ action: NanoMuseChatAction) {
        guard let id = main.chatId else { return }
        NanoMuseChatAction.post(action, session: main.liveId ?? id)
    }

    // MARK: Rooms

    @ViewBuilder
    private var roomLayer: some View {
        switch tab {
        case .chat:
            EmptyView()
        case .feed:
            NanoMuseFeedRoom(
                chrome: chrome,
                onDiscuss: { post in discussPost(post) },
                onOpenSession: { id in openSideChat(id) }
            )
        case .ideas:
            NanoMuseIdeasRoom(
                chrome: chrome,
                onSend: { prompt in startChat(with: prompt) },
                onCreateRoutine: { idea in createRoutine(from: idea) },
                onStartGoal: { category, seed in startGoal(category, seed: seed) }
            )
        case .goals:
            NanoMuseGoalsRoom(
                chrome: chrome,
                onStartGoal: { category in startGoal(category) },
                onOpenSession: { id in openSideChat(id) }
            )
        case .library:
            NanoMuseLibraryRoom(chrome: chrome, sessionId: main.isDraft ? nil : main.chatId)
        }
    }

    /// What the rooms need for their Muse header.
    private var chrome: NanoMuseRoomChrome {
        NanoMuseRoomChrome(liveId: main.liveId, name: agentName, hasMainSession: !main.isDraft && main.chatId != nil, onMenu: { drawerOpen = true })
    }

    /// "Create a goal › Health": the opener goes to the main chat; the model takes it from there (GoalFlow).
    private func startGoal(_ category: NanoMuseGoalCategory, seed: String? = nil) {
        guard let id = main.chatId else { return }
        let opener = NanoMuseGoalFlow.startCreation(session: id, category: category)
        let trimmed = (seed ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        sendToMainChat(trimmed.isEmpty ? opener : opener + " " + trimmed)
    }

    /// A routine from an idea: created at the idea's time (9:00 when it has none), then the editor,
    /// as a sheet of this view. Up to 1.0.4 the Goals room was asked to open it, and that room is
    /// not on screen while the Ideas room is, so the routine was made and nothing opened.
    private func createRoutine(from idea: NanoMuseIdea) {
        let at = NanoMuseDay.parseClock(idea.time) ?? (hour: 9, minute: 0)
        let routine = NanoMuseScheduler.shared.create(NanoMuseRoutine(
            label: String(idea.title.prefix(40)),
            prompt: idea.promptText,
            hour: at.hour,
            minute: at.minute,
            repeatMode: .daily
        ))
        editingRoutine = routine
    }

    /// "Discuss" on a feed card: a side chat that opens on the post.
    private func discussPost(_ post: NanoMusePost) {
        Task { @MainActor in
            let vm = ViewModelCache.shared.createDraft()
            let id = await vm.ensureSessionReturningId()
            await ChatStore.shared.updateSessionTitle(id, title: String(post.title.prefix(40)))
            ViewModelCache.shared.cacheDraft(vm, sessionId: id)
            openSideChat(id)
            vm.nmSendNow(NanoMuseFeedFlow.discussOpener(post))
        }
    }

    /// A new side chat with the text already in the composer.
    private func startChat(with prompt: String) {
        let draftId = NanoMuseMainChat.draftPrefix + UUID().uuidString
        ViewModelCache.pendingTransfer = ViewModelCache.PendingTransfer(targetId: draftId, inputText: prompt, attachments: [])
        openSideChat(draftId)
    }
}

extension Notification.Name {
    /// `object` is a session id (or a `__new__…` draft id): the shell shows it.
    static let nanoMuseOpenChat = Notification.Name("nanoMuse.openChat")
}

/// The upstream layout, presented from the drawer as a sheet (swipe down
/// to come back). Opening Settings goes through the deep-link coordinator
/// once the view is on screen.
private struct NanoMuseClassicCover: View {
    var wantsSettings: Bool

    var body: some View {
        ContentView()
            .nanoMuseStudioPresenter(enabled: true)
            .onAppear {
                guard wantsSettings else { return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                    DeepLinkCoordinator.shared.pendingSettingsTarget = .home
                }
            }
    }
}

// MARK: - The column on a wide window

/// The chat on a regular width (an iPad, a wide Split View pane): the message list, the
/// composer pill and the bottom bar share one centred column, so the conversation reads as one
/// column and not as three widths. Up to 1.0.3 the list was capped at 900 pt, the composer with
/// it and the bar at 420 pt: on an iPad in portrait the composer ran across the window, the bar
/// sat 420 pt wide under it and the agent's replies stayed in a 340 pt pill at the left edge.
/// The column is 760 pt, the width the web console gives its chat (`max-w-[760px]` in
/// `web/src/App.tsx`); the rows keep their 16 pt padding inside it and the two pills are as wide
/// as the rows' content, so their edges line up with the bubbles'. A compact width (every
/// iPhone, a narrow pane) is unchanged: the rows and the composer take the window and the bar
/// keeps its 420 pt cap, which no phone reaches.
enum NanoMuseColumn {
    /// The column's outer width, the rows' 16 pt padding included.
    static let width: CGFloat = 760
    /// The rows' horizontal padding, the composer's margins and the bar's inset: one number.
    static let margin: CGFloat = 16
    /// The composer pill and the bottom bar on a regular width: the column less its margins.
    static var pillWidth: CGFloat { width - margin * 2 }
    /// The agent's reply pill on a regular width, the web console's `wide:max-w-[600px]`; on a
    /// compact one it stays 340 pt, as Android's NmAssistantBubble.
    static let agentPillWidth: CGFloat = 600

    /// The width of a pill for a size class: the column's on a regular width, `fallback` on a
    /// compact one (the bar's 420 pt cap; nothing for the composer, which takes the window).
    static func pillWidth(for sizeClass: UserInterfaceSizeClass?, otherwise fallback: CGFloat?) -> CGFloat? {
        sizeClass == .regular ? pillWidth : fallback
    }

    /// The agent's reply pill for a size class.
    static func agentPillWidth(for sizeClass: UserInterfaceSizeClass?) -> CGFloat {
        sizeClass == .regular ? agentPillWidth : 340
    }
}

// MARK: - Bottom bar

/// Android's MuseBottomBar: a floating frosted-glass pill a little above the bottom edge, five
/// glyphs and no labels. The pill is `.ultraThinMaterial` under the shell's surface tone at 55
/// percent, with a 1 pt hairline; the current tab shows its filled glyph on a soft indicator
/// capsule that springs across to the tab tapped next, the others stay outlined and muted. The
/// pill is as wide as the composer above it (the same 16 pt margins): capped at 420 pt on a
/// compact width, the column's width on a regular one (NanoMuseColumn).
struct NanoMuseBottomBar: View {
    @Binding var selected: NanoMuseTab
    var onPick: (NanoMuseTab) -> Void
    @Namespace private var indicator
    /// Reduce Motion on: the indicator moves to the tapped tab without the spring.
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Regular on an iPad: the pill takes the column's width, the composer's.
    @Environment(\.horizontalSizeClass) private var sizeClass

    /// The indicator capsule behind the selected glyph, centred in its slot; the five slots share
    /// the pill's width equally.
    static let tabSize = CGSize(width: 60, height: 46)
    /// The pill's padding above and below the slots.
    static let pillPadding: CGFloat = 6
    /// Between the pill and the bottom safe area.
    static let bottomGap: CGFloat = 12
    /// The pill's distance from the screen's sides: the composer's margins in the shell
    /// (AIChatView, `nmPill`), so the two capsules stack with one edge.
    static let inset: CGFloat = 16
    /// The pill's cap on a compact width (an iPhone's composer never reaches it); a regular width
    /// takes `NanoMuseColumn.pillWidth` instead, so the pill is as wide as the composer there too.
    static let maxWidth: CGFloat = 420
    /// How much of the screen the bar takes above the safe area: the rooms' bottom safe-area
    /// inset and the chat's `nmBottomOverlay`, so their content scrolls under the pill and stops
    /// above it at rest; the glass blurs whatever passes behind.
    static var height: CGFloat { tabSize.height + pillPadding * 2 + bottomGap }

    var body: some View {
        HStack(spacing: 2) {
            ForEach(NanoMuseTab.allCases) { tab in
                let isSelected = selected == tab
                Button {
                    onPick(tab)
                } label: {
                    Group {
                        if tab == .library {
                            NanoMuseCategoryShape(filled: isSelected)
                                .fill(style: FillStyle(eoFill: true))
                                .frame(width: 24, height: 24)
                        } else {
                            Image(systemName: isSelected ? tab.selectedSymbol : tab.symbol)
                                .font(.system(size: 22, weight: isSelected ? .semibold : .regular))
                        }
                    }
                    .foregroundStyle(isSelected ? NanoMuseTones.tabIndicatorGlyph : Color.secondary)
                    // The capsule keeps its 60 by 46 (narrower only when the slot is).
                    .frame(maxWidth: Self.tabSize.width)
                    .frame(height: Self.tabSize.height)
                    .background {
                        if isSelected {
                            Capsule()
                                .fill(NanoMuseTones.tabIndicator)
                                .matchedGeometryEffect(id: "indicator", in: indicator)
                        }
                    }
                    // The slot: an equal share of the pill, all of it tappable.
                    .frame(maxWidth: .infinity)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text(tab.title))
                .accessibilityAddTraits(isSelected ? .isSelected : [])
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, Self.pillPadding)
        .background {
            Capsule().fill(.ultraThinMaterial)
            Capsule().fill(NanoMuseTones.surface.opacity(0.55))
        }
        .overlay(Capsule().strokeBorder(NanoMuseTones.hairline, lineWidth: 1))
        .animation(reduceMotion ? nil : Animation.spring(response: 0.35, dampingFraction: 0.8), value: selected)
        .frame(maxWidth: NanoMuseColumn.pillWidth(for: sizeClass, otherwise: Self.maxWidth))
        .frame(maxWidth: .infinity)
        .padding(.horizontal, Self.inset)
        .padding(.bottom, Self.bottomGap)
    }
}

/// Material's `Category` icon (top triangle, bottom-left square, bottom-right circle on a 24x24
/// grid), matching Android's Library tab icon (`Icons.Outlined.Category` / `Icons.Filled.Category`).
private struct NanoMuseCategoryShape: Shape {
    let filled: Bool

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 24.0
        let ox = rect.minX + (rect.width - 24.0 * s) / 2.0
        let oy = rect.minY + (rect.height - 24.0 * s) / 2.0
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: ox + x * s, y: oy + y * s)
        }
        func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
            CGRect(x: ox + x * s, y: oy + y * s, width: w * s, height: h * s)
        }

        var p = Path()
        p.move(to: pt(12, 2))
        p.addLine(to: pt(6.5, 11))
        p.addLine(to: pt(17.5, 11))
        p.closeSubpath()
        if !filled {
            p.move(to: pt(12, 5.84))
            p.addLine(to: pt(13.93, 9))
            p.addLine(to: pt(10.07, 9))
            p.closeSubpath()
        }

        p.addEllipse(in: box(13, 13, 9, 9))
        if !filled {
            p.addEllipse(in: box(15, 15, 5, 5))
        }

        p.addRect(box(3, 13.5, 8, 8))
        if !filled {
            p.addRect(box(5, 15.5, 4, 4))
        }
        return p
    }
}

// MARK: - Room header

extension Notification.Name {
    /// `object` is one of "settings", "coding", "routines", "systemFiles", "sharedFolders",
    /// "chatFiles": the home opens that page over the current tab.
    static let nanoMuseHomeAction = Notification.Name("nanoMuse.homeAction")
}

/// What Feed / Ideas / Goals / Library need to draw the Muse header: the
/// main chat's live id (its mood and status stay on the face while the
/// person is elsewhere), the agent's name, and the drawer.
struct NanoMuseRoomChrome {
    var liveId: String?
    var name: String
    /// The main chat is a real session (its files can be browsed).
    var hasMainSession: Bool
    var onMenu: () -> Void

    /// Ask the home to open one of its pages ("settings", "systemFiles", …).
    func open(_ page: String) {
        NotificationCenter.default.post(name: .nanoMuseHomeAction, object: page)
    }
}

/// The big-face header on the four rooms: the drawer disc on the left, the
/// room's own trailing content on the right (Android: NanoMuseHome.TabHeader).
struct NanoMuseRoomHeader<Trailing: View>: View {
    var chrome: NanoMuseRoomChrome
    @ViewBuilder var trailing: () -> Trailing

    init(chrome: NanoMuseRoomChrome, @ViewBuilder trailing: @escaping () -> Trailing) {
        self.chrome = chrome
        self.trailing = trailing
    }

    var body: some View {
        NanoMuseChatHeaderHost(
            liveId: chrome.liveId,
            name: chrome.name,
            onFace: { NotificationCenter.default.post(name: .nanoMuseOpenAgentPage, object: chrome.liveId) },
            leading: {
                NanoMuseRoundButton(symbol: "line.3.horizontal", label: AppLocalized("Chats and settings"), action: chrome.onMenu)
            },
            trailing: trailing
        )
    }
}

/// The ••• menu of a room: the room's own entries first, then System files and Settings, as Android.
struct NanoMuseRoomMenu<Items: View>: View {
    var chrome: NanoMuseRoomChrome
    @ViewBuilder var items: () -> Items

    init(chrome: NanoMuseRoomChrome, @ViewBuilder items: @escaping () -> Items) {
        self.chrome = chrome
        self.items = items
    }

    var body: some View {
        Menu {
            items()
            Button { chrome.open("systemFiles") } label: { Label(AppLocalized("System files"), systemImage: "doc.text") }
            Button { chrome.open("settings") } label: { Label(AppLocalized("Settings"), systemImage: "gearshape") }
        } label: {
            NanoMuseRoundDisc(symbol: "ellipsis")
        }
        .accessibilityLabel(Text(AppLocalized("More")))
    }
}

/// The big-face header bound to the main chat's view model once it exists
/// in the cache; until then (a draft that was never sent, the first frame
/// after launch) the face sits idle.
struct NanoMuseChatHeaderHost<Leading: View, Trailing: View>: View {
    /// The id the view model is cached under (nil for an unsent draft).
    var liveId: String?
    var name: String
    var onFace: () -> Void
    @ViewBuilder var leading: () -> Leading
    @ViewBuilder var trailing: () -> Trailing

    @State private var vm: AIChatViewModel?

    var body: some View {
        Group {
            if let vm {
                NanoMuseLiveHeader(vm: vm, name: name, onFace: onFace, leading: leading, trailing: trailing)
            } else {
                NanoMuseStillHeader(name: name, onFace: onFace, leading: leading, trailing: trailing)
            }
        }
        .task(id: liveId) { await bind() }
    }

    /// AIChatView puts the view model in the cache as it appears; look a few times, then give up quietly.
    private func bind() async {
        vm = nil
        vm = await NanoMuseChatLookup.viewModel(for: liveId)
    }
}

/// A page in a sheet: a navigation stack with a Done button.
struct NanoMusePageSheet<Content: View>: View {
    var title: String
    @ViewBuilder var content: () -> Content
    @Environment(\.dismiss) private var dismiss

    init(title: String, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        NavigationStack {
            content()
                .navigationTitle(title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(AppLocalized("Done")) { dismiss() }
                    }
                }
        }
    }
}

// MARK: - Drawer

/// The side drawer (Android: SideChatDrawer): the agent's name, the main
/// chat, Devices and Coding agents, the side chats with the archive glyph
/// to the full list, and a bottom strip — settings · system files · search
/// · new side chat.
struct NanoMuseDrawer: View {
    @Binding var isOpen: Bool
    var agentName: String
    var currentId: String?
    var mainId: String?
    var onOpenMain: () -> Void
    var onOpenSession: (String) -> Void
    var onNewChat: () -> Void
    @ObservedObject var deviceChats: NanoMuseDeviceConversations
    var deviceChatPrefix: String
    var onPinMain: (String) -> Void
    var onDevices: () -> Void
    var onCoding: () -> Void
    var onSystemFiles: () -> Void
    var onAllChats: () -> Void
    var onSettings: () -> Void

    @ObservedObject private var hub = NanoMuseHub.shared
    @ObservedObject private var sync = NanoMuseSync.shared
    @StateObject private var rename = NanoMuseRenamePrompt()
    @State private var sessions: [ChatSession] = []
    @State private var query = ""
    @State private var dragOffset: CGFloat = 0
    @State private var deleteCandidate: String?
    @State private var deleteDeviceChat: NanoMuseDeviceConversations.Chat?
    @State private var deviceChatSaveError = false
    /// Reduce Motion on: the panel fades in instead of sliding in from the edge.
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// The agent's name follows Dynamic Type, capped as the header's lines are (NanoMuseHeaderMetrics).
    @ScaledMetric(relativeTo: .title2) private var nameSize: CGFloat = 24

    /// The panel's width: most of the window, at most 320 pt. Measured from the window the
    /// drawer is in rather than the screen, so an iPad window narrower than the screen (Stage
    /// Manager, Split View) gets a drawer that fits it.
    private func width(in container: CGFloat) -> CGFloat { min(320, container * 0.82) }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                if isOpen {
                    Color.black.opacity(0.35)
                        .ignoresSafeArea()
                        .onTapGesture { close() }
                        .transition(.opacity)
                    panel(width: width(in: geo.size.width))
                        .frame(width: width(in: geo.size.width))
                        .offset(x: min(0, dragOffset))
                        .transition(reduceMotion ? .opacity : .move(edge: .leading))
                        .gesture(
                            DragGesture()
                                .onChanged { v in dragOffset = v.translation.width }
                                .onEnded { v in
                                    if v.translation.width < -60 { close() }
                                    dragOffset = 0
                                }
                        )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
        .allowsHitTesting(isOpen)
        .animation(.easeInOut(duration: 0.22), value: isOpen)
        .nmOnChange(of: isOpen) { open in
            if open { refresh() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .sessionDidUpdate).throttle(for: .seconds(1), scheduler: RunLoop.main, latest: true)) { _ in
            if isOpen { refresh() }
        }
    }

    /// The side chats: everything but the main chat, the search applied.
    private var filtered: [ChatSession] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let own = sessions.filter { !$0.isRemote && $0.id != mainId }
        guard !q.isEmpty else { return own }
        return own.filter { ($0.title ?? "").lowercased().contains(q) || ($0.lastMessage ?? "").lowercased().contains(q) }
    }

    private var filteredDeviceChats: [NanoMuseDeviceConversations.Chat] {
        guard deviceChats.available else { return [] }
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return deviceChats.chats.filter { chat in
            let name = deviceChats.device(for: chat.destination)?.name ?? chat.destination.name
            return q.isEmpty || name.localizedCaseInsensitiveContains(q) || chat.title.localizedCaseInsensitiveContains(q)
        }
    }

    private var mainSelected: Bool { currentId == nil || currentId == mainId }

    /// Android: "Off" when the hub is off, "Only this one" when no other device is online, else the count.
    private var devicesLine: String {
        if !hub.enabled { return AppLocalized("Off") }
        let online = hub.others.filter(\.online).count
        if online == 0 { return AppLocalized("Only this one") }
        return String(format: AppLocalized("%d devices"), online)
    }

    /// Computers online whose runtime can show and steer coding agents (Cursor, Codex, Claude Code).
    private var codingComputers: Int {
        hub.others.filter { $0.online && $0.isComputer && ($0.actions.isEmpty || $0.actions.contains("coding.sessions")) }.count
    }

    private func panel(width: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(agentName)
                .font(.system(size: NanoMuseHeaderMetrics.capped(nameSize, base: 24), weight: .bold))
                .lineLimit(1)
                .padding(.horizontal, 20)
                .padding(.top, 18)
                .padding(.bottom, 14)

            fixedRow(AppLocalized("Main chat"), symbol: "house", selected: mainSelected) {
                close()
                onOpenMain()
            }
            fixedRow(AppLocalized("Devices"), symbol: "laptopcomputer.and.iphone", value: devicesLine) {
                close()
                onDevices()
            }
            // Android: the row shows once a computer that can list coding agents is online, with their count.
            if codingComputers > 0 {
                fixedRow(AppLocalized("Coding agents"), symbol: "terminal", value: "\(codingComputers)") {
                    close()
                    onCoding()
                }
            }

            HStack {
                Text(AppLocalized("Side chats"))
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    close()
                    onAllChats()
                } label: {
                    Image(systemName: "archivebox")
                        .font(.system(size: 16, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text(AppLocalized("All chats")))
            }
            .padding(.leading, 20)
            .padding(.trailing, 10)
            .padding(.top, 14)

            if filtered.isEmpty && filteredDeviceChats.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.system(size: 22))
                        .foregroundStyle(.secondary)
                    Text(AppLocalized("Start a side chat"))
                        .font(.body.weight(.medium))
                    Text(AppLocalized("Side chats are an optional way to keep conversations organised by topic."))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 20)
                .padding(.top, 16)
                Spacer(minLength: 0)
            } else {
                List {
                    deviceChatRows
                    ForEach(filtered) { session in
                        Button {
                            close()
                            onOpenSession(session.id)
                        } label: {
                            row(session)
                        }
                        .listRowBackground(session.id == currentId ? NanoMuseTones.fill : Color.clear)
                        .contextMenu {
                            Button {
                                close()
                                onPinMain(session.id)
                            } label: {
                                Label(AppLocalized("Make this the main chat"), systemImage: "house")
                            }
                            Button {
                                rename.open(session.id)
                            } label: {
                                Label(AppLocalized("Rename chat"), systemImage: "pencil")
                            }
                            Divider()
                            Button(role: .destructive) {
                                deleteCandidate = session.id
                            } label: {
                                Label(AppLocalized("Delete chat"), systemImage: "trash")
                            }
                        } preview: {
                            // The default preview lifts the List cell, which the system lays out
                            // wider than the drawer; the drawer then clips it at its edge and the
                            // chat shows through. An explicit preview does not: the system sets it
                            // 16 pt in from the edge, so it is the panel's width less 16 pt each side.
                            row(session)
                                .padding(.horizontal, 20)
                                .padding(.vertical, 12)
                                .frame(width: width - 32, alignment: .leading)
                                .background(NanoMuseTones.surface)
                        }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .nmRenameAlert(rename)
                .alert(AppLocalized("Delete chat"), isPresented: Binding(get: { deleteCandidate != nil }, set: { if !$0 { deleteCandidate = nil } })) {
                    Button(AppLocalized("Cancel"), role: .cancel) {}
                    Button(AppLocalized("Delete"), role: .destructive) {
                        if let id = deleteCandidate {
                            NanoMuseChatDelete.delete(id)
                            sessions.removeAll { $0.id == id }
                        }
                        deleteCandidate = nil
                    }
                } message: {
                    Text(AppLocalized("The chat and its messages are removed from this device. With sync on, the other devices remove it too."))
                }
            }

            Divider()
            HStack(spacing: 4) {
                stripButton(symbol: "gearshape", label: AppLocalized("Settings")) {
                    close()
                    onSettings()
                }
                stripButton(symbol: "doc.text", label: AppLocalized("System files")) {
                    close()
                    onSystemFiles()
                }
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                    TextField(AppLocalized("Search"), text: $query)
                        .font(.subheadline)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(NanoMuseTones.fill, in: Capsule())
                stripButton(symbol: "square.and.pencil", label: AppLocalized("New side chat")) {
                    close()
                    onNewChat()
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 8)
        }
        .background(NanoMuseTones.surface.ignoresSafeArea())
        .alert(AppLocalized("Delete chat"), isPresented: Binding(
            get: { deleteDeviceChat != nil }, set: { if !$0 { deleteDeviceChat = nil } }
        ), presenting: deleteDeviceChat) { chat in
            Button(AppLocalized("Cancel"), role: .cancel) {}
            Button(AppLocalized("Delete"), role: .destructive) {
                do {
                    try deviceChats.remove(chat)
                    if currentId == deviceChatPrefix + chat.id { onOpenMain() }
                } catch {
                    deviceChatSaveError = true
                }
            }
        } message: { _ in
            Text(AppLocalized("This removes the device chat from this iPhone."))
        }
        .alert(AppLocalized("Could not save the device chat."), isPresented: $deviceChatSaveError) {
            Button(AppLocalized("OK"), role: .cancel) {}
        }
    }

    private var deviceChatRows: some View {
        ForEach(filteredDeviceChats) { chat in
            let id = deviceChatPrefix + chat.id
            let name = deviceChats.device(for: chat.destination)?.name ?? chat.destination.name
            Button {
                close()
                onOpenSession(id)
            } label: {
                Label {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(chat.turns.isEmpty ? name : chat.title).lineLimit(1)
                        if !chat.turns.isEmpty {
                            Text(name).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                } icon: {
                    Image(systemName: chat.destination.symbol)
                }
            }
            .listRowBackground(id == currentId ? NanoMuseTones.fill : Color.clear)
            .contextMenu {
                if chat.pending?.state != .accepted, !deviceChats.sending.contains(chat.id) {
                    Button(role: .destructive) { deleteDeviceChat = chat } label: {
                        Label(AppLocalized("Delete chat"), systemImage: "trash")
                    }
                }
            }
        }
    }

    private func fixedRow(_ title: String, symbol: String, value: String? = nil, selected: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .font(.system(size: 17))
                    .frame(width: 24)
                Text(title)
                    .font(.body)
                Spacer()
                if let value {
                    Text(value)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .foregroundStyle(.primary)
            .padding(.horizontal, 20)
            .padding(.vertical, 11)
            .background(selected ? NanoMuseTones.fill : Color.clear, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .padding(.horizontal, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func stripButton(symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 18))
                .foregroundStyle(.primary)
                .frame(width: 40, height: 36)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label))
    }

    private func row(_ session: ChatSession) -> some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text((session.title?.isEmpty == false ? session.title : nil) ?? AppLocalized("New chat"))
                    .font(.body)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                // C8: a chat that arrived through sync is an ordinary chat in this list; the
                // device shows under each of its bubbles ("From Pixel 8"), not here.
                if let last = session.lastMessage, !last.isEmpty {
                    Text(last)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Text(Self.when(session.updatedAt))
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }

    private func close() {
        isOpen = false
    }

    private func refresh() {
        Task { @MainActor [self] in
            // C10: the signed-in account's conversations and the unowned ones; another account's stay hidden
            let list = NanoMuseSync.shared.visible(await ChatStore.shared.listSessions())
            sessions = list.sorted { $0.updatedAt > $1.updatedAt }
        }
    }

    private static let relative: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        return f
    }()

    static func when(_ date: Date) -> String {
        relative.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - Star moments

/// Watches the activity tracker for turns that ran to their end and reports
/// each one that counts as a task (C1) to `NanoMuseStar`, whose gate decides
/// whether to ask for a star; the shell shows `NanoMuseStar.shared.pending`.
@MainActor
final class NanoMuseStarWatch {
    static let shared = NanoMuseStarWatch()

    private var active: Set<String> = []
    private var cancellable: AnyCancellable?

    private init() {}

    func start() {
        guard cancellable == nil else { return }
        active = SessionActivityTracker.shared.activeSessions
        cancellable = SessionActivityTracker.shared.$activeSessions
            .receive(on: RunLoop.main)
            .sink { [weak self] now in self?.activeChanged(now) }
    }

    private func activeChanged(_ now: Set<String>) {
        let ended = active.subtracting(now)
        active = now
        guard !ended.isEmpty else { return }
        for sid in ended where Self.countsAsTask(sid) {
            NanoMuseStar.shared.taskFinished()
        }
    }

    /// C1: a task is a turn the person started that ran to its end — not the
    /// first conversation while it is still going, not the feed's writing,
    /// not a routine's run, not a turn that failed.
    static func countsAsTask(_ sid: String) -> Bool {
        if NanoMuseFeedFlow.isFeedSession(sid) { return false }
        if NanoMuseScheduler.shared.routines.contains(where: { $0.sessionId == sid }) { return false }
        switch NanoMuseFirstConversation.shared.phase {
        case .askUserName, .askAgentName, .named: return false
        default: break
        }
        if let vm = ViewModelCache.shared.get(for: sid) {
            if vm.errorMessage != nil || vm.messages.last?.error != nil { return false }
            guard vm.messages.contains(where: { $0.role == .user }) else { return false }
        }
        return true
    }
}
