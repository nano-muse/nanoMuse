//
//  NanoMuseSettings.swift
//  nanoMuse
//
//  Settings as Muse cards, in Android's order: the model, the agent, the
//  phone, the app, about. Reached from the drawer, the ••• menus and the
//  agent page; the classic layout's Settings sheet has it as its first row.
//  Also the "All routines" page. Android: ui/settings/SettingsScreen.kt.
//

import SwiftUI
import UIKit

// MARK: - Settings home

struct NanoMuseSettingsHomeView: View {
    /// Open the upstream Settings sheet (every OpenMinis page is there); nil when already inside it.
    var onAllSettings: (() -> Void)? = nil

    @ObservedObject private var store = ProviderConfigStore.shared
    @ObservedObject private var hub = NanoMuseHub.shared
    @ObservedObject private var updates = NanoMuseUpdateCheck.shared // C2: the installed build and the latest release
    @Environment(\.openURL) private var openURL

    var body: some View {
        NanoMusePage(title: AppLocalized("Settings")) {
            modelCard
            agentCard
            phoneCard
            appCard
            aboutCard
            if let onAllSettings {
                NanoMuseCard {
                    NanoMuseActionRow(title: AppLocalized("All settings"), action: onAllSettings)
                }
                NanoMuseCaption(text: AppLocalized("Providers, model groups, skills, appearance and the rest of the OpenMinis settings."))
            }
        }
        .onAppear { updates.checkIfStale() }
    }

    // MARK: Card 1 — the model

    /// The chat slot's line, `<provider> · <model>`, under the card's title.
    private var chatLine: String? {
        _ = store.modelGroups
        _ = store.instances
        return NanoMuseModelSlots.line(.chat)
    }

    private var modelCard: some View {
        NanoMuseCard {
            NavigationLink {
                NanoMuseModelsView()
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(AppLocalized("Models"))
                            .font(.headline)
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                        Text(chatLine ?? AppLocalized("Add a provider and pick its models"))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer(minLength: 8)
                    Text(AppLocalized("Change"))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(NanoMuseTones.action)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: NanoMuseCloud.label, value: cloudLine) { NanoMuseCloudView() }
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: AppLocalized("Manage Providers")) { ProviderInstancesView() }
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: AppLocalized("Image & video models")) { NanoMuseMediaModelsView() }
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: AppLocalized("Token Usage")) { UsageStatsView() }
        }
    }

    /// Android: "Sign in" until signed in; then what is left of the allowance (in yuan on a relay that
    /// prices in money, the account page's headline figure; tokens on an older relay), or who is
    /// signed in when there is no ceiling.
    private var cloudLine: String {
        _ = store.instances
        guard NanoMuseCloud.isSignedIn, let account = NanoMuseCloud.account else { return AppLocalized("Sign in") }
        if account.unlimited { return account.hint }
        if let left = account.poolLeftCny {
            let whole = left.rounded() == left
            return String(format: AppLocalized("%@ left"), "¥" + left.formatted(.number.precision(.fractionLength(whole ? 0 : 2))))
        }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        let left = formatter.string(from: NSNumber(value: account.remaining)) ?? "\(account.remaining)"
        return String(format: AppLocalized("%@ left"), left)
    }

    // MARK: Card 2 — the agent

    private var computers: Int { hub.others.filter(\.isComputer).count }

    private var agentCard: some View {
        NanoMuseCard {
            Group {
                NanoMuseLinkRow(title: AppLocalized("Soul")) { SoulSettingsView() }
                NanoMuseRowDivider()
                NanoMuseActionRow(title: AppLocalized("Avatar")) {
                    NotificationCenter.default.post(name: .nanoMuseOpenAvatarStudio, object: nil)
                }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Memory")) { MemoryManagementView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("System files")) { NanoMuseSystemFilesView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Skills")) { SkillsManagementView() }
                NanoMuseRowDivider()
            }
            Group {
                NanoMuseLinkRow(title: AppLocalized("Connectors")) { NanoMuseConnectorsView() }
                NanoMuseRowDivider()
                // Android's Hands row; on iPhone the page explains why the switch is not here.
                NanoMuseLinkRow(title: AppLocalized("Hands"), value: AppLocalized("Not on iPhone")) { NanoMuseHandsView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Computers"), value: computers == 0 ? AppLocalized("None") : "\(computers)") { NanoMuseComputersView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Coding agents")) { NanoMuseCodingView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Environment Variables")) { EnvironmentVariablesView() }
            }
        }
    }

    // MARK: Card 3 — the phone

    private var phoneCard: some View {
        NanoMuseCard {
            Group {
                NanoMuseLinkRow(title: AppLocalized("Permissions")) { OffloadPermissionSettingsView() }
                NanoMuseRowDivider()
                // Android: "Background & notifications" — what the phone lets the agent do while the app is away.
                NanoMuseLinkRow(title: AppLocalized("Background & notifications")) { NanoMuseBackgroundView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Storage")) { StorageManagementView() }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Shared Folders")) { SharedFoldersSettingsView() }
            }
            Group {
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Mount External Folders")) { MountedFoldersSettingsView() }
                if #available(iOS 17.0, *) {
                    NanoMuseRowDivider()
                    NanoMuseLinkRow(title: AppLocalized("iCloud Sync")) { CloudSyncSettingsV2View() }
                }
                NanoMuseRowDivider()
                NanoMuseLinkRow(title: AppLocalized("Backup & Restore")) { BackupAndRestoreView() }
            }
        }
    }

    // MARK: Card 4 — the app

    private var appCard: some View {
        NanoMuseCard {
            NanoMuseLinkRow(title: AppLocalized("Appearance")) { NanoMuseAppearanceView() }
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: AppLocalized("Data controls")) { NanoMuseDataControlsView() }
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: AppLocalized("Network")) { NanoMuseNetworkView() }
            NanoMuseRowDivider()
            NanoMuseLinkRow(title: AppLocalized("Logs")) { LogManagementView() }
        }
    }

    // MARK: Card 5 — about

    private var aboutCard: some View {
        NanoMuseCard {
            NanoMuseLinkRow(title: AppLocalized("About nanoMuse")) { AboutView() }
            NanoMuseRowDivider()
            NanoMuseActionRow(title: AppLocalized("Privacy Policy")) {
                openURL(NanoMuseLinks.privacy)
            }
            NanoMuseRowDivider()
            NanoMuseActionRow(title: AppLocalized("Feedback")) {
                openURL(NanoMuseLinks.newIssue())
            }
            NanoMuseRowDivider()
            // C2: the installed build and the latest release (NanoMuseUpdateCheck); "Update" when a newer one is out.
            NanoMuseActionRow(
                title: AppLocalized("Version"),
                value: updates.installedLine,
                titleColor: .primary,
                chevron: false
            ) {
                if updates.latestIsNewer { openURL(updates.releasePage) } else { Task { @MainActor in await updates.checkNow() } }
            }
            HStack(spacing: 8) {
                Text(updates.latestLine)
                    .font(.footnote)
                    .foregroundStyle(updates.latestIsNewer ? NanoMuseTones.action : Color.secondary)
                    .lineLimit(2)
                Spacer(minLength: 8)
                if updates.latestIsNewer {
                    Button(AppLocalized("Update")) { openURL(updates.releasePage) }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(NanoMuseTones.action)
                        .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
        }
    }
}

// MARK: - Links

/// The project's public pages.
enum NanoMuseLinks {
    /// The policy on the site (docs/privacy.md is its source), as Android's PRIVACY_URL.
    static let privacy = URL(string: "https://nanomuse.cn/privacy/")!
    /// The own-key guide on the site (docs/own-key.md), when the relay sent no address of its own (Android's OWN_KEY_DOCS).
    static let ownKeyDocs = "https://nanomuse.cn/own-key"

    /// A new GitHub issue with the build and the device filled in (no personal data): the
    /// issue form's fields by id (.github/ISSUE_TEMPLATE/bug_report.yml); a bare `body`
    /// would be dropped on the way to the form.
    static func newIssue() -> URL {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        var components = URLComponents(string: "https://github.com/nano-muse/nanoMuse/issues/new")!
        components.queryItems = [
            URLQueryItem(name: "template", value: "bug_report.yml"),
            URLQueryItem(name: "labels", value: "bug,ios"),
            URLQueryItem(name: "surface", value: "iPhone app"),
            URLQueryItem(name: "version", value: "\(version) (\(build))"),
            URLQueryItem(name: "os", value: "iOS \(UIDevice.current.systemVersion), \(UIDevice.current.model)"),
        ]
        return components.url ?? URL(string: "https://github.com/nano-muse/nanoMuse/issues")!
    }
}

// MARK: - Computers

/// Settings → Computers: this phone on the hub, the other devices, and what can be asked of them.
struct NanoMuseComputersView: View {
    var body: some View {
        List {
            NanoMuseDevicesSection()
            NanoMuseReachSection()
        }
        .navigationTitle(AppLocalized("Computers"))
        .navigationBarTitleDisplayMode(.inline)
    }
}

extension NanoMuseFirstRun {
    /// Forget the setup's state so it shows again (the Cloud sign-in and the providers stay).
    static func reset() {
        for key in ["nanomuse.setup.done", "nanomuse.setup.source_chosen", NanoMuseFirstRun.notificationsKey] { UserDefaults.standard.removeObject(forKey: key) }
    }
}

// MARK: - All routines

/// Every routine on this phone, the goal check-ins and the feed's included: on/off, edit, run now.
struct NanoMuseRoutinesView: View {
    @ObservedObject private var scheduler = NanoMuseScheduler.shared
    @ObservedObject private var goals = NanoMuseGoalStore.shared
    @State private var editing: NanoMuseRoutine?
    @Environment(\.openURL) private var openURL

    var body: some View {
        List {
            Section {
                Text(AppLocalized("A routine is a message the agent sends itself at a set time, in its own conversation. On the iPhone it runs when the app is open: when it comes due while the app is asleep, the phone shows a reminder and the run happens as soon as you open it. iOS also wakes the app now and then in the background; when it does, the routine runs there."))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if scheduler.routines.isEmpty {
                Section {
                    Text(AppLocalized("Nothing scheduled yet."))
                        .foregroundStyle(.secondary)
                }
            } else {
                Section(AppLocalized("Routines")) {
                    ForEach(scheduler.routines) { routine in
                        routineRow(routine)
                    }
                }
            }
            Section {
                Button {
                    editing = NanoMuseRoutine(label: "", prompt: "", hour: 9, minute: 0)
                } label: {
                    Label(AppLocalized("New routine"), systemImage: "plus")
                }
                Button {
                    scheduler.requestNotificationPermission()
                } label: {
                    Label(AppLocalized("Allow reminders"), systemImage: "bell")
                }
                Button {
                    if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                } label: {
                    Label(AppLocalized("Background App Refresh in iOS Settings"), systemImage: "arrow.clockwise")
                }
            } footer: {
                Text(AppLocalized("Reminders need notification permission; background runs need Background App Refresh for nanoMuse."))
            }
        }
        .navigationTitle(AppLocalized("Scheduled tasks"))
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $editing) { routine in
            NanoMuseRoutineEditor(routine: routine)
        }
    }

    private func label(for routine: NanoMuseRoutine) -> String {
        if let goalId = routine.goalId, let goal = goals.goal(id: goalId) {
            return String(format: AppLocalized("Check-in: %@"), goal.title)
        }
        return routine.label.isEmpty ? AppLocalized("Routine") : routine.label
    }

    private func routineRow(_ routine: NanoMuseRoutine) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(label(for: routine)).font(.body.weight(.medium))
                Text(routine.enabled ? routine.cadence : AppLocalized("Off")).font(.caption).foregroundStyle(.secondary)
                if let next = routine.nextDue(after: Date()), routine.enabled {
                    Text(String(format: AppLocalized("next %@"), NanoMuseDay.relative(next))).font(.caption2).foregroundStyle(.tertiary)
                }
                if let last = routine.runs.first {
                    Text(String(format: last.ok ? AppLocalized("last run %@") : AppLocalized("last run %@, failed"), NanoMuseDay.relative(last.at)))
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            Spacer()
            if scheduler.running.contains(routine.id) {
                ProgressView()
            } else {
                Toggle("", isOn: Binding(get: { routine.enabled }, set: { scheduler.setEnabled(routine.id, $0) }))
                    .labelsHidden()
                    .tint(NanoMuseTones.action)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { editing = routine }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) { scheduler.delete(routine.id) } label: { Label(AppLocalized("Delete"), systemImage: "trash") }
            Button { Task { @MainActor in await scheduler.run(routine.id) } } label: { Label(AppLocalized("Run now"), systemImage: "play") }
                .tint(NanoMuseTones.action)
        }
    }
}
