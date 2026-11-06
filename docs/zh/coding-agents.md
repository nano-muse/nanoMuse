# 编程助手

Android 的助手筛选项可以横向滚动，每个名称都保持单行显示。筛选项还会标明助手正在运行、已安装或未安装。未安装的助手仍然可以选择，便于查找它以前保存的会话。

你可以从同一账号下的手机、浏览器或另一台电脑，查看并继续电脑上 Cursor、Codex、Claude Code 和 DeepSeek Harness 的会话，也可以让 nanoMuse 代为操作。例如，回家途中可以用手机接着处理电脑上的编程任务。

nanoMuse 不会向这些助手安装插件，也不会把它们的模型请求经由其他服务器转发。电脑上的运行时（负责执行任务的本地程序）或桌面版会读取助手保存在磁盘上的记录；你发送新消息时，它会启动该助手自己的 CLI（命令行程序），并把输出一边接收一边显示。其他设备通过 hub（设备互联服务）发出请求，hub 只转发消息帧，也就是双方交换的数据包。

在 Windows 上，进程检测遇到非 UTF-8 的命令输出时，会按控制台的实际字符编码解码。因此，进程名称带重音字符也不会中断编程助手列表的加载。

桌面版接收助手输出时，会完整保留中文和其他 UTF-8 字符。即使同一个字符的字节分散在多次管道读取中，或最后一行没有换行符，也不会丢失或显示成乱码。

## 在应用中使用 {#in-the-apps}

如果助手无法继续已保存的会话，重试会改为新建会话，并清空失败尝试的输出。失败尝试中尚未接收完整的一行也会一起丢弃，避免混入新的结果。

- **手机**：打开抽屉中的「编程助手」，也可进入设置 → 编程助手，或打开 `nanomuse://coding` 链接。先选电脑，再选助手和会话，就能阅读记录、输入消息。运行时可以实时查看生成的文字和调用的工具，需要时点「停止」。
- **网页版**：打开「编程助手」页面。页面先列出本机助手，再列出账号下其他电脑的助手。
- **桌面版**：进入设置 → 编程助手，也可在设置 → 设备中，点击设备卡片上的「编程助手」标签。页面先显示本机每个助手的版本、当前运行的进程数和聊天记录，再显示账号下其他电脑。选定助手和聊天后，可以查看完整记录、输入消息，实时查看文字和工具调用，并用「停止」结束运行。电脑上没有安装这些助手时，页面会明确说明。
- **nanoMuse**：直接向它提问或下达任务，例如「我上次让 Cursor 做了什么？」或「让 api 仓库里的 Codex 给解析器加一个测试」。它会调用 `coding_agents` 工具，使用与页面相同的只读记录读取功能和执行程序。默认操作本机，指定 `device` 则操作另一台电脑。

设备列表只显示在 hub 中声明支持 `coding.*` 动作的电脑。运行着 Python 运行时或 nanoMuse 桌面版的电脑可以声明这些动作，手机不会声明。

桌面版查看另一台电脑的任务时，工具调用次数按执行电脑的规则计算：Codex 在工具完成时计数，其他助手在工具开始时计数。说明性消息不算工具调用。如果途中漏收事件，最终结果会提供执行电脑的统计值，用于补正次数。

## 读取哪些内容 {#what-is-read}

| 助手 | 磁盘上的会话 | 启动命令 |
|---|---|---|
| Cursor | `~/.cursor/projects/<workspace-slug>/agent-transcripts/<id>/<id>.jsonl`；CLI 聊天另有 `~/.cursor/chats/<hash>/<id>/meta.json`，其中记录 `cwd`（工作目录） | `cursor-agent -p --output-format stream-json --stream-partial-output --force [--resume <id>] [--workspace <dir>] "<text>"` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl` | `codex exec [resume <id>] --json --skip-git-repo-check -c sandbox_mode="workspace-write" [-C <dir>] "<text>"` |
| Claude Code | `~/.claude/projects/<workspace-slug>/<id>.jsonl` | `claude -p --output-format stream-json --verbose --permission-mode acceptEdits [--resume <id>] "<text>"` |
| dsh（DeepSeek Harness） | `~/.dsh/sessions/<workspace-slug>/<id>/session.v4.jsonl.zstd` | `dsh --profile headless --json [--session-id <id>] "<text>"` |

读取记录时，无法解析的行会跳过，目录不存在则视为该助手没有会话。`~` 通常指用户主目录；如果设置了 `NANOMUSE_CODING_HOME`，则改用它指定的目录。这适用于将宿主机 CLI 目录挂载到其他位置的容器，也用于测试。

每条会话记录会列出所属助手、id、标题（第一条用户消息）、工作区、时间戳、消息数、最后一轮对话，以及 `resumable`（能否继续原会话）。Cursor 的 IDE（集成开发环境）聊天可以读取，但无法通过 CLI 继续，标记为 `resumable: false`、`source: "ide"`。向这种聊天发消息时，会在同一工作区新建 CLI 会话，并引用旧聊天的标题和最后一轮对话；运行结果标记为 `resumed: false`，应用也会在输入框上方说明。记录中标为可继续、但 CLI 实际找不到的会话，也采用同样的处理方式。

dsh 是 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)，这里读取的是 `dsh web` 和 DeepSeek 自家桌面应用保存在 `~/.dsh` 中的聊天。Python 运行时和 nanoMuse 桌面版都能读取并继续这些聊天。运行时通过其依赖包 `zstandard` 读取文件。nanoMuse 桌面版自己的聊天保存在独立的数据目录，不包含在这些记录中。

dsh 的会话文件使用 **zstd 压缩**，而且每次写入都会在末尾追加一个新的压缩数据块，称为「帧」。只解压一次就会在第一帧结束处停止，长会话因此只能读到开头几行。nanoMuse 会逐帧读取到文件末尾；如果最后一帧正写到一半，只会跳过这一个未完成的帧。

以下两类内容不属于用户实际进行的聊天，会从结果中排除：一是 `source.kind` 不等于 `user` 的 `user/message`，例如运行时上下文、技能目录和后台任务通知；二是文件头中带有 `origin: "subagent"` 或 `parentSession` 的会话，也就是子智能体会话。

dsh 的 CLI 查找方式与其他助手不同。除了查找 `PATH`（系统搜索可执行程序的目录列表），还会尝试桌面应用内置的 harness。桌面应用将它打包在 `…/Resources/dsh/`，通过 `node …/dsh/lib/bin.js <profile>` 启动。因此，一台电脑可能已有 dsh 会话，却没有可直接运行的 `dsh` 命令。桌面版插件会从自身启动命令中找到这个内置入口，再用 node 启动。与其他三个助手一样，`PATH` 中已安装的 `dsh` 仍然优先。

内置入口只作为发送消息时的备用方案。只有 `PATH` 中存在 `dsh`，或 `~/.dsh` 目录存在，才会将 dsh 标记为已安装，避免在从未使用过它的电脑上额外列出一个助手。无论使用哪个入口，Python 运行时（`nanomuse serve`）也一样，执行时都会设置 `DSH_HOME=~/.dsh`。这是因为 nanoMuse 桌面版为自己使用的 harness 设置了独立的 `DSH_HOME`；如果沿用那个目录，就既找不到要继续的外部 dsh 会话，新建会话也不会出现在当前列表中。

助手的 `running` 字段表示当前仍在运行的进程数量。Linux 从 `/proc` 读取，macOS 使用 `ps`，Windows 使用 `tasklist`，并检查 `node.exe` 的命令行以识别由 node 启动的 Cursor CLI。检测不会使用 `pgrep -f`，每两秒最多执行一次。

执行程序收到助手的结束事件后就停止读取，不会等待管道 EOF（输出流完全关闭）。原因是 `cursor-agent` 回答后仍会保留一个后台工作服务，等待 EOF 会让任务一直无法结束。随后，执行程序会等待进程退出，超过宽限时间则终止进程。

Python 运行时按工作区查找会话时，会先检查每份记录实际所属的工作区，再限制返回数量。其他项目中较新的聊天不会挤掉这个项目的历史。由于不同路径可能映射为助手存储中的同一个目录名，归属以记录内保存的工作区为准，不靠目录名推断。

## 在哪里执行，使用哪些权限 {#where-it-runs}

每个助手都在其所在电脑上运行，并使用它原有的权限修改那台电脑的文件：Codex 使用 `workspace-write`（允许写入工作区），Claude Code 使用 `acceptEdits`，Cursor 使用 `--force`，dsh 的无界面模式按自身沙箱策略执行。沙箱是限制程序能访问哪些资源的隔离机制。

因此，给编程助手发消息与在该电脑上执行命令按相同方式管理。哨兵（Sentinel，执行操作前检查风险和权限的组件）将 `coding_agents send` 归为 `sensitive`，与 `shell` 同级。在 `ask` 模式下，审批卡片会列明助手、文件夹和消息，等你决定是否允许。请求只会经由同一账号的 hub 会话在该账号设备之间传递。电脑也可以拒绝远程控制；关闭「远程控制」后，Python 运行时的 `coding.*` 仅在本机可用。

桌面版的 `coding.send` 和 `coding.stop` 使用与 `shell`、`files` 相同的权限检查。关闭「远程控制」时，尚未信任的设备发来请求，会在电脑屏幕上弹出审批卡片。你可以允许一次、总是允许或拒绝；超时未回答也会决定请求结果。只读操作直接返回，不询问。

编程助手自己的 API key 和登录信息仍由各助手管理，nanoMuse 不会接触。聊天记录从本地磁盘读取，只发送给发起请求的设备。

## API {#the-api}

运行时（`nanomuse serve`）提供以下 API，调用时需要应用 token（用于验证访问权限的令牌）：

```
GET  /api/coding                                  → {agents: [{id, name, installed, cli, version, sessions_root, running}], runs: […]}
GET  /api/coding/sessions?agent=&limit=&device=   → {sessions: [{agent, id, title, workspace, path, created_at, updated_at, messages, status, last_user, last_assistant, source, resumable}]}
GET  /api/coding/sessions/{agent}/{id}?device=    → the session with transcript: [{role, text}]
POST /api/coding/send    {agent, text, session_id?, workspace?, device?}  → the run
POST /api/coding/stop    {run, device?}
```

一次运行的结构是 `{id, agent, session_id, asked_session_id, workspace, text, started_at, ended_at, status, output, resumed, error, tools, device?}`。`status` 可以是 `running`、`done`、`failed` 或 `stopped`，分别表示运行中、完成、失败、已停止。

最近 50 次已结束的运行会保存在 `<data_dir>/coding/runs.json`，运行时启动后重新读取，因此重启不会丢失这些记录。重启前仍在执行的任务会标为 `stopped` 并附上说明，因为对应 CLI 进程已随运行时退出。

任务运行期间，内部消息总线会发送 `{"kind": "coding", "run": id, …}` 事件，打开的应用可实时接收。事件包括：`started {session_id, model}`、`text {text, partial}`、`tool {text, phase}`、`done`、`error`。Cursor 先发送增量文字，再发送完整消息，因此应用会用最终消息替换此前逐段显示的文字。

桌面版通过本机回环 API（只供这台电脑内部通信的接口）`nanomuse/cloud/coding` 向自己的窗口提供相同数据结构：`GET` 返回助手和运行记录，另有 `GET /sessions`、`GET /sessions/{agent}/{id}`、`POST /send`、`POST /stop`。`GET /events` 以服务器持续推送的方式发送上述运行事件。桌面版的 `runs.json` 保存在插件数据目录下的 `coding/` 中。

## 通过 hub 访问其他电脑 {#over-the-hub}

`device` 用于指定另一台电脑。请求会转换为 hub 动作：`coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs`，见 [hub.md](hub.md)。

`coding.send` 带上 `wait` 时，会持续接收目标电脑消息总线中的运行事件，将每一步作为 `event` 帧转发。帧的内容包含运行 id，调用方可用它发出 `coding.stop`。任务结束后，`result` 帧返回完整的运行结果。

测试位于 `tests/test_coding.py`，涵盖用固定聊天样本读取记录、统一不同助手的输出格式、模拟 CLI 及 API。hub 通信路径由 `tests/test_hub.py` 测试；桌面版的对应实现用相同方式测试，文件为 `harness/dsh-nanomuse/tests/coding.test.mjs`。
