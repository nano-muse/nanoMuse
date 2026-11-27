//
//  NanoMuseHeader.swift
//  nanoMuse
//
//  The Muse header in the chat's navigation bar: the agent's face, its
//  name and one status line that says what it is doing right now. The
//  Android twin is ui/header/NanoMuseHeader.kt + ui/home/MuseHeader.kt.
//

import SwiftUI
import Combine

/// Posted by "Avatar studio…" on the agent page (and the face's menu); the
/// shell (or the root in the OpenMinis layout) presents the avatar studio.
extension Notification.Name {
    static let nanoMuseOpenAvatarStudio = Notification.Name("nanoMuse.openAvatarStudio")
}

// MARK: - Status line

enum NanoMuseStatus {
    /// What the header says, in order of importance (Android §2.2):
    /// a risky step needs approval > waiting for the person > the avatar
    /// studio's own line > the running step's own title > writing the
    /// reply > "On it: <request>" > "On it" > the avatar's motion clips
    /// being made > nothing (idle, the model line may show).
    static func line(
        waiting: Bool,
        needsApproval: Bool = false,
        processing: Bool,
        toolName: String,
        toolTitle: String,
        request: String?,
        studio: String?,
        motion: String? = nil
    ) -> String? {
        if needsApproval { return AppLocalized("Needs approval") }
        if waiting { return AppLocalized("Waiting for you") }
        if let studio, !studio.isEmpty { return studio }
        if processing {
            if toolName == "text" { return AppLocalized("Writing the reply") }
            if !toolName.isEmpty, !toolTitle.isEmpty { return toolTitle }
            if let brief = requestBrief(request) { return String(format: AppLocalized("On it: %@"), brief) }
            return AppLocalized("On it")
        }
        if let motion, !motion.isEmpty { return motion }
        return nil
    }

    /// The first ~36 characters of the request, cut at a word boundary
    /// when one is found past 18.
    static func requestBrief(_ request: String?) -> String? {
        guard let raw = request?.replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        if raw.count <= 36 { return raw }
        let head = String(raw.prefix(36))
        if let space = head.lastIndex(of: " "), head.distance(from: head.startIndex, to: space) >= 18 {
            return String(head[..<space]) + "…"
        }
        return head + "…"
    }
}

// MARK: - Mood

/// Derives the face's mood from what the chat is doing. Happy and error
/// linger a few seconds after a turn ends, as on Android.
@MainActor
final class NanoMuseMoodModel: ObservableObject {
    @Published private(set) var afterglow: NanoMuseMood?
    private var afterglowTask: Task<Void, Never>?

    func turnEnded(withError: Bool) {
        afterglowTask?.cancel()
        afterglow = withError ? .error : .happy
        let seconds: Double = withError ? 4 : 3
        afterglowTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            self?.afterglow = nil
        }
    }

    func mood(waiting: Bool, working: Bool) -> NanoMuseMood {
        if waiting { return .waiting }
        if working { return .working }
        if let afterglow { return afterglow }
        return .idle
    }
}

// MARK: - Header scrim

/// What stands behind the Muse header over the main chat. Not a bar: a scrim, as Android's
/// header wrapper since #331. A gradient of the canvas colour from 80 percent at the top edge
/// through 35 percent a little past the middle to clear at the bottom, so the conversation
/// scrolls under the header and dissolves into the canvas instead of stopping at a line; and,
/// while the list is scrolled away from the latest message, a second fade in the full canvas
/// colour from the top edge (Android's `nmTopFade`), so the older messages melt away under the
/// face rather than show through it. The scrim takes the taps the material took before it, so
/// a tap on the header never reaches a message under it.
struct NanoMuseHeaderScrim: View {
    /// The list is scrolled up, away from the latest message.
    var scrolledUp: Bool

    var body: some View {
        ZStack {
            LinearGradient(
                stops: [
                    .init(color: ChatColors.background.opacity(0.8), location: 0),
                    .init(color: ChatColors.background.opacity(0.35), location: 0.55),
                    .init(color: ChatColors.background.opacity(0), location: 1),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            LinearGradient(
                colors: [ChatColors.background, ChatColors.background.opacity(0)],
                startPoint: .top,
                endPoint: .bottom
            )
            .opacity(scrolledUp ? 1 : 0)
            .animation(.easeInOut(duration: 0.25), value: scrolledUp)
        }
        .contentShape(Rectangle())
        // A tap on the bare scrim ends here: the rows the list has under the header (nmTopOverlay)
        // are not to be tapped through it. The header's own discs and pills lie over the scrim and
        // take their taps first.
        .onTapGesture {}
    }
}

/// Finds a conversation's view model in the cache. AIChatView puts it there as it appears, so
/// the header and the scrim look a few times, then give up quietly.
enum NanoMuseChatLookup {
    @MainActor
    static func viewModel(for liveId: String?) async -> AIChatViewModel? {
        guard let liveId else { return nil }
        for _ in 0..<20 {
            if let found = ViewModelCache.shared.get(for: liveId) { return found }
            try? await Task.sleep(for: .milliseconds(150))
            if Task.isCancelled { return nil }
        }
        return nil
    }
}

/// The scrim bound to the main chat's view model once it is in the cache (the same wait as
/// `NanoMuseChatHeaderHost`): the second fade follows the list's `isNearBottom`. Until the
/// model exists there is nothing to scroll, so the scrim stands still.
struct NanoMuseChatScrimHost: View {
    /// The id the view model is cached under (nil for an unsent draft).
    var liveId: String?

    @State private var vm: AIChatViewModel?

    var body: some View {
        Group {
            if let vm {
                NanoMuseLiveScrim(vm: vm)
            } else {
                NanoMuseHeaderScrim(scrolledUp: false)
            }
        }
        .task(id: liveId) {
            vm = nil
            vm = await NanoMuseChatLookup.viewModel(for: liveId)
        }
    }
}

/// The scrim watching one conversation's list position.
struct NanoMuseLiveScrim: View {
    @ObservedObject var vm: AIChatViewModel

    var body: some View {
        NanoMuseHeaderScrim(scrolledUp: !vm.messages.isEmpty && !vm.isNearBottom)
    }
}

// MARK: - Header title (navigation bar principal item)

/// Face · name · status line, sized for the 44 pt navigation band. Observes
/// the activity tracker and the gates itself so the chat's equatable
/// toolbar host does not have to rebuild for every tick.
struct NanoMuseHeaderTitle: View {
    @ObservedObject var vm: AIChatViewModel
    var soulName: String
    var modelName: String
    var isReadOnly = false
    var onTapText: () -> Void

    @ObservedObject private var tracker = SessionActivityTracker.shared
    @ObservedObject private var permissions = OffloadPermissionManager.shared
    @ObservedObject private var gate = ConfigConfirmationGate.shared
    @ObservedObject private var studio = NanoMuseAvatarStudioModel.shared
    @ObservedObject private var avatarFlow = NanoMuseAvatarFlow.shared
    @ObservedObject private var motion = NanoMuseAvatarMotion.shared
    @StateObject private var moods = NanoMuseMoodModel()
    // Dynamic Type, capped as in the big-face header (NanoMuseHeaderMetrics)
    @ScaledMetric(relativeTo: .subheadline) private var nameSize: CGFloat = 14
    @ScaledMetric(relativeTo: .caption) private var statusSize: CGFloat = 11

    private var waiting: Bool {
        permissions.pendingRequest != nil || gate.pending != nil
    }

    private var info: SessionActivityTracker.SessionToolInfo? {
        guard let sid = vm.sessionId else { return nil }
        return tracker.sessionToolInfo[sid]
    }

    private var lastRequest: String? {
        vm.messages.last(where: { $0.role == .user })?.content
    }

    private var statusLine: String? {
        NanoMuseStatus.line(
            waiting: gate.pending != nil,
            needsApproval: permissions.pendingRequest != nil,
            processing: vm.isProcessing,
            toolName: info?.toolName ?? "",
            toolTitle: info?.toolStatus ?? "",
            request: lastRequest,
            studio: avatarFlow.statusLine ?? studio.headerStatus,
            motion: motion.statusLine
        )
    }

    private var mood: NanoMuseMood {
        moods.mood(waiting: waiting, working: vm.isProcessing || studio.isBusy)
    }

    var body: some View {
        HStack(spacing: 8) {
            // The face opens the agent's page (Android: AgentProfileScreen); the studio is one of its doors.
            Button {
                NotificationCenter.default.post(name: .nanoMuseOpenAgentPage, object: vm.nmSessionKey)
            } label: {
                NanoMuseFaceView(mood: mood, size: 32)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(AppLocalized("About the agent")))

            Button(action: onTapText) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(soulName)
                        .font(.system(size: NanoMuseHeaderMetrics.capped(nameSize, base: 14), weight: .semibold))
                        .foregroundStyle(ChatColors.primaryText)
                        .lineLimit(1)
                    Text(statusLine ?? modelName)
                        .font(.system(size: NanoMuseHeaderMetrics.capped(statusSize, base: 11)))
                        .foregroundStyle(statusLine == nil ? ChatColors.tertiaryText : NanoMuseTones.action)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .animation(.easeInOut(duration: 0.2), value: statusLine)
                }
                .fixedSize(horizontal: false, vertical: true)
            }
            .buttonStyle(.plain)

            if !isReadOnly {
                NanoMuseThinkingButton(vm: vm)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nmOnChange(of: vm.isProcessing) { processing in
            guard !processing else { return }
            let failed = vm.errorMessage != nil || vm.messages.last?.error != nil
            moods.turnEnded(withError: failed)
        }
    }
}
