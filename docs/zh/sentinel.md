# 哨兵（Sentinel）

Meta 把 Muse 的安全模型描述为一个独立的「哨兵」（Sentinel）智能体，坐在模型和它的工具之间：审批敏感操作、让凭据不落入模型之手、记录发生了什么。nanoMuse 实现了同样的分离。智能体从不自己执行工具，而是把调用交给 `Sentinel.guard()`：

```
agent ──► Sentinel.guard() ──► policy ──► approval (if needed) ──► vault.resolve ──► execute
agent ◄── redact(result)   ◄── taint bookkeeping ◄─────────────────────────────────────┘
```

代码：`nanomuse/sentinel/gate.py`（关口）、`policy.py`（决策）、`audit.py`（日志）。保险库在 `nanomuse/vault/`。

## 风险级别 {#risk-levels}

每个工具都声明一个静态的 `risk`：

| 级别 | 含义 | 例子 |
|---|---|---|
| `safe` | 可逆、本地 | `files`（工作区之内）、`web_search`、`remember`、`goals`、`contacts`、`skills`（列出、使用）、`phone_screen` |
| `moderate` | 触及外部或改变状态 | `web_fetch`、`python_execute`、`read_emails`、`browser`、`forget`、`phone_act` |
| `sensitive` | 难以撤销或外部可见 | `shell`、`send_email`、`skills`（保存、删除；技能是模型以后会照着做的长期指令，所以写一个技能总是会问） |

工具可以在 `assess()` 里为某一次调用提高级别：`shell` 遇到 `rm -rf`、`sudo`、`curl | sh` 这类模式会附上一条警告；`python_execute` 对纯计算和工作区内的文件是 `moderate`（前提是沙箱在工作；没有沙箱时，在 macOS、Windows 或没装 bubblewrap 的 Linux 机器上，每个脚本都是 `sensitive`，因为静态检查是仅剩的一道墙），而当代码访问网络、启动其他程序、读环境变量、删文件或触及工作区之外的路径时是 `sensitive`，原因写在卡片上；`web_fetch` 直接拒绝私有地址和回环地址，每一跳重定向都查；`phone_act` 在一次点击的 `label`（操作器对手指下面是什么的描述）含有 确认支付、转账、提交订单、发送、删除 或 `[gui] sensitive_words` 里的另一个词时，或者一步同时输入并提交时，是带警告的 `sensitive`；没有 label 的点击自带一条警告（[gui.md](gui.md)）。工具还声明 `reads_private_data`（污染这段对话）和 `egress`，可选带 `egress_target`（这次调用把数据发往的主机；`shell` 和 `python_execute` 未知；手机上是 App 的 id），供污点追踪使用。

`shell` 和 `python_execute` 启动的子进程拿到的是清洗过的环境：名字像凭据的变量（`*KEY*`、`*TOKEN*`、`*SECRET*`、`*PASSW*`、`*CREDENTIAL*`、`*AUTH*`、`*COOKIE*`、`*SESSION*`）、所有 `NANOMUSE_`、`AWS_`、`AZURE_`、`GOOGLE_`、`GH_`、`GITHUB_`、`NPM_` 开头的，再加 `SSH_AUTH_SOCK`，都在子进程启动前移除，所以模型写的代码读不到模型自己的 API key，也读不到 `os.environ` 里的保险库密钥。这两个工具都不接受 `{{vault:NAME}}` 占位符：带占位符的命令会被拒绝并说明原因，而不是拿字面文本去跑；保险库里的值只送达用它们配置的连接器。编程 CLI（`coding_tool`：Codex、Claude Code、Cursor）拿到同样清洗过的环境，再加上它们各自的账号变量（`OPENAI_*`/`CODEX_*`、`ANTHROPIC_*`/`CLAUDE_*` 以及当 `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX` 这么要求时的云凭据、`CURSOR_*`），运行时的其他东西一概没有。

## 沙箱 {#the-sandbox}

Meta Muse 给每个用户的智能体一台独立的 VM。nanoMuse 跑在你的机器上，所以在 Linux 上做了退而求其次的事：每一次 `shell` 和 `python_execute` 调用都在自己的命名空间里运行，由 [bubblewrap](https://github.com/containers/bubblewrap) 创建（Flatpak 背后的那个工具；无需特权，`apt install bubblewrap` / `dnf install bubblewrap`）。箱子里面：

- 工作区（和 `agent.extra_roots`）是仅有的可写位置：`/usr`、`/etc`、`/opt`、`/var` 只读，`/tmp` 是这次调用私有的，`/proc` 和 `/dev` 是全新的；
- 你的家目录不存在，连带保险库、数据目录、ssh 密钥、云凭据和浏览器配置都不存在。仅有的例外：正在运行的 Python 所在的目录（venv 或 `uv` 管理的解释器常常在家目录下），只读，这样 `python_execute` 用的解释器和包和 nanoMuse 一样；技能文件夹（内置的和你的），只读，这样技能的脚本和参考文件能在里面运行和读取；还有你刻意共享的：`[sandbox] share_read_only` 给程序（装着 node 和飞书 CLI 的 `~/.nvm`），`share` 给工具还必须写入的状态（它的登录态，`~/.lark-cli` 和 `~/.local/share/lark-cli`）。你家目录下共享的目录在箱子自己的家目录下同一位置也看得到，所以到 `$HOME` 里找东西的工具能找到；家目录的其余部分留在外面。位于工作区之内的数据目录会被遮住；
- **没有网络**，除非这次调用被评估为需要它：运行网络程序（`curl`、`wget`、`pip`、`git`、`ssh`、`npm`、`docker`……）、含有 URL 或主机名、或者写了 `network=true` 的 `shell` 命令；导入网络模块（`requests`、`httpx`、`socket`、`urllib`……）或启动其他程序的 `python_execute` 脚本。其他一切只带回环接口运行。因为没有网络而失败的命令，结果里会附一条说明，模型可以带 `network=true` 再跑一次，那就成了一次外发调用，和其他任何调用一样过同样的审查；
- 进程树、IPC、UTS 和 cgroup 命名空间都是分开的；`HOME` 和 `TMPDIR` 指向私有的 `/tmp`；设置了 `NANOMUSE_SANDBOX=bwrap`，脚本能据此判断。

这改变了「外发」对 `shell` 的含义：没有沙箱时，每条 shell 命令都被当作可能访问网络的（读过私密数据之后就会问）；有沙箱时，只有拿到网络的命令才算。读完邮件后一条装在箱子里的 `ls` 什么也发不出去，所以不会因为这个理由问；但它仍是 `sensitive`，在 `ask` 模式下仍会问，和每条 shell 命令一样。

`[sandbox] mode` 是 `auto`（默认：bubblewrap 装了并且能在这里创建命名空间时就用）、`bwrap`（坚持用：用不了时 `nanomuse doctor` 失败，日志说明原因）或 `off`。在它跑不起来的地方，也就是 macOS、Windows 和大多数 Docker 容器（默认的 seccomp 配置挡住了非特权用户命名空间，这没关系：容器本身就是箱子），命令照旧运行，带着清洗过的环境，以工作区为工作目录，「设置 → 安全」会说明这一点。`nanomuse doctor` 打印沙箱那一行；设置 API 把它放在 `sandbox` 下。

**Ubuntu 24.04 及其衍生版**用 AppArmor 限制非特权用户命名空间：`kernel.apparmor_restrict_unprivileged_userns=1` 让没有自己 AppArmor 配置的程序创建的命名空间没有任何 capability。看机器不同，bubblewrap 要么直接失败（`bwrap: setting up uid map: Permission denied`），要么箱子建起来了但建不了它的网络命名空间（`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`）。第二种情况下 nanoMuse 保留文件系统的箱子，放弃网络：状态行写着「网络未被阻断」，`shell` 命令按没有箱子的方式判断：每一条都可能访问外部。两种情况的解法都是 `/usr/bin/bwrap` 的标准配置，Ubuntu 25.04 随 `apparmor` 提供，24.04 在 `apparmor-profiles` 里（Flatpak 出过一次回归之后它被从默认集合里拿掉了）：

```bash
sudo apt install apparmor-profiles
sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
```

`nanomuse doctor` 会指出是这种情况。关掉限制（`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`）也行，但削弱的是整台机器，不只是箱子。

## 决策顺序 {#decision-order}

每次调用，第 1 到第 4 步里第一个匹配的步骤给出决定；第 5、6 步随后对每个决定都会检查，只能把「允许」改成「询问」：

1. **`deny_tools`** → 拒绝。
2. **`[[sentinel.rules]]`**：`tool`（glob，`*` 表示任意）加 `match`，一个参数名 → glob 模式的映射，拿 `str(value)` 来匹配。第一条匹配的规则生效，给出它的 `action`。
3. **`always_allow_tools` / `always_ask_tools`**。
4. **风险 × 模式**，前面都没有匹配时：

| 模式 | `safe` | `moderate` | `sensitive` |
|---|---|---|---|
| `ask`（默认） | 允许 | 允许 | 询问 |
| `strict` | 允许 | 询问 | 询问 |
| `auto` | 允许 | 允许 | 允许 |

5. **污点**：到这里的决定是允许，这段对话已被污染，**而且**这次调用外发到不在 `egress_allowlist` 里的主机（或目的地未知）→ 询问，不论这个允许来自模式、`always_allow_tools` 还是一条规则。目的地已知时审批卡片会显示它。
6. **警告**：带警告的调用（`rm -rf`、`sudo`、`curl | sh`、读环境变量或删文件的代码）绝不会被模式或 `always_allow_tools` 放行；它会问。只有一条明确的 `allow` 规则能覆盖这一点。

`auto` 仍然遵守 `deny_tools`、deny 规则、第 5 步和第 6 步。污点规则在每种模式下都成立：一段对话读过邮件、日历、联系人或其他私密来源之后，要把数据发往 `egress_allowlist` 之外主机的调用会询问，`auto` 不会把这个问题改成放行。`nanomuse daemon`、`--auto` 和 App 里的「放手」设置用的就是它，后台的目标检查也是，所以无人值守的运行里出现危险命令或读过私密数据后的外发时，它变成动态里的一张卡片，而不是直接跑掉。`nanomuse daemon` 旁边没有人：仍需要审批的那一步会被拒绝并留下说明，模型继续做它能做的。

## 审批 {#approvals}

决定是「询问」时，界面（控制台，或 App 里的审批卡片）显示工具、调用的摘要、导致这次调用的你的请求（「目的」）、精确的参数、风险级别和原因。你可以拒绝，或者带一个范围允许：

| 回答 | 效果 |
|---|---|
| 拒绝 | 工具不运行；模型收到一个「Sentinel blocked」结果，并被告知不要重试同一个调用 |
| 一次 | 只这一次；什么都不记 |
| 本次对话 | 只要这次调用来自的聊天还在（它之后的每一轮都覆盖；删除或清空聊天就结束；重启后不保留），即手机 App 一直有的那个中间范围；对 `shell` 来说覆盖的是整个工具，不只是当前命令里的程序。聊天之外的运行（`nanomuse run`、定时任务）自成一个对话 |
| 直到重启 | 直到进程退出 |
| 24 小时 | 带过期时间持久化在 `<data_dir>/approvals.json` 里 |
| 总是 | 持久化，直到你撤销 |

审批是一项能力，不是一种心情。它绑定一个**授权键**：工具加上这次调用触及的东西：`web_fetch:example.com`、`send_email:alice@example.com`、`shell:git`、`browser:booking.com`。允许 `git` 命令用于本次会话，对 `curl` 什么也没说；`git status | head` 这样的管道需要每个程序都被覆盖（批准它时每个程序分别获得授权），发给两个人的邮件需要两个收件人都被覆盖。唯一有意为之的例外是 `shell` 上的「本次对话」：现在需要 `git` 的任务，一会儿就会需要 `ls` 和 `wc`，所以这个回答覆盖对话余下时间里的整个 shell，而目的地（收件人、主机）即使在其中也仍然绑定。没有明确目标的工具（`python_execute`、一个 MCP 工具）整体授权，而对能访问网络的任意代码，哨兵只提供「一次」和「本次对话」。带警告的调用（`rm -rf`、`sudo`、`curl | sh`）一次一批；长期许可永远不覆盖它。

你授出的一切都列在 App 里形象下方（「权限」），每一项有自己的撤销按钮；`DELETE /api/approvals/grants/{key}` 和 `DELETE /api/approvals` 从 API 做同样的事，`nanomuse chat` 的 `/forget-approvals` 在控制台里清掉它们。

在 App 里，没人回答的卡片在 `server.approval_timeout` 秒（默认一小时）后超时，算作拒绝。卡片等待期间智能体照常接收新消息。服务器停止时仍在等待的卡片在重启后标记为过期；它们背后的那次运行没有了。

## 污点追踪 {#taint-tracking}

读取私密数据（`read_emails`、`recall`、`contacts`、工作区之外的文件、标记了 `reads_private_data` 的 MCP 服务器）会把这段对话标记为已污染。从那以后，这段对话里任何把数据发往 `egress_allowlist` 之外主机的调用都需要审批，不论它的风险级别，也不论模式，`auto` 也一样。污点按对话记录：一个读过你邮件的侧边聊天不会让旁边的聊天跟着询问，清空或删除一段对话只会去掉它自己的污点。污点只放在内存里，重启后不保留，也不会跟着通过记忆或工作区文件跨过对话的数据走。这是对提示注入的实际防线：一个网页没法指使智能体把你的收件箱发到某处，而你事先看不到目的地。

`nanomuse chat` 用 `/tainted` 显示状态；`/reset` 随对话一起清掉它，其他对话保持原样。默认白名单覆盖搜索、维基百科、GitHub 和 PyPI；按你自己的连接器改 `egress_allowlist`。你自己在设置里定下的目的地（`[connectors.search]` 下的搜索服务商，不管是哪家）和白名单同等对待：模型没法改它的指向，所以读过私密数据之后的搜索照样通过，和用 DuckDuckGo 时一样。

## 凭据保险库 {#credential-vault}

```bash
nanomuse vault set EMAIL_PASSWORD        # prompted; stored Fernet-encrypted in <data_dir>/vault.enc
nanomuse vault list                      # names only
nanomuse vault delete EMAIL_PASSWORD
```

配置值（模型的 key、邮件、日历和联系人的链接、搜索的 key）用 `{{vault:NAME}}` 引用机密；模型看到的是占位符，连接器用真实值构建。工具参数**不**携带机密：没有任何正式工具选择接受（`accepts_secrets`），所以 `shell` 或 `python_execute` 调用里的 `{{vault:NAME}}` 会被拒绝并说明原因，而不是拿字面文本去跑（你自己的工具可以选择接受；哨兵会在执行前一刻替换）。如果某个机密出现在任何工具的输出里，模型读到之前它就被换回 `{{vault:NAME}}`。密钥是 `<data_dir>/vault.key`（首次使用时创建，权限 600）或 `NANOMUSE_VAULT_KEY`。

## 审计日志 {#audit-log}

每条用户消息、每轮模型输出、每个决策、审批、工具调用和结果都带 UTC 时间戳追加到 `<data_dir>/audit.jsonl`：

```bash
nanomuse audit -n 50          # table
nanomuse audit --json         # raw lines
```

App 里的活动面板（点形象）读的是同一个文件。

## 它能防什么、不能防什么 {#what-this-does-and-does-not-protect-against}

Meta Muse 把每个用户的智能体跑在各自的云端 VM 里，哨兵在 VM 之外。nanoMuse 跑在你的机器上，以你的用户身份，哨兵是同一个进程里的一个模块。这改变了这些保护措施能承诺什么。老实说：

**覆盖到的**

- *模型做了你没要求的事。* 每个工具调用都过策略；敏感和危险的调用停下来等决定；许可限定在一个工具和一个目标上，可以撤销。
- *试图外泄数据的提示注入。* 私密数据一旦被读取，外发到白名单之外的任何主机都先询问，目的地写在卡片上。`web_fetch` 不能被指向回环、链路本地、私有或云元数据地址，经重定向也不行。
- *模型看到你的机密。* key 和密码放在加密的保险库里，以占位符进入工具调用；审批之后才替换，结果里再抹掉。子进程不继承看起来像凭据的环境变量，在沙箱里也读不到保险库、数据目录或你家目录下的任何其他东西。模型永远看不到 App 的访问令牌。
- *不知道发生了什么。* 一切都在 `audit.jsonl` 和「活动」视图里。

**没覆盖到的：运行之前先知道**

- *操作系统级隔离，在沙箱跑不起来的地方。* Linux 上有 bubblewrap 时，箱子里的命令只看得到工作区，够不着你的家目录，没有网络，除非调用声明需要（见[沙箱](#the-sandbox)）；但 bubblewrap 命名空间不是 VM，内核漏洞或你批准的一次 `network=true` 调用，该是什么还是什么。其他所有地方 `shell` 和 `python_execute` 以你的身份运行：你批准的命令能做你能做的一切，模式检查只是绊线，对抗性脚本躲得开。如果工作区碰得到任何你丢了会心疼的东西，就在容器里或一个专用用户账号下运行 nanoMuse（Docker 镜像就是这样一种配置）。
- *磁盘上的保险库密钥。* 默认情况下 Fernet 密钥就放在保险库旁边（`vault.key`，权限 600）。能读你数据目录的人就能解开保险库。如果这对你重要，从密钥管理服务设置 `NANOMUSE_VAULT_KEY`。
- *DNS 重绑定。* `web_fetch` 在请求前检查解析出来的地址；一个片刻之后给出不同答案的恶意 DNS 服务器仍能把请求指向内部地址。污点规则和白名单限制了这样一次抓取能和什么组合起来。
- *糟糕的授权。* 「总是允许 `shell:curl`」就和它听起来的一样强。警告仍会问，但 `curl` 的目的地不会被检查。
- *App 所在的网络。* API 默认由 bearer token 保护，走明文 HTTP。别把端口暴露到互联网；用 Tailscale 或 TLS 反向代理。在「连接」屏里输入的机密走的就是这条连接。
- *模型服务商看到什么。* 每条记忆都在系统提示里发给聊天模型；记忆本来就是干这个的。聊天里附的图片在聊天模型接受图片时（`llm.vision`）作为图像内容发给它；文档在智能体用 `files` 读它之前哪儿也不去，读了之后它的文字就和所有工具结果走同一条路。开了按含义回忆时，每条记忆的文字也会发给 embedding 端点，每条一次，每条消息一次。当那是模型自己的端点时，没有新东西被分享；当它是另一个服务（`memory.embedding_base_url`）时，那个服务也看到你的记忆和消息；本地的 Ollama 是不与任何人分享的选择。embedding 调用不是工具调用，所以在污点规则之外；它们从不携带保险库的值。
- *审批疲劳。* 如果卡片看都不看就批，以上一切都帮不了你。

和「覆盖到的」清单相矛盾的任何事都请报告，见 [SECURITY.md](../../SECURITY.md)。

## 写一个安全的工具 {#writing-a-safe-tool}

- 设一个诚实的 `risk`；拿不准就 `moderate`。
- 输出可能包含用户私密数据时设 `reads_private_data = True`；调用会把数据发往任何地方时设 `egress = True`（主机已知时在 `assess()` 里给出 `egress_target`）。
- 重写 `assess()`，对危险的参数模式提高级别，并生成一段简短、人能读的 `summary`；审批卡片显示的就是它。
- 永远别自己读机密。确实需要的工具用 `accepts_secrets = True` 选择接受，让哨兵来解析 `{{vault:NAME}}` 占位符；内置工具都不这么做。
- 用 `ToolResult(error=...)` 返回错误，而不是抛异常；`safe_execute` 兜住其余的。
