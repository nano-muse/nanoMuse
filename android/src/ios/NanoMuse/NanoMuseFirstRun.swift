//
//  NanoMuseFirstRun.swift
//  nanoMuse
//
//  The first run, the way Android does it (ui/onboarding/FirstRunSetup.kt):
//  Welcome (the account) → Password (only after a sign-in that created the
//  account) → Which model answers → Notifications → Meet <name>. Android's
//  Hands page does not exist on iPhone (no accessibility service to grant);
//  the phone page asks for notifications instead, which routines need.
//
//  Then the first conversation (onboarding/FirstConversation.kt): no form.
//  The app speaks first (scripted, zero tokens), asks what to call the
//  person, and the model — not a regex — reads the answer and reports in a
//  `nanomuse-naming` block; the app shows a name chooser under the model's
//  question and writes the pick to SOUL.md on the spot. Everything the app
//  shows on its own behalf is virtual: in the message list only, never in
//  the database or the model's history.
//

import Combine
import Foundation
import SwiftUI
import UserNotifications

// MARK: - When the setup shows

enum NanoMuseFirstRun {
    private static let doneKey = "nanomuse.setup.done"
    private static let sourceKey = "nanomuse.setup.source_chosen"
    static let notificationsKey = "nanomuse.setup.notifications_seen"

    static var isDone: Bool { UserDefaults.standard.bool(forKey: doneKey) }
    static func markDone() { UserDefaults.standard.set(true, forKey: doneKey) }
    static var sourceChosen: Bool { UserDefaults.standard.bool(forKey: sourceKey) }
    static func markSourceChosen() { UserDefaults.standard.set(true, forKey: sourceKey) }
    static var notificationsSeen: Bool { UserDefaults.standard.bool(forKey: notificationsKey) }
    static func markNotificationsSeen() { UserDefaults.standard.set(true, forKey: notificationsKey) }

    /// Whether the home shows the setup instead of the chat. It comes back when nothing could
    /// answer: neither a sign-in (the account's models) nor a provider of one's own with a key.
    /// A phone with its own key works signed out; the sign-in waits under Settings for the Cloud
    /// models, sync and the hub. Otherwise it stays only for a brand-new install, no conversation
    /// yet, until *Start* has been tapped, so the hand-off into the first conversation is
    /// deliberate.
    static func needed(signedIn: Bool, hasProviders: Bool, hasSessions: Bool, done: Bool) -> Bool {
        (!signedIn && !hasProviders) || (!hasSessions && !done)
    }

    enum Stage: Int { case welcome, password, source, models, notifications, meet }

    /// The page to show, from what the app has. Android has a Hands page where the iPhone
    /// has Notifications: routines and goal check-ins need the permission.
    /// Signed out with a provider of one's own (`hasProviders`), the account pages are skipped:
    /// the password is the account's and the source question is answered by the key.
    static func stage(signedIn: Bool, hasProviders: Bool = false, hasGroups: Bool, sourceChosen: Bool, modelsSkipped: Bool, fresh: Bool, passwordAnswered: Bool, notificationsSeen: Bool = true) -> Stage {
        if !signedIn && !hasProviders { return .welcome }
        if signedIn && fresh && !passwordAnswered { return .password }
        if signedIn && !sourceChosen { return .source }
        if !hasGroups && !modelsSkipped { return .models }
        if !notificationsSeen { return .notifications }
        return .meet
    }

    /// The dot that lights: account · phone · meet (the model pages fold into the first), as Android.
    static func dot(_ stage: Stage) -> Int {
        switch stage {
        case .welcome, .password, .source, .models: return 0
        case .notifications: return 1
        case .meet: return 2
        }
    }
}

// MARK: - The setup screen

struct NanoMuseFirstRunView: View {
    /// Start was tapped: the setup is done, the first conversation begins in the chat.
    var onStart: () -> Void
    var onSettings: () -> Void

    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var modelsSkipped = false
    @State private var sourceChosen = NanoMuseFirstRun.sourceChosen
    @State private var notificationsSeen = NanoMuseFirstRun.notificationsSeen
    @State private var passwordAnswered = false
    @State private var showSignIn = false
    @State private var showOwnKey = false
    @State private var showGroups = false
    @State private var agentName = SoulStore.cachedMetadata.name

    private var signedIn: Bool {
        _ = store.instances
        return NanoMuseCloud.isSignedIn
    }

    private var stage: NanoMuseFirstRun.Stage {
        NanoMuseFirstRun.stage(
            signedIn: signedIn,
            hasProviders: store.instances.contains { $0.isEnabled && $0.hasAnyCredential && $0.id != NanoMuseCloud.instance?.id },
            hasGroups: store.modelGroups.contains { !$0.memberEntryIds.isEmpty },
            sourceChosen: sourceChosen,
            modelsSkipped: modelsSkipped,
            fresh: signedIn && NanoMuseCloud.freshAccount,
            passwordAnswered: passwordAnswered,
            notificationsSeen: notificationsSeen
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                NanoMuseDots(current: NanoMuseFirstRun.dot(stage), total: 3)
                HStack {
                    Spacer()
                    Button(action: onSettings) {
                        Image(systemName: "gearshape")
                            .font(.system(size: 18, weight: .medium))
                            .foregroundStyle(.primary)
                            .frame(width: 44, height: 44)
                    }
                    .accessibilityLabel(AppLocalized("Settings"))
                }
                .padding(.trailing, 8)
            }
            .frame(height: 56)
            Group {
                switch stage {
                case .welcome: welcomePage
                case .password: NanoMusePasswordPage { NanoMuseCloud.clearFreshAccount(); passwordAnswered = true }
                case .source: sourcePage
                case .models: modelsPage
                case .notifications: NanoMuseNotificationsPage { NanoMuseFirstRun.markNotificationsSeen(); notificationsSeen = true }
                case .meet: meetPage
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .id(stage)
            .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .move(edge: .leading).combined(with: .opacity)))
            .animation(.easeInOut(duration: 0.26), value: stage)
        }
        .background(NanoMuseTones.surface.ignoresSafeArea())
        .sheet(isPresented: $showSignIn) { NavigationStack { NanoMuseCloudView() } }
        // Signed in: the sheet has done its job and goes, so the next page (the password, the
        // source) is in view at once instead of behind the account page.
        .nmOnChange(of: signedIn) { now in
            if now, showSignIn { showSignIn = false }
        }
        .sheet(isPresented: $showOwnKey) { NanoMuseOwnKeySheet { _ in } }
        .sheet(isPresented: $showGroups) { NavigationStack { ModelGroupsView() } }
        .onReceive(NotificationCenter.default.publisher(for: .soulMdChanged)) { _ in
            agentName = SoulStore.cachedMetadata.name
        }
    }

    // The first page: the app's tile (docs/brand.md: the sign-in page stands for the app, not the
    // agent), one line on what it is, the notice, and the door, the account, with a way past it
    // for a key of one's own.
    private var welcomePage: some View {
        NanoMuseSetupPage(
            hero: { NanoMuseBrandMark(size: 96) },
            title: AppLocalized("Welcome to nanoMuse"),
            subtitle: AppLocalized("An open-source personal agent for every device you own."),
            primaryLabel: AppLocalized("Sign in · free"),
            onPrimary: { showSignIn = true },
            secondaryLabel: AppLocalized("Use your own API key instead"),
            onSecondary: { NanoMuseFirstRun.markSourceChosen(); sourceChosen = true; showOwnKey = true },
            finePrint: AppLocalized("One account keeps your devices together and carries the free model use; nothing is charged. Your own API key can be added right after."),
            learnMore: URL(string: "https://github.com/nano-muse/nanoMuse/blob/main/docs/cloud.md")
        ) {
            NanoMuseFeatureRow(symbol: "bubble.left.and.bubble.right", title: AppLocalized("Chat, pictures, video"), subtitle: AppLocalized("A capable model, image and video generation, tools, skills and memory, on your phone"))
            NanoMuseFeatureRow(symbol: "desktopcomputer", title: AppLocalized("Reach: your computers, from here"), subtitle: AppLocalized("Pair a Mac, Windows or Linux machine and give it work from the phone"))
            // Android's third row is Hands (it uses the phone); the iPhone has no such service, so: goals and the feed.
            NanoMuseFeatureRow(symbol: "calendar.badge.clock", title: AppLocalized("Goals and a daily feed"), subtitle: AppLocalized("It checks in on what you are working towards and writes you a short post every morning"))
            NanoMuseNoticeCard(title: AppLocalized("Free, open source, non-profit"), body: AppLocalized("nanoMuse is a non-profit open-source community project, free, forever. The model comes with a free allowance paid by the developer; after that, your own key. Nothing is sold; what the relay keeps is in the privacy policy, and Settings → Data controls is yours."))
                .padding(.top, 8)
        }
    }

    // Right after the sign-in: which model answers.
    private var sourcePage: some View {
        NanoMuseSetupPage(
            hero: { NanoMuseHeroGlyph(symbol: "cloud") },
            title: AppLocalized("Which model answers?"),
            subtitle: AppLocalized("Your account already brings one. You can add your own API key as well and switch at any time."),
            primaryLabel: AppLocalized("Use the nanoMuse Cloud model"),
            onPrimary: { NanoMuseFirstRun.markSourceChosen(); sourceChosen = true },
            secondaryLabel: AppLocalized("I have my own API key"),
            onSecondary: { NanoMuseFirstRun.markSourceChosen(); sourceChosen = true; showOwnKey = true },
            finePrint: AppLocalized("The two do not compete: the Cloud model stays available, and each model group picks its own.")
        ) {
            NanoMuseFeatureRow(symbol: "cloud", title: AppLocalized("Use the nanoMuse Cloud model"), subtitle: AppLocalized("DeepSeek for chat, with pictures and clips too, and a free allowance per account paid by the developer. Nothing to configure."))
            NanoMuseFeatureRow(symbol: "key", title: AppLocalized("I have my own API key"), subtitle: AppLocalized("Alibaba Cloud Bailian, OpenRouter, OpenAI, Anthropic, DeepSeek and other OpenAI-compatible endpoints. The key stays on this phone."))
        }
    }

    // Own-key path only: the provider is there, its models are not chosen yet.
    private var modelsPage: some View {
        NanoMuseSetupPage(
            hero: { NanoMuseHeroGlyph(symbol: "sparkles") },
            title: AppLocalized("Choose models"),
            subtitle: AppLocalized("The models your provider serves are listed for you; pick up to three"),
            primaryLabel: AppLocalized("Continue"),
            onPrimary: { showGroups = true },
            secondaryLabel: AppLocalized("Skip for now"),
            onSecondary: { modelsSkipped = true },
            finePrint: AppLocalized("Your key stays on this phone and is sent only to the provider you chose.")
        ) {
            EmptyView()
        }
    }

    // The last page: the face again, and the hand-off into the first conversation.
    private var meetPage: some View {
        NanoMuseSetupPage(
            hero: { NanoMuseFaceView(mood: .idle, size: 104) },
            title: String(format: AppLocalized("Meet %@"), agentName),
            subtitle: AppLocalized("A first conversation: it asks what to call you and picks its own name"),
            primaryLabel: AppLocalized("Start"),
            onPrimary: { NanoMuseFirstRun.markDone(); onStart() },
            finePrint: AppLocalized("Before anything it cannot take back, such as deleting, sending or paying, it stops and asks you first.")
        ) {
            EmptyView()
        }
    }
}

/// Right after a sign-in that created the account: a password, so the next device signs in
/// without waiting for a code. Skippable; Account has the same form later.
struct NanoMusePasswordPage: View {
    var onDone: () -> Void
    @State private var next = ""
    @State private var again = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NanoMuseSetupPage(
            hero: { NanoMuseHeroGlyph(symbol: "key") },
            title: AppLocalized("Set a password"),
            subtitle: AppLocalized("Your account is in. With a password, your computers and your other phones sign in at once, without waiting for a code."),
            primaryLabel: AppLocalized("Set the password"),
            onPrimary: { Task { await save() } },
            secondaryLabel: AppLocalized("Skip for now"),
            onSecondary: onDone,
            finePrint: AppLocalized("Optional. You can set or change it later under Account."),
            busy: busy
        ) {
            VStack(spacing: 10) {
                SecureField(AppLocalized("New password (8 characters or more)"), text: $next)
                    .textContentType(.newPassword)
                    .textFieldStyle(.roundedBorder)
                SecureField(AppLocalized("Repeat the new password"), text: $again)
                    .textContentType(.newPassword)
                    .textFieldStyle(.roundedBorder)
                if let error {
                    Text(error).font(.footnote).foregroundStyle(.red).multilineTextAlignment(.center)
                }
            }
        }
    }

    private func save() async {
        guard !busy else { return }
        if next.count < 8 { error = AppLocalized("The password needs at least 8 characters."); return }
        if next != again { error = AppLocalized("The two passwords differ."); return }
        error = nil
        busy = true
        defer { busy = false }
        do {
            try await NanoMuseCloud.setPassword(next, current: nil)
            onDone()
        } catch {
            self.error = NanoMuseCloud.describe(error)
        }
    }
}

/// The phone page (Android has Hands here): notifications, so a routine coming due or a goal
/// check-in can call the person back to the app. Continue asks iOS; Skip leaves it for later.
struct NanoMuseNotificationsPage: View {
    var onDone: () -> Void
    @State private var status: UNAuthorizationStatus = .notDetermined
    @State private var busy = false

    private var granted: Bool { status == .authorized || status == .provisional || status == .ephemeral }

    var body: some View {
        NanoMuseSetupPage(
            hero: { NanoMuseBrandMark(size: 96) }, // the permission ask carries the app's mark, as the sign-in does (#224.6)
            title: AppLocalized("Notifications"),
            subtitle: AppLocalized("Routines and goal check-ins run at a set time. On the iPhone the agent cannot wake itself, so a reminder brings you back when one is due."),
            primaryLabel: granted ? AppLocalized("Continue") : AppLocalized("Allow notifications"),
            onPrimary: { if granted { onDone() } else { ask() } },
            secondaryLabel: granted ? nil : AppLocalized("Skip for now"),
            onSecondary: onDone,
            finePrint: AppLocalized("Everything else works without it. It lives under iOS Settings → nanoMuse whenever you want it."),
            busy: busy
        ) {
            NanoMuseFeatureRow(symbol: "clock", title: AppLocalized("Routines"), subtitle: AppLocalized("A message the agent sends itself at a set time: the feed every morning, anything you schedule."))
            NanoMuseFeatureRow(symbol: "target", title: AppLocalized("Goal check-ins"), subtitle: AppLocalized("It asks how a goal is going, when you said it should."))
        }
        .task { await refresh() }
    }

    private func refresh() async {
        status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    private func ask() {
        guard !busy else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            if status == .notDetermined {
                _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            } else if let url = URL(string: UIApplication.openSettingsURLString) {
                _ = await UIApplication.shared.open(url)
            }
            await refresh()
            if granted { onDone() }
        }
    }
}

/// Hero, title, one line under it, the page's own rows, then the pill(s) and the fine print.
struct NanoMuseSetupPage<Hero: View, Content: View>: View {
    @ViewBuilder var hero: () -> Hero
    var title: String
    var subtitle: String
    var primaryLabel: String
    var onPrimary: () -> Void
    var secondaryLabel: String? = nil
    var onSecondary: (() -> Void)? = nil
    var finePrint: String
    var learnMore: URL? = nil
    var busy: Bool = false
    @ViewBuilder var content: () -> Content

    /// The fine print as one paragraph, *Learn more* a link at its end.
    private var finePrintText: Text {
        guard let learnMore else { return Text(verbatim: finePrint) }
        let label = AppLocalized("Learn more")
        let link = (try? AttributedString(markdown: "[\(label)](\(learnMore.absoluteString))")) ?? AttributedString(label)
        return Text(verbatim: finePrint + " ") + Text(link)
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 14) {
                    hero()
                        .padding(.top, 12)
                    Text(title)
                        .font(.system(size: 26, weight: .semibold, design: .rounded))
                        .multilineTextAlignment(.center)
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 12)
                    VStack(alignment: .leading, spacing: 10) {
                        content()
                    }
                    .padding(.top, 10)
                }
                .padding(.horizontal, 24)
                .frame(maxWidth: 520)
                .frame(maxWidth: .infinity)
            }
            VStack(spacing: 10) {
                Button(action: onPrimary) {
                    HStack {
                        if busy { ProgressView().tint(.white) }
                        Text(primaryLabel).font(.headline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .tint(NanoMuseTones.action)
                .controlSize(.large)
                .disabled(busy)
                if let secondaryLabel, let onSecondary {
                    Button(secondaryLabel, action: onSecondary)
                        .font(.subheadline.weight(.medium))
                        .disabled(busy)
                }
                // One paragraph with the link at its end, so a long fine print wraps as text
                // instead of sitting beside a "Learn more" column.
                finePrintText
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .tint(NanoMuseTones.action)
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 24)
            .padding(.top, 8)
            .padding(.bottom, 12)
            .frame(maxWidth: 520)
        }
    }
}

struct NanoMuseFeatureRow: View {
    var symbol: String
    var title: String
    var subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(NanoMuseTones.action)
                .frame(width: 32, height: 32)
                .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold))
                Text(subtitle).font(.footnote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

struct NanoMuseNoticeCard: View {
    var title: String
    var body_: String
    init(title: String, body: String) { self.title = title; self.body_ = body }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.footnote.weight(.semibold))
            Text(body_).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct NanoMuseHeroGlyph: View {
    var symbol: String
    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 40, weight: .medium))
            .foregroundStyle(NanoMuseTones.action)
            .frame(width: 104, height: 104)
            .background(NanoMuseTones.fill, in: Circle())
    }
}

struct NanoMuseDots: View {
    var current: Int
    var total: Int
    var body: some View {
        HStack(spacing: 6) {
            ForEach(0..<total, id: \.self) { i in
                Capsule()
                    .fill(i == current ? NanoMuseTones.action : NanoMuseTones.hairline)
                    .frame(width: i == current ? 18 : 6, height: 6)
            }
        }
    }
}

// MARK: - The first conversation

/// What the model told the app in a `nanomuse-naming` block.
struct NanoMuseNamingBlock: Equatable {
    /// The block had a `user_address` key (nil value = the user wants no form of address).
    var addressGiven: Bool
    var userAddress: String?
    /// Names the model suggests for itself, already cleaned.
    var suggestions: [String]
    /// The name the user gave the agent, if this block says so.
    var agentName: String?
}

struct NanoMuseNamingCard: Equatable {
    var suggestions: [String]
    var chosen: String?
}

@MainActor
final class NanoMuseFirstConversation: ObservableObject {
    static let shared = NanoMuseFirstConversation()

    nonisolated static let block = "naming"
    nonisolated static let takenNames = "Siri, Alexa, Cortana, Jarvis, Muse, Gemini, Copilot, 小爱, 小度, 小艺, 天猫精灵, 豆包, 文心, 通义, 阿福"
    nonisolated static let maxName = 16
    nonisolated static let namePoolEN = ["Pip", "Wren", "Juno", "Remy", "Tilly", "Milo", "Sol", "Fig"]
    nonisolated static let namePoolZH = ["豆丁", "小满", "团团", "叮叮", "小北", "一一", "小竹", "阿岳"]

    enum Phase: String {
        /// Never started; eligible on the next fresh draft if the name is still the default.
        case none
        /// The opening is on screen; the user is answering "what should I call you?".
        case askUserName
        /// The model asked for its name; the chooser card is showing.
        case askAgentName
        /// The name was just picked from the chooser; the model's next reply is its first as itself.
        case named
        /// Over — either completed or the user talked past it.
        case done
    }

    private enum Keys {
        static let phase = "nanomuse.first_conversation.phase"
        static let session = "nanomuse.first_conversation.session"
        static let address = "nanomuse.first_conversation.address"
        static let suggestions = "nanomuse.first_conversation.suggestions"
    }

    @Published private(set) var card: NanoMuseNamingCard?
    /// The virtual opening lines, by message id, so a reload can tell them from real ones.
    private(set) var introIds: Set<UUID> = []

    var phase: Phase {
        get { UserDefaults.standard.string(forKey: Keys.phase).flatMap(Phase.init(rawValue:)) ?? .none }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: Keys.phase); objectWillChange.send() }
    }

    /// The session (draft key or real id) the conversation is bound to.
    private(set) var sessionKey: String? {
        get { UserDefaults.standard.string(forKey: Keys.session) }
        set { UserDefaults.standard.set(newValue, forKey: Keys.session) }
    }

    /// Whether the intro belongs in `current`'s transcript — either it starts here or it already did.
    func shouldShowIntro(current: String, hasOtherSessions: Bool) -> Bool {
        if let bound = sessionKey, phase != .none {
            // A dead draft (left before the first message) re-seeds in the next draft.
            return bound == current || (phase == .askUserName && !Self.isRealSession(bound) && !Self.isRealSession(current))
        }
        return phase == .none && !hasOtherSessions && SoulStore.cachedMetadata.name == SoulMetadata.default.name
    }

    /// A draft's key starts with `__new__` (ContentView.makeNewSessionId) or is the bare "draft"; a real session's is its id.
    nonisolated static func isRealSession(_ key: String) -> Bool {
        !(key.hasPrefix("__new__") || key == "draft")
    }

    /// Bind to `current` and step into `.askUserName` if this is the start.
    func start(current: String) {
        sessionKey = current
        if phase == .none { phase = .askUserName }
        if phase == .askAgentName { card = NanoMuseNamingCard(suggestions: currentSuggestions()) }
    }

    /// The draft became a real session: keep following it.
    func rebind(from draft: String, to real: String) {
        if sessionKey == draft { sessionKey = real }
    }

    func isBound(to key: String) -> Bool { sessionKey == key && phase != .none }

    /// The three opening paragraphs, in the app's language.
    func intro() -> [String] {
        [
            AppLocalized("Hi, I'm nanoMuse, the assistant that lives on your phone. Let me take a few things off your plate."),
            AppLocalized("A bit about how I work:\n\n- I have my own computer, a Linux sandbox and a browser, so I can run commands, open websites and fill in forms.\n- I can read and organise the files and photos you share with me, and take care of reminders and scheduled tasks.\n- Before any step that matters, I ask you first.\n- Everything runs on this phone. Your messages go to the model you configured; signed in to nanoMuse Cloud, this conversation also follows you to your other devices. Data controls switches that off."),
            AppLocalized("Before we start, what should I call you?"),
        ]
    }

    /// Put the opening in the chat when this is where the first conversation starts (or where it already is).
    func seedIfNeeded(vm: AIChatViewModel) async {
        let key = vm.nmSessionKey
        let hasSessions = !NanoMuseSync.shared.visible(await ChatStore.shared.listSessions()).isEmpty // C12: a new account meets the muse afresh
        guard shouldShowIntro(current: key, hasOtherSessions: hasSessions) else { return }
        start(current: key)
        let present = vm.messages.contains { introIds.contains($0.id) }
        if !present {
            var fresh: [ChatMessage] = []
            for text in intro() {
                fresh.append(ChatMessage(role: .assistant, content: text, blocks: [AssistantBlock(kind: .text, content: text)]))
            }
            introIds = Set(fresh.map(\.id))
            vm.messages.insert(contentsOf: fresh, at: 0)
        }
    }

    /// What the person typed goes to the model as it is; the model says what it meant in a block.
    func handle(_ text: String, in vm: AIChatViewModel) -> Bool {
        false
    }

    /// The model's reply just finished. Reads its `nanomuse-naming` block, if any, and moves the
    /// phase; a reply without one leaves the phase alone (the user talked about something else,
    /// and the model steered back).
    func afterTurn(session: String, assistantText: String?, vm: AIChatViewModel) {
        guard isBound(to: session) else { return }
        let block = Self.parseBlock(assistantText)
        switch phase {
        case .askUserName:
            guard let block, block.addressGiven else { return }
            if let address = block.userAddress { saveAddress(address) }
            if !block.suggestions.isEmpty { UserDefaults.standard.set(block.suggestions.joined(separator: "\n"), forKey: Keys.suggestions) }
            phase = .askAgentName
            card = NanoMuseNamingCard(suggestions: currentSuggestions())
        case .askAgentName:
            if let name = block?.agentName {
                // The model already replied as itself in this turn, so the ritual is over.
                applyName(name)
                phase = .done
                card = nil
                finished()
            }
        case .named:
            phase = .done
            card = nil
            finished()
        case .none, .done:
            break
        }
    }

    /// The agent has its name (C5): the first feed day gets written in the background, once.
    private func finished() {
        NanoMuseFeedFlow.writeFirstDayIfNeeded()
    }

    /// A chip was tapped: the name is saved at once; the model's next reply is its first as itself.
    func pick(name: String) {
        guard phase == .askAgentName else { return }
        applyName(name)
        phase = .named
    }

    /// The user moved on to something the app handles itself (an avatar change): drop the chooser.
    func dismissChooser() {
        if phase == .askAgentName {
            phase = .done
            card = nil
        }
    }

    /// Forget the whole thing (the SOUL name stays): used when the person resets the setup.
    func reset() {
        for key in [Keys.phase, Keys.session, Keys.address, Keys.suggestions] { UserDefaults.standard.removeObject(forKey: key) }
        card = nil
        introIds = []
        objectWillChange.send()
    }

    private func applyName(_ name: String) {
        let current = SoulStore.load() ?? SoulMDParser.parse(SoulStore.defaultContent)
        var file = current
        file.metadata.name = name
        try? SoulStore.save(file)
        // C8: the name is the account's — the other devices hear it (debounced, with the face kept).
        NanoMuseProfileSync.shared.nameChanged()
        card = NanoMuseNamingCard(suggestions: card?.suggestions ?? currentSuggestions(), chosen: name)
    }

    /// The system-prompt addendum for the current phase; nil once it is over.
    func systemAddendum(session: String) -> String? {
        guard isBound(to: session) else { return nil }
        let address = UserDefaults.standard.string(forKey: Keys.address)
        let addressLine = address.map { " The user goes by \"\($0)\"; address them that way." } ?? ""
        let fence = "```nanomuse-" + Self.block
        switch phase {
        case .askUserName:
            var s = "First conversation. The app already showed the user this opening on your behalf:\n"
            for line in intro() { s += "  > " + line.replacingOccurrences(of: "\n", with: "\n  > ") + "\n" }
            s += "They are now replying to the last line (what should I call you?). Decide from their message what they meant:\n"
            s += "(a) If it says how to address them (a name, a nickname, \"just call me boss\"), confirm it in one short sentence, "
            s += "ask in one sentence what they would like to call you, and end the reply with exactly this fenced block:\n"
            s += fence + "\n{\"user_address\": \"<how to address them>\", \"suggest\": [\"<name 1>\", \"<name 2>\"]}\n```\n"
            s += "`suggest` holds two names for yourself the user could pick, in the language they write: two-character Chinese names "
            s += "in the spirit of 豆丁 or 小满 (warm, a little playful, easy to say) when they write Chinese; short English names like Pip or Wren otherwise. "
            s += "Never suggest the name of an existing assistant or product (\(Self.takenNames)), nor the user's own name. "
            s += "The app renders the block as a chooser under your reply, so do not list the names in your text.\n"
            s += "(b) If they say they would rather not be called anything in particular, do the same with \"user_address\": null.\n"
            s += "(c) If the message is about something else (a question, a task, small talk), help with it first, in full, "
            s += "and end with one light sentence bringing the question back (what should I call you?). No block in that case; the app keeps waiting.\n"
            s += "Reply in the user's language; keep it short."
            return s
        case .askAgentName:
            let chips = currentSuggestions()
            var s = "First conversation. You asked what the user would like to call you; the app is showing a chooser under that question with "
            s += chips.map { "\"\($0)\"" }.joined(separator: ", ") + " and \"something else\". Decide from their message:\n"
            s += "(a) If it gives you a name, typed on its own, \"call you 豆丁\", \"the first one\" (meaning \"\(chips.first ?? "")\"): "
            s += "that is your name from now on. Reply as yourself: one short line about the name, then three bullets with the most useful things you can do "
            s += "for them right now on this phone (choose from: running commands in your Linux sandbox, browsing websites and filling forms, "
            s += "reading and organising files and photos they share, setting reminders and scheduled tasks, searching the web), one concrete line each, no emoji; "
            s += "end by asking what they want to try first. Then end the reply with exactly this fenced block:\n"
            s += fence + "\n{\"agent_name\": \"<the name>\"}\n```\n"
            s += "The app saves the name to SOUL.md from the block; do not call minis-config for it.\n"
            s += "(b) If the message is about something else, help with it first, in full, and end with one light sentence bringing the naming back; "
            s += "no block, the chooser stays.\n"
            s += "Reply in the user's language." + addressLine
            return s
        case .named:
            let name = SoulStore.cachedMetadata.name
            return "First conversation. The user just named you \"\(name)\"; the app already saved it to SOUL.md, so it is your name now; do not call minis-config for it. "
                + "Reply in the user's language: one short line about the name, then three bullets with the most useful things you can do for them right now on this phone "
                + "(choose from: running commands in your Linux sandbox, browsing websites and filling forms, reading and organising files and photos they share, "
                + "setting reminders and scheduled tasks, searching the web). One concrete line each, no emoji. End by asking what they want to try first." + addressLine
        case .none, .done:
            return nil
        }
    }

    private func saveAddress(_ address: String) {
        UserDefaults.standard.set(address, forKey: Keys.address)
        let file = NanoMuseDirs.memory.appendingPathComponent("GLOBAL.md")
        let current = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
        let updated = Self.withAddress(address, in: current)
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? updated.data(using: .utf8)?.write(to: file, options: .atomic)
    }

    /// "- Call them: X" under "## About the user" in GLOBAL.md; an existing line is replaced.
    nonisolated static func withAddress(_ address: String, in current: String) -> String {
        let line = "- Call them: \(address)"
        let lines = current.components(separatedBy: "\n")
        if lines.contains(where: { $0.trimmingCharacters(in: .whitespaces).hasPrefix("- Call them:") }) {
            return lines.map { $0.trimmingCharacters(in: .whitespaces).hasPrefix("- Call them:") ? line : $0 }.joined(separator: "\n")
        }
        if current.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "## About the user\n\(line)\n"
        }
        var trimmed = current
        while trimmed.hasSuffix("\n") || trimmed.hasSuffix(" ") { trimmed.removeLast() }
        return trimmed + "\n\n## About the user\n\(line)\n"
    }

    /// The model's suggestions when it gave some; otherwise two from the bundled pool, in the app's language.
    private func currentSuggestions() -> [String] {
        if let saved = UserDefaults.standard.string(forKey: Keys.suggestions) {
            let names = saved.components(separatedBy: "\n").filter { !$0.isEmpty }
            if !names.isEmpty { return names }
        }
        return Self.poolPick(seed: sessionKey ?? "", chinese: NanoMuseLocale.isChinese)
    }

    /// Two names from the pool, stable for a given seed.
    nonisolated static func poolPick(seed: String, chinese: Bool) -> [String] {
        let pool = chinese ? namePoolZH : namePoolEN
        var h: UInt64 = 1469598103934665603
        for b in seed.utf8 { h = (h ^ UInt64(b)) &* 1099511628211 }
        let first = Int(h % UInt64(pool.count))
        var second = Int((h >> 17) % UInt64(pool.count))
        if second == first { second = (second + 1) % pool.count }
        return [pool[first], pool[second]]
    }

    /// The last `nanomuse-naming` block in `text`, or nil when there is none or it is not JSON.
    nonisolated static func parseBlock(_ text: String?) -> NanoMuseNamingBlock? {
        guard let text, let o = NanoMuseFences.lastObject(block, in: text) else { return nil }
        let suggestions = ((o["suggest"] as? [Any]) ?? []).compactMap { cleanName($0 as? String) }
        var seen: [String] = []
        for s in suggestions where !seen.contains(s) { seen.append(s) }
        let addressGiven = o.keys.contains("user_address")
        let address = o["user_address"] is NSNull ? nil : cleanName(o["user_address"] as? String)
        let agent = o["agent_name"] is NSNull ? nil : cleanName(o["agent_name"] as? String)
        return NanoMuseNamingBlock(addressGiven: addressGiven, userAddress: address, suggestions: Array(seen.prefix(3)), agentName: agent)
    }

    /// A usable name: one line, quotes and trailing punctuation gone, not absurdly long.
    nonisolated static func cleanName(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let ns = raw as NSString
        let t = nmNameQuoteEdges.stringByReplacingMatches(in: raw, range: NSRange(location: 0, length: ns.length), withTemplate: "").trimmingCharacters(in: .whitespaces)
        if t.isEmpty || t.contains("\n") || t.count > maxName { return nil }
        return t
    }
}

/// Quotes and trailing punctuation around a name.
private let nmNameQuoteEdges = try! NSRegularExpression(pattern: "^[\\s\"'“”‘’「」『』]+|[\\s\"'“”‘’「」『』。，、！!？?.]+$")

// MARK: - The name chooser card

/// Under the model's "what would you like to call me?": two names and "Something else…".
struct NanoMuseNamingCardView: View {
    @ObservedObject var vm: AIChatViewModel
    @ObservedObject private var flow = NanoMuseFirstConversation.shared
    @State private var custom = ""
    @State private var writing = false
    @FocusState private var focused: Bool

    var body: some View {
        if let card = flow.card {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    NanoMuseFaceView(mood: .happy, size: 28, showsRing: false)
                    Text(AppLocalized("Give me a name"))
                        .font(.subheadline.weight(.semibold))
                }
                if let chosen = card.chosen {
                    Label(chosen, systemImage: "checkmark.circle.fill")
                        .font(.body.weight(.medium))
                        .foregroundStyle(NanoMuseTones.action)
                } else {
                    NanoMuseFlowLayout(spacing: 8) {
                        ForEach(card.suggestions, id: \.self) { name in
                            Button {
                                choose(name)
                            } label: {
                                Text(name)
                                    .font(.subheadline.weight(.medium))
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 8)
                                    .background(NanoMuseTones.fill, in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                        Button {
                            writing = true
                            focused = true
                        } label: {
                            Text(AppLocalized("Something else…"))
                                .font(.subheadline.weight(.medium))
                                .padding(.horizontal, 14)
                                .padding(.vertical, 8)
                                .overlay(Capsule().stroke(NanoMuseTones.hairline))
                        }
                        .buttonStyle(.plain)
                    }
                    if writing {
                        HStack(spacing: 8) {
                            TextField(AppLocalized("Write a name here"), text: $custom)
                                .textFieldStyle(.roundedBorder)
                                .focused($focused)
                                .submitLabel(.done)
                                .onSubmit { submitCustom() }
                            Button(AppLocalized("Done")) { submitCustom() }
                                .disabled(NanoMuseFirstConversation.cleanName(custom) == nil)
                        }
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(NanoMuseTones.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(NanoMuseTones.hairline))
        }
    }

    private func submitCustom() {
        guard let name = NanoMuseFirstConversation.cleanName(custom) else { return }
        choose(name)
    }

    private func choose(_ name: String) {
        flow.pick(name: name)
        vm.nmSendNow(name)
    }
}
