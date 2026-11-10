# 编程助手

Android 的助手筛选项可以横向滚动，每个名称都保持单行显示。筛选项还会标明助手正在运行、已安装或未安装。未安装的助手仍然可以选择，便于查找它以前保存的会话。

你可以从同一账号下的手机、浏览器或另一台电脑，查看并继续电脑上 Cursor、Codex、Claude Code 和 DeepSeek Harness 的会话，也可以让 nanoMuse 代为操作。例如，回家途中可以用手机接着处理电脑上的编程任务。

nanoMuse 不会向这些助手安装插件，也不会把它们的模型请求经由其他服务器转发。电脑上的运行时（负责执行任务的本地程序）或桌面版会读取助手保存在磁盘上的记录；你发送新消息时，它会启动该助手自己的 CLI（命令行程序），并把输出一边接收一边显示。其他设备通过 hub（设备互联服务）发出请求，hub 只转发消息帧，也就是双方交换的数据包。

在 Windows 上，进程检测遇到非 UTF-8 的命令输出时，会按控制台的实际字符编码解码。因此，进程名称带重音字符也不会中断编程助手列表的加载。

桌面版接收助手输出时，会完整保留中文和其他 UTF-8 字符。即使同一个字符的字节分散在多次管道读取中，或最后一行没有换行符，也不会丢失或显示成乱码。

桌面版切换电脑或助手时，列表和推荐文件夹只显示当前选择的内容。新内容加载期间会隐藏上一项的结果。打开聊天时，输入框会等待该聊天加载完成，再使用它保存的工作目录。

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

每条会话记录会列出所属助手、id、标题（Codex 优先使用只读 `state_*.sqlite` 中保存的名称，其次读取 `session_index.jsonl`，都没有时才使用第一条实际用户消息）、工作区、时间戳、消息数、最后一轮对话，以及 `resumable`（能否继续原会话）。Cursor 的 IDE（集成开发环境）聊天可以读取，但无法通过 CLI 继续，标记为 `resumable: false`、`source: "ide"`。向这种聊天发消息时，会在同一工作区新建 CLI 会话，并引用旧聊天的标题和最后一轮对话；运行结果标记为 `resumed: false`，应用也会在输入框上方说明。记录中标为可继续、但 CLI 实际找不到的会话，也采用同样的处理方式。注入的 `AGENTS.md` 指令不会作为聊天消息或备用标题显示。

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

### 结构化浏览，协议 2

结构化时间线、文件变更分组和写入冲突确认的展示参考开源软件 Remodex 中远程控制编程智能体的界面。网络与执行仍完全使用 nanoMuse Hub，不需要 Remodex relay、匹配码、SDK 或守护进程。

Codex 续聊出现会话写入占用错误时，电脑返回失败运行及 `resume_conflict: {process, continuation}`，不再自动新建会话。`process` 尽可能提供进程名和 PID，无法查询时为空。iOS 提供「取消」和「新建会话」：取消保留问题草稿，新建立即替换当前聊天页面，并在同一工作区启动新运行。第一条消息是电脑返回的完整 `Continuing… Last exchange… Now…` 文本，只展示一次，并沿用完全匹配切换到历史。上下文取最后两条可读消息，每条最多 800 个字符，不是模型生成的摘要或完整历史。仅打开锁文件不会被认定为写入占用。Codex 的 `thread/resume` 错误 `already has an active writer` 也会识别为占用，即使 CLI 只通过 stderr 返回错误。

排查续聊时，电脑插件和 iOS App 都需要更新。PC 开发环境的 `npm run start` 只重新编译 Electron 外壳：先编译插件，退出桌面版，在 `harness/desktop` 执行 `npm run prepare-dsh`，再启动。已安装的桌面版需要重新打包安装。电脑本地日志中的 `coding diagnostic` 和 `coding-resume-v2` 记录每次尝试的结果、失败分类和会话标识，不记录提示词或原始 CLI 错误。iOS 在「设置 → 日志」开启日志后复现，再打开当天的日志。`NanoMuseCoding` 记录返回结果是否包含占用信息、弹框选择，以及完成后的实时提示词是否完全匹配新历史用户消息。日志只记录文本长度，不记录聊天正文。反馈时只提供相关条目，其他日志类别可能包含私人数据。

iOS 的历史和实时回复都将同一轮工具调用默认折叠为回复顶部的一项汇总，展开后才显示各次调用。文件变更仍显示在最终回复下方：点击具体文件直接打开该文件的行级 diff，点击整体变更入口则查看输入、输出和文件列表。diff 使用同时支持横向和纵向滚动的区域，长代码行可横向查看，仅在记录包含行号时保留紧凑行号栏。「项目 / 聊天」与上方助手筛选项使用相同的胶囊样式。文件 diff 首次打开时从行左侧开始，加载更多时保留当前滚动位置。增删代码行使用明显的绿色、红色底色，行号采用对应颜色，左侧显示亮色标记条。缺少行号的 patch 也保留底色和标记条。

iOS 切换电脑时，会在新列表加载期间隐藏上一台电脑的项目和会话。已打开的对话仍绑定原来的目标设备。如果历史、输出或差异页面加载失败，可点击「刷新」从最新版本的第一页重新读取，不会混合内容变更前后的分页。

iOS 编程助手分为「项目」和「聊天」，项目会话按电脑上的目录聚合，可选择已安装的助手在项目下新建会话。配色和 Markdown 渲染沿用 nanoMuse。工具记录可以展开查看输出和文件变更行数，进入「执行详情」查看输入和分页输出，再进入文件查看该次工具调用留下的 patch。记录缺少 patch、行数或行号时不会推测，也不会把工作区当前的 Git diff 当作历史变更。

「项目 / 聊天」切换位于「最近的会话」紧上方。会话全屏打开，滚动不会关闭页面。工具折叠时仍显示文件变更入口，同一轮的文件变更也会汇总到最后一条助手回复下方。点击具体文件直接查看已记录的 diff，整体入口保留执行详情。尚未加载的旧记录需先向上加载，才会出现在汇总中。Codex 标题优先读取只读 `state_*.sqlite` 中保存的会话名称，其次读取 `session_index.jsonl`，都没有时才使用第一条实际用户消息。注入的 `AGENTS.md` 指令不会作为聊天消息或备用标题显示。

Python 运行时与桌面插件提供相同的协议。这是编程子协议 2 的增量扩展，不改变 Hub 帧版本。旧客户端继续读取 `transcript`，iOS 连接旧电脑时退回纯文本。

| 指令 | 参数 | 返回 |
|---|---|---|
| `coding.agents` | `fresh?` | `protocol_version: 2`，各助手的 `capabilities` |
| `coding.sessions` | `protocol_version: 2, agent?, workspace?, scope?, limit?, cursor?` | 会话、版本、下一页游标、总数、`bounded` |
| `coding.projects` | 无 | 已知项目目录、ID、助手 ID 和更新时间 |
| `coding.project.validate` | `workspace` | 验证绝对目录存在，不返回文件内容 |
| `coding.session` | `agent, session_id, protocol_version: 2, limit?, cursor?, tail?` | 会话元数据、`timeline`、分页信息和关联运行，不重复传输 `transcript` |
| `coding.item` | `agent, session_id, item_id, run_id?, limit?, cursor?` | 工具记录、输入、分页输出、`source_truncated` |
| `coding.diff` | `agent, session_id, diff_reference, run_id?, limit?, cursor?` | 分页 patch、文件路径和 `diff_scope: item` |
| `coding.watch` | `agent, session_id, version?, run_id?` | 快照是否变化、版本、状态和关联运行 |
| `coding.send` | 原参数加 `scope?, request_id?, protocol_version?` | 原运行结构，加结构化 `item` 事件和有界时间线 |

时间线记录包含稳定 `id`、`turn_id`、`sequence`、`revision`、`role`、`kind`、`text`、`status`。类型包括消息、命令、工具和文件变更。命令展示真实 `display_command` 和 `cwd`，记录提供时才有退出码、耗时。工具预览包含输入、输出预览和截断标记，文件包含路径、可选行数和不透明的 `diff_reference`。同一工具的新版本替换旧记录，不重复追加。Codex 原始 patch 和 Claude Edit 输入没有原始行号，只有标准 unified hunk 才显示行号。

历史分页最多 200 条，输出和 diff 每页最多 32,768 个字符，单个工具输出保留最多 262,144 个字符并标记截断。内容变化使游标失效，返回 `stale_cursor`，格式错误返回 `invalid_cursor`，应从头刷新，不混合不同版本的页。会话发现扫描最近 500 条，到达上限时返回 `bounded`；iOS 每次加载 100 条，可以搜索和继续加载。聊天通过 `tail: true` 先加载最近 100 条，再按时间顺序向上加载旧记录。

新会话传 `scope: chats` 时，在电脑的 `~/Documents/nanoMuse/Chats/` 下创建独立目录；已知 Codex 非项目目录也归为聊天，其余目录归为项目。发送和停止仍通过现有远程控制与 Sentinel 权限检查。工具和 diff 只解析指定会话或其 nanoMuse 运行中的引用，不接受任意文件路径。目录验证不绕过发送权限。

相同 `request_id` 的并发发送只启动一次，不同内容复用同一 ID 返回 `request_conflict`。完成运行在现有 50 条保留范围内跨重启去重。iOS 使用 `wait: false`，电脑端完成权限检查后立即返回运行 ID，再每三秒查询这次运行的快照。运行期间和新会话尚未获得会话 ID 时也会查询，完成、失败和停止状态来自关联运行，不再依赖长时间等待的发送请求。旧电脑通过 `coding.runs` 跟踪。断线后不会自动重发消息，关闭会话后结束轮询，历史更新不会强制滚动。

一旦观察到工具开始执行或返回结果，恢复会话的运行失败后就保留失败状态。错误中出现「not found」也不会自动新建会话重做这次任务。

发送等待电脑授权时会返回 `authorization` 事件，iOS 显示等待授权状态，发送失败时保留电脑返回的具体错误。未开启远程控制时，需要在桌面端允许请求卡片，或者先信任这台手机。Agent 返回终止性错误后，即使后台进程仍持有输出管道或退出码为零，也会结束为失败，不继续空等。

当前兼容级适配器支持浏览 Codex、Claude Code、Cursor 和 dsh，并控制 nanoMuse 发起的 CLI 运行。**尚未接管外部正在运行的 Agent，也未提供原生审批**：`control_external_run`、`approve` 和任意 `file` 能力为 false。独立的 Codex app-server 富控制适配器不属于本阶段。Cursor IDE 会话保留「在同一工作区继续为新会话」行为。

`device` 用于指定另一台电脑。请求会转换为 hub 动作：`coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs`，见 [hub.md](hub.md)。

`coding.send` 带上 `wait` 时，会持续接收目标电脑消息总线中的运行事件，将每一步作为 `event` 帧转发。帧的内容包含运行 id，调用方可用它发出 `coding.stop`。任务结束后，`result` 帧返回完整的运行结果。

测试位于 `tests/test_coding.py`，涵盖用固定聊天样本读取记录、统一不同助手的输出格式、模拟 CLI 及 API。hub 通信路径由 `tests/test_hub.py` 测试；桌面版的对应实现用相同方式测试，文件为 `harness/dsh-nanomuse/tests/coding.test.mjs`。
