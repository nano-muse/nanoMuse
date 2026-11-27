import SwiftUI

struct NanoMusePublicWatchSettings: View {
    @ObservedObject private var watches = NanoMusePublicWatches.shared
    @ObservedObject private var locks = SessionLockStore.shared
    @State private var owner = ""
    @State private var kind = "github_repo"
    @State private var target = ""
    @State private var scholar: NanoMuseWatchRow?
    @State private var scholarRevision = 0
    @State private var failed = false

    private static let kinds = ["github_repo", "github_user", "research_author", "research_work", "research_topic", "feed"]
    private func name(_ kind: String) -> String {
        switch kind {
        case "github_repo": return AppLocalized("GitHub repository")
        case "github_user": return AppLocalized("GitHub account")
        case "research_author": return AppLocalized("Researcher (OpenAlex or ORCID)")
        case "research_work": return AppLocalized("Paper (DOI)")
        case "research_topic": return AppLocalized("Research topic")
        case "scholar_profile": return "Google Scholar"
        default: return "RSS / Atom"
        }
    }
    private func hint(_ kind: String) -> String {
        switch kind {
        case "github_repo": return "owner/repository"
        case "github_user": return "https://github.com/…"
        case "research_author": return "A… / ORCID"
        case "research_work": return "10.…/…"
        case "research_topic": return AppLocalized("Research topic")
        default: return "https://…"
        }
    }
    private func origin(_ row: NanoMuseWatchRow) -> String {
        switch row.origin {
        case "recurring": return AppLocalized("Mentioned more than once")
        case "chat": return AppLocalized("From your chat")
        case "connected": return AppLocalized("From a connected source")
        default: return AppLocalized("Added by you")
        }
    }
    var body: some View {
        let observed = watches.revision
        return Form {
            if watches.available && !locks.appIsLocked {
                Section {
                    Toggle(AppLocalized("Follow public sources"), isOn: Binding(get: { watches.enabled },
                        set: { _ = edit(["enabled": $0], at: observed) })).tint(NanoMuseTones.action)
                } footer: {
                    Text(AppLocalized("This iPhone checks followed sources when iOS gives it time. The first check sets a baseline. Suggestions wait for your confirmation."))
                }
                ForEach(["suggested", "active", "paused"], id: \.self) { status in
                    let items = watches.rows.filter { $0.status == status }
                    if !items.isEmpty {
                        Section {
                            ForEach(items) { row in rowView(row, at: observed) }
                        } header: {
                            Text(status == "suggested" ? AppLocalized("Suggested sources") : status == "active" ? AppLocalized("Following") : AppLocalized("Paused"))
                        }
                    }
                }
                if watches.enabled {
                    Section {
                        Picker(AppLocalized("Source"), selection: $kind) {
                            ForEach(Self.kinds, id: \.self) { k in Text(name(k)).tag(k) }
                        }
                        field(kind, $target)
                        Button(AppLocalized("Add")) {
                            if edit(["kind": kind, "target": target], at: observed) { target = "" }
                        }.disabled(target.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    } header: { Text(AppLocalized("Add a source")) }
                }
            } else { Text(AppLocalized("Sources unavailable.")) }
        }
        .navigationTitle(AppLocalized("Public sources"))
        .onAppear { owner = NanoMuseAccountData.shared.current; watches.reload() }
        .onReceive(locks.$appIsLocked) { _ in Task { watches.reload() } }
        .onReceive(locks.$lockedSessionIds) { _ in Task { watches.reload() } }
        .sheet(item: $scholar) { row in
            NanoMuseScholarBinding { bindingKind, verified in
                let ok = edit(["id": row.id, "action": "confirm", "kind": bindingKind, "target": verified], at: scholarRevision)
                if ok { scholar = nil }
                return ok
            }
        }
        .alert(AppLocalized("Check the source and try again."), isPresented: $failed) { Button(AppLocalized("OK")) {} }
    }

    @ViewBuilder private func rowView(_ row: NanoMuseWatchRow, at observed: Int) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(row.label).font(.body).textSelection(.enabled)
            Text(name(row.kind) + " · " + origin(row)).font(.footnote).foregroundStyle(.secondary)
            if row.unavailable { Text(AppLocalized("Source unavailable. Will retry.")).font(.footnote).foregroundStyle(.secondary) }
            if let ms = row.lastChecked {
                HStack(spacing: 4) {
                    Text(AppLocalized("Last checked"))
                    Text(Date(timeIntervalSince1970: ms / 1000), style: .relative)
                }.font(.caption).foregroundStyle(.secondary).accessibilityElement(children: .combine)
            }
            HStack(spacing: 18) {
                if row.status == "suggested" {
                    Button(AppLocalized("Follow")) {
                        if row.kind == "scholar_profile" { scholarRevision = observed; scholar = row }
                        else { _ = edit(["id": row.id, "action": "confirm"], at: observed) }
                    }.disabled(!watches.enabled)
                } else if row.status == "paused" {
                    Button(AppLocalized("Resume")) { _ = edit(["id": row.id, "action": "resume"], at: observed) }.disabled(!watches.enabled)
                } else {
                    Button(AppLocalized("Pause")) { _ = edit(["id": row.id, "action": "pause"], at: observed) }
                }
                Button(AppLocalized("Remove"), role: .destructive) { _ = edit(["id": row.id, "action": "dismiss"], at: observed) }
            }.buttonStyle(.borderless)
        }.padding(.vertical, 3)
    }
    private func field(_ type: String, _ value: Binding<String>) -> some View {
        TextField(hint(type), text: value).textInputAutocapitalization(.never).autocorrectionDisabled()
    }
    private func edit(_ fields: [String: Any], at revision: Int) -> Bool {
        let ok = watches.edit(fields, owner: owner, revision: revision)
        if !ok, case nil = scholar { failed = true }
        return ok
    }
}

private struct NanoMuseScholarBinding: View {
    let confirm: (String, String) -> Bool
    @State private var byPaper = false
    @State private var value = ""
    @State private var invalid = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker(AppLocalized("Source"), selection: $byPaper) {
                        Text(AppLocalized("Researcher (OpenAlex or ORCID)")).tag(false)
                        Text(AppLocalized("Paper (DOI)")).tag(true)
                    }
                    TextField(byPaper ? "10.…/…" : "A… / ORCID", text: $value)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button(AppLocalized("Follow")) {
                        invalid = !confirm(byPaper ? "research_work" : "research_author", value)
                    }.disabled(value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if invalid { Text(AppLocalized("Check the source and try again.")).foregroundStyle(.secondary) }
                } footer: {
                    Text(AppLocalized("Enter a verified researcher ID or a paper DOI for this profile."))
                }
            }.navigationTitle("Google Scholar")
        }
    }
}
