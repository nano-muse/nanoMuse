# Coding agents

The Cursor, Codex and Claude Code sessions on your computer, seen and steered from
any device of your account (the phone on the way home, the browser, another
computer) and from the Muse itself.

Nothing is installed into the agents and nothing is proxied through anyone's
server. The runtime or the desktop app on the computer reads what the agents
leave on disk, starts their own command-line interface for a new message, and
streams what comes back. Another device asks over the hub; the hub only carries
the frames.

## In the apps

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
  button. A computer with none of the three installed says so.
- **The Muse**: ask it ("what did I ask Cursor to do last?", "tell Codex in the
  api repo to add a test for the parser"), and it uses the `coding_agents` tool
  with the same read-only readers and the same runner, on this computer or,
  with `device`, on another one.

Only computers that announce the `coding.*` actions on the hub appear: one
running the runtime, or one with the desktop app, which announces them too; a
phone never does.

## What is read

| Agent | Sessions on disk | Started with |
|---|---|---|
| Cursor | `~/.cursor/projects/<workspace-slug>/agent-transcripts/<id>/<id>.jsonl`; CLI chats also `~/.cursor/chats/<hash>/<id>/meta.json` (the `cwd`) | `cursor-agent -p --output-format stream-json --stream-partial-output --force [--resume <id>] [--workspace <dir>] "<text>"` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl` | `codex exec [resume <id>] --json --skip-git-repo-check -c sandbox_mode="workspace-write" [-C <dir>] "<text>"` |
| Claude Code | `~/.claude/projects/<workspace-slug>/<id>.jsonl` | `claude -p --output-format stream-json --verbose --permission-mode acceptEdits [--resume <id>] "<text>"` |

Reading is best effort: a line that does not parse is skipped, a missing
directory is an agent with no sessions. The `~` is the user's home unless
`NANOMUSE_CODING_HOME` names another directory (a container that mounts the
host's CLI homes somewhere else, or a test). A session lists its agent, id, title
(the first user message), workspace, timestamps, message count, the last
exchange and whether it is `resumable`. Cursor IDE chats can be read but not
resumed from the CLI (`resumable: false`, `source: "ide"`): a message to one
goes straight out as a fresh CLI chat in the same workspace, with the old chat's
title and last exchange quoted, and the run says `resumed: false`; the apps say
so above the composer. The same fallback runs when a chat the store called
resumable turns out unknown to the CLI.

`running` on an agent is the number of its processes alive right now, read from
`/proc` on Linux, `ps` on macOS and `tasklist` (plus the command lines of
`node.exe`, for the node-bundled Cursor CLI) on Windows; never `pgrep -f`, and
at most once every two seconds.

The runner stops reading when the agent's terminal event arrives, not at pipe
EOF: `cursor-agent` leaves a worker server running after it answers and would
otherwise hold the run open forever. The process is then waited for and killed
after a grace period.

## Where it runs

Every agent runs with the permissions it has on that computer (Codex in
`workspace-write`, Claude Code with `acceptEdits`, Cursor with `--force`) and
edits files there. Sending a message is therefore treated like running a
command on that computer: the request travels only between devices of one
account, over the account's own hub session, and the computer can refuse remote
control altogether (*Remote control* off keeps `coding.*` local). On the desktop
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
POST /api/coding/send    {agent, text, session_id?, workspace?, device?, wait?}  → the run
POST /api/coding/stop    {run_id, device?}
```

A run is `{id, agent, session_id, asked_session_id, workspace, text, started_at,
ended_at, status, output, resumed, error, tools, device?}`; `status` is `running`,
`done`, `error` or `stopped`. The last 50 finished runs are kept in
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
