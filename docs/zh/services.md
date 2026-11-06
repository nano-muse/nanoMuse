# 国内服务：不操作屏幕也能使用哪些功能 {#国内服务-智能体不用屏幕也能够到的}

[工具选择顺序](gui.md#the-ladder)将操作手机屏幕放在最后。要让智能体优先使用其他方式，日常使用的国内服务就需要提供可调用的 CLI（命令行工具）或 MCP 服务器（通过统一协议向智能体提供工具的服务）。本文列出已经验证、仍待验证和不推荐的接入方式，并遵守以下标准：

> 服务工具必须在手机使用的根文件系统中实际调用、得到响应并留下记录，才能进入[展示站](showcase.md)。安装成功只能证明软件包可安装，不能证明服务能用。本文底部附有调用记录。

当前 Android App 使用 Alpine Linux 3.21 minirootfs 作为根文件系统，即 Linux 程序运行所需的基础目录和文件。它由 `android/scripts/prepare_android_sandbox.sh` 在构建时下载，App 再通过 proot 运行，见 [android.md](android.md)。初始系统不带 Node 和 Python，首次有任务需要时，智能体才用 `apk add` 安装。本文底部的记录来自 2026-09-24，测试使用旧版 Python 实现的镜像，与当前系统采用相同的 Alpine 基础，但预装了 Node 22 和 Python 3.12。旧方案说明见 [local-runtime.md](local-runtime.md)。当时是在构建机上通过 QEMU 用户态模拟 arm64 执行；本文尚未收录当前 App 根文件系统的独立运行记录。该模拟没有验证 PRoot 本身和手机网络，检查清单为这两项保留了验证项。下文提到的技能都是 Python 运行时内置技能，位于 `nanomuse/skills/builtin/`。

## 第一档：已有验证记录 {#tier-1-verified}

这些工具已在根文件系统中运行、返回响应，并被用于展示站。各项验证覆盖的范围见表格。

| 服务 | 接入方式 | 验证情况 | 用户需要准备什么 | 技能 |
|---|---|---|---|---|
| **12306**（火车票） | [12306-mcp](https://github.com/Joooook/12306-mcp)，基于 12306 公开时刻表的社区 MCP 服务器：`npx -y 12306-mcp`，使用 stdio 标准输入输出通信 | 已在根文件系统中安装；实时查询第二天早上北京 → 上海的车票，1.0 s 返回车次、余票和价格。仅支持查询，不能订票 | 无需 key 或登录 | `train-tickets`，用此服务查询，只有用户要求时才在手机上订票 |
| **飞书 / Lark** | [lark-cli](https://github.com/larksuite/cli)，官方 CLI：`npm i -g @larksuite/cli` | 1.0.96 已在根文件系统中安装并运行；构建机上的已配置实例调用 `lark-cli auth status` 能返回身份信息。用户需先执行一次 `lark-cli config init --new`，再执行 `lark-cli auth login`，两步都通过浏览器链接完成 | 飞书账号，以及首次配置和登录 | `feishu` |
| **高德地图**（地图、天气） | [高德 MCP Server](https://lbs.amap.com/api/mcp-server/summary)，官方服务，托管地址 `https://mcp.amap.com/mcp?key=…`，也可运行 `npx -y @amap/amap-maps-mcp-server` | 软件包可在根文件系统中运行并列出十二个工具；实际业务调用需带 key 访问托管地址。构建机没有 key，地理编码和路线查询仍需由用户完成验证 | 在 console.amap.com 申请免费 Web 服务 key，并以 `AMAP_KEY` 存入保险库 | `amap` |
| **腾讯会议** | [tmeet](https://github.com/TencentCloud/tencentmeeting-cli)，腾讯官方 CLI，以 Go 二进制提供：`npm i -g @tencentcloud/tmeet` | v1.0.18 已在根文件系统中安装并运行；`tmeet auth status` 和 `tmeet meeting create --help` 均返回结果。登录使用 OAuth 设备授权流程，即用户在浏览器中确认授权一次；`tmeet auth login --no-browser` 会在手机上打印链接 | 腾讯会议账号，首次使用时登录一次 | `tencent-meeting` |

`device` MCP 服务器提供手机自身的剪贴板、日历、联系人、闹钟、位置、通知和照片功能，见 [device.md](device.md)。它不属于第三方服务，因此不列入上表；其验证通过 Android App 完成。

## 第二档：仍需逐项验证 {#tier-2-to-be-run-one-by-one}

这些服务已有接入工具，但尚未在根文件系统中使用真实 key 完成调用，或者还没有对应技能。以下按计划尝试的顺序排列。

| 服务 | 接入方式 | 当前状态 | 尚未完成的原因 |
|---|---|---|---|
| **快递100**（物流查询） | [快递100 MCP Server](https://github.com/kuaidi100-api/kuaidi100-MCP)，官方服务，可用托管地址 `https://api.kuaidi100.com/mcp/streamable?key=…`，或运行 `npx -y @kuaidi100-mcp/kuaidi100-mcp-server` | 软件包能在根文件系统中运行，并列出四个工具：`query_trace`、`estimate_time`、`estimate_time_with_logistic`、`estimate_price`。`kuaidi100` 技能已按这些工具编写。真实查询需账号，按单号收费，注册后有免费试用 | 构建机没有 key；完成一次 `query_trace` 并保留记录后可移入第一档 |
| **百度地图** | [@baidumap/mcp-server-baidu-map](https://lbsyun.baidu.com/faq/api?title=mcpserver/base)，官方软件包，npm 版本 1.0.5 | 尚未运行，功能与高德类似；其中一家结果有误时，另一家才有补充价值 | 需要 key；展示站已有高德接入 |
| **腾讯位置服务** | [官方 MCP Server](https://lbs.qq.com/service/MCPServer/MCPServerGuide/overview)，托管地址 `https://mcp.map.qq.com/sse?key=…`，也支持 Streamable HTTP；提供地理编码、地点搜索、路线、IP 定位和天气 | 尚未运行 | 需要启用 WebServiceAPI 的 key；其他原因与百度地图相同 |
| **和风天气** | 基于 QWeather API 的社区服务器，例如 PyPI 上的 `hefeng-weather-mcp`；未找到官方服务器 | 尚未运行。展示站用高德 `maps_weather` 获取预报；需要逐小时天气或空气质量数据时可考虑和风 | 需要创建项目、准备 key id 和 Ed25519 私钥，配置步骤比其他服务多 |
| **钉钉** | 社区 `dingtalk-mcp-server`，提供消息、待办和日历；钉钉自己的智能体平台并非 MCP 服务器 | 尚未运行 | 需要企业账号并注册应用；现有展示案例没有使用需求 |
| **语雀** | 社区 `yuque-mcp-server`，通过语雀开放 API 接入 | 尚未运行 | 需要个人 token（访问凭据）；可参照 `feishu` 技能编写，预计约一个下午 |
| **百度网盘** | 已宣布支持 MCP，但尚未确认可用软件包或接口地址 | 尚未运行 | 暂无已确认可运行的接入方式 |
| **携程 / 飞猪 / 饿了么** | [阿里云百炼 MCP 市场](https://bailian.console.aliyun.com)中的托管服务，需要百炼账号 | 尚未运行。展示站的酒店预算案例改用 App 内浏览器访问携程，即工具选择顺序中的第三级，没有百炼账号的人也可以使用 | 需要百炼账号，并按市场调用次数付费；适合托管演示，个人版本没有必要依赖它 |

## 第三档：不推荐 {#tier-3-not-recommended}

以下接入方式不推荐使用，原因列在表中。

| 服务 | 原因 |
|---|---|
| **微信**自动化，包括社区「wechat MCP」服务器 | 违反使用条款，账号可能被限制。只有用户明确要求读或回微信时，智能体才通过手机屏幕操作，这些内容不用于公开材料 |
| **小红书 MCP 服务器** | 社区服务器抓取已登录会话，存在封号风险。用户要求时，可以通过屏幕完成同类任务 |
| **支付宝 / 微信支付** MCP 服务器 | 面向商户收款、退款，不用于个人账号。付款由用户完成，智能体会在付款前停止 |
| 任何要求将用户**密码**写入配置文件的工具 | 保险库用于保存 key 和 token。工具若不能通过设备授权流程或二维码让用户登录，智能体就不应替用户保管这类登录 |

## 添加服务 {#adding-one}

接入 MCP 服务器时，在 `config.toml` 中添加 `[[mcp.servers]]` 配置块，也可以在 App 中进入连接 → MCP 服务器。key 存入保险库，并使用 `{{vault:NAME}}` 引用。`risk` 应如实表示风险级别，`egress` 表示是否向外发送数据；参数含快递单号、手机号等用户信息时，设置 `reads_private_data = true`。

接入 CLI 时，将它安装到根文件系统，或在电脑上共享给沙箱。程序使用 `sandbox.share_read_only` 只读共享，登录状态使用 `share` 共享。然后编写技能，说明具体命令，以及修改数据前需要询问用户的事项。`config/config.example.toml` 提供了高德、12306 和快递100 的配置示例，字段说明见 [configuration.md](configuration.md#mcp-servers)。

工具在根文件系统中成功调用一次后，把记录补充到下方，并将它移到上一档。

## 验证记录 {#verification-log}

以下记录生成于 2026-09-24，环境是旧版 Python 镜像 `nanomuse-rootfs:aarch64`，包含 Alpine 3.21.8、Node 22.23.2、npm 10.9.1、Python 3.12.14 和 nanomuse 0.1.0，在 x86_64 构建机上由 QEMU 用户态运行。当时使用镜像自带的 `nanomuse-mirror cn` 切换软件源；当前 App 会在首次启动时自行测速选择镜像。测试脚本约 60 行 Python，使用智能体本身采用的 `mcp` 客户端，依次建立连接、调用 `tools/list` 和若干 `tools/call`。

```
$ npm i -g 12306-mcp @larksuite/cli @tencentcloud/tmeet @amap/amap-maps-mcp-server @kuaidi100-mcp/kuaidi100-mcp-server
added 386 packages in 2m            (136 s under emulation; a phone is faster)
/usr/local/bin: 12306-mcp kuaidi100-mcp lark-cli mcp-amap tmeet …

== 12306-mcp (stdio)
connected in 15.5s · 8 tools
  get-current-date, get-stations-code-in-city, get-station-code-of-citys, get-station-code-by-names,
  get-station-by-telecode, get-tickets, get-interline-tickets, get-train-route-stations
$ get-current-date {}                                        (0.1s) → 2026-09-24
$ get-station-code-of-citys {"citys": "北京|上海"}            (0.1s) → {"北京":{"station_code":"BJP",…},"上海":{"station_code":"SHH",…}}
$ get-tickets {"date":"2026-09-25","fromStation":"北京","toStation":"上海","trainFilterFlags":"G",
               "earliestStartTime":7,"latestStartTime":9,"sortFlag":"startTime","limitedNum":3}   (1.0s)
G565 北京南 -> 上海虹桥 07:07 -> 13:12 历时：06:05   商务座: 无票 2156元 · 一等座: 无票 967元 · 二等座: 无票 576元
G549 北京南 -> 上海虹桥 07:13 -> 13:03 历时：05:50   商务座: 剩余16张票 2315元 · 一等座: 无票 967元 · 二等座: 无票 598元
G5   北京   -> 上海     07:40 -> 12:32 历时：04:52   商务座: 无票 2350元 · 一等座: 无票 1075元 · 二等座: 无票 672元 · 无座: 剩余19张票

== lark-cli
lark-cli version 1.0.96
$ lark-cli auth status → {"ok": false, "error": {"type": "config", "subtype": "not_configured",
   "hint": "run `lark-cli config init --new` … open it in a browser to complete setup."}}      (the owner's step)

== tmeet
tmeet version v1.0.18
$ tmeet auth status → Not logged in. Please use 'tmeet auth login' to authenticate.            (the owner's step)
$ tmeet meeting create --help → --subject, --start, --end (ISO 8601), --invitees, --password, --waiting-room,
   --meeting-type / --recurring-type / --until-type / --until-count / --until-date, --join-type, --auto-record-type, --auto-asr …

== @amap/amap-maps-mcp-server (stdio, AMAP_MAPS_API_KEY set to a placeholder — tools only)
connected · 12 tools: maps_regeocode, maps_geo, maps_ip_location, maps_weather, maps_search_detail, maps_bicycling,
  maps_direction_walking, maps_direction_driving, maps_direction_transit_integrated, maps_distance, maps_text_search, maps_around_search

== @kuaidi100-mcp/kuaidi100-mcp-server (stdio, KUAIDI100_API_KEY set to a placeholder — tools only)
connected in 4.1s · 4 tools: query_trace, estimate_time, estimate_time_with_logistic, estimate_price
  (the server prints one non-JSON line, "MCP server is running…", on stdout first; the client logs it and carries on)
```

在构建机本机环境，即 x86_64、Node 20 中，同一条 12306 查询包含 `npx` 启动在内共用时 3.5 s。已配置的 `lark-cli` 实例运行 `auth status` 后，报告机器人身份可用、用户身份需要刷新。`feishu` 技能会在以用户身份执行操作前检查这一状态。
