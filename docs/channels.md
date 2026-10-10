# Chat apps

Your nanoMuse inside the chat apps you already use: Feishu (飞书 / Lark), DingTalk
(钉钉), WeCom (企业微信) and Telegram. Write to the bot from your phone and the same
Muse answers: one conversation per chat, the reply typed out as it comes, tool work
shown as a status line, approvals answered with a word or a button. Chats you mark
*deliver here* also get what the Muse does on its own: check-ins, reminders, the result
of a background task, the question it needs you to answer.

Nothing needs a public address. Each vendor offers a long connection the bot opens from
inside your network (Telegram: long polling), so the runtime behind your router or on a
laptop is enough. The vendors' own SDKs do the socket work; they are optional extras:

```sh
pip install 'nanomuse[feishu]'      # lark-oapi
pip install 'nanomuse[dingtalk]'    # dingtalk-stream
pip install 'nanomuse[wecom]'       # wecom-aibot-sdk-python
pip install 'nanomuse[channels]'    # all three; Telegram needs nothing extra
```

The Docker image carries all of them. Without an SDK the app shows the line to install
and leaves the switch alone.

## Where to find it

* **App**: Settings → *Chat apps* (「聊天入口」). One card per app: the switch, the
  credentials, who may talk to it, the paired chats and their *deliver here* switch,
  a *Send a test message* button and the setup steps with a link to the vendor console.
* **Terminal**: `nanomuse channels status | pending | approve <code> | deny <code> |
  login feishu [--lark] | test <name>`. With `nanomuse serve` running the commands go
  through its API; otherwise they edit the files under `<data_dir>/channels/` and the
  server picks them up when it starts (or on *Reload*).
* **API**: `GET /api/channels`, `PUT /api/channels/<name>`, `POST
  /api/channels/pairing/<code>/approve|deny`, `PUT|DELETE
  /api/channels/<name>/chats/<sender>`, `POST /api/channels/<name>/test`, `POST
  /api/channels/deliver {text}`, `POST /api/channels/reload`, and for Feishu `POST
  /api/channels/feishu/login` + `GET /api/channels/feishu/login/<device_code>`.
* **config.toml**: a `[channels.<name>]` table works too, for a server set up by hand:

  ```toml
  [channels.telegram]
  enabled = true
  bot_token = "${TELEGRAM_BOT_TOKEN}"
  allow_from = ["123456789"]      # Telegram user ids that never need a code
  group_policy = "mention"        # or "open"
  ```

  What the app saves wins per field. Secrets set in the app go to the vault
  (`{{vault:CHANNEL_TELEGRAM_BOT_TOKEN}}` stays in the file) and are never shown
  again; a secret field only says whether something is set.

## Setting up each app

The console names below are as of 2026; vendors move things around.

### Feishu / Lark

The short way: in the app press **Create the bot by QR code** (or run `nanomuse
channels login feishu`, `--lark` for the international edition), scan with Feishu,
confirm, done: the App ID and Secret are saved and the channel switches on. This is
Feishu's own scan-to-create flow for personal agents; it makes an app with the bot
capability and the long-connection events already set.

By hand, at <https://open.feishu.cn/app> (Lark: <https://open.larksuite.com/app>):

1. *Create custom app* → *Add capability* → **Bot**.
2. *Permissions*: `im:message`, `im:message.p2p_msg:readonly`,
   `im:message.group_at_msg:readonly`, `im:resource` (images and files).
3. *Events & callbacks*: subscription mode **Long connection**, add
   `im.message.receive_v1`; callback mode **Long connection**, add
   `card.action.trigger` (the approval buttons).
4. *Credentials & Basic Info*: copy **App ID** and **App Secret** into the app;
   pick *feishu* or *lark*. Leave *Encrypt Key* and *Verification Token* empty unless
   you set them in the console.
5. *Version management* → create a version → publish.

Replies are interactive cards with a markdown body; while a reply streams the card is
patched in place (about once a second). A 👍 on your message means the Muse is working
on it. In groups the bot answers when it is @-mentioned.

### DingTalk

At <https://open-dev.dingtalk.com/>:

1. *Create app* (企业内部应用) → *Add capability* → **Robot** (机器人).
2. Message receive mode: **Stream** (Stream 模式). No callback URL.
3. *Credentials & Basic Info* (凭证与基础信息): copy **Client ID** (AppKey) and
   **Client Secret** (AppSecret).
4. *Permissions*: the robot's send-message scope (`qyapi_robot_sendmsg`) so a
   *deliver here* chat can be written to without a message to reply to.
5. Publish the version; add the robot to a group or find it in the address book.

DingTalk messages cannot be edited, so a reply arrives once, when it is complete.
A robot in a DingTalk group only hears messages that @ it.

### WeCom

In the WeCom admin console (企业微信管理后台) → *Security & management* → **Intelligent
robot** (智能机器人):

1. *Create robot* → **API mode** (API 模式), connection **long connection** (长连接).
2. Copy the **Bot ID** and **Secret** into the app.
3. Add the robot to the chats where it should listen, or let people find it in the
   address book.

The socket host (`openws.work.weixin.qq.com`) is added to `NO_PROXY` for the runtime
process; a corporate HTTPS proxy usually cannot carry it. Replies stream over the same
socket; proactive messages (delivery) are markdown.

### Telegram

1. In Telegram talk to **@BotFather**, send `/newbot`, copy the token into the app.
2. Direct messages work at once. For a group, add the bot to it; with BotFather's
   *Group Privacy* on (the default) it only hears @-mentions and replies to its own
   messages, which matches the *mention* policy.
3. If `api.telegram.org` is out of reach from the computer, set **Proxy**
   (`socks5://…` or `http://…`).

Replies are sent and then edited in place while they stream (Telegram's 4096-character
limit splits long ones). Approvals are two inline buttons.

## Pairing: who may talk to the bot

Anyone who finds the bot can write to it; the Muse answers only people you let in.

* The first direct message from an unknown person gets a **pairing code** (six
  letters and digits, no 0/O/1/I, good for ten minutes) and nothing else; the
  message does not reach the Muse. Approve the code under Settings → Chat apps, or
  `nanomuse channels approve <code>`. The person is told, and from then on their
  messages go through.
* **Always allowed** (`allow_from`): vendor user ids that never need a code. A lone
  `*` lets everyone in, only for a bot nobody else can reach.
* **Groups**: unknown people in a group are ignored quietly (no codes in groups). An
  approved person's group message is answered when the bot is @-mentioned
  (`group_policy = "mention"`), or on every message (`"open"`). The group is its own
  conversation; the sender's name travels with each line.
* **Remove** a paired chat in the app (or delete it from `pairing.json`); the next
  message gets a new code.

Pairings and codes live in `<data_dir>/channels/pairing.json` (the data directory,
not the workspace), so the agent's own file tools cannot change who may talk to it.

## How a chat maps to the Muse

Each chat is one conversation of the agent, with the id
`channel-<app>-<chat id>` and the title *Feishu · Ann* / *Telegram · Team* in the app's
drawer. A message from the chat goes through the same entry point as a message typed in
the app, so everything else (memory, goals, the Sentinel, skills) is the same Muse.
Attachments (photos, files, voice notes) are saved under the workspace's `attachments/`
and attached to the message.

While the run works:

* text streams into the reply as the model writes (where the vendor allows edits);
* a running tool shows as a short italic line in the same message ("Searching the
  web", 正在运行命令) until text replaces it;
* an **approval** the Sentinel asks for arrives in the chat: a card with 允许 / 拒绝
  buttons on Feishu and Telegram, a message asking for the word on DingTalk and WeCom.
  `allow`, `yes`, `ok`, `允许`, `同意` approve once; `deny`, `no`, `拒绝`, `不行` refuse.
  The decision is the same as pressing the card in the app;
* files the run produced (an artifact event) are sent when the run ends;
* a **question** the Muse asks is delivered, and your next line answers it.

Language follows `agent.language`: `zh` for Chinese lines, `en` for English, `auto` for
both.

## Deliver here

Switch *Deliver here* on for a paired chat and it also receives what the Muse does
without being asked, the same events the phone app turns into notifications: a
background run's final words (quiet ones excepted), an approval that is waiting (answer
it from the chat), a question that needs you. One Muse may deliver to several chats;
each decides for itself. `POST /api/channels/deliver {"text": …}` sends a line to all
of them, useful from a script or a reminder.

## Security

* Secrets go to the vault and never come back out of the API; the settings file holds
  placeholders. Logs carry the vendor's error text, not credentials.
* Only paired or allow-listed people reach the Muse; unknown people get a code, or
  silence in a group. A button press on an approval card is honoured only from a
  paired person.
* An approval from a chat is a *once* decision with the reason "from Feishu" (etc.);
  nothing is remembered from a chat.
* The channel data lives in the data directory, outside the agent's reach.
* The connections are outbound only; no port is opened and no public URL is involved.

## Troubleshooting

| What you see | What it means |
|---|---|
| **Not installed** | the SDK is missing on the machine running nanoMuse: run the line shown (`pip install 'nanomuse[feishu]'`), then switch the channel on again |
| **Needs settings** | a required field is empty; the card names it |
| **Error** with the vendor's words | the credentials were refused or the vendor is unreachable; fix and switch off/on, or *Save* again |
| the bot does not answer in a group | the group policy is *mention* and the bot was not @-mentioned; or the sender is not paired (groups never show codes) |
| Feishu replies but no reaction / no card buttons | missing `im:message.group_at_msg:readonly` / `im:resource`, or `card.action.trigger` is not on the long connection |
| Feishu: "app secret invalid" | the App Secret was regenerated in the console; paste the new one |
| DingTalk connects but gets nothing | the robot's receive mode is not *Stream*, or the version was not published |
| WeCom: connection errors behind a proxy | the socket bypasses `HTTPS_PROXY`; the host must be reachable directly |
| Telegram: `Conflict: terminated by other getUpdates request` | the same token is polled from two places (another runtime, or a webhook); use one |
| codes keep coming back | approve one within ten minutes; `nanomuse channels pending` lists them |
| `nanomuse channels …` says the server refused the token | `server.token` in config.toml differs from the running server's; or run it with the same `--config` |

`nanomuse channels status --json` prints the same view the app gets.
