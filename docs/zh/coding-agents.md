# 编程助手

Android 的编程智能体筛选项支持横向滚动，名称保持单行显示，并标明运行中、已安装或未安装。未安装的智能体仍可筛选，方便查看它留下的历史会话。

## iOS 结构化浏览，协议 2

Codex 续聊出现会话写入占用错误时，电脑返回失败运行及
`resume_conflict: {process, continuation}`，不再自动新建会话。
`process` 尽可能提供进程名和 PID，无法查询时为空。
iOS 提供「取消」和「新建会话」：取消保留问题草稿，新建立即替换当前聊天页面，
在同一工作区启动新运行。第一条消息就是电脑返回的完整
`Continuing… Last exchange… Now…` 文本，只展示一次，并沿用完全匹配切换到历史。
上下文取最后两条可读消息，每条最多 800 个字符，不是模型生成的摘要或完整历史。
仅打开锁文件不会被认定为写入占用。
Codex 的 `thread/resume` 错误 `already has an active writer` 也会识别为占用，
即使 CLI 只通过 stderr 返回错误。

排查续聊时，电脑插件和 iOS App 都需要更新。PC 开发环境的 `npm run start`
只重新编译 Electron 外壳：先编译插件，退出桌面版，在 `harness/desktop` 执行
`npm run prepare-dsh`，再启动。已安装的桌面版需要重新打包安装。
电脑本地日志中的 `coding diagnostic` 和 `coding-resume-v2` 记录每次尝试的结果、
失败分类和会话标识，不记录提示词或原始 CLI 错误。
iOS 在「设置 → 日志」开启日志后复现，再打开当天的日志。
`NanoMuseCoding` 记录返回结果是否包含占用信息、弹框选择，
以及完成后的实时提示词是否完全匹配新历史用户消息。日志只记录文本长度，
不记录聊天正文。反馈时只提供相关条目，其他日志类别可能包含私人数据。

iOS 的历史和实时回复都将同一轮工具调用默认折叠为回复顶部的一项汇总，
展开后才显示各次调用。文件变更仍显示在最终回复下方：点击具体文件直接
打开该文件的行级 diff，点击整体变更入口则查看输入、输出和文件列表。
diff 使用同时支持横向和纵向滚动的区域，长代码行可横向查看，
仅在记录包含行号时保留紧凑行号栏。「项目 / 聊天」与上方助手筛选项
使用相同的胶囊样式。
文件 diff 首次打开时从行左侧开始，加载更多时保留当前滚动位置。
增删代码行使用明显的绿色、红色底色，行号采用对应颜色，左侧显示亮色标记条。
缺少行号的 patch 也保留底色和标记条。

iOS 编程助手分为「项目」和「聊天」，项目会话按电脑上的目录聚合，
可选择已安装的助手在项目下新建会话。配色和 Markdown 渲染沿用 nanoMuse。
工具记录可以展开查看输出和文件变更行数，进入「执行详情」查看输入和分页输出，
再进入文件查看该次工具调用留下的 patch。记录缺少 patch、行数或行号时不会推测，
也不会把工作区当前的 Git diff 当作历史变更。

「项目 / 聊天」切换位于「最近的会话」紧上方。会话全屏打开，滚动不会关闭页面。
工具折叠时仍显示文件变更入口，同一轮的文件变更也会汇总到最后一条助手回复下方。
点击具体文件直接查看已记录的 diff，整体入口保留执行详情。尚未加载的旧记录需先向上加载，
才会出现在汇总中。Codex 标题优先读取只读 `state_*.sqlite` 中保存的会话名称，
其次读取 `session_index.jsonl`，都没有时才使用第一条实际用户消息。
注入的 `AGENTS.md` 指令不会作为聊天消息或备用标题显示。

Python 运行时与桌面插件提供相同的协议。所有跨设备数据仍通过 nanoMuse Hub，
无需 Remodex relay、匹配码、SDK 或守护进程。这是编程子协议 2 的增量扩展，
不改变 Hub 帧版本。旧客户端继续读取 `transcript`，iOS 连接旧电脑时退回纯文本。

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

时间线记录包含稳定 `id`、`turn_id`、`sequence`、`revision`、`role`、`kind`、
`text`、`status`。类型包括消息、命令、工具和文件变更。
命令展示真实 `display_command` 和 `cwd`，记录提供时才有退出码、耗时。
工具预览包含输入、输出预览和截断标记，文件包含路径、可选行数和不透明的
`diff_reference`。同一工具的新版本替换旧记录，不重复追加。
Codex 原始 patch 和 Claude Edit 输入没有原始行号，只有标准 unified hunk 才显示行号。

历史分页最多 200 条，输出和 diff 每页最多 32,768 个字符，单个工具输出保留
最多 262,144 个字符并标记截断。内容变化使游标失效，返回 `stale_cursor`，
格式错误返回 `invalid_cursor`，应从头刷新，不混合不同版本的页。
会话发现扫描最近 500 条，到达上限时返回 `bounded`；iOS 每次加载 100 条，
可以搜索和继续加载。聊天通过 `tail: true` 先加载最近 100 条，再按时间顺序向上加载旧记录。

新会话传 `scope: chats` 时，在电脑的 `~/Documents/nanoMuse/Chats/` 下创建
独立目录；已知 Codex 非项目目录也归为聊天，其余目录归为项目。
发送和停止仍通过现有远程控制与 Sentinel 权限检查。工具和 diff 只解析
指定会话或其 nanoMuse 运行中的引用，不接受任意文件路径。目录验证不绕过发送权限。

相同 `request_id` 的并发发送只启动一次，不同内容复用同一 ID 返回
`request_conflict`。完成运行在现有 50 条保留范围内跨重启去重。
iOS 使用 `wait: false`，电脑端完成权限检查后立即返回运行 ID，再每三秒查询
这次运行的快照。运行期间和新会话尚未获得会话 ID 时也会查询，完成、失败和
停止状态来自关联运行，不再依赖长时间等待的发送请求。旧电脑通过 `coding.runs`
跟踪。断线后不会自动重发消息，关闭会话后结束轮询，历史更新不会强制滚动。

发送等待电脑授权时会返回 `authorization` 事件，iOS 显示等待授权状态，
发送失败时保留电脑返回的具体错误。未开启远程控制时，需要在桌面端允许
请求卡片，或者先信任这台手机。Agent 返回终止性错误后，即使后台进程仍持有
输出管道或退出码为零，也会结束为失败，不继续空等。

当前兼容级适配器支持浏览 Codex、Claude Code、Cursor 和 dsh，并控制
nanoMuse 发起的 CLI 运行。**尚未接管外部正在运行的 Agent，也未提供原生审批**：
`control_external_run`、`approve` 和任意 `file` 能力为 false。
独立的 Codex app-server 富控制适配器不属于本阶段。
Cursor IDE 会话保留「在同一工作区继续为新会话」行为。

你电脑上的 Cursor、Codex、Claude Code 和 DeepSeek Harness 会话，从你账号下的任何一台设备都能看、能指挥（回家路上的手机、浏览器、另一台电脑），也能由 Muse 自己来做。

什么都不装进这些助手里，什么都不经过谁的服务器中转。电脑上的运行时或桌面版读取助手留在磁盘上的东西，有新消息时启动它们自己的命令行界面，再把返回的内容流式传回来。另一台设备通过 hub（设备互联）发出请求；hub 只负责传帧。

Windows 上的进程检测会按控制台编码读取非 UTF-8 的命令输出，带重音字符的进程名不会再导致编程助手列表加载失败。

桌面版会完整保留编程助手输出中的中文和其他 UTF-8 字符，即使同一个字符分几次从管道读入，或最后一行没有换行符，也不会因此变成乱码。

## 在 App 里 {#in-the-apps}

编程智能体无法恢复已保存的会话时，会在新会话中重试，并从新输出开始展示。失败尝试中尚未输出完整的一行也会随旧输出一并清除。

- **手机**：抽屉里的「编程助手」一行（或「设置 → 编程助手」，或 `nanomuse://coding` 链接）。选一台电脑、一个助手、一个会话；读记录；输入一条消息，看着它跑（文字一边生成一边显示，工具一个个被调用），跑偏了就停掉。
- **网页版**：「编程助手」页面。这台电脑上的助手在最上面，账号下其他电脑的排在后面。
- **桌面版**：「设置 → 编程助手」，也可以从「设置 → 设备」里设备卡片上的「编程助手」标签打开。先是这台电脑（每个助手的版本、此刻在跑的进程数和它的聊天），再是账号下的其他电脑；一个助手的聊天列表、一个聊天的记录、输入框、边跑边显示的运行（文字和工具）和一个「停止」按钮。一个都没装的电脑会如实说明。
- **Muse**：直接问它（「我上次让 Cursor 做了什么？」「让 api 仓库里的 Codex 给解析器加一个测试」），它会用 `coding_agents` 工具，读的是同一套只读读取器，跑的是同一个运行器，在这台电脑上，或者带上 `device`，在另一台上。

只有在 hub 上声明了 `coding.*` 动作的电脑才会出现：跑着运行时的，或装了桌面版的（桌面版同样声明这些动作）；手机永远不会。

桌面版查看另一台电脑上的编程任务时，工具次数按执行端的规则统计：Codex 在工具完成时计数，其他助手在工具开始时计数，说明性消息不计入。最终结果会带回执行端的次数，补正可能因事件丢失造成的差异。

## 读的是什么 {#what-is-read}

| 助手 | 磁盘上的会话 | 启动命令 |
|---|---|---|
| Cursor | `~/.cursor/projects/<workspace-slug>/agent-transcripts/<id>/<id>.jsonl`；CLI 聊天另有 `~/.cursor/chats/<hash>/<id>/meta.json`（里面的 `cwd`） | `cursor-agent -p --output-format stream-json --stream-partial-output --force [--resume <id>] [--workspace <dir>] "<text>"` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl` | `codex exec [resume <id>] --json --skip-git-repo-check -c sandbox_mode="workspace-write" [-C <dir>] "<text>"` |
| Claude Code | `~/.claude/projects/<workspace-slug>/<id>.jsonl` | `claude -p --output-format stream-json --verbose --permission-mode acceptEdits [--resume <id>] "<text>"` |
| dsh（DeepSeek Harness） | `~/.dsh/sessions/<workspace-slug>/<id>/session.v4.jsonl.zstd` | `dsh --profile headless --json [--session-id <id>] "<text>"` |

读取是尽力而为：解析不了的一行跳过，目录不存在就当这个助手没有会话。`~` 是用户的主目录，除非 `NANOMUSE_CODING_HOME` 指向了别的目录（比如一个把宿主机的 CLI 主目录挂到别处的容器，或者一个测试）。一个会话列出它的助手、id、标题（Codex 优先使用保存的名称，否则使用第一条实际用户消息）、工作区、时间戳、消息数、最后一轮对话，以及是否 `resumable`。Cursor 的 IDE 聊天能读但不能从 CLI 续上（`resumable: false`，`source: "ide"`）：发给它的消息会直接作为一个新的 CLI 聊天在同一个工作区里发出，引用旧聊天的标题和最后一轮对话，运行结果写明 `resumed: false`；App 会在输入框上方说明这一点。当一个被存储标为可续的聊天在 CLI 那里查无此号时，走的也是同样的回退。

dsh 就是 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)：`dsh web` 和 DeepSeek 自己的桌面应用里的聊天，存在 `~/.dsh` 下。运行时和 nanoMuse 桌面版都能读取并驱动它们；运行时用它的依赖 `zstandard` 读取这个存储。nanoMuse 桌面版自己的聊天存在它自己的目录里，不在其中。

dsh 的存储有两点要说明：它是 **zstd** 压缩的，而且是随着会话写入**一帧帧追加**的，所以只解压一次会在第一帧结束处停下，长聊天会丢掉开头几行之后的所有内容。因此会一帧接一帧地读到文件末尾；最后一帧如果正写到一半，只丢掉这一帧。另有两种会话不是人聊过的对话，会被排除：`source.kind` 不是 `user` 的 `user/message`（运行时上下文、技能目录、后台任务通知都是以这种方式到达的），以及 header 里写着 `origin: "subagent"` 或带有 `parentSession` 的会话。

dsh 也是唯一不只从 `PATH` 上找命令行的助手：桌面版把 harness 打包在自己里面（`…/Resources/dsh/`），以 `node …/dsh/lib/bin.js <profile>` 启动，所以装了桌面版的电脑有 dsh 会话，`PATH` 上却没有 `dsh`。因此桌面版插件会回退到它自己正运行在其中的那个 harness（用它自己命令行里的入口），并通过 node 启动它。`PATH` 上装好的 `dsh` 仍然优先使用，和其他三个一样。这个回退只用于发送消息：只有 `PATH` 上有 `dsh` 或者 `~/.dsh` 存在时，dsh 才算已安装，没人用过它的电脑不会多列出一个助手。无论哪种，运行时（`nanomuse serve`）上也一样，这次运行都带上 `DSH_HOME=~/.dsh`：桌面版给它自己运行的 harness 设置的 `DSH_HOME` 指向它自己的目录，在那里运行既找不到要续上的聊天，新建的聊天也不会出现在列表里。

助手的 `running` 是它此刻还活着的进程数，Linux 上读 `/proc`，macOS 上用 `ps`，Windows 上用 `tasklist`（外加 `node.exe` 的命令行，因为 Cursor CLI 是随 node 打包的）；从不使用 `pgrep -f`，而且每两秒最多读一次。

运行器在助手的终止事件到达时就停止读取，而不是等到管道 EOF：`cursor-agent` 回答完之后会留一个 worker 服务器跑着，否则这次运行会被永远挂住。随后等待该进程，宽限期过后将其杀掉。

Python 运行时按工作区列出会话时，会先核对记录中的工作区，再限制返回数量。其他项目
里更新的聊天不会挤掉这个工作区的历史。不同路径可能对应同一个存储目录名，因此以
会话记录中的工作区为准，不根据目录名猜测归属。

## 在哪里跑 {#where-it-runs}

每个助手都以它在那台电脑上拥有的权限运行（Codex 在 `workspace-write` 下，Claude Code 带 `acceptEdits`，Cursor 带 `--force`，dsh headless 按它自己的沙箱策略），并且在那里改文件。所以发一条消息被当作在那台电脑上运行一条命令来对待：对哨兵来说 `coding_agents send` 是 `sensitive`，和 `shell` 同级（`ask` 模式下卡片会写明助手、文件夹和消息）；请求只在同一个账号的设备之间传递，走该账号自己的 hub 会话，而且那台电脑可以完全拒绝远程控制（「远程控制」关掉后，`coding.*` 只在本机可用）。在桌面版上，`coding.send` 和 `coding.stop` 过的是和 `shell`、`files` 同一道关：「远程控制」关着时，尚未信任的设备会在屏幕上弹出一张卡片，由回答（这一次、总是、不行，或没人及时回答）决定；只读动作直接应答，不问。

助手自己的 API key 和登录状态是它们自己的；nanoMuse 从不接触。记录是从磁盘读出来给你看的；除了发起请求的那台设备，不会发给任何地方。

## API {#the-api}

在运行时（`nanomuse serve`）上，需要 App 令牌：

```
GET  /api/coding                                  → {agents: [{id, name, installed, cli, version, sessions_root, running}], runs: […]}
GET  /api/coding/sessions?agent=&limit=&device=   → {sessions: [{agent, id, title, workspace, path, created_at, updated_at, messages, status, last_user, last_assistant, source, resumable}]}
GET  /api/coding/sessions/{agent}/{id}?device=    → the session with transcript: [{role, text}]
POST /api/coding/send    {agent, text, session_id?, workspace?, device?}  → the run
POST /api/coding/stop    {run, device?}
```

一次运行是 `{id, agent, session_id, asked_session_id, workspace, text, started_at, ended_at, status, output, resumed, error, tools, device?}`；`status` 是 `running`、`done`、`failed` 或 `stopped` 之一。最近 50 次已结束的运行保存在 `<data_dir>/coding/runs.json`，运行时启动时读回来，所以记录能挺过重启；当时还在跑的运行回来时变成 `stopped`，并附一句说明（CLI 进程随运行时一起结束了）。运行期间，总线上传递 `{"kind": "coding", "run": id, …}` 事件，每个打开的 App 都实时跟着：`started {session_id, model}`、`text {text, partial}`（Cursor 先发增量，再发整条消息；App 用最终那条替换掉流式显示的文字）、`tool {text, phase}`、`done`、`error`。

桌面版把同样的数据形状提供给它自己的窗口，路径在 `nanomuse/cloud/coding` 下（页面的本机回环 API）：`GET`（助手和运行记录）、`GET /sessions`、`GET /sessions/{agent}/{id}`、`POST /send`、`POST /stop`，以及 `GET /events`，上面那些运行事件的服务器推送流。它的 `runs.json` 放在插件数据目录的 `coding/` 下。

## 经由 hub {#over-the-hub}

`device` 指定另一台电脑；同样的请求以 hub 动作传递（`coding.agents`、`coding.sessions`、`coding.session`、`coding.send`、`coding.stop`、`coding.runs`；见 [hub.md](hub.md)）。带 `wait` 的 `coding.send` 跟着目标机总线上的这次运行，把每一步作为 `event` 帧转发，帧体带运行 id，所以调用方可以 `coding.stop` 它；`result` 帧是结束后的运行。

测试在 `tests/test_coding.py`（基于固定记录样本的读取器、流规范化、一个假 CLI、API），hub 这条路径在 `tests/test_hub.py`；桌面版的移植以同样的方式测试，在 `harness/dsh-nanomuse/tests/coding.test.mjs`。
