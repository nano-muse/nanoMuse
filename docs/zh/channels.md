# 聊天入口

把你的 nanoMuse 放进你已经在用的聊天软件：飞书 / Lark、钉钉、企业微信和 Telegram。在手机上给机器人发消息，回答的就是同一个 Muse：每个聊天对应一个对话，回复边生成边发回来，工具在跑时显示一行状态，审批用一个词或一个按钮回答。标了「推送到这里」的聊天还会收到 Muse 自己主动做的事：问候、提醒、后台任务的结果、它需要你回答的问题。

不需要公网地址。每家都提供一种由机器人从你的网络内部主动发起的长连接（Telegram 是长轮询），所以运行时放在路由器后面或一台笔记本上就够了。socket 的活由各家自己的 SDK 来干；它们是可选的额外依赖：

```sh
pip install 'nanomuse[feishu]'      # lark-oapi
pip install 'nanomuse[dingtalk]'    # dingtalk-stream
pip install 'nanomuse[wecom]'       # wecom-aibot-sdk-python
pip install 'nanomuse[channels]'    # all three; Telegram needs nothing extra
```

Docker 镜像带全了这些。没装 SDK 时，应用会显示要安装的那行命令，开关保持不动。

## 在哪里找到它 {#where-to-find-it}

* **应用**：设置 → 「聊天入口」。每个聊天软件一张卡片：开关、凭据、谁可以和它说话、已配对的聊天和各自的「推送到这里」开关、一个「发一条测试消息」按钮，还有设置步骤和指向厂商控制台的链接。
* **终端**：`nanomuse channels status | pending | approve <code> | deny <code> | login feishu [--lark] | test <name>`。`nanomuse serve` 在跑时，这些命令走它的 API；否则它们直接改 `<data_dir>/channels/` 下的文件，服务器启动时（或按「重新加载」时）读入。
* **API**：`GET /api/channels`、`PUT /api/channels/<name>`、`POST /api/channels/pairing/<code>/approve|deny`、`PUT|DELETE /api/channels/<name>/chats/<sender>`、`POST /api/channels/<name>/test`、`POST /api/channels/deliver {text}`、`POST /api/channels/reload`，飞书还有 `POST /api/channels/feishu/login` + `GET /api/channels/feishu/login/<device_code>`。
* **config.toml**：手工搭的服务器也可以写一张 `[channels.<name>]` 表：

  ```toml
  [channels.telegram]
  enabled = true
  bot_token = "${TELEGRAM_BOT_TOKEN}"
  allow_from = ["123456789"]      # Telegram user ids that never need a code
  group_policy = "mention"        # or "open"
  ```

  应用里保存的值按字段优先。在应用里填的密钥进保险库（文件里留的是 `{{vault:CHANNEL_TELEGRAM_BOT_TOKEN}}`），之后不再显示；密钥字段只告诉你有没有填过。

## 逐个设置 {#setting-up-each-app}

下面的控制台名称是 2026 年时的叫法；厂商会挪地方。

### 飞书 / Lark {#feishu-lark}

最快的办法：在应用里按「扫码创建机器人」（或运行 `nanomuse channels login feishu`，国际版加 `--lark`），用飞书扫码，确认，完成；App ID 和 Secret 已经保存，这个入口随即打开。这是飞书自己为个人智能体提供的扫码建应用流程；它创建出来的应用已经带上机器人能力和长连接事件。

手动的话，到 <https://open.feishu.cn/app>（Lark：<https://open.larksuite.com/app>）：

1. 「创建企业自建应用」→「添加应用能力」→ **机器人**。
2. 「权限管理」：`im:message`、`im:message.p2p_msg:readonly`、`im:message.group_at_msg:readonly`、`im:resource`（图片和文件）。
3. 「事件与回调」：订阅方式选 **长连接**，添加 `im.message.receive_v1`；回调方式选 **长连接**，添加 `card.action.trigger`（审批按钮）。
4. 「凭证与基础信息」：把 **App ID** 和 **App Secret** 复制到应用里；选 *feishu* 或 *lark*。「Encrypt Key」和「Verification Token」留空，除非你在控制台里设了。
5. 「版本管理与发布」→ 创建版本 → 发布。

回复是带 markdown 正文的可交互卡片；回复流式生成时，卡片原地更新（大约每秒一次）。你的消息上出现一个 👍，表示 Muse 正在处理。群里 @ 它才回答。

### 钉钉 {#dingtalk}

到 <https://open-dev.dingtalk.com/>：

1. 「创建应用」（企业内部应用）→「添加应用能力」→ **机器人**。
2. 消息接收模式：**Stream 模式**。不需要回调地址。
3. 「凭证与基础信息」：复制 **Client ID**（AppKey）和 **Client Secret**（AppSecret）。
4. 「权限管理」：机器人发消息的权限（`qyapi_robot_sendmsg`），这样「推送到这里」的聊天在没有消息可回复时也能写入。
5. 发布版本；把机器人加进群，或在通讯录里找到它。

钉钉消息不能编辑，所以回复在写完后一次发出。钉钉群里的机器人只听得到 @ 它的消息。

### 企业微信 {#wecom}

在企业微信管理后台 →「安全与管理」→ **智能机器人**：

1. 「创建机器人」→ **API 模式**，连接方式选 **长连接**。
2. 把 **Bot ID** 和 **Secret** 复制到应用里。
3. 把机器人加进它该听的聊天，或者让大家在通讯录里找到它。

socket 主机（`openws.work.weixin.qq.com`）已加进运行时进程的 `NO_PROXY`；公司的 HTTPS 代理通常带不动它。回复经同一个 socket 流式返回；主动消息（推送）是 markdown。

### Telegram {#telegram}

1. 在 Telegram 里找 **@BotFather**，发 `/newbot`，把 token 复制到应用里。
2. 私聊立刻可用。群聊要先把机器人拉进群；BotFather 的「Group Privacy」开着（默认）时，它只听得到 @ 它的消息和对它自己消息的回复，正好对应 *mention* 策略。
3. 这台电脑连不上 `api.telegram.org` 的话，填 **代理**（`socks5://…` 或 `http://…`）。

回复先发出，再在流式生成时原地编辑（超过 Telegram 的 4096 字符上限会拆成几条）。审批是两个内联按钮。

## 配对：谁可以和机器人说话 {#pairing-who-may-talk-to-the-bot}

找到机器人的人都能给它发消息；Muse 只回答你放进来的人。

* 陌生人的第一条私聊只会得到一个**配对码**（六位字母和数字，不含 0/O/1/I，十分钟有效），别的什么都没有；这条消息不会到 Muse。在 设置 → 聊天入口 里通过这个码，或者运行 `nanomuse channels approve <code>`。对方会收到通知，此后的消息就通了。
* **免配对的 ID**（`allow_from`）：不需要配对码的厂商用户 id。单独一个 `*` 放行所有人，只适合别人都找不到的机器人。
* **群**：群里的陌生人被静静忽略（群里不发配对码）。已配对的人在群里的消息，机器人被 @ 时才回答（`group_policy = "mention"`），或者每条都回（`"open"`）。群本身是一个独立的对话；每一行都带着发送者的名字。
* 在应用里**移除**一个已配对的聊天（或从 `pairing.json` 里删掉）；对方的下一条消息会收到新的配对码。

配对关系和配对码存在 `<data_dir>/channels/pairing.json`（在数据目录，不在工作区），所以智能体自己的文件工具改不了谁可以和它说话。

## 聊天怎么对应到 Muse {#how-a-chat-maps-to-the-muse}

每个聊天是智能体的一个对话，id 是 `channel-<app>-<chat id>`，在应用抽屉里的标题是「飞书 · Ann」/「Telegram · Team」。来自聊天的消息和在应用里打的字走同一个入口，所以其他一切，记忆、目标、哨兵（Sentinel）、技能，都是同一个 Muse。附件（照片、文件、语音）保存在工作区的 `attachments/` 下，并附在消息上。

运行进行时：

* 文字随着模型的输出流进回复（厂商允许编辑的地方）；
* 正在运行的工具在同一条消息里显示为一行斜体短句（「正在搜索网页」「正在运行命令」），直到被文字替换；
* 哨兵要求的**审批**会到聊天里：飞书和 Telegram 是带「允许」/「拒绝」按钮的卡片，钉钉和企业微信是一条要你回一个词的消息。`allow`、`yes`、`ok`、`允许`、`同意` 是允许一次；`deny`、`no`、`拒绝`、`不行` 是拒绝。这个决定和在应用里按卡片是一样的；
* 运行产生的文件（构件事件）在运行结束时发出；
* Muse 提出的**问题**会送到聊天里，你的下一行就是回答。

语言跟随 `agent.language`：`zh` 时这些短句是中文，`en` 是英文，`auto` 两种都有。

## 推送到这里 {#deliver-here}

给一个已配对的聊天打开「推送到这里」，它还会收到 Muse 没被要求也会做的事，也就是手机 App 变成通知的那些事件：后台运行的最后一句话（安静的除外）、等待中的审批（可以直接在聊天里回答）、需要你的问题。一个 Muse 可以推送到好几个聊天；每个聊天自己决定。`POST /api/channels/deliver {"text": …}` 给它们全部发一行字，脚本或提醒里用得上。

## 安全 {#security}

* 密钥进保险库，从不经 API 回传；设置文件里只有占位符。日志里是厂商的错误原文，不含凭据。
* 只有已配对或在放行名单里的人能到达 Muse；陌生人得到一个配对码，在群里则是沉默。审批卡片上的按钮，只有已配对的人按才算数。
* 来自聊天的审批是一次性的决定，理由是「来自飞书」（等等）；聊天里不会记住任何东西。
* 聊天入口的数据放在数据目录，智能体够不着。
* 连接都是向外发起的；不开端口，不涉及公网地址。

## 排错 {#troubleshooting}

| 你看到的 | 意思 |
|---|---|
| **未安装** | 运行 nanoMuse 的机器上缺 SDK：运行显示的那行（`pip install 'nanomuse[feishu]'`），再把这个入口重新打开 |
| **还缺设置** | 有必填项是空的；卡片会写明是哪一项 |
| **出错**，后面是厂商的原话 | 凭据被拒，或连不上厂商；改好后关掉再开，或再按一次「保存」 |
| 机器人在群里不回答 | 群策略是 *mention* 而机器人没被 @；或者发送者没有配对（群里从不显示配对码） |
| 飞书有回复，但没有表情回应 / 卡片没有按钮 | 缺 `im:message.group_at_msg:readonly` / `im:resource`，或者 `card.action.trigger` 没有放在长连接上 |
| 飞书：「app secret invalid」 | App Secret 在控制台里被重新生成了；贴新的 |
| 钉钉连上了但收不到东西 | 机器人的接收模式不是 *Stream*，或者版本没有发布 |
| 企业微信：代理后面连接出错 | socket 绕开了 `HTTPS_PROXY`；主机必须能直连 |
| Telegram：`Conflict: terminated by other getUpdates request` | 同一个 token 在两处轮询（另一个运行时，或一个 webhook）；只留一个 |
| 配对码一直来 | 十分钟内通过一个；`nanomuse channels pending` 列出全部 |
| `nanomuse channels …` 说服务器拒绝了 token | config.toml 里的 `server.token` 和正在跑的服务器的不一致；或者用同一个 `--config` 运行它 |

`nanomuse channels status --json` 输出的和应用看到的是同一份。
