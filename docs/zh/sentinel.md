# 哨兵（Sentinel）

Meta 对 Muse 安全机制的描述是：模型与工具之间有独立的 Sentinel 智能体，负责审批敏感操作、隔离凭据并记录执行过程。nanoMuse 也将提出操作和执行检查分开。智能体不会自行执行工具，而是把调用交给 `Sentinel.guard()`。这里的审批，是让你决定是否允许具体操作：

```
agent ──► Sentinel.guard() ──► policy ──► approval (if needed) ──► vault.resolve ──► execute
agent ◄── redact(result)   ◄── taint bookkeeping ◄─────────────────────────────────────┘
```

相关代码为 `nanomuse/sentinel/gate.py`，负责执行检查；`policy.py`，负责决策；`audit.py`，负责日志。凭据保险库位于 `nanomuse/vault/`。

## 风险级别 {#risk-levels}

每个工具通过 `risk` 声明基础风险级别：

| 级别 | 含义 | 示例 |
|---|---|---|
| `safe` | 本地、可撤销的操作 | `files`，限工作区内；`goals`、`reminders`、`triggers` 的列表、查看和目标计划逐步进度记录；`contacts` 的查找、查看、列表；`skills` 的列表和使用；`phone_screen`、`computer_screen` |
| `moderate` | 访问外部服务或改变状态 | `web_fetch`；会向搜索服务发送查询的 `web_search`；`python_execute`、`read_emails`、`browser`；会影响后续各轮任务的 `remember`、`forget`；`contacts` 的添加和删除；`phone_act`；`goals`、`reminders`、`triggers` 的创建、取消，以及目标的 `set_status`、`update`。创建会设立模型日后自主执行的长期工作，因此 `strict` 模式会在创建前询问；取消或更新则会改变、停止这些工作 |
| `sensitive` | 难以撤销，或会在外部产生可见影响 | `shell`、`send_email`；`skills` 的保存和删除。技能会成为模型日后遵循的指令，因此写入技能始终需要询问 |

工具还可以通过 `assess()` 提高某次调用的风险：

- `shell` 发现 `rm -rf`、`sudo`、`curl | sh` 等命令模式时会附加警告。
- `python_execute` 在有效沙箱中进行纯计算或访问工作区文件时为 `moderate`。如果没有沙箱，例如 macOS、Windows 或未安装 bubblewrap 的 Linux，则所有脚本都为 `sensitive`，因为此时只有静态代码检查。即使沙箱有效，只要代码访问网络、启动其他程序、读取环境变量、删除文件或访问工作区外路径，也会升为 `sensitive`，并在审批卡片上说明原因。
- `web_fetch` 会直接拒绝私有地址和回环地址，每一次重定向都重新检查。
- `phone_act` 会检查点击动作的 `label`，即操作器对点击目标的文字描述。包含「确认支付」「转账」「提交订单」「发送」「删除」或 `[gui] sensitive_words` 中其他词语时，会升为 `sensitive` 并附带警告。一次动作同时输入和提交时也如此。没有 `label` 的点击会另外警告，见 [gui.md](gui.md)。

工具还会声明 `reads_private_data`，表示调用会读取私密数据并将对话标为已污染；`egress` 表示会向外发送数据；可选的 `egress_target` 给出发送目的地。网络调用的目的地通常是主机名，`shell` 和 `python_execute` 无法确定，手机操作则使用 App ID。这些信息用于污染追踪，也就是在接触私密数据后检查数据可能流向哪里。

`shell` 和 `python_execute` 启动子进程前，会移除可能含凭据的环境变量。包括名称匹配 `*KEY*`、`*TOKEN*`、`*SECRET*`、`*PASSW*`、`*CREDENTIAL*`、`*AUTH*`、`*COOKIE*`、`*SESSION*` 的变量；所有以 `NANOMUSE_`、`AWS_`、`AZURE_`、`GOOGLE_`、`GH_`、`GITHUB_`、`NPM_` 开头的变量；以及 `SSH_AUTH_SOCK`。因此，模型生成的代码无法从 `os.environ` 读取模型自己的 API key 或保险库密钥。API 是程序调用接口，key 是访问服务的密钥。这两个工具也不接受 `{{vault:NAME}}` 占位符，命令带占位符时会被拒绝并说明原因。保险库的真实值只交给已配置使用它们的连接器。编程 CLI，即 `coding_tool` 中的 Codex、Claude Code、Cursor，使用同样清理后的环境，但会补入各自账号变量：`OPENAI_*` / `CODEX_*`、`ANTHROPIC_*` / `CLAUDE_*`、`CURSOR_*`；当 `CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` 指定使用云服务时，也会补入所需云凭据。其他运行时环境变量不会传入。

递归强制删除警告既识别 `rm -rf` 这样的组合参数，也识别 `rm -r -f`、`rm --recursive --force` 这样的分开参数。后续命令的参数、其他长选项或 `--` 后的文件名不会被拼成这一组合。检查危险模式前，会先拼接反斜杠紧接换行的续行，包括被拆开的命令名或参数。审批卡片和实际执行仍使用原始命令。这些检查用于识别常见命令模式，不能覆盖所有 shell 程序；引号中的字面文本也可能触发警告。

`Path(...).rmdir()` 与 `Path(...).unlink()`、`os.rmdir()` 一样会触发删除警告。即使沙箱正常工作，这类 Python 调用也会升为 `sensitive`；已有的长期授权不能跳过警告。


## 沙箱 {#the-sandbox}

沙箱是限制程序可访问的文件、网络和系统资源的隔离环境。Meta Muse 为每个用户的智能体提供独立 VM（虚拟机）。nanoMuse 运行在你的机器上，在 Linux 上通过 [bubblewrap](https://github.com/containers/bubblewrap) 为每次 `shell` 和 `python_execute` 调用创建独立命名空间。命名空间是 Linux 隔离进程资源视图的机制。bubblewrap 也是 Flatpak 使用的隔离工具，无需特权，可通过 `apt install bubblewrap` 或 `dnf install bubblewrap` 安装。沙箱中的规则如下：

- 只有工作区及 `agent.extra_roots` 可写。`/usr`、`/etc`、`/opt`、`/var` 为只读；`/tmp` 仅属于当前调用；`/proc` 和 `/dev` 单独创建。
- 默认看不到你的主目录，因此也看不到保险库、数据目录、SSH 密钥、云凭据和浏览器配置。例外包括：以只读方式提供的当前 Python 所在目录，因为 venv 或 `uv` 管理的解释器常位于主目录中，这样 `python_execute` 可以使用与 nanoMuse 相同的解释器和包；以只读方式提供的内置及用户技能目录，供脚本和参考资料使用；以及你明确共享的目录。`[sandbox] share_read_only` 用于程序，例如装有 Node 和飞书 CLI 的 `~/.nvm`；`share` 用于工具需要写入的状态，例如登录目录 `~/.lark-cli`、`~/.local/share/lark-cli`。主目录下的共享目录会映射到沙箱自身 `$HOME` 下的相同位置，方便工具查找，其余主目录内容仍不可见。若数据目录位于工作区内，也会被遮蔽。
- 默认没有外网连接，只有被评估为需要网络的调用才开放。`shell` 运行 `curl`、`wget`、`pip`、`git`、`ssh`、`npm`、`docker` 等网络程序，命令含 URL 或主机名，或明确指定 `network=true` 时，会被视为需要网络。`python_execute` 导入 `requests`、`httpx`、`socket`、`urllib` 等网络模块，或启动其他程序时也如此。其余调用仅有回环接口。因缺少网络而失败时，结果会附带说明；模型可以加 `network=true` 重试，但这会被视为向外发送数据的调用，重新接受检查。
- 进程树、IPC、UTS 和 cgroup 使用独立命名空间。它们分别涉及进程可见范围、进程间通信、主机名称和资源分组。`HOME`、`TMPDIR` 指向私有 `/tmp`，并设置 `NANOMUSE_SANDBOX=bwrap`，供脚本判断运行环境。

沙箱也改变了 `shell` 的外发判定。没有沙箱时，每条 shell 命令都可能访问网络，因此读取私密数据后的调用会询问；有沙箱时，只有获准使用网络的命令才视为外发。例如读完邮件后，在断网沙箱中运行 `ls` 无法发送数据，因此不会因污染规则而询问。但它仍属于 `sensitive`，在 `ask` 模式下仍与其他 shell 命令一样需要审批。

`[sandbox] mode` 有三种值：`auto` 为默认值，bubblewrap 已安装且能创建命名空间时使用；`bwrap` 表示必须使用，无法创建时 `nanomuse doctor` 失败并在日志中说明原因；`off` 表示关闭。macOS、Windows 和多数 Docker 容器中无法运行 bubblewrap。Docker 默认 seccomp 规则会阻止非特权用户命名空间，而容器本身已经提供隔离。在这些环境中，命令仍使用清理后的环境变量，并以工作区为当前目录运行；设置 → 安全会说明实际情况。`nanomuse doctor` 会显示沙箱状态，设置 API 在 `sandbox` 字段中返回同样信息。

**Ubuntu 24.04 及其衍生版**通过 AppArmor 限制非特权用户命名空间。开启 `kernel.apparmor_restrict_unprivileged_userns=1` 后，没有专用 AppArmor 配置的程序创建的命名空间不能获得 capabilities，即额外系统权限。这可能使 bubblewrap 直接报 `bwrap: setting up uid map: Permission denied`，也可能允许文件隔离却无法建立网络命名空间，报 `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`。后一种情况下，nanoMuse 保留文件系统隔离，放弃网络隔离，状态行显示「网络未被阻断」，并将每条 `shell` 命令都视为可能联网。两种情况都可以通过安装 `/usr/bin/bwrap` 的标准 AppArmor 配置解决。Ubuntu 25.04 的 `apparmor` 自带该配置，24.04 则放在 `apparmor-profiles` 中，因为此前 Flatpak 回归问题使其被移出默认配置集：

```bash
sudo apt install apparmor-profiles
sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
```

`nanomuse doctor` 会识别并说明这种情况。也可以通过 `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` 关闭限制，但这会降低整台机器的防护。

## 决策顺序 {#decision-order}

每次工具调用，先按第 1 至第 4 步检查，首个匹配项决定初步结果。随后第 5、6 步会继续检查，并可能要求审批；即使当前模式通常跳过询问，也不会自动放行这类审批。

1. **`deny_tools`**：拒绝调用。
2. **`[[sentinel.rules]]`**：根据 `tool` 和 `match` 匹配规则。`tool` 使用 glob 通配模式，`*` 表示任意工具；`match` 是「参数名 → glob 模式」映射，对 `str(value)` 进行匹配。第一条匹配规则的 `action` 生效。
3. **`always_allow_tools` / `always_ask_tools`**：按始终允许或始终询问配置处理。
4. **风险级别与模式**：前面都不匹配时，使用下表。

| 模式 | `safe` | `moderate` | `sensitive` |
|---|---|---|---|
| `ask`（默认） | 允许 | 允许 | 询问 |
| `strict` | 允许 | 询问 | 询问 |
| `auto` | 允许 | 允许 | 允许 |

5. **污染检查**：当前对话已经读取私密数据，且调用会向 `egress_allowlist` 之外或无法确定的目的地发送数据时，需要询问。前面的模式、`always_allow_tools`、`always_ask_tools` 或规则都不能免除这项检查。目的地已知时，审批卡片会显示它。
6. **警告检查**：包含 `rm -rf`、`sudo`、`curl | sh`，或读取环境变量、删除文件等代码的调用，不会仅因模式或 `always_allow_tools` 而放行，仍需询问。只有明确的 `allow` 规则能覆盖警告。

`auto` 仍遵守 `deny_tools`、拒绝规则以及第 5、6 步。污染规则在所有模式下都生效：对话读取邮件、日历、联系人等私密来源后，向 `egress_allowlist` 外发送数据必须询问，`auto` 也不例外。`nanomuse daemon`、`--auto`、App 的「放手」设置和后台目标检查使用此模式，因此无人值守任务遇到危险命令或涉及私密数据的外发时，会在「动态」中生成审批卡片。`nanomuse daemon` 没有用户界面可供当场回答，仍需审批的步骤会被拒绝并附上说明，模型则继续处理其他可做的部分。

## 审批 {#approvals}

决定为询问时，控制台或 App 审批卡片会显示工具、调用摘要、引发这次操作的用户请求，即「目的」、完整参数、风险级别和原因。你可以拒绝，也可以选择授权范围：

| 回答 | 效果 |
|---|---|
| 拒绝 | 不运行工具，模型收到「Sentinel blocked」结果，并被告知不要重复尝试同一次调用 |
| 允许一次 | 仅允许当前调用，不保存授权 |
| 本次对话都允许 | 对发起调用的聊天持续有效，覆盖后续各轮，清空或删除聊天后结束，重启后不保留。这与手机 App 原有的中间授权范围相同。对于 `shell`，覆盖整个工具，不仅是当前命令中的程序。`nanomuse run` 或定时任务等聊天之外的运行，各自视为独立对话 |
| 直到重启 | 保留至进程退出 |
| 24 小时 | 带过期时间保存到 `<data_dir>/approvals.json` |
| 总是允许 | 持久保留，直到你撤销 |

每项授权都对应明确的**授权键**，由工具和目标共同组成，例如 `web_fetch:example.com`、`send_email:alice@example.com`、`shell:git`、`browser:booking.com`。本次会话允许 `git` 不代表允许 `curl`；`git status | head` 这样的管道中，每个程序都需要授权，批准时会分别授予；邮件发给两人时，也要覆盖两个收件人。

`shell` 的「本次对话都允许」是特例。因为任务使用 `git` 后通常还会调用 `ls`、`wc` 等程序，这个选项会覆盖当前对话剩余时间内的整个 shell 工具。但收件人、主机等目的地仍按目标限定。没有明确目标的工具，例如 `python_execute` 和 MCP 工具，则按整个工具授权。对于可联网的任意代码，哨兵只提供「允许一次」和「本次对话都允许」。带警告的调用，例如 `rm -rf`、`sudo`、`curl | sh`，必须逐次审批，长期授权不能覆盖。

App 形象下方的「权限」会列出全部授权，每项都可以单独撤销。API 提供 `DELETE /api/approvals/grants/{key}` 和 `DELETE /api/approvals`；终端 `nanomuse chat` 可用 `/forget-approvals` 清除授权。

同一对话同时调用同一工具时，后来的调用会等待当前审批，再重新检查策略和已保存授权。选了可复用的范围后，范围内的调用不再重复弹卡；「允许一次」仍需逐次回答。其他对话不必等待这张卡片，在那里批准同一工具也会保留各自的对话授权。警告、不同目的地和明确拒绝规则仍分别检查。

绑定到已有聊天的重复提醒和触发器，会复用该聊天的授权。单独运行的任务仍各自拥有对话授权范围。将持久授权改为「直到重启」时，旧磁盘记录也会移除，避免重启后恢复旧权限。

App 中无人回答的卡片会在 `server.approval_timeout` 秒后超时，默认一小时，并按拒绝处理。等待审批时，智能体仍可接收新消息。服务器停止时尚未处理的卡片，会在重启后标为过期，因为对应任务已不再运行。

## 可选的模型观察 {#optional-model-observations}

Python 运行时可以调用模型，观察工具权限决定。在网页版打开「权限 → 模型审核（仅观察）」，或在 `config.toml` 中设置 `[sentinel.review] mode = "observe"`。默认是 `off`。该设置独立于哨兵的 `ask`、`strict` 和 `auto` 策略，作用于 Python 运行时，不包含手机原生权限关口或 DSH 自身的审批系统。

每次观察都会发起一个独立的模型请求。模型配置留空时，使用当前执行任务的模型，也包括仅为这一轮选择的模型。需要单独配置时，可在 `[sentinel.review]` 下填写 `provider`、`model`、`base_url` 和可选的 `api_key`，也可以在权限页填写。只修改模型名时，可以复用当前服务商的凭据；更换服务商或地址时，不会把原地址的 key 带到新地址。在网页中填写的 key 存入保险库，key 输入框留空表示保留，明确选择清除才会删除。`config.toml` 中的独立 key 必须同时指定服务商或地址，避免随对话模型切换而发往其他地址。设置保存失败时，当前地址和原 key 保持有效。

审核模型只收到有长度限制的任务依据、风险标记，以及保险库占位符替换前的实际工具参数快照。已知凭据和常见凭据字段会脱敏，不发送整段对话、工具输出，也不额外读取文件。审核模型无法取得脚本依赖或远端 MCP 的实现。缺失或被截断的上下文会明确标记；输入不完整时，`allow` 建议会改为 `ask`。启用观察会将这些有限信息发送给所选服务商，并增加模型调用。脱敏不能保证任意任务文本都不含私密信息。

审核建议不会授予权限、拒绝操作或代替你回答审批卡片。观察在后台运行，默认超时为 5 秒，输入上限为 6,000 个字符，请求的输出预算为 1,024 个 token。部分服务商适配器（包括 ChatGPT 登录）不执行该 token 预算，但审核超时和最多接受 256 个字符响应的限制仍然有效。最多同时运行四个审核，超出的请求记录为跳过。服务商错误、超时和无效响应只留下记录，不改变正常审批结果。

「活动」和 `audit.jsonl` 中的 `sentinel_review` 记录包含模型建议、实际权限决定、决定来源、模型、状态和完整调用快照的哈希值。服务商返回 token 用量时也会记录。哈希值用于识别被观察的参数，不能证明脚本依赖或远端代码安全。这些记录不保存审核模型的原始推理、响应或服务商错误。第一阶段用于收集和评估审核结果，尚不提供由模型自动批准的模式。

## 污染追踪 {#taint-tracking}

读取 `read_emails`、`recall`、`contacts`、工作区外文件，或标有 `reads_private_data` 的 MCP 服务器等私密来源后，当前对话会被标为已污染。这表示后续内容可能含有私密数据。此后，该对话中向 `egress_allowlist` 之外主机发送数据的调用都需要审批，不受风险级别或运行模式影响，包括 `auto`。

污染状态按对话分别保存。一个旁聊读取了邮件，不会让其他聊天也进入污染状态；清空或删除对话只清除它自身的标记。标记仅存在内存中，重启后不保留；数据如果通过记忆或工作区文件跨对话流动，标记也不会跟随。这项机制用于防范提示注入，即网页等外部内容诱导模型执行用户未要求的指令。例如网页试图让智能体外发你的收件箱时，系统会先要求你查看目的地并确认。

在 `nanomuse chat` 中用 `/tainted` 查看状态；`/reset` 会同时清空当前对话和它的污染标记，不影响其他对话。默认允许列表包含搜索、维基百科、GitHub 和 PyPI，可以修改 `egress_allowlist` 以适应自己的连接器。你在设置中明确指定的目的地，例如 `[connectors.search]` 中的任意搜索服务商，也按允许列表处理，因为模型无法将它改指其他地方。因此读取私密信息后，搜索仍可像使用 DuckDuckGo 时一样执行。

## 凭据保险库 {#credential-vault}

```bash
nanomuse vault set EMAIL_PASSWORD        # prompted; stored Fernet-encrypted in <data_dir>/vault.enc
nanomuse vault list                      # names only
nanomuse vault delete EMAIL_PASSWORD
```

模型 key、邮件配置、日历和联系人链接、搜索 key 等配置值，可用 `{{vault:NAME}}` 引用机密。模型只看到占位符，连接器初始化时使用真实值。正式内置工具均未启用 `accepts_secrets`，因此工具参数不能携带机密。`shell` 或 `python_execute` 中出现该占位符时，会被拒绝并说明原因。你自己编写的工具可以明确启用该能力，哨兵会在执行前才替换真实值。

任何工具输出中出现保险库机密时，都会在送给模型前替换为 `[REDACTED:NAME]`。保险库采用 Fernet 加密，密钥来自首次使用时创建、权限为 600 的 `<data_dir>/vault.key`，或环境变量 `NANOMUSE_VAULT_KEY`。

## 审计日志 {#audit-log}

每条用户消息、每轮模型输出，以及每次决策、审批、工具调用和结果，都会带 UTC 时间戳追加到 `<data_dir>/audit.jsonl`。JSONL 是每行一条 JSON 记录的日志格式：

```bash
nanomuse audit -n 50          # table
nanomuse audit --json         # raw lines
```

点击 App 中的形象打开「活动」面板时，读取的也是同一日志文件。

## 保护范围与限制 {#what-this-does-and-does-not-protect-against}

Meta Muse 将每位用户的智能体放在独立云端 VM 中，哨兵位于 VM 外。nanoMuse 则以你的用户身份在本机运行，哨兵与智能体位于同一进程。因此，两者的隔离边界不同。下面说明 nanoMuse 可以提供哪些保护，以及哪些问题不在保证范围内。

**已有保护**

- *模型执行超出请求范围的操作*。每次工具调用都经过策略检查，敏感或危险调用会停下等待决定。授权按工具和目标限定，并可撤销。
- *提示注入试图外泄数据*。读取私密信息后，向允许列表之外的主机外发数据需要先询问，卡片会显示已知目的地。`web_fetch` 禁止访问回环、链路本地、私有、运营商级 NAT 地址，包括 100.64.0.0/10 范围的 Tailscale 网络，以及云元数据地址。IPv4、IPv6 和重定向都受检查。
- *模型直接看到机密*。key 和密码存放在加密保险库中，以占位符引用，通过审批后才解析，并从结果中脱敏。子进程不继承疑似凭据环境变量；在有效沙箱中也无法读取保险库、数据目录和主目录的其他内容。模型不会看到 App 的访问令牌。
- *无法追查执行过程*。所有过程记录在 `audit.jsonl` 和「活动」视图中。

**需要了解的限制**

- *沙箱不可用时，没有操作系统级隔离*。Linux 上有效的 bubblewrap 沙箱只开放工作区，不开放主目录，默认断网，见[沙箱](#the-sandbox)。但命名空间隔离不等同于 VM，不能消除内核漏洞风险，也不会撤销你批准的 `network=true` 访问。其他环境中，`shell` 和 `python_execute` 以你的身份运行，获批命令能执行你有权限执行的任何操作。命令模式检查可以被恶意脚本绕过。如果工作区涉及重要数据，请在容器或专用用户账号中运行；Docker 镜像就是一种这样的配置。
- *磁盘上的保险库密钥*。默认 Fernet 密钥保存在保险库旁的 `vault.key`，权限为 600。能读取数据目录的人也能解密保险库。如需避免这种情况，请通过密钥管理服务设置 `NANOMUSE_VAULT_KEY`。
- *DNS 重绑定*。`web_fetch` 在请求前检查域名解析结果；如果恶意 DNS 服务器稍后返回另一个地址，请求仍可能被引向内网。污染规则和允许列表会限制这类抓取与其他操作组合的方式。
- *过宽的授权*。选择「总是允许 `shell:curl`」会持续授权该程序。带警告的调用仍会询问，但系统不会检查 `curl` 的目的地。
- *App 的网络连接*。API 默认使用 bearer token（请求中携带的访问凭据）验证，传输为明文 HTTP。不要把端口直接开放到互联网，应使用 Tailscale 或 TLS 加密反向代理。在「连接」页面输入的机密也通过这条网络连接传输。
- *模型服务商可以看到的内容*。记忆会放入系统提示词发送给聊天模型。聊天附件中的图片在 `llm.vision` 支持图像时作为图像输入发送；文档在智能体使用 `files` 读取前不会发送，读取后文字会与其他工具结果一样进入模型请求。启用按含义回忆后，每条记忆的文本及每条消息还会各向 embedding（文本向量化）接口发送一次。使用模型自身接口时，不会新增接收方；使用 `memory.embedding_base_url` 指定的其他服务时，该服务也会收到记忆和消息。选择本地 Ollama 可让这部分处理留在本机。embedding 不属于工具调用，不受污染规则控制，但不会携带保险库值。
- *审批疲劳*。如果不阅读卡片就直接批准，这些审批措施无法发挥作用。

如果发现实际行为与「已有保护」不符，请按 [SECURITY.md](../../SECURITY.md) 报告。

## 编写安全的工具 {#writing-a-safe-tool}

- 如实设置 `risk`；无法确定时使用 `moderate`。
- 输出可能含用户私密数据时，设置 `reads_private_data = True`。调用会向外发送数据时，设置 `egress = True`；已知目的地主机时，在 `assess()` 中提供 `egress_target`。
- 重写 `assess()`，遇到危险参数模式时提高风险级别，并生成简短易懂的 `summary`，供审批卡片显示。
- 不要自行读取机密。确实需要时，明确设置 `accepts_secrets = True`，让哨兵解析 `{{vault:NAME}}`；内置工具均未启用这一能力。
- 使用 `ToolResult(error=...)` 返回错误，不要直接抛出异常；未处理的异常由 `safe_execute` 捕获。
