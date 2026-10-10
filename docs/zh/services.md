# 国内服务：智能体不用屏幕也能够到的

[阶梯](gui.md#the-ladder)把手机屏幕排在最后一级。要让这个排序有意义，第一级得是真的：撑起国内一天生活的那些服务，得有智能体真能调用的 CLI 或 MCP 服务器。这一页就是那张清单（哪些跑过、哪些还没有、哪些我们不会推荐），以及让它保持诚实的一条规则：

> **没有在手机的根文件系统里跑过、留下记录之前，什么都不进[展示站](showcase.md)。** 装得上的包不等于能用的服务。「跑过」的意思是工具被调用了、也回答了；记录在这一页的底部。

这个根文件系统就是本地 Android 构建在手机上解开的那份 Alpine Linux（[local-runtime.md](local-runtime.md)），里面有 Node 22 和 Python 3.12。下面的一切都是 2026-09-24 在那个镜像里、arm64 模拟器（构建机上的 QEMU 用户态）上跑的；PRoot 本身和手机的网络是模拟器碰不到的两样东西，检查清单里给它们各留了一行。

## 一档：已验证 {#tier-1-verified}

在 rootfs 里跑过、答了、进了展示站。

| 服务 | 通过什么 | 验证情况 | 需要用户提供什么 | 技能 |
|---|---|---|---|---|
| **12306**（火车票） | [12306-mcp](https://github.com/Joooook/12306-mcp)，社区 MCP 服务器，基于 12306 的公开时刻表：`npx -y 12306-mcp`，stdio | 已装进 rootfs；一次实时查询第二天早上的 北京 → 上海，1.0 秒返回车次、座位和票价。只能查询：服务器不能订票 | 不需要：没有 key，不用登录 | `train-tickets`（在这里查；只在被要求时才去手机上订） |
| **飞书 / Lark** | [lark-cli](https://github.com/larksuite/cli)，官方 CLI：`npm i -g @larksuite/cli` | 已装进 rootfs 并能运行（1.0.96）；在构建机上，配置好的安装对 `lark-cli auth status` 会回答它的身份。登录是机主的事：先 `lark-cli config init --new` 一次，再 `lark-cli auth login`，两步都通过浏览器里的链接完成 | 一个飞书账号；那两步登录，做一次 | `feishu` |
| **高德地图**（地图、天气） | [高德 MCP Server](https://lbs.amap.com/api/mcp-server/summary)，官方：托管在 `https://mcp.amap.com/mcp?key=…`，或 `npx -y @amap/amap-maps-mcp-server` | 包能在 rootfs 里跑并列出它的十二个工具；实时调用走带 key 的托管地址。构建机上没有 key，所以实时的地理编码和路线调用是检查清单里留给机主的那一行 | 一个 console.amap.com 的免费 Web 服务 key，放在保险库里叫 `AMAP_KEY` | `amap` |
| **腾讯会议** | [tmeet](https://github.com/TencentCloud/tencentmeeting-cli)，腾讯官方 CLI（Go 二进制，`npm i -g @tencentcloud/tmeet`） | 已装进 rootfs 并能运行（v1.0.18）；`tmeet auth status` 和 `tmeet meeting create --help` 都有回答。登录是 OAuth 设备流程，机主点一次（`tmeet auth login --no-browser` 在手机上打印链接） | 一个腾讯会议账号；登录一次 | `tencent-meeting` |

`device` MCP 服务器（手机自己的剪贴板、日历、通讯录、闹钟、位置、通知、照片；[device.md](device.md)）不是第三方服务，不列在这里；它是用 Android 应用验证的。

## 二档：待逐个跑 {#tier-2-to-be-run-one-by-one}

服务器是有的；但还没有带着真实的 key 在 rootfs 里跑过，或者还没有技能。按我们打算尝试的顺序排。

| 服务 | 通过什么 | 状态 | 为什么还没有 |
|---|---|---|---|
| **快递100**（快递） | [快递100 MCP Server](https://github.com/kuaidi100-api/kuaidi100-MCP)，官方：托管（`https://api.kuaidi100.com/mcp/streamable?key=…`）或 `npx -y @kuaidi100-mcp/kuaidi100-mcp-server` | 包能在 rootfs 里跑并列出它的四个工具（`query_trace`、`estimate_time`、`estimate_time_with_logistic`、`estimate_price`）；`kuaidi100` 技能是照着它们写的。实时查询需要账号：按单号付费，注册有免费试用 | 构建机上没有 key。有一条留了记录的 `query_trace` 就升到一档 |
| **百度地图** | [@baidumap/mcp-server-baidu-map](https://lbsyun.baidu.com/faq/api?title=mcpserver/base)，官方（npm 上 1.0.5） | 没跑过。和高德同一类；第二家地图只在其中一家出错时才有意义 | 需要 key；展示站有高德就够了 |
| **腾讯位置服务** | [官方 MCP Server](https://lbs.qq.com/service/MCPServer/MCPServerGuide/overview)，托管（`https://mcp.map.qq.com/sse?key=…`，也支持 Streamable HTTP）：地理编码、地点搜索、路线、IP 定位、天气 | 没跑过 | 需要开通了 WebServiceAPI 的 key；原因同百度 |
| **和风天气** | 基于和风天气 API 的社区服务器（PyPI 上的 `hefeng-weather-mcp` 等）；没找到官方服务器 | 没跑过。高德的 `maps_weather` 给展示站提供天气预报；和风是给想要逐小时或空气质量数据的人 | 需要一个项目、一个 key id 和一把 Ed25519 私钥，比其他家都重的设置 |
| **钉钉** | `dingtalk-mcp-server`（社区，消息 / 待办 / 日历）；钉钉自己的智能体平台不是 MCP 服务器 | 没跑过 | 需要企业账号和应用注册；没有展示案例用到它 |
| **语雀** | `yuque-mcp-server`（社区），基于语雀开放 API | 没跑过 | 个人 token；照 `feishu` 技能的样子写，一个下午就能接上 |
| **百度网盘** | 宣布过支持 MCP；没找到能确认的包或接口 | 没跑过 | 还没有可以跑的东西 |
| **携程 / 飞猪 / 饿了么** | [阿里云百炼 MCP 市场](https://bailian.console.aliyun.com)里的服务器，托管在百炼账号后面 | 没跑过。展示站的酒店预算案例改用应用内浏览器浏览携程（阶梯的第三级），因为没有百炼账号的人也能这样用 | 需要百炼账号和市场的按次计费；给托管的演示值得，给个人构建不值 |

## 三档：不推荐 {#tier-3-not-recommended}

列出来，免得有人问。

| 服务 | 为什么 |
|---|---|
| **微信**：对它的任何自动化，包括社区的「wechat MCP」服务器 | 违反使用条款；账号会被限制。智能体只在用户明确要求时，才在手机屏幕上读和回微信，而且这些都不会出现在公开材料里 |
| **小红书 MCP 服务器** | 社区服务器抓的是已登录的会话；小红书会封账号。被要求时，屏幕能做同样的事 |
| **支付宝 / 微信支付** MCP 服务器 | 它们是给商户的（收款、退款），不是给个人自己的账号。付款是用户自己的事；智能体在那之前停下 |
| 任何需要把用户**密码**写进配置文件的东西 | 保险库里放的是 key 和 token；一个工具自己不能用设备流程或二维码完成的登录，就不是智能体该持有的登录 |

## 添加一个 {#adding-one}

MCP 服务器：在 `config.toml` 里写一个 `[[mcp.servers]]` 块（或者在应用里 连接 → MCP 服务器），key 放在保险库里写成 `{{vault:NAME}}`，`risk` 和 `egress` 如实填写，参数里带用户数据（快递单号、手机号）时 `reads_private_data = true`。CLI：装进 rootfs，或者在电脑上共享给沙箱（程序用 `sandbox.share_read_only`，它的登录用 `share`），然后写一个技能，说明要跑哪些命令、写操作前要问什么。`config/config.example.toml` 里有高德、12306 和快递100 的块；[configuration.md](configuration.md#mcp-servers) 解释各字段。

它在 rootfs 里跑过、回答过一次之后，把记录加到下面，再把它往上挪一档。

## 验证记录 {#verification-log}

在 `nanomuse-rootfs:aarch64`（Alpine 3.21.8、Node 22.23.2、npm 10.9.1、Python 3.12.14、nanomuse 0.1.0）里，x86_64 上的 QEMU 用户态，2026-09-24。镜像源用 `nanomuse-mirror cn` 切换。探针是一个 60 行的 Python 脚本，用的是智能体自己用的那个 `mcp` 客户端：连接、`tools/list`、几次 `tools/call`。

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

在构建机本身（x86_64、Node 20）上，同一条 12306 查询算上 `npx` 启动用了 3.5 秒；配置好的那份安装上，`lark-cli auth status` 报告机器人身份就绪、用户身份需要刷新，这正是 `feishu` 技能在以用户名义做任何事之前要检查的。
