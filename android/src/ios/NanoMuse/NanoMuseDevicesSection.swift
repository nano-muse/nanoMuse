// nanoMuse: the account's devices on the hub, shown under the nanoMuse Cloud account —
// this iPhone's two switches (reachable · operable), its name, the other devices with an
// online dot (tap an offline one to forget it), and the web console's address.

import SwiftUI
import UIKit

struct NanoMuseDevicesSection: View {
    var onDeviceChat: ((HubDevice) -> Void)?
    @ObservedObject private var hub = NanoMuseHub.shared
    @State private var enabled = NanoMuseHub.shared.enabled
    @State private var remote = NanoMuseHub.shared.remoteControl
    @State private var name = NanoMuseHub.shared.name
    @State private var editingName = false
    @State private var forgetting: HubDevice?

    var body: some View {
        Section {
            Toggle(isOn: $enabled) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(AppLocalized("Reachable from your devices"))
                    Text(status).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .nmOnChange(of: enabled) { on in hub.enabled = on }
            Toggle(AppLocalized("Let other devices operate this iPhone"), isOn: $remote)
                .nmOnChange(of: remote) { on in hub.remoteControl = on }
            Button {
                editingName = true
            } label: {
                LabeledContent(AppLocalized("This iPhone's name"), value: name)
            }
            .tint(.primary)
        } header: {
            Text(AppLocalized("Devices"))
        } footer: {
            Text(AppLocalized("Every device signed in to this account is a Muse: this iPhone, your computers running nanoMuse Desktop, the web console. Each can ask the others for things, on any network, through nanoMuse Cloud. On iOS the others can open links here and send notifications; the iPhone's own Muse works on the iPhone."))
        }
        .alert(AppLocalized("This iPhone's name"), isPresented: $editingName) {
            TextField(AppLocalized("Name"), text: $name)
            Button(AppLocalized("OK")) { hub.name = name; name = hub.name }
            Button(AppLocalized("Cancel"), role: .cancel) { name = hub.name }
        }

        Section {
            if hub.others.isEmpty {
                Text(AppLocalized("No other device yet. On your computer, install nanoMuse Desktop and sign in with the same account; it appears here within seconds."))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(hub.others) { d in
                    // Online: "Ask this device" — the main chat with "@<name> " in the composer (C7,
                    // as Android's DevicesSection). Offline: a tap offers to forget it.
                    Button {
                        if d.online {
                            NotificationCenter.default.post(name: .nanoMuseHomeAction, object: "askDevice", userInfo: ["text": "@\(d.name) "])
                        } else {
                            forgetting = d
                        }
                    } label: {
                        HStack {
                            Image(systemName: d.isPhone ? "iphone" : "desktopcomputer").foregroundStyle(.primary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(d.name).foregroundStyle(.primary)
                                Text(Self.subtitle(for: d))
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Circle().fill(d.online ? Color.green : Color.secondary.opacity(0.35)).frame(width: 10, height: 10)
                        }
                    }
                    .accessibilityHint(d.online ? AppLocalized("Ask this device") : AppLocalized("Forget"))
                    if let onDeviceChat {
                        Button { onDeviceChat(d) } label: {
                            Label(String(format: AppLocalized("Start a device chat with %@"), d.name), systemImage: "square.and.pencil")
                        }
                    }
                }
            }
        } footer: {
            if hub.others.contains(where: { $0.online }) {
                Text(AppLocalized("Tap a device that is online to write to it from the chat: the message starts with @ and its name, and that device does the work."))
            } else {
                Text(AppLocalized("In a chat on your computer, just ask: “send my iPhone a notification”, “open this page on my iPhone”."))
            }
        }
        .confirmationDialog(forgetting?.name ?? "", isPresented: Binding(get: { forgetting != nil }, set: { if !$0 { forgetting = nil } }), titleVisibility: .visible) {
            Button(AppLocalized("Forget"), role: .destructive) {
                if let d = forgetting { hub.forget(d.id) }
                forgetting = nil
            }
        } message: {
            Text(AppLocalized("Take this device off the list. It comes back the next time it signs in with this account."))
        }

        Section {
            Button {
                UIPasteboard.general.string = hub.webConsoleURL
            } label: {
                LabeledContent {
                    Text(AppLocalized("Copy link")).foregroundStyle(.tint)
                } label: {
                    Label(AppLocalized("Web console"), systemImage: "globe")
                    Text(hub.webConsoleURL).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .tint(.primary)
        } footer: {
            Text(AppLocalized("Open the link in any browser, sign in with the same account, and drive your devices from there."))
        }
    }

    private var status: String {
        if !enabled { return AppLocalized("Off") }
        switch hub.state {
        case .connected: return AppLocalized("Connected")
        case .idle, .connecting: return AppLocalized("Connecting…")
        case .reconnecting, .replaced: return AppLocalized("Reconnecting…")
        case .paused: return AppLocalized("Paused by the relay")
        case .refused: return AppLocalized("Sign in again")
        case .error(let message): return message.isEmpty ? AppLocalized("Connecting…") : message
        }
    }

    /// "macOS · online", or "macOS · offline · 2 hours ago" (Android: `DateUtils.getRelativeTimeSpanString`).
    static func subtitle(for d: HubDevice) -> String {
        var parts = [d.os, d.online ? AppLocalized("online") : AppLocalized("offline")]
        if !d.online, let seen = d.lastSeen {
            parts.append(RelativeDateTimeFormatter().localizedString(for: seen, relativeTo: Date()))
        }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
