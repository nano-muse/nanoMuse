# Coding agents

On Android, the agent filters scroll horizontally and keep each name on one line. Each filter shows whether the agent is running, installed or not installed. Uninstalled agents remain selectable so their saved sessions can still be found.

The Cursor, Codex, Claude Code and DeepSeek Harness sessions on your computer, seen and steered
from any device of your account (the phone on the way home, the browser, another
computer) and from the Muse itself.

Nothing is installed into the agents and nothing is proxied through anyone's
server. The runtime or the desktop app on the computer reads what the agents
leave on disk, starts their own command-line interface for a new message, and
streams what comes back. Another device asks over the hub; the hub only carries
the frames.

On Windows, process discovery decodes command output using the console encoding when it is not UTF-8. Accented process names no longer interrupt the coding agent list.

The desktop preserves Chinese text and other UTF-8 characters when a coding agent's output arrives across several pipe reads, including the last line without a newline.

When you switch computers or agents on desktop, lists and suggested folders show only
the current selection. Previous results disappear while the new selection loads. A
chat composer waits for that chat to load before using its saved workspace.

## In the apps

When a coding agent cannot resume a saved session, the retry starts a new session with clean output. A partially streamed line from the failed attempt is discarded along with its accumulated output.

- **Phone**: the drawer's *Coding* row (or *Settings → Coding agents*, or the
  `nanomuse://coding` link). Pick a computer, an agent, a session; read the
  transcript; type a message and watch the run (the text as it streams, the
  tools as they are called) and stop it if it goes wrong.
- **Web**: the *Coding* screen. This computer's agents at the top, the
  account's other computers after them.
- **Desktop**: *Settings → Coding agents*, also opened by the *Coding agents*
  chip on a device card under *Settings → Devices*. This computer first (each
  agent with its version, how many of its processes run right now and its
  chats), then the account's other computers; an agent's chats, a chat's
  transcript, a composer, the run as it streams (text and tools) and a *Stop*
  button. A computer with none of them installed says so.
- **The Muse**: ask it ("what did I ask Cursor to do last?", "tell Codex in the
  api repo to add a test for the parser"), and it uses the `coding_agents` tool
  with the same read-only readers and the same runner, on this computer or,
  with `device`, on another one.

Only computers that announce the `coding.*` actions on the hub appear: one
running the runtime, or one with the desktop app, which announces them too; a
phone never does.

When the desktop follows a coding run on another computer, its tool count uses the same phase as the originating runner: completion for Codex, start for the other agents. Notes do not count as tools. The final result supplies the originating computer's count if any events were missed.

## What is read

| Agent | Sessions on disk | Started with |
|---|---|---|
| Cursor | `~/.cursor/projects/<workspace-slug>/agent-transcripts/<id>/<id>.jsonl`; CLI chats also `~/.cursor/chats/<hash>/<id>/meta.json` (the `cwd`) | `cursor-agent -p --output-format stream-json --stream-partial-output --force [--resume <id>] [--workspace <dir>] "<text>"` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl` | `codex exec [resume <id>] --json --skip-git-repo-check -c sandbox_mode="workspace-write" [-C <dir>] "<text>"` |
| Claude Code | `~/.claude/projects/<workspace-slug>/<id>.jsonl` | `claude -p --output-format stream-json --verbose --permission-mode acceptEdits [--resume <id>] "<text>"` |
| dsh (DeepSeek Harness) | `~/.dsh/sessions/<workspace-slug>/<id>/session.v4.jsonl.zstd` | `dsh --profile headless --json [--session-id <id>] "<text>"` |

Reading is best effort: a line that does not parse is skipped, a missing
directory is an agent with no sessions. The `~` is the user's home unless
`NANOMUSE_CODING_HOME` names another directory (a container that mounts the
host's CLI homes somewhere else, or a test). A session lists its agent, id, title
(the stored Codex name, or the first actual user message as a fallback), workspace, timestamps, message count, the last
exchange and whether it is `resumable`. Cursor IDE chats can be read but not
resumed from the CLI (`resumable: false`, `source: "ide"`): a message to one
goes straight out as a fresh CLI chat in the same workspace, with the old chat's
title and last exchange quoted, and the run says `resumed: false`; the apps say
so above the composer. The same fallback runs when a chat the store called
resumable turns out unknown to the CLI.

dsh is [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): the
chats of `dsh web` and of DeepSeek's own desktop app, kept under `~/.dsh`. The
runtime and the nanoMuse desktop app both read and drive them; the runtime reads
the store with `zstandard`, one of its dependencies. nanoMuse's own desktop chats
are kept in its own home and are not among them.

dsh's store needs two things said: it is **zstd**, and it is **many zstd frames**
appended as the session is written, so decompressing it once stops at the end of
the first frame and a long chat loses everything after its opening lines. The
frames are therefore read one after another to the end, and a last frame cut short
by a write in progress costs only that frame. Two kinds of session are
also not chats the person had and are left out: a `user/message` whose
`source.kind` is not `user` (runtime context, the skill catalog, background-job
notices all arrive that way), and a session whose header says `origin:
"subagent"` or names a `parentSession`.

dsh is also the one agent whose command line is not looked for on `PATH` alone:
the desktop app ships the harness inside itself (`…/Resources/dsh/`) and starts it
as `node …/dsh/lib/bin.js <profile>`, so a computer with the app has dsh sessions
but no `dsh` on `PATH`. The desktop plugin therefore falls back to the harness it
is running inside (the entry in its own command line) and starts that through
node. A `dsh` installed on `PATH` is still used first, as for the other three.
That fallback only sends: dsh counts as installed when a `dsh` is on `PATH` or
`~/.dsh` exists, so a computer where nobody has used it does not list a fourth
agent.
Either way, and on the runtime too, the run gets `DSH_HOME=~/.dsh`: the desktop
app points `DSH_HOME` at its own home for the harness it runs, and a run there
would neither find the chat it was asked to continue nor leave a new one where the
list looks.

`running` on an agent is the number of its processes alive right now, read from
`/proc` on Linux, `ps` on macOS and `tasklist` (plus the command lines of
`node.exe`, for the node-bundled Cursor CLI) on Windows; never `pgrep -f`, and
at most once every two seconds.

The runner stops reading when the agent's terminal event arrives, not at pipe
EOF: `cursor-agent` leaves a worker server running after it answers and would
otherwise hold the run open forever. The process is then waited for and killed
after a grace period.

When the Python runtime lists sessions for a workspace, it checks each transcript's
workspace before applying the result limit. Newer chats in other projects do not hide
that workspace's history. The stored workspace takes priority over a directory name,
since different paths can map to the same directory name in a coding agent's store.

## Where it runs

Every agent runs with the permissions it has on that computer (Codex in
`workspace-write`, Claude Code with `acceptEdits`, Cursor with `--force`, dsh
headless under its own sandbox policy) and edits files there. Sending a message
is therefore treated like running a command on that computer: to the Sentinel
`coding_agents send` is `sensitive`, the same level as `shell` (in `ask` mode the
card names the agent, the folder and the message), and the request travels
only between devices of one account, over the account's own hub session, and the
computer can refuse remote control altogether (*Remote control* off keeps
`coding.*` local). On the desktop
app `coding.send` and `coding.stop` pass the same gate as `shell` and `files`:
with *Remote control* off, a device that is not yet trusted raises a card on the
screen, and the answer (once, always, no, or none in time) decides; the
read-only actions are answered without asking.

The agents' own API keys and sign-ins are theirs; nanoMuse never sees them. The
transcripts are read from disk and shown to you; they are not sent anywhere but
to the device that asked.

## The API

On the runtime (`nanomuse serve`), behind the app token:

```
GET  /api/coding                                  → {agents: [{id, name, installed, cli, version, sessions_root, running}], runs: […]}
GET  /api/coding/sessions?agent=&limit=&device=   → {sessions: [{agent, id, title, workspace, path, created_at, updated_at, messages, status, last_user, last_assistant, source, resumable}]}
GET  /api/coding/sessions/{agent}/{id}?device=    → the session with transcript: [{role, text}]
POST /api/coding/send    {agent, text, session_id?, workspace?, device?}  → the run
POST /api/coding/stop    {run, device?}
```

A run is `{id, agent, session_id, asked_session_id, workspace, text, started_at,
ended_at, status, output, resumed, error, tools, device?}`; `status` is `running`,
`done`, `failed` or `stopped`. The last 50 finished runs are kept in
`<data_dir>/coding/runs.json` and read back when the runtime starts, so the
record survives a restart; a run that was still going then comes back as
`stopped` with a note (the CLI process ended with the runtime). While it runs the bus carries `{"kind": "coding", "run":
id, …}` events every open app follows live: `started {session_id, model}`, `text
{text, partial}` (Cursor sends deltas, then the whole message; the apps replace
the streamed text with the final one), `tool {text, phase}`, `done`, `error`.

The desktop app serves the same shapes to its own window under
`nanomuse/cloud/coding` (the page's loopback API): `GET` (agents and runs),
`GET /sessions`, `GET /sessions/{agent}/{id}`, `POST /send`, `POST /stop`, and
`GET /events`, a server-sent stream of the run events above. Its `runs.json`
lives in the plugin's data directory under `coding/`.

## Over the hub

### Structured browsing, protocol 2

When a Codex resume fails with a session writer conflict, the computer returns a failed
run with `resume_conflict: {process, continuation}` instead of silently starting another
session. `process` is a best-effort process name and PID, empty when unavailable.
The iOS app offers Cancel or Create conversation. Cancel keeps the question in the draft;
Create immediately replaces the current chat with a fresh page and starts a new run in
the same workspace. Its first message is the exact `Continuing… Last exchange… Now…`
prompt returned by the computer. This carries the last two readable messages, at most
800 characters each, not a model-generated summary or the entire history. The full prompt
is shown once and used by the existing exact-text match when the completed run moves
into history. Merely opening a lock file is not treated as a writer conflict.
Codex's `thread/resume` error `already has an active writer` is also a writer conflict,
including when the CLI reports it only on stderr.

For resume diagnostics, update both the desktop plugin and iOS app. In desktop
development, `npm run start` rebuilds only the Electron shell: build the plugin, quit
the desktop app, run `npm run prepare-dsh` in `harness/desktop`, then restart it.
An installed desktop app needs a rebuilt installer. Local desktop logs include
`coding diagnostic` and the marker `coding-resume-v2`, with attempt outcomes,
failure categories and session identifiers. They do not include prompts or raw CLI errors.
On iOS, enable logging under Settings → Logs before reproducing, then open today's log.
`NanoMuseCoding` entries record the reply's conflict flag, alert decisions and whether
the completed live prompt exactly matched a new historical user message. These entries
contain text lengths, not conversation contents. Share only the relevant entries;
other categories in the same log may contain private data.

On iOS, each response turn's tools are collapsed into one tool-call summary above
the assistant messages, for both live runs and history. Expand it to browse the
individual calls. File changes remain below the final reply: selecting a specific
file opens its recorded line diff directly, while the overall change entry opens
execution details with inputs, output and the file list.
The diff uses one horizontal-and-vertical scroll area for long lines. It reserves
compact columns only when recorded line numbers exist. The Projects / Chats
filter uses the same pill-style controls as the agent filters above it.
Opening a file diff starts at the left edge; loading more keeps the current scroll position.
Added and removed code lines use solid tinted backgrounds, matching coloured line numbers
and a bright left-edge marker, including patches without recorded line numbers.

Switching computers on iOS hides the previous computer's projects and sessions while
the new list loads. An open conversation keeps its original destination. If a paged
history, output or diff fails to load, use **Refresh** to restart from the latest
first page; pages from changed content are never combined.

The iOS coding screen separates **Projects** and **Chats**, groups project sessions
by folder, and starts a new conversation with an installed agent in that folder.
It uses nanoMuse's existing colours and Markdown renderer. Tool rows expand into
recorded output and file counts; **Execution details** opens the inputs and paged
output; selecting a file opens its recorded patch directly. Missing patches or counts stay
unavailable, rather than being reconstructed from today's workspace.

The Projects / Chats switch sits directly above Recent sessions. A conversation
opens full screen, so scrolling cannot dismiss it. Recorded file changes remain
visible when a tool row is collapsed and are also grouped below the last assistant
reply of their turn. Tap a file to open its execution details and recorded diff.
Older history must be loaded before its file changes can appear in this summary.
Codex titles use the saved thread name in its read-only `state_*.sqlite` metadata,
then `session_index.jsonl`, then the first actual user message. Injected
`AGENTS.md` instructions are excluded from messages and fallback titles.

The Python runtime and desktop plugin answer the same additional hub actions.
The structured timeline, file-change grouping and writer-conflict prompt draw on
the interface open-source Remodex shows for controlling coding agents remotely.
No Remodex relay, pairing code, SDK or daemon is needed. These are coding subprotocol
2 additions, not a new hub envelope version. Existing plain `transcript` clients
remain supported; an older computer still supplies plain text to the iOS screen.

| Action | Arguments | Result |
|---|---|---|
| `coding.agents` | `fresh?` | `protocol_version: 2`; each agent has `capabilities` |
| `coding.sessions` | `protocol_version: 2, agent?, workspace?, scope?, limit?, cursor?` | `sessions`, `version`, `next_cursor`, `total`, `bounded` |
| `coding.projects` | none | Known project folders, IDs, agent IDs, latest update |
| `coding.project.validate` | `workspace` | Whether an absolute project directory exists; no file contents |
| `coding.session` | `agent, session_id, protocol_version: 2, limit?, cursor?, tail?` | Session metadata, `timeline`, page metadata, recent owned runs; no duplicate `transcript` payload |
| `coding.item` | `agent, session_id, item_id, run_id?, limit?, cursor?` | Item, recorded input, paged `output`, `source_truncated` |
| `coding.diff` | `agent, session_id, diff_reference, run_id?, limit?, cursor?` | Paged patch `data`, path, `diff_scope: item` |
| `coding.watch` | `agent, session_id, version?, run_id?` | Snapshot `changed`, `version`, status, owned runs |
| `coding.send` | Existing arguments plus `scope?, request_id?, protocol_version?` | Existing run; structured `item` events and a bounded final timeline |

An item has `id`, `turn_id`, `sequence`, `revision`, `role`, `kind`, `text`, and
`status`. Kinds are `message`, `command`, `tool`, `file_change`. Command metadata
contains `display_command`, `cwd`, and, only when recorded, `exit_code` and
`duration_ms`. Previews carry `input_preview`, `output_preview`, `text_truncated`,
and files with `path`, optional counts and an opaque `diff_reference`. Repeated
events replace an item's previous revision, not append another tool row.
Raw Codex patch hunks and Claude Edit inputs have no original line positions;
only a recorded unified hunk produces numbered lines.

History pages contain at most 200 items, output/diff pages at most 32,768
characters. Individual tool outputs are retained up to 262,144 characters and
report truncation. A cursor is valid only for the same content version; changed
content returns `stale_cursor`, malformed tokens `invalid_cursor`. Reload from
the beginning instead of combining incompatible pages. Session discovery scans
the most recent 500 sessions; `bounded` reports reaching this bound. The iOS list
loads 100 sessions at a time and supports search and further pages. Chats request
`tail: true` for the latest 100 items, then prepend earlier pages in chronological order.

`scope: chats` on a new send creates a separate directory under
`~/Documents/nanoMuse/Chats/`; known Codex rootless directories are also classified
as Chats. Other workspaces are Projects. Sending and stopping still use the
existing remote-control/Sentinel gate. Read-only item/diff requests only resolve
references in the specified session or an associated nanoMuse-owned run, never
an arbitrary path. Validation does not bypass the send gate.

`request_id` deduplicates an identical send, including concurrent requests.
After observing a tool start or result, a failed resumed run stays failed. An error
containing "not found" cannot silently start a new conversation and repeat the work.
Reuse with different content returns `request_conflict`. Finished runs retain
the identity across restart within the existing 50-run retention. The iOS client
uses `wait: false` to receive the run ID after the computer's permission gate,
then follows that run with three-second foreground snapshot requests, including
while it is running and before a new session has an ID. Completion, failure and
stop status come from the owned run; a lost long-lived send response is not required.
Older computers are followed through `coding.runs`. The client does not
automatically resend after a connection failure. Polling ends when the chat closes;
history updates do not force-scroll someone reading earlier messages.

A gated send emits `authorization` while waiting for permission on the computer.
iOS shows that waiting state and includes the computer's error details when a send
fails. With remote control off, allow the desktop's request card or trust the phone
before sending. Agent terminal failures end the run even if a helper retains its
output pipe or the process exits with code zero.

The compatibility adapters browse Codex, Claude Code, Cursor and dsh records,
and control CLI runs started by nanoMuse. **External-run control and native
agent approvals are not implemented by these adapters**:
`control_external_run`, `approve`, and arbitrary `file` capabilities are false.
The separate Codex app-server control adapter is not part of this stage.
Cursor IDE sessions retain the existing continue-as-new behaviour.

`device` names another computer; the same request travels as hub actions
(`coding.agents`, `coding.sessions`, `coding.session`, `coding.send`,
`coding.stop`, `coding.runs`; see [hub.md](hub.md)). `coding.send` with `wait`
follows the run on the target's bus and forwards each step as an `event` frame
whose body carries the run id, so the caller can `coding.stop` it; the `result`
frame is the finished run.

The tests are `tests/test_coding.py` (the readers on fixture transcripts, the
stream normaliser, a fake CLI, the API) and the hub path in `tests/test_hub.py`;
the desktop's port is tested the same way in
`harness/dsh-nanomuse/tests/coding.test.mjs`.
