import SwiftUI

struct NanoMuseDeviceChatPicker: View {
    @ObservedObject private var hub = NanoMuseHub.shared
    let onLocal: () -> Void
    let onDevice: (HubDevice) -> Void

    var body: some View {
        List {
            Button(action: onLocal) {
                Label(AppLocalized("This iPhone"), systemImage: "iphone")
            }
            Section(AppLocalized("Devices")) {
                ForEach(hub.others) { device in
                    Button { onDevice(device) } label: {
                        Label {
                            VStack(alignment: .leading) {
                                Text(device.name)
                                Text(NanoMuseDevicesSection.subtitle(for: device))
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                            }
                        } icon: {
                            Image(systemName: device.isPhone ? "iphone" : "desktopcomputer")
                        }
                    }
                }
            }
        }
    }
}

struct NanoMuseDeviceChatView: View {
    @ObservedObject var conversations: NanoMuseDeviceConversations
    @ObservedObject private var hub = NanoMuseHub.shared
    @Environment(\.nmBottomOverlay) private var bottomOverlay
    @State private var error: String?
    let id: String

    private struct Recovery: Equatable {
        let turn: String?
        let connected: Bool
        let sending: Bool
    }

    var body: some View {
        if conversations.available, let chat = conversations.chats.first(where: { $0.id == id }) {
            let name = conversations.device(for: chat.destination)?.name ?? chat.destination.name
            let pending = chat.pending
            let target = pending?.alternate ?? chat.destination
            let canRecover = conversations.canSend(to: target)
            let sending = conversations.sending.contains(id)
            let recovery = Recovery(turn: pending?.id, connected: canRecover, sending: sending)
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    Label(name, systemImage: chat.destination.symbol)
                        .font(.headline)
                    if let status = availability(for: chat.destination) {
                        Text(status).font(.footnote).foregroundStyle(.secondary)
                    }
                    if chat.contextLost {
                        Text(AppLocalized("Start a new conversation on this device."))
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal)
                .padding(.vertical, 8)
                Divider()
                transcript(chat, sending: sending)
                Divider()
                if let pending {
                    HStack {
                        Button(AppLocalized("Refresh")) {
                            run { try await conversations.refresh(chat, turn: pending) }
                        }
                        .disabled(sending)
                        Spacer()
                        Button(AppLocalized("Stop"), role: .destructive) {
                            run { try await conversations.stop(chat, turn: pending) }
                        }
                    }
                    .disabled(!canRecover)
                    .padding(.horizontal)
                    .padding(.top, 8)
                }
                composer(chat)
            }
            .padding(.bottom, bottomOverlay)
            .background(ChatColors.background)
            .navigationTitle(AppLocalized("Device chat"))
            .navigationBarTitleDisplayMode(.inline)
            .task(id: recovery) {
                guard let pending, canRecover, !sending else { return }
                do {
                    try await conversations.refresh(chat, turn: pending)
                    while conversations.chats.first(where: { $0.id == id })?.pending?.state == .accepted {
                        try await Task.sleep(nanoseconds: 3_000_000_000)
                        try await conversations.refresh(chat, turn: pending)
                    }
                } catch {
                    if !Task.isCancelled { self.error = NanoMuseHubErrors.describe(error) }
                }
            }
            .alert(AppLocalized("Device chat"), isPresented: Binding(
                get: { error != nil }, set: { if !$0 { error = nil } }
            )) {
                Button(AppLocalized("OK"), role: .cancel) {}
            } message: {
                Text(error ?? "")
            }
        }
    }

    private func availability(for destination: NanoMuseDeviceConversations.Destination) -> String? {
        guard hub.connected else { return AppLocalized("Not connected to the hub right now.") }
        guard let device = conversations.device(for: destination), device.online else {
            return AppLocalized("offline")
        }
        return device.actions.contains("task.status") ? nil : AppLocalized("This device needs a nanoMuse update for device chats.")
    }

    private func transcript(_ chat: NanoMuseDeviceConversations.Chat, sending: Bool) -> some View {
        ScrollViewReader { scroll in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(chat.turns) { turn in
                        VStack(alignment: .trailing, spacing: 4) {
                            if let destination = turn.alternate {
                                Label(destination.name, systemImage: destination.symbol)
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Text(turn.prompt)
                                .textSelection(.enabled)
                                .padding(10)
                                .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 14))
                        }
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        if turn.state.pending {
                            pendingReply(chat, turn: turn, sending: sending)
                        } else if turn.state == .completed, let answer = turn.answer, !answer.isEmpty {
                            Text(answer).textSelection(.enabled)
                        } else {
                            Text(result(for: turn)).foregroundStyle(.secondary)
                        }
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
            .scrollDismissesKeyboard(.interactively)
            .onAppear { scroll.scrollTo("end", anchor: .bottom) }
            .nmOnChange(of: chat.turns.last?.id) { _ in scroll.scrollTo("end", anchor: .bottom) }
        }
    }

    private func result(for turn: NanoMuseDeviceConversations.Turn) -> String {
        switch turn.state {
        case .cancelled: return AppLocalized("Stopped.")
        case .interrupted: return AppLocalized("The device was interrupted. Some steps may have run.")
        case .completed: return AppLocalized("The device finished without an answer.")
        default:
            if turn.error == "context_lost" { return AppLocalized("Start a new conversation on this device.") }
            return NanoMuseHubErrors.describe(code: turn.error ?? "")
        }
    }

    private func pendingReply(_ chat: NanoMuseDeviceConversations.Chat, turn: NanoMuseDeviceConversations.Turn, sending: Bool) -> some View {
        let live = conversations.live[id]
        return VStack(alignment: .leading, spacing: 8) {
            if let status = availability(for: turn.alternate ?? chat.destination) {
                Text(status).foregroundStyle(.secondary)
            } else if sending || turn.state == .accepted {
                Text(AppLocalized("Working…")).foregroundStyle(.secondary)
            } else {
                Text(AppLocalized("Delivery is uncertain. Refresh to check the device."))
                    .foregroundStyle(.secondary)
            }
            if let step = live?.step, !step.isEmpty { Text(step).font(.footnote) }
            if let text = live?.text, !text.isEmpty { Text(text).textSelection(.enabled) }
            ForEach(live?.approvals ?? []) { approval in
                VStack(alignment: .leading, spacing: 8) {
                    Text(approval.preview)
                    if !approval.reason.isEmpty { Text(approval.reason).font(.footnote) }
                    HStack {
                        Button(AppLocalized("Deny")) {
                            run { try await conversations.approve(approval, allow: false, chat: chat, turn: turn) }
                        }
                        Button(AppLocalized("Allow once")) {
                            run { try await conversations.approve(approval, allow: true, chat: chat, turn: turn) }
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(!conversations.canSend(to: turn.alternate ?? chat.destination))
                }
                .padding(10)
                .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    private func composer(_ chat: NanoMuseDeviceConversations.Chat) -> some View {
        let text = chat.draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let route = NanoMuseDeviceConversations.route(text, devices: hub.others)
        let hit: NanoMuseDeviceMention.Hit?
        let ambiguous: Bool
        switch route {
        case .alternate(let alternate): hit = alternate; ambiguous = false
        case .bound: hit = nil; ambiguous = false
        case .ambiguous: hit = nil; ambiguous = true
        }
        let destination = hit.map { NanoMuseDeviceConversations.Destination($0.device) } ?? chat.destination
        let prompt = hit?.task ?? text
        return VStack(alignment: .leading, spacing: 6) {
            if ambiguous {
                Text(AppLocalized("Check the device name and ID. Use @Device Name [device-id]."))
                    .font(.footnote).foregroundStyle(.secondary)
            } else if hit != nil, let status = availability(for: destination) {
                Text(status).font(.footnote).foregroundStyle(.secondary)
            }
            composerField(chat, destination: destination, prompt: prompt, alternate: hit?.device, ambiguous: ambiguous)
        }
        .padding()
    }

    private func composerField(_ chat: NanoMuseDeviceConversations.Chat, destination: NanoMuseDeviceConversations.Destination,
                               prompt: String, alternate: HubDevice?, ambiguous: Bool) -> some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(AppLocalized("Message"), text: Binding(
                get: { conversations.chats.first(where: { $0.id == id })?.draft ?? "" },
                set: {
                    do { try conversations.draft($0, in: id) }
                    catch { self.error = AppLocalized("Could not save the device chat.") }
                }
            ), axis: .vertical)
            .lineLimit(1...5)
            .textFieldStyle(.roundedBorder)
            Button {
                run { try await conversations.send(chat, prompt: prompt, to: alternate) }
            } label: {
                Image(systemName: "arrow.up.circle.fill").font(.title2)
            }
            .accessibilityLabel(Text(AppLocalized("Send")))
            .disabled(ambiguous || prompt.isEmpty || chat.pending != nil || (alternate == nil && chat.contextLost) || !conversations.canSend(to: destination))
        }
    }

    private func run(_ operation: @escaping () async throws -> Void) {
        error = nil
        Task { @MainActor in
            do { try await operation() }
            catch let failure as HubError { error = NanoMuseHubErrors.describe(failure) }
            catch { self.error = AppLocalized("Could not save the device chat.") }
        }
    }
}
