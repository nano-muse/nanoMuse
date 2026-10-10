# 编程助手

你电脑上的 Cursor、Codex 和 Claude Code 会话，从你账号下的任何一台设备都能看、能指挥（回家路上的手机、浏览器、另一台电脑），也能由 Muse 自己来做。

什么都不装进这些助手里，什么都不经过谁的服务器中转。电脑上的运行时或桌面版读取助手留在磁盘上的东西，有新消息时启动它们自己的命令行界面，再把返回的内容流式传回来。另一台设备通过 hub（设备互联）发出请求；hub 只负责传帧。

## 在 App 里 {#in-the-apps}

- **手机**：抽屉里的「编程助手」一行（或「设置 → 编程助手」，或 `nanomuse://coding` 链接）。选一台电脑、一个助手、一个会话；读记录；输入一条消息，看着它跑（文字一边生成一边显示，工具一个个被调用），跑偏了就停掉。
- **网页版**：「编程助手」页面。这台电脑上的助手在最上面，账号下其他电脑的排在后面。
- **桌面版**：「设置 → 编程助手」，也可以从「设置 → 设备」里设备卡片上的「编程助手」标签打开。先是这台电脑（每个助手的版本、此刻在跑的进程数和它的聊天），再是账号下的其他电脑；一个助手的聊天列表、一个聊天的记录、输入框、边跑边显示的运行（文字和工具）和一个「停止」按钮。三个都没装的电脑会如实说明。
- **Muse**：直接问它（「我上次让 Cursor 做了什么？」「让 api 仓库里的 Codex 给解析器加一个测试」），它会用 `coding_agents` 工具，读的是同一套只读读取器，跑的是同一个运行器，在这台电脑上，或者带上 `device`，在另一台上。

只有在 hub 上声明了 `coding.*` 动作的电脑才会出现：跑着运行时的，或装了桌面版的（桌面版同样声明这些动作）；手机永远不会。

## 读的是什么 {#what-is-read}

| 助手 | 磁盘上的会话 | 启动命令 |
|---|---|---|
| Cursor | `~/.cursor/projects/<workspace-slug>/agent-transcripts/<id>/<id>.jsonl`；CLI 聊天另有 `~/.cursor/chats/<hash>/<id>/meta.json`（里面的 `cwd`） | `cursor-agent -p --output-format stream-json --stream-partial-output --force [--resume <id>] [--workspace <dir>] "<text>"` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl` | `codex exec [resume <id>] --json --skip-git-repo-check -c sandbox_mode="workspace-write" [-C <dir>] "<text>"` |
| Claude Code | `~/.claude/projects/<workspace-slug>/<id>.jsonl` | `claude -p --output-format stream-json --verbose --permission-mode acceptEdits [--resume <id>] "<text>"` |

读取是尽力而为：解析不了的一行跳过，目录不存在就当这个助手没有会话。`~` 是用户的主目录，除非 `NANOMUSE_CODING_HOME` 指向了别的目录（比如一个把宿主机的 CLI 主目录挂到别处的容器，或者一个测试）。一个会话列出它的助手、id、标题（第一条用户消息）、工作区、时间戳、消息数、最后一轮对话，以及是否 `resumable`。Cursor 的 IDE 聊天能读但不能从 CLI 续上（`resumable: false`，`source: "ide"`）：发给它的消息会直接作为一个新的 CLI 聊天在同一个工作区里发出，引用旧聊天的标题和最后一轮对话，运行结果写明 `resumed: false`；App 会在输入框上方说明这一点。当一个被存储标为可续的聊天在 CLI 那里查无此号时，走的也是同样的回退。

助手的 `running` 是它此刻还活着的进程数，Linux 上读 `/proc`，macOS 上用 `ps`，Windows 上用 `tasklist`（外加 `node.exe` 的命令行，因为 Cursor CLI 是随 node 打包的）；从不使用 `pgrep -f`，而且每两秒最多读一次。

运行器在助手的终止事件到达时就停止读取，而不是等到管道 EOF：`cursor-agent` 回答完之后会留一个 worker 服务器跑着，否则这次运行会被永远挂住。随后等待该进程，宽限期过后将其杀掉。

## 在哪里跑 {#where-it-runs}

每个助手都以它在那台电脑上拥有的权限运行（Codex 在 `workspace-write` 下，Claude Code 带 `acceptEdits`，Cursor 带 `--force`），并且在那里改文件。所以发一条消息被当作在那台电脑上运行一条命令来对待：请求只在同一个账号的设备之间传递，走该账号自己的 hub 会话，而且那台电脑可以完全拒绝远程控制（「远程控制」关掉后，`coding.*` 只在本机可用）。在桌面版上，`coding.send` 和 `coding.stop` 过的是和 `shell`、`files` 同一道关：「远程控制」关着时，尚未信任的设备会在屏幕上弹出一张卡片，由回答（这一次、总是、不行，或没人及时回答）决定；只读动作直接应答，不问。

助手自己的 API key 和登录状态是它们自己的；nanoMuse 从不接触。记录是从磁盘读出来给你看的；除了发起请求的那台设备，不会发给任何地方。

## API {#the-api}

在运行时（`nanomuse serve`）上，需要 App 令牌：

```
GET  /api/coding                                  → {agents: [{id, name, installed, cli, version, sessions_root, running}], runs: […]}
GET  /api/coding/sessions?agent=&limit=&device=   → {sessions: [{agent, id, title, workspace, path, created_at, updated_at, messages, status, last_user, last_assistant, source, resumable}]}
GET  /api/coding/sessions/{agent}/{id}?device=    → the session with transcript: [{role, text}]
POST /api/coding/send    {agent, text, session_id?, workspace?, device?, wait?}  → the run
POST /api/coding/stop    {run_id, device?}
```

一次运行是 `{id, agent, session_id, asked_session_id, workspace, text, started_at, ended_at, status, output, resumed, error, tools, device?}`；`status` 是 `running`、`done`、`error` 或 `stopped` 之一。最近 50 次已结束的运行保存在 `<data_dir>/coding/runs.json`，运行时启动时读回来，所以记录能挺过重启；当时还在跑的运行回来时变成 `stopped`，并附一句说明（CLI 进程随运行时一起结束了）。运行期间，总线上传递 `{"kind": "coding", "run": id, …}` 事件，每个打开的 App 都实时跟着：`started {session_id, model}`、`text {text, partial}`（Cursor 先发增量，再发整条消息；App 用最终那条替换掉流式显示的文字）、`tool {text, phase}`、`done`、`error`。

桌面版把同样的数据形状提供给它自己的窗口，路径在 `nanomuse/cloud/coding` 下（页面的本机回环 API）：`GET`（助手和运行记录）、`GET /sessions`、`GET /sessions/{agent}/{id}`、`POST /send`、`POST /stop`，以及 `GET /events`，上面那些运行事件的服务器推送流。它的 `runs.json` 放在插件数据目录的 `coding/` 下。

## 经由 hub {#over-the-hub}

`device` 指定另一台电脑；同样的请求以 hub 动作传递（`coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs`；见 [hub.md](hub.md)）。带 `wait` 的 `coding.send` 跟着目标机总线上的这次运行，把每一步作为 `event` 帧转发，帧体带运行 id，所以调用方可以 `coding.stop` 它；`result` 帧是结束后的运行。

测试在 `tests/test_coding.py`（基于固定记录样本的读取器、流规范化、一个假 CLI、API），hub 这条路径在 `tests/test_hub.py`；桌面版的移植以同样的方式测试，在 `harness/dsh-nanomuse/tests/coding.test.mjs`。
