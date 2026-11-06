# 聊天入口

你可以在平时使用的聊天软件中与 nanoMuse 对话，目前支持飞书 / Lark、钉钉、企业微信和 Telegram。用手机给机器人发消息，就能使用同一个 nanoMuse：每个聊天各自对应一段对话，回复会随生成进度显示，执行工具时会显示状态，需要审批时可以回复文字或点击按钮。开启「推送到这里」的聊天还会收到主动消息，包括问候、提醒、后台任务结果，以及需要你回答的问题。

这些入口都不需要公网地址。机器人会从你的网络内部主动建立长连接，让双方持续收发消息；Telegram 使用长轮询，也就是发送请求并等待新消息后再继续请求。因此，在路由器后面的电脑或笔记本上运行 nanoMuse 就可以使用。连接由各厂商的 SDK（软件开发工具包）处理，这些 SDK 是按需安装的可选依赖：

```sh
pip install 'nanomuse[feishu]'      # lark-oapi
pip install 'nanomuse[dingtalk]'    # dingtalk-stream
pip install 'nanomuse[wecom]'       # wecom-aibot-sdk-python
pip install 'nanomuse[channels]'    # all three; Telegram needs nothing extra
```

Docker 镜像已包含全部 SDK。未安装对应 SDK 时，应用会显示安装命令，并保持该入口的开关不变。

飞书或钉钉消息到达运行时（负责执行智能体任务的本地程序）后，如果处理失败，运行时日志会记录入口名称和错误。机器人显示已连接、却收到消息不回答时，可以先检查这份日志。

## 设置入口 {#where-to-find-it}

* **应用**：进入设置 → 聊天入口。每种聊天软件各有一张卡片，包含开关、连接凭据、允许联系机器人的用户、已配对的聊天、每个聊天的「推送到这里」开关，以及「发一条测试消息」按钮。卡片还提供设置步骤和厂商控制台链接。
* **终端**：使用 `nanomuse channels status | pending | approve <code> | deny <code> | login feishu [--lark] | test <name>`。如果 `nanomuse serve` 正在运行，命令会调用它的 API（供程序访问功能的接口）；否则直接修改 `<data_dir>/channels/` 中的文件，由服务在启动或点击「重新加载」时读取。
* **API**：提供 `GET /api/channels`、`PUT /api/channels/<name>`、`POST /api/channels/pairing/<code>/approve|deny`、`PUT|DELETE /api/channels/<name>/chats/<sender>`、`POST /api/channels/<name>/test`、`POST /api/channels/deliver {text}`、`POST /api/channels/reload`。飞书另有 `POST /api/channels/feishu/login` 和 `GET /api/channels/feishu/login/<device_code>`。
* **config.toml**：手动配置服务器时，也可以添加 `[channels.<name>]` 配置段：

  ```toml
  [channels.telegram]
  enabled = true
  bot_token = "${TELEGRAM_BOT_TOKEN}"
  allow_from = ["123456789"]      # Telegram user ids that never need a code
  group_policy = "mention"        # or "open"
  ```

  每个字段都以应用中保存的值为优先。在应用中输入的密钥会存入保险库（专门保存敏感凭据的位置），文件中只留下 `{{vault:CHANNEL_TELEGRAM_BOT_TOKEN}}` 这样的占位符。保存后不会再次显示密钥，字段只提示是否已设置。

## 配置各聊天软件 {#setting-up-each-app}

下面使用的是 2026 年各厂商控制台的名称，厂商之后可能调整位置或名称。

### 飞书 / Lark {#feishu-lark}

你可以在应用中点击「扫码创建机器人」，用飞书扫描并确认。也可以运行 `nanomuse channels login feishu`，国际版 Lark 加上 `--lark`。完成后，App ID 和 Secret 会自动保存，聊天入口随即启用。这是飞书为个人智能体提供的扫码创建应用流程，创建的应用已经配置好机器人能力和长连接事件。

如果手动配置，打开 <https://open.feishu.cn/app>，Lark 则打开 <https://open.larksuite.com/app>：

1. 选择「创建企业自建应用」→「添加应用能力」→「机器人」。
2. 在「权限管理」中添加 `im:message`、`im:message.p2p_msg:readonly`、`im:message.group_at_msg:readonly` 和 `im:resource`，最后一项用于图片和文件。
3. 在「事件与回调」中，将事件订阅方式设为「长连接」，添加 `im.message.receive_v1`；将回调方式也设为「长连接」，添加 `card.action.trigger`，用于处理审批按钮。
4. 在「凭证与基础信息」中，将「App ID」和「App Secret」复制到 nanoMuse，选择 *feishu* 或 *lark*。如果没有在厂商控制台设置「Encrypt Key」和「Verification Token」，这两项留空。
5. 进入「版本管理与发布」，创建版本并发布。

回复以交互卡片发送，正文支持 Markdown 排版。文字生成过程中，应用会约每秒更新一次原卡片。你的消息上出现 👍，表示 nanoMuse 正在处理。在群聊中，只有 @ 机器人时才会收到回答。

### 钉钉 {#dingtalk}

打开 <https://open-dev.dingtalk.com/>：

1. 创建「企业内部应用」，进入「添加应用能力」，添加「机器人」。
2. 将消息接收模式设为「Stream 模式」，不需要回调 URL（接收厂商推送请求的公网地址）。
3. 在「凭证与基础信息」中复制「Client ID」（AppKey）和「Client Secret」（AppSecret）。
4. 在「权限管理」中添加机器人发送消息的权限 `qyapi_robot_sendmsg`。这样，开启「推送到这里」的聊天即使没有等待回复的消息，也能接收主动推送。
5. 发布版本，再将机器人加入群聊，或在通讯录中找到它。

钉钉不支持编辑已发出的消息，因此回复会在生成完毕后整条发送。群聊中的机器人只能收到 @ 它的消息。

### 企业微信 {#wecom}

进入企业微信管理后台 → 安全与管理 → 智能机器人：

1. 点击「创建机器人」，选择「API 模式」，连接方式选择「长连接」。
2. 将「Bot ID」和「Secret」复制到 nanoMuse。
3. 将机器人加入需要接收消息的聊天，或让用户在通讯录中找到它。

运行时会将长连接使用的主机 `openws.work.weixin.qq.com` 加入 `NO_PROXY`（不经过代理的地址列表），因为企业 HTTPS 代理通常无法转发这种连接。回复会通过同一条 socket 连接逐段发送，主动推送的消息采用 Markdown 格式。

运行时最多保留 1,000 个企业微信聊天的回复帧，即用于向该聊天继续发送回复的数据。如果某个聊天的回复帧已被清理，下一条等待发送的回复会一次完整发出，不再逐段更新。该聊天收到新消息后，会重新获得回复帧。

### Telegram {#telegram}

1. 在 Telegram 中找到「@BotFather」，发送 `/newbot`，将得到的 token（机器人访问令牌）复制到 nanoMuse。
2. 私聊可以直接使用。群聊需要先添加机器人。BotFather 的「Group Privacy」默认开启，此时机器人只会收到 @ 它的消息和对它自己消息的回复，与 *mention* 策略一致。
3. 如果运行 nanoMuse 的电脑无法访问 `api.telegram.org`，设置「代理」，格式为 `socks5://…` 或 `http://…`。

回复先发送，再随文字生成不断编辑原消息。超过 Telegram 的 4096 字符限制时会拆分为多条。审批消息包含两个可直接点击的按钮。

## 配对：决定谁能与机器人对话 {#pairing-who-may-talk-to-the-bot}

任何找到机器人的人都能给它发消息，但只有你允许的人才能让 nanoMuse 处理消息。

* 陌生人第一次私聊时，只会收到一个**配对码**，原消息不会交给 nanoMuse。配对码由六位字母和数字组成，不含容易混淆的 0/O/1/I，十分钟内有效。你可以在设置 → 聊天入口中批准，或运行 `nanomuse channels approve <code>`。对方会收到通知，此后发送的消息才会交给智能体。
* **免配对的 ID**（`allow_from`）：填入聊天平台的用户 id，这些用户无需配对码。单独填 `*` 会允许所有人，仅适合其他人无法访问的机器人。
* **群聊**：未获准的用户会被忽略，群内不会发送配对码。获准用户的消息在 `group_policy = "mention"` 时需要 @ 机器人，设为 `"open"` 则每条消息都会回答。每个群拥有独立对话，每条消息都附带发送者姓名。
* 在应用中「移除」已配对聊天，或从 `pairing.json` 删除该配对后，对方下次发消息时需要重新获取配对码。

配对关系和配对码保存在 `<data_dir>/channels/pairing.json`。这是数据目录，不是工作区，因此智能体自己的文件工具无法修改哪些人可以与它对话。

## 聊天如何对应到 nanoMuse 对话 {#how-a-chat-maps-to-the-muse}

每个聊天对应智能体的一段独立对话，id 为 `channel-<app>-<chat id>`，在应用抽屉中的标题类似「飞书 · Ann」或「Telegram · Team」。聊天软件收到的消息与 nanoMuse 应用中输入的消息使用同一个处理入口，因此记忆、目标、哨兵（Sentinel，检查操作风险和权限的组件）及技能等能力相同。照片、文件、语音等附件会保存在工作区的 `attachments/` 目录，并附在消息上。

任务执行时：

* 平台允许编辑消息时，回复会随模型输出逐段显示。
* 工具执行期间，同一条消息中会显示简短的斜体状态，例如「正在搜索网页」或「正在运行命令」，随后被回复文字替换。
* 哨兵要求你确认的**审批**会发送到聊天中。飞书和 Telegram 使用带「允许」「拒绝」按钮的卡片；钉钉和企业微信发送文字，让你回复关键词。`allow`、`yes`、`ok`、`允许`、`同意` 表示允许一次；`deny`、`no`、`拒绝`、`不行` 表示拒绝。效果与在 nanoMuse 应用中点击审批卡片相同。
* 任务生成的文件会在运行结束后发送，对应内部的构件事件。
* nanoMuse 提出的**问题**也会发送到聊天中，你的下一条消息会作为回答。

状态文字的语言由 `agent.language` 决定：`zh` 使用中文，`en` 使用英文，`auto` 同时提供两种语言。

## 推送到这里 {#deliver-here}

为已配对聊天开启「推送到这里」后，它还会接收主动消息，也就是手机应用会显示为通知的那些事件：后台任务的最终回复，设置为安静的任务除外；等待你决定的审批，可直接在聊天中回答；以及需要你回答的问题。同一个 nanoMuse 可以推送到多个聊天，每个聊天独立设置。`POST /api/channels/deliver {"text": …}` 会给所有启用推送的聊天发送文字，适合从脚本或提醒任务中调用。

## 安全 {#security}

* 密钥存入保险库，API 不会返回原文，配置文件只保存占位符。日志包含厂商错误信息，不包含连接凭据。
* 只有已配对或在允许名单中的用户能让 nanoMuse 处理消息。陌生人私聊只会收到配对码，在群聊中则不会得到回应。审批卡片也只接受已配对用户的按钮操作。
* 从聊天入口作出的审批仅限本次，记录的理由会注明「来自飞书」等来源，不会保存为长期授权。
* 聊天入口的数据保存在智能体无法访问的数据目录中。
* 所有连接都由运行时主动向外建立，不需要开放接收端口，也不需要公网 URL。

## 排查问题 {#troubleshooting}

| 你看到的情况 | 原因及处理方法 |
|---|---|
| 「未安装」 | 运行 nanoMuse 的电脑缺少 SDK。运行页面显示的命令，例如 `pip install 'nanomuse[feishu]'`，再开启聊天入口 |
| 「还缺设置」 | 某个必填字段为空，卡片会指出具体字段 |
| 「出错」，并显示厂商错误信息 | 凭据未通过验证，或无法连接厂商。修正后关闭再开启入口，或再次点击「保存」 |
| 群里的机器人不回答 | 群策略为 *mention*，但消息没有 @ 机器人；或者发送者尚未配对，群内不会显示配对码 |
| 飞书有回复，但没有表情回应或审批按钮 | 缺少 `im:message.group_at_msg:readonly`、`im:resource`，或没有为长连接配置 `card.action.trigger` |
| 飞书提示「app secret invalid」 | 控制台重新生成过 App Secret，需要填入新的值 |
| 钉钉连接成功但收不到消息 | 接收模式未设为 *Stream*，或版本尚未发布 |
| 企业微信在代理环境中连接失败 | socket 连接不经过 `HTTPS_PROXY`，对应主机必须能够直连 |
| Telegram 提示 `Conflict: terminated by other getUpdates request` | 两处正在使用同一个 token 接收消息，例如另一个运行时或 webhook（接收消息的回调接口）。只保留一处 |
| 反复收到配对码 | 需要在十分钟内批准一个配对码，可用 `nanomuse channels pending` 查看待处理列表 |
| `nanomuse channels …` 提示服务器拒绝 token | config.toml 中的 `server.token` 与正在运行的服务器不一致，或命令需要使用与服务器相同的 `--config` |

`nanomuse channels status --json` 输出的数据与应用页面读取的相同。
