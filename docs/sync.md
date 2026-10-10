# What stays on a phone, and whose it is

A phone can be signed in as one account today and another tomorrow: a family's
tablet, a phone handed on, a tester with two accounts. This page is the table of
every piece of state the nanoMuse apps keep on the phone, where it lives, whether
it belongs to the **account**, the **device** or to nobody in particular, and what
happens to it on each of the four events: *sign out*, *switch* (sign in as
another account), *delete the account* and *reinstall*. Contract C12, 0.1.40; the
earlier rule for conversations alone (C10, 0.1.39) is in
[every-device.md](every-device.md#whose-conversations-a-device-shows).

## The rule

- **Every chat has an owner.** The account that was signed in when the chat was
  first seen on this phone, or *nobody* for a chat made while signed out. Chats
  from before 0.1.40 are claimed the same way the first time the updated app
  runs: by the account signed in at that moment (a chat that had already been
  synced keeps the account its sync mapping names), else as nobody's.
- **You see the signed-in owner's chats and no others**: in the drawer, the
  search, the Chat tab, the Library, *Today's chats*, Siri's shortcuts, and in
  what goes up to the relay. Signed out, only the chats made while signed out
  show; every account's are out of sight.
- **A sign-out asks one question**: *Keep this account's chats on this device*,
  **off by default**. Off, the account's chats, memory, feed, goals, routines and
  face are removed from the phone; with sync on, the relay still has the chats
  for the next sign-in. On, all of it is put aside in a folder of the account's
  and comes back untouched when the account signs in again. Signing in as a
  different account, and *Use a different server*, go through the same sign-out.
- **Delete the account** deletes it at the relay and removes everything of it
  from the phone, with no question: there is nothing to come back to. The next
  sign-in with the same address is a new account and starts empty.
- **A key the relay refuses** (*Sign out everywhere* from another device, a
  relay reset, a relay bug: a `401` nobody on this phone asked for) is a
  sign-out nobody could answer, so the phone answers it the careful way: the
  account's data is **kept**, exactly as *Keep this account's chats on this
  device* would (the chats stay hidden behind their owner rows, the files and
  preferences go aside under the account's folder, the relay key is removed),
  and the sign-in page says *Your sign-in on this phone was ended. Sign in
  again to continue; your chats are kept on this device until then.* The next
  sign-in with the **same account id** restores all of it; a different account
  sees nothing of it. Only when the relay answers `401 account_deleted` (the
  account itself no longer exists) is there nothing to come back to, and the
  phone removes the data as *Delete the account* would.
- **A reinstall starts empty.** On Android, the app no longer takes part in the
  device backup (`allowBackup="false"`): nothing of it is copied to Google, and a
  fresh install has no chats, no memory, no key. On the iPhone, a fresh install
  (no marker in UserDefaults, no provider, no chat) deletes the device-only
  Keychain items a previous install left (the relay's key, OAuth tokens,
  environment variables); the relay's key is saved on the device only, never in
  iCloud Keychain, and a 0.1.39 key moves there on the first launch. A restore
  from the person's own iPhone backup brings UserDefaults and files back
  together, marker included, and is treated as the same install.
- **The account's key is the relay's opaque `account.id`**, never the number or
  the address; the folder names on disk are hashes of it. Nothing of the sorting
  involves the relay: an older relay behaves the same.

## Android

Paths are under the app's private `files/`; preferences are the `nanomuse`
SharedPreferences file unless named. *Out* means removed; *aside* means moved
under `minis-global/nanomuse/accounts/<key>/` and restored when that account
returns; *stays* means untouched. The *Key refused* column reads `bad_key` (or
any other `401`) first, `account_deleted` second.

| State | Where | Whose | Sign out (keep off / on) | Switch | Key refused (`bad_key` / `account_deleted`) | Delete account | Reinstall |
|---|---|---|---|---|---|---|---|
| Chats, messages, attachments, hands traces | upstream `minis.db`, `minis-sessions/<id>/` | account (owner row in `nanomuse_sync.db` → `session_owners`) | out / stay hidden | as sign out, then the new account's show | stay hidden / out | out | gone (no backup) |
| Chats made while signed out | the same | nobody (`""`) | aside while signed in, back when signed out | aside | back / back | stay | gone |
| Sync mappings (cids, cursor, known mids) | `nanomuse_sync.db` | account | out with the chats / stay | stay for the account that left | stay / out | out | gone |
| What the muse remembers (SOUL.md, USER.md, GLOBAL.md, diary) | `minis-global/memory/` | account | out / aside | aside; the new account's back or empty | aside / out | out | gone |
| Feed posts and preferences | `minis-global/nanomuse/feed/`, `feed-preferences.md` | account | out / aside | aside | aside / out | out | gone |
| Goals | `minis-global/nanomuse/goals.json` | account | out / aside | aside | aside / out | out | gone |
| Routines (the scheduled tasks, the feed's and the goals' included) | `minis_scheduled_tasks_prefs` | account | alarms off, out / aside (`routines.json`) | aside | alarms off, aside / out | out | gone |
| The face | `minis-global/nanomuse/avatar/` | account (the relay's profile has it too) | out / aside | aside | aside / out | out | gone |
| The shared workspace | `minis-global/shared/` | account | out / aside | aside | aside / out | out | gone |
| Main chat, first conversation, feed switches | prefs `main_chat.*`, `first_conversation.*`, `feed.*` | account | out / aside (`prefs.json`) | aside | aside / out | out | gone |
| The relay key, account id, allowance, models | the provider store (the key encrypted), prefs `cloud.*` and the account rows of `nanomuse` | account | out | replaced | out / out | out | gone |
| Device name and presence at the hub | `minis_device_identity`, prefs `hub.*` | device | stay | stay | stay / stay | stay | new identity |
| Remembered approvals | `minis-global/nanomuse/grants.json` | device | stay (per chat: out with the chat) | stay | stay / stay (per chat: out with the chat) | stay | gone |
| Your own providers and keys, appearance, hands, language | upstream stores | device | stay | stay | stay / stay | stay | gone |
| Ideas | app assets | nobody | — | — | — | — | — |

Code: `io.github.nanomuse.account.AccountScope` (the rules, unit-tested),
`AccountData` (applies them: `reconcile`, `leave`, `enter`), the `session_owners`
table in `SyncEntities.kt`, `ConversationSync.hidden` (what every list leaves
out), the hooks in `ChatRepository.createSession` and `MinisApp`, the sheet in
`CloudAccountScreen`.

## iPhone and iPad

Paths are in the app's sandbox: Application Support, or the app group's
`MinisConfig/` and `var/minis/`. *Aside* means moved under
`MinisConfig/nanomuse/accounts/<hash>/`. The *Key refused* column reads as on
Android: `bad_key` first, `account_deleted` second.

| State | Where | Whose | Sign out (keep off / on) | Switch | Key refused (`bad_key` / `account_deleted`) | Delete account | Reinstall |
|---|---|---|---|---|---|---|---|
| Chats, messages, media | upstream's SQLite store | account (owner row in `nanomuse-owners.json`) | out / stay hidden | as sign out, then the new account's show | stay hidden / out | out | gone |
| Chats made while signed out | the same | nobody | aside while signed in, back when signed out | aside | back / back | stay | gone |
| Sync tables (per account, cids, cursor, known mids) | `nanomuse-sync-accounts.json` | account | out with the chats / stay | stay for the account that left | stay / out | out | gone |
| What the muse remembers | app group `memory/` | account | out / aside | aside | aside / out | out | gone |
| Feed posts and preferences | `MinisConfig/nanomuse/feed/`, `feed-preferences.md` | account | out / aside | aside | aside / out | out | gone |
| Goals | `MinisConfig/nanomuse/goals.json` | account | out / aside | aside | aside / out | out | gone |
| Routines | `MinisConfig/nanomuse/routines.json` | account | notifications off, out / aside | aside | notifications off, aside / out | out | gone |
| The face (stills; the clips are redrawn) | Application Support `nanomuse/avatar/` | account | out / aside | aside | aside / out | out | gone |
| The shared workspace | app group `shared/` | account | out / aside | aside | aside / out | out | gone |
| Main chat, first conversation, feed switches | UserDefaults `nanomuse.main_chat.*`, `nanomuse.first_conversation.*`, `nanomuse.feed.*` | account | out / aside (`defaults.plist`) | aside | aside / out | out | gone |
| The relay key | Keychain, this device only (`…ThisDeviceOnly`, not synchronizable) | account | out | replaced | out / out | out | swept on the first launch |
| Account id, allowance, models, region | UserDefaults `nanomuse.cloud.*`, the provider store | account | out | replaced | out / out | out | gone |
| Device id and name at the hub | UserDefaults `nanomuse.hub.*`, Keychain `…app.device` | device | stay | stay | stay / stay | stay | new identity |
| Your own providers and keys | the provider store; keys in Keychain, synchronizable (upstream's choice) | device | stay | stay | stay / stay | stay | the config is gone; a synchronizable key stays in the person's iCloud Keychain |
| Appearance, the star, setup flags | UserDefaults | device | stay | stay | stay / stay | stay | gone |

**iCloud.** Upstream's own iCloud sync of chats and providers (*Settings → iCloud*,
off by default) and iCloud Keychain are the person's Apple ID, not the account's.
With upstream's iCloud sync on, a chat deleted by a sign-out is deleted through it
as a chat deleted by hand would be, and a chat kept aside can reach the person's
other iPhone without its owner row; on that phone it is claimed by whoever is
signed in there. The owners file, the sync tables and the folders put aside are
in the iPhone's device backup like the rest of the app's data.

Code: `NanoMuse/NanoMuseAccountData.swift` (owners, `leave`, `enter`, the
Keychain), `NanoMuseSync.shows` and `dropTable`, `NanoMuseSignOutSheet.swift`,
the hooks in `ChatStore.createSession` and `NanoMuseShell`.

## The relay

`POST /v1/auth/delete` removes every row of the account: the account, its keys,
devices, profile (name, face, connectors), the ledger, events, the kept
*Data controls* conversations and video tasks, the synced conversations,
messages and cursors. It drops its hub connections and, from the relay that ships with 0.1.40, forgets
the account's live *working* notes too (they were memory, not rows). The relay's
tests sign an account up, fill every table, delete it, and check that every
table has zero rows for it and that the same address signing up again gets a new
account id and an empty sync store.

One thing outlives the account for a while: the SHA-256 hashes of the keys it
held, in `deleted_keys`, for 90 days. They name nobody (no account id, no
address, no device), and they are what lets a phone that still holds one of
those keys hear `401 account_deleted` instead of `401 bad_key`, the difference
between *remove the account's data, there is nothing to come back to* and *keep
it aside, the person may sign in again*. A relay from before 0.1.40 answers
`bad_key` for both, and the phone keeps the data; nothing is lost, the folder
simply waits.

## For the maintainers

The old records a person saw after deleting an account in 0.1.39 were the
phone's: a chat with no sync mapping (a side chat with the side-chat switch
off, a chat from before 0.1.39) had no owner, so it showed under every
account and was pushed under the next one. The relay had already deleted its
side. C12 gives every chat an owner and makes a sign-out take the account's
data with it unless asked not to.
