import SwiftUI

/// The sections of the account page under the identity line, in the order of the Android
/// account screen: the password, the devices holding a key, a star row (once, as the policy
/// says), the pool in yuan with the ways on when it runs low (your own key, an invitation — and
/// a star, once), the invite code, what was used by kind and by model, the account's timeline.
/// Lives inside `NanoMuseCloudView`'s `Form`, which adds the links and the ways out below.
/// Everything comes from the relay each time the page opens; nothing of it is kept on the phone.
struct NanoMuseAccountSections: View {
    /// The parent's view of the balance, refreshed together with the sheet.
    @Binding var account: NanoMuseCloudAccount?

    @State private var sheet: NanoMuseSheet?
    @State private var sessions: [NanoMuseSession] = []
    @State private var events: [NanoMuseEvent] = []
    @State private var error: String?
    @State private var usageScope = 0
    @State private var starAsk = false
    /// The allowance is used up and the policy says this is a moment to ask: the star row under the ways on.
    @State private var exhaustedAsk = false
    /// The vendor (or plan) whose sheet is open, from the ways on.
    @State private var pick: NanoMuseVendorPick?

    var body: some View {
        Group {
            passwordSection
            sessionsSection
            if starAsk {
                Section {
                    NanoMuseStarCard(text: NanoMuseStar.words(for: .signedIn)) {
                        starAsk = false
                    }
                }
            }
            allowanceSection
            if let invite = sheet?.invite { inviteSection(invite) }
            usageSection
            if !events.isEmpty { timelineSection }
        }
        .task { await load() }
        .sheet(item: $pick) { p in NanoMuseVendorSheet(vendor: p.vendor, signIn: p.auth) }
    }

    // MARK: - Allowance

    @ViewBuilder
    private var allowanceSection: some View {
        Section {
            if let sheet {
                if sheet.member || sheet.spend?.unlimited == true {
                    Text(AppLocalized("Member: no cap on this account."))
                        .font(.subheadline)
                } else if let spend = sheet.spend, let grant = spend.grant, grant > 0 {
                    let left = spend.remaining ?? 0
                    VStack(alignment: .leading, spacing: 6) {
                        ProgressView(value: min(spend.total / grant, 1))
                        Text(String(format: AppLocalized("%@ of %@ left"), yuan(left), yuan(grant)))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        if let usd = spend.usdCny, usd > 0 {
                            let spent = yuan(spend.total)
                            let dollars = (spend.total / usd).formatted(.number.precision(.fractionLength(2)))
                            Text(String(format: AppLocalized("%@ spent (about $%@)"), spent, dollars))
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                        }
                    }
                    .padding(.vertical, 4)
                    if spend.low { waysOn(spend) }
                } else if let spend = sheet.spend {
                    Text(String(format: AppLocalized("Spent so far: %@. No allowance figure from this relay."), yuan(spend.total)))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else if let account {
                    // an older relay: tokens, as before
                    let remaining = account.remaining.formatted()
                    let granted = account.granted.formatted()
                    Text(account.unlimited ? AppLocalized("No limit on this account") : String(format: AppLocalized("%@ of %@ tokens left"), remaining, granted))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            } else if let error {
                Text(error).foregroundStyle(.red).font(.subheadline)
            } else {
                HStack { ProgressView(); Text(AppLocalized("Loading…")).foregroundStyle(.secondary) }
            }
        } header: {
            Text(AppLocalized("Allowance"))
        }
    }

    /// When the pool is low or spent: the ways on as the relay lists them for the region
    /// (`spend.guidance`, contract C11; the bundled catalogue when it sent none) — your own
    /// key, a plan you already pay for, an invitation — and, once, a star.
    @ViewBuilder
    private func waysOn(_ spend: NanoMuseSheet.Spend) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(spend.exhausted
                ? AppLocalized("The allowance is used up. Two ways to keep going, and a third if you like the project.")
                : AppLocalized("Most of the allowance is spent. Good time to set up a way on."))
                .font(.subheadline)
            // Contract C5: mainland China hears about Alibaba Cloud Bailian first; everyone else about OpenRouter.
            let ways = NanoMuseWays.resolve(guidance: spend.guidance ?? NanoMuseAllowance.storedGuidance(), catalogue: NanoMuseCatalogue.bundled, mainland: NanoMuseRegion.isMainland, chinese: NanoMuseCatalogue.chinese)
            NanoMuseWaysList(
                ways: ways,
                inviteBonusCny: spend.inviteBonusCny ?? sheet?.invite?.bonusCny ?? 5,
                inviteeBonusCny: spend.inviteeBonusCny,
                inviteBelow: sheet?.invite != nil,
                docs: spend.ownKeyDocs ?? (ways.docs.isEmpty ? NanoMuseLinks.ownKeyDocs : ways.docs),
                compact: false
            ) { pick = $0 }
            // nanoMuse: the policy's gate (NanoMuseStar / contract C1), not a bare "starred" check
            if spend.exhausted && exhaustedAsk {
                Label {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(NanoMuseStar.words(for: .exhausted))
                            .font(.caption).foregroundStyle(.secondary)
                        HStack(spacing: 12) {
                            Button(AppLocalized("Star on GitHub")) { NanoMuseStar.open() }
                                .font(.caption.weight(.medium))
                            Button(AppLocalized("I already starred")) { NanoMuseStar.markStarred(); exhaustedAsk = false }
                                .font(.caption.weight(.medium))
                        }
                    }
                } icon: { Image(systemName: "star") }
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Invite

    private func inviteSection(_ invite: NanoMuseSheet.Invite) -> some View {
        Section {
            HStack {
                Text(invite.code).font(.body.monospaced())
                Spacer()
                Button {
                    UIPasteboard.general.string = invite.code
                } label: { Label(AppLocalized("Copy"), systemImage: "doc.on.doc") }
                .labelStyle(.iconOnly)
            }
            if !invite.url.isEmpty {
                ShareLink(item: URL(string: invite.url) ?? NanoMuseStar.repoURL) {
                    Label(AppLocalized("Share the link"), systemImage: "square.and.arrow.up")
                }
            }
        } header: {
            Text(AppLocalized("Invite a friend"))
        } footer: {
            let bonus = yuan(invite.bonusCny)
            let earned = yuan(invite.earnedCny)
            let invited = invite.invites.formatted()
            Text(String(format: AppLocalized("A friend who signs up with your code gets %@ of credit, and so do you. %@ invited · %@ earned."), bonus, invited, earned))
        }
    }

    // MARK: - Usage

    @ViewBuilder
    private var usageSection: some View {
        if let sheet {
            Section {
                Picker("", selection: $usageScope) {
                    Text(AppLocalized("Today")).tag(0)
                    Text(AppLocalized("All time")).tag(1)
                }
                .pickerStyle(.segmented)
                let rows = usageScope == 0 ? sheet.today : sheet.total
                if rows.isEmpty {
                    Text(AppLocalized("Nothing used yet.")).foregroundStyle(.secondary).font(.subheadline)
                } else {
                    ForEach(rows) { row in usageLine(row, label: kindWord(row.kind)) }
                }
                if usageScope == 1 {
                    ForEach(sheet.byModel) { row in usageLine(row, label: row.model ?? row.kind) }
                }
            } header: {
                Text(AppLocalized("Usage"))
            }
        }
    }

    private func usageLine(_ row: NanoMuseSheet.UsageRow, label: String) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                let tokens = (row.promptTokens + row.completionTokens).formatted()
                let requests = row.requests.formatted()
                Text(String(format: AppLocalized("%@ requests · %@ tokens"), requests, tokens))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(yuan(row.costCny)).foregroundStyle(.secondary)
        }
    }

    private func kindWord(_ kind: String) -> String {
        switch kind {
        case "chat": return AppLocalized("Chat")
        case "image": return AppLocalized("Images")
        case "video": return AppLocalized("Video")
        case "realtime": return AppLocalized("Calls")
        default: return kind
        }
    }

    // MARK: - Password

    @State private var passwordOpen = false
    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var passwordBusy = false
    @State private var passwordNote: String?

    private var passwordSection: some View {
        Section {
            if passwordOpen {
                if sheet?.hasPassword == true {
                    SecureField(AppLocalized("Current password"), text: $currentPassword)
                        .textContentType(.password)
                }
                SecureField(sheet?.hasPassword == true ? AppLocalized("New password (8 or more)") : AppLocalized("Password (8 or more)"), text: $newPassword)
                    .textContentType(.newPassword)
                HStack {
                    Button(AppLocalized("Save")) { Task { await savePassword() } }
                        .disabled(passwordBusy || !passwordValid)
                    Spacer()
                    Button(AppLocalized("Cancel"), role: .cancel) { passwordOpen = false; newPassword = ""; currentPassword = "" }
                        .disabled(passwordBusy)
                }
            } else {
                Button {
                    passwordNote = nil
                    passwordOpen = true
                } label: {
                    Label(sheet?.hasPassword == true ? AppLocalized("Change password") : AppLocalized("Add a password"), systemImage: "lock")
                }
            }
        } header: {
            Text(AppLocalized("Password"))
        } footer: {
            if let passwordNote {
                Text(passwordNote)
            } else if passwordOpen && sheet?.hasPassword == true {
                Text(AppLocalized("Leave the new password empty to remove it."))
            } else {
                Text(AppLocalized("With one, you can sign in without waiting for a code. Codes keep working either way."))
            }
        }
    }

    private var passwordValid: Bool {
        let has = sheet?.hasPassword == true
        if has && currentPassword.isEmpty { return false }
        if newPassword.isEmpty { return has } // removal
        return newPassword.count >= 8
    }

    private func savePassword() async {
        passwordBusy = true
        defer { passwordBusy = false }
        do {
            try await NanoMuseCloud.setPassword(newPassword, current: currentPassword.isEmpty ? nil : currentPassword)
            passwordNote = newPassword.isEmpty ? AppLocalized("Password removed.") : AppLocalized("Saved.")
            passwordOpen = false
            newPassword = ""
            currentPassword = ""
            await load()
        } catch {
            passwordNote = NanoMuseCloud.describe(error)
        }
    }

    // MARK: - Sessions

    @State private var sessionBusy: String?

    private var sessionsSection: some View {
        Section {
            if sessions.isEmpty {
                Text(AppLocalized("No device holds a key.")).foregroundStyle(.secondary).font(.subheadline)
            }
            ForEach(sessions) { s in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.device.isEmpty ? AppLocalized("A device") : s.device) + Text(s.current ? " · \(AppLocalized("this phone"))" : "")
                        let via = s.via == "password" ? AppLocalized("a password") : AppLocalized("a code")
                        let when = (s.lastUsedAt ?? s.createdAt).formatted(.relative(presentation: .named))
                        Text(String(format: AppLocalized("Signed in with %@ · last used %@"), via, when))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if !s.current {
                        Button(AppLocalized("Sign out")) { Task { await revoke(s.prefix) } }
                            .font(.caption)
                            .disabled(sessionBusy != nil)
                    }
                }
            }
        } header: {
            Text(AppLocalized("Signed in on"))
        }
    }

    private func revoke(_ prefix: String) async {
        sessionBusy = prefix
        defer { sessionBusy = nil }
        do {
            try await NanoMuseCloud.revokeSession(prefix: prefix)
            sessions = (try? await NanoMuseCloud.sessions()) ?? sessions.filter { $0.prefix != prefix }
        } catch {
            self.error = NanoMuseCloud.describe(error)
        }
    }

    // MARK: - Timeline

    private var timelineSection: some View {
        Section {
            ForEach(events.prefix(40)) { e in
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(e.kind.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: ".", with: " "))
                        if !e.detail.isEmpty {
                            Text(e.detail).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Text(e.at.formatted(date: .abbreviated, time: .shortened))
                        .font(.caption).foregroundStyle(.tertiary)
                }
            }
        } header: {
            Text(AppLocalized("Account activity"))
        }
    }

    // MARK: - Loading

    private func load() async {
        error = nil
        do {
            let next = try await NanoMuseCloud.sheet()
            sheet = next
            account = NanoMuseCloud.account
            // nanoMuse: contract C1 — the policy's gate decides, once per moment
            if NanoMuseStar.shared.signedIn() { starAsk = true }
            if next.spend?.exhausted == true, NanoMuseStar.shared.due(.exhausted) {
                NanoMuseStar.shared.markShown(.exhausted)
                exhaustedAsk = true
            }
        } catch {
            self.error = NanoMuseCloud.describe(error)
        }
        sessions = (try? await NanoMuseCloud.sessions()) ?? []
        events = (try? await NanoMuseCloud.events()) ?? []
    }

    private func yuan(_ n: Double) -> String {
        let whole = n.rounded() == n
        return "¥" + n.formatted(.number.precision(.fractionLength(whole ? 0 : 2)))
    }
}

/// One card asking for a star: the reason, "Star on GitHub", "Not now", "I already starred".
struct NanoMuseStarCard: View {
    var text: String
    var onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(AppLocalized("A star on GitHub helps")).font(.subheadline.weight(.semibold))
                    Text(text).font(.caption).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "star.fill").foregroundStyle(Color.accentColor)
            }
            HStack {
                Button(AppLocalized("Star on GitHub")) { NanoMuseStar.open(); onDone() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                Button(AppLocalized("Not now")) { onDone() }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                Button(AppLocalized("I already starred")) { NanoMuseStar.markStarred(); onDone() }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
        }
        .padding(.vertical, 4)
    }
}
