# Glossary

This page explains terms used in the documentation. Interface labels follow the apps. Configuration keys, technical identifiers and product names keep their original spelling.

## Agent and devices

| Term | Meaning |
|---|---|
| Agent<br>智能体 | An AI program that uses tools to carry out tasks as well as reply. |
| Runtime<br>运行时 | The program that runs the agent loop, tools and scheduled work. |
| Host / harness<br>宿主 / 执行框架 | The application or framework that loads the agent and provides its execution environment. |
| Relay / nanoMuse Cloud<br>中继 / nanoMuse Cloud | The service for account sign-in, model forwarding and communication between the account's devices. |
| Hub<br>hub（设备互联） | The relay's connection through which devices of one account exchange requests and events. |
| Remote control<br>远程控制 | Allowing another device of the account to request actions on this device. |
| Hands<br>「手」 | The agent's ability to read a screen and click, type or swipe. |
| Operator<br>操作器 | The loop that reads a screen, asks its model for an action and executes it. |
| Capsule<br>胶囊 | The floating task display with the current step and Stop control. |
| Stage / glow / marker<br>舞台 / 光晕 / 标记 | The operation display area, its visual boundary and the indication of an action's position. |
| Trajectory / trace<br>轨迹 | A task's sequence of screens, actions and results. |
| Main chat / side chat<br>主要聊天 / 旁聊 | The main ongoing conversation and additional separate task conversations. |
| Context / system prompt<br>上下文 / 系统提示词 | The information supplied to the model, and the standing instructions included with it. |
| Feed / Ideas / Goals / Library<br>动态 / 点子 / 目标 / 资源库 | The app's pages for posts, task suggestions, plans and generated files. |
| Routine / trigger / goal check<br>例程 / 触发器 / 目标检查 | Work run at a scheduled time, work started by an event, and a scheduled review of a goal. |

## Models and credentials

| Term | Meaning |
|---|---|
| LLM, large language model<br>大语言模型 | A model that understands and generates language. The agent asks it for a reply or the next tool call; image support depends on the model. |
| Provider<br>服务商 | The vendor or service supplying a model endpoint. |
| Endpoint / Base URL<br>端点 / 基础地址 | An address receiving API requests, and the base address used to build those request URLs. |
| API key<br>API 密钥（key） | A credential used to authenticate requests to a service. |
| Access token<br>访问令牌 | A credential issued after authentication or authorisation, sometimes with an expiry time. |
| Token usage<br>模型 token 用量 | Units used by a model to represent input and output, not a direct character count. |
| Allowance<br>额度 | The amount of model use available to an account. |
| Model slot / Automatic<br>模型用途设置 / 自动 | A separate choice for chat, screen operation, images or video; Automatic resolves a source using the documented order. |
| Multimodal / vision<br>多模态 / 视觉能力 | Support for multiple data types, such as text and images. |
| Embeddings / semantic recall<br>嵌入向量 / 语义检索 | Numerical representations of text, used to retrieve memories by similarity of meaning. |
| OAuth / PKCE<br>OAuth / PKCE | An authorisation flow, with PKCE binding a returned authorisation code to the client that started it. |
| Vault<br>保险库 | The encrypted store for credentials referenced as `{{vault:NAME}}`. |

## Tools and connections

| Term | Meaning |
|---|---|
| Tool call<br>工具调用 | A structured request from the model for a program to perform an operation. |
| Skill<br>技能 | A folder with a `SKILL.md` describing how to perform a class of tasks. |
| Connector<br>连接器 | A configured connection that gives the agent access to a service's tools or data. |
| MCP server<br>MCP 服务器 | A service exposing tools or data through the Model Context Protocol. |
| CLI / shell<br>命令行工具 / shell | A program controlled by text commands, and the command interpreter that runs them. |
| API / REST<br>程序接口 / REST | Interfaces for programs to exchange requests and data; REST commonly uses HTTP routes and methods. |
| JSON / TOML<br>JSON / TOML | JSON represents structured data exchanged by programs; TOML is a human-readable configuration format, as in `config.toml`. |
| stdio<br>标准输入输出 | Communication with a local process through its input and output streams. |
| WebSocket / frame<br>WebSocket / 消息帧 | A persistent two-way connection and an individual message sent over it. |
| SSE<br>服务器发送事件 | An HTTP connection over which a server sends a stream of events to a client. |
| Webhook<br>事件回调 | An HTTP address another program calls when an event occurs. |
| WebView / Playwright<br>内嵌网页组件 / 浏览器自动化工具 | WebView displays web pages inside an app; Playwright controls a browser programmatically. |
| Accessibility tree / OCR<br>无障碍树 / 文字识别 | Structured screen controls, and text recognised from an image. |
| GUI / grounding<br>图形界面 / 屏幕定位 | The visible interface, and matching the intended element to the position to act on. |

## Permissions and deployment

| Term | Meaning |
|---|---|
| Sentinel<br>哨兵（Sentinel） | The component that checks a tool call's risk and decides whether to allow, ask or deny. |
| Approval / grant scope<br>审批 / 授权范围 | A user decision about an action, and the actions or time covered by a remembered decision. |
| Taint<br>污染标记 | A record that a conversation has read private data, used when checking later outbound actions. |
| Sandbox / workspace<br>沙箱 / 工作区 | An environment restricting a command's access, and the directory for the agent's working files. |
| Egress allowlist<br>外发白名单 | The hosts allowed as outbound destinations under the configured policy. |
| ARM64 / x64<br>ARM64 / x64 | Processor architectures. Choose a matching installer: ARM64 is common on phones and Apple Silicon computers; x64 on Intel and AMD computers. |
| Self-hosting / Docker<br>自行部署 / Docker | Running the service on your own server; Docker packages it and its environment in containers. |
| Loopback / LAN / reverse proxy<br>回环地址 / 局域网 / 反向代理 | An address for the same computer, a local network, and a service forwarding incoming requests to an internal one. |
| TLS / HTTPS<br>连接加密 / HTTPS | TLS encrypts network traffic; HTTPS is HTTP protected by TLS. |
| CI / regression test<br>持续集成 / 回归测试 | Automated project checks, and checks that existing behaviour still works after changes. |
| MockLLM / replay / live<br>模拟模型 / 回放 / 真实模型运行 | Scripted responses, recorded responses used again, and new calls to the configured model. |
| P95 latency<br>P95 耗时 | The duration at or below which 95% of the measured samples fall. |
| Idempotent / cursor / tombstone<br>幂等 / 游标 / 删除标记 | Safe repeat processing, a position in an incremental feed, and a record of a deletion for sync. |
