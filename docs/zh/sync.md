# 手机上留着什么，又是谁的

一部手机今天可以登录一个账号，明天换另一个：家里共用的平板，转手的手机，有两个账号的测试者。这一页是一张表：nanoMuse 的手机 App 在手机上保存的每一项状态，存在哪里，属于**账号**、**设备**，还是谁都不属于，以及在四个事件上各会发生什么：*退出登录*、*切换*（以另一个账号登录）、*删除账号*和*重装*。约定 C12，0.1.40；更早的、只针对对话的规则（C10，0.1.39）在 [every-device.md](every-device.md#whose-conversations-a-device-shows)。

## 规则 {#the-rule}

- **每一场聊天都有主人。** 这场聊天第一次在这部手机上出现时登录着的那个账号；在登出状态下创建的聊天，主人是*无*。0.1.40 之前的聊天，在更新后的 App 第一次运行时按同一规则认领：归当时登录着的账号（已经同步过的聊天，保留它同步映射里记的那个账号），否则归无人。
- **你只看到当前登录的主人的聊天**：抽屉、搜索、聊天标签页、资源库、「今天的聊天」、Siri 快捷指令，以及上传到中继的内容，都是如此。登出状态下只显示登出时创建的聊天；每个账号的都看不见。
- **退出登录只问一个问题**：「把这个账号的聊天留在这台设备上」，**默认关**。关着时，这个账号的聊天、记忆、动态、目标、例程和形象从手机上移除；开着同步的话，中继仍然保存着聊天，等下次登录。开着时，这些全部放到这个账号自己的一个文件夹里，账号再登录时原样回来。换一个账号登录，以及「使用其他服务器」，都走同一个退出登录流程。
- **删除账号**会在中继删掉它，并把它的一切从手机上移除，不问任何问题：没有什么可以回来的了。之后用同一个地址登录是一个新账号，从零开始。
- **被中继拒绝的 key**（另一台设备上的「在所有设备退出」、中继重置、中继的 bug：这部手机上谁都没要求过的一个 `401`）是一次没人能回答的退出登录，所以手机用谨慎的方式回答：账号的数据**保留**，和「把这个账号的聊天留在这台设备上」的效果完全一样（聊天藏在它们的主人行后面，文件和偏好放到账号的文件夹下，中继 key 被移除），登录页写着「这台手机上的登录已结束。重新登录即可继续；在那之前，你的聊天会留在这台设备上。」下一次用**同一个账号 id** 登录就全部恢复；换一个账号什么都看不到。只有中继回答 `401 account_deleted`（账号本身已经不存在了）才真的没有什么可以回来的，这时手机像「删除账号」那样移除数据。
- **重装从零开始。** 在 Android 上，App 不再参与设备备份（`allowBackup="false"`）：它的东西一点也不会复制到 Google，全新安装没有聊天、没有记忆、没有 key。在 iPhone 上，全新安装（UserDefaults 里没有标记，没有服务商，没有聊天）会删掉上一次安装留下的仅限本机的钥匙串条目（中继的 key、OAuth 令牌、环境变量）；中继的 key 只保存在设备上，从不进 iCloud 钥匙串，0.1.39 的 key 在第一次启动时会挪到那里。从本人自己的 iPhone 备份恢复会把 UserDefaults 和文件一起带回来，标记也在，视为同一次安装。
- **账号的键是中继那个不透明的 `account.id`**，从来不是手机号或邮箱地址；磁盘上的文件夹名是它的哈希。归类的任何一步都不涉及中继：旧版中继的行为也一样。

## Android {#android}

路径都在 App 私有的 `files/` 下；偏好项若未注明，都在 `nanomuse` 这个 SharedPreferences 文件里。*清除*指移除；*搁置*指移到 `minis-global/nanomuse/accounts/<key>/` 下，账号回来时恢复；*保留*指不动。「key 被拒」一列先读 `bad_key`（或任何其他 `401`），再读 `account_deleted`。

| 状态 | 位置 | 属于谁 | 退出登录（保留关 / 开） | 切换 | key 被拒（`bad_key` / `account_deleted`） | 删除账号 | 重装 |
|---|---|---|---|---|---|---|---|
| 聊天、消息、附件、手的轨迹 | 上游的 `minis.db`、`minis-sessions/<id>/` | 账号（`nanomuse_sync.db` → `session_owners` 里的主人行） | 清除 / 保留并隐藏 | 同退出登录，然后显示新账号的 | 保留并隐藏 / 清除 | 清除 | 没了（无备份） |
| 登出状态下创建的聊天 | 同上 | 无（`""`） | 登录期间搁置，登出后回来 | 搁置 | 回来 / 回来 | 保留 | 没了 |
| 同步映射（cid、游标、已知 mid） | `nanomuse_sync.db` | 账号 | 随聊天清除 / 保留 | 为离开的账号保留 | 保留 / 清除 | 清除 | 没了 |
| Muse 记得的东西（SOUL.md、USER.md、GLOBAL.md、日记） | `minis-global/memory/` | 账号 | 清除 / 搁置 | 搁置；新账号的回来，或者为空 | 搁置 / 清除 | 清除 | 没了 |
| 动态的帖子和偏好 | `minis-global/nanomuse/feed/`、`feed-preferences.md` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 目标 | `minis-global/nanomuse/goals.json` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 例程（定时任务，包括动态和目标的） | `minis_scheduled_tasks_prefs` | 账号 | 闹钟关掉，清除 / 搁置（`routines.json`） | 搁置 | 闹钟关掉，搁置 / 清除 | 清除 | 没了 |
| 形象 | `minis-global/nanomuse/avatar/` | 账号（中继的资料里也有） | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 共享工作区 | `minis-global/shared/` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 主要聊天、第一场对话、动态开关 | 偏好项 `main_chat.*`、`first_conversation.*`、`feed.*` | 账号 | 清除 / 搁置（`prefs.json`） | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 中继 key、账号 id、额度、模型 | 服务商存储（key 加密）、偏好项 `cloud.*` 和 `nanomuse` 里的账号行 | 账号 | 清除 | 替换 | 清除 / 清除 | 清除 | 没了 |
| 设备名和在 hub 的在场状态 | `minis_device_identity`、偏好项 `hub.*` | 设备 | 保留 | 保留 | 保留 / 保留 | 保留 | 新身份 |
| 记住的审批 | `minis-global/nanomuse/grants.json` | 设备 | 保留（按聊天的：随聊天清除） | 保留 | 保留 / 保留（按聊天的：随聊天清除） | 保留 | 没了 |
| 你自己的服务商和 key、外观、手、语言 | 上游的存储 | 设备 | 保留 | 保留 | 保留 / 保留 | 保留 | 没了 |
| 点子 | App 资源 | 无 | — | — | — | — | — |

代码：`io.github.nanomuse.account.AccountScope`（规则，有单元测试），`AccountData`（应用规则：`reconcile`、`leave`、`enter`），`SyncEntities.kt` 里的 `session_owners` 表，`ConversationSync.hidden`（每个列表都略过的内容），`ChatRepository.createSession` 和 `MinisApp` 里的钩子，`CloudAccountScreen` 里的底部面板。

## iPhone 和 iPad {#iphone-and-ipad}

路径都在 App 的沙箱里：Application Support，或 App 群组的 `MinisConfig/` 和 `var/minis/`。*搁置*指移到 `MinisConfig/nanomuse/accounts/<hash>/` 下。「key 被拒」一列的读法和 Android 一样：先 `bad_key`，再 `account_deleted`。

| 状态 | 位置 | 属于谁 | 退出登录（保留关 / 开） | 切换 | key 被拒（`bad_key` / `account_deleted`） | 删除账号 | 重装 |
|---|---|---|---|---|---|---|---|
| 聊天、消息、媒体 | 上游的 SQLite 存储 | 账号（`nanomuse-owners.json` 里的主人行） | 清除 / 保留并隐藏 | 同退出登录，然后显示新账号的 | 保留并隐藏 / 清除 | 清除 | 没了 |
| 登出状态下创建的聊天 | 同上 | 无 | 登录期间搁置，登出后回来 | 搁置 | 回来 / 回来 | 保留 | 没了 |
| 同步表（按账号：cid、游标、已知 mid） | `nanomuse-sync-accounts.json` | 账号 | 随聊天清除 / 保留 | 为离开的账号保留 | 保留 / 清除 | 清除 | 没了 |
| Muse 记得的东西 | App 群组的 `memory/` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 动态的帖子和偏好 | `MinisConfig/nanomuse/feed/`、`feed-preferences.md` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 目标 | `MinisConfig/nanomuse/goals.json` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 例程 | `MinisConfig/nanomuse/routines.json` | 账号 | 通知关掉，清除 / 搁置 | 搁置 | 通知关掉，搁置 / 清除 | 清除 | 没了 |
| 形象（静态图；短视频会重新生成） | Application Support 的 `nanomuse/avatar/` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 共享工作区 | App 群组的 `shared/` | 账号 | 清除 / 搁置 | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 主要聊天、第一场对话、动态开关 | UserDefaults `nanomuse.main_chat.*`、`nanomuse.first_conversation.*`、`nanomuse.feed.*` | 账号 | 清除 / 搁置（`defaults.plist`） | 搁置 | 搁置 / 清除 | 清除 | 没了 |
| 中继 key | 钥匙串，仅限本机（`…ThisDeviceOnly`，不可同步） | 账号 | 清除 | 替换 | 清除 / 清除 | 清除 | 第一次启动时清扫 |
| 账号 id、额度、模型、地区 | UserDefaults `nanomuse.cloud.*`、服务商存储 | 账号 | 清除 | 替换 | 清除 / 清除 | 清除 | 没了 |
| 在 hub 的设备 id 和名字 | UserDefaults `nanomuse.hub.*`、钥匙串 `…app.device` | 设备 | 保留 | 保留 | 保留 / 保留 | 保留 | 新身份 |
| 你自己的服务商和 key | 服务商存储；key 在钥匙串里，可同步（上游的选择） | 设备 | 保留 | 保留 | 保留 / 保留 | 保留 | 配置没了；可同步的 key 留在本人的 iCloud 钥匙串里 |
| 外观、星标、引导标志 | UserDefaults | 设备 | 保留 | 保留 | 保留 / 保留 | 保留 | 没了 |

**iCloud。** 上游自己的聊天和服务商 iCloud 同步（「设置 → iCloud」，默认关）和 iCloud 钥匙串属于本人的 Apple ID，不属于账号。上游的 iCloud 同步开着时，退出登录删掉的聊天会像手动删除的聊天一样通过它删掉，而搁置的聊天可能不带主人行就到了本人的另一部 iPhone 上；在那部手机上，它归那里登录着的人。主人文件、同步表和搁置的文件夹，和 App 的其他数据一样在 iPhone 的设备备份里。

代码：`NanoMuse/NanoMuseAccountData.swift`（主人、`leave`、`enter`、钥匙串），`NanoMuseSync.shows` 和 `dropTable`，`NanoMuseSignOutSheet.swift`，`ChatStore.createSession` 和 `NanoMuseShell` 里的钩子。

## 中继 {#the-relay}

`POST /v1/auth/delete` 删除这个账号的每一行：账号本身、它的 key、设备、资料（名字、形象、连接器）、账本、事件、「数据控制」保留的对话和视频任务、同步的对话、消息和游标。它还断开这个账号的 hub 连接，而且从随 0.1.40 发布的中继起，也会忘掉这个账号的实时「正在处理」提示（它们在内存里，不是行）。中继的测试会注册一个账号，填满每张表，删掉它，再检查每张表里属于它的行都是零，并且同一个地址再注册会拿到新的账号 id 和一个空的同步存储。

有一样东西会在账号之后多活一阵：它持有过的 key 的 SHA-256 哈希，放在 `deleted_keys` 里，保留 90 天。它们指不出任何人（没有账号 id，没有地址，没有设备），而它们让一部仍握着其中一把 key 的手机听到的是 `401 account_deleted` 而不是 `401 bad_key`，这就是*移除账号的数据，没有什么可以回来的了*和*搁置起来，这个人可能还会再登录*之间的区别。0.1.40 之前的中继对两种情况都回答 `bad_key`，手机就保留数据；什么都不会丢，文件夹只是在等。

## 给维护者 {#for-the-maintainers}

0.1.39 里有人删除账号后还能看到的旧记录，是手机自己的：一场没有同步映射的聊天（旁聊开关关着时的旁聊、0.1.39 之前的聊天）没有主人，于是在每个账号下都显示，还会被推到下一个账号名下。中继那边早已删掉了自己的部分。C12 给每一场聊天一个主人，并让退出登录把账号的数据一起带走，除非明确要求不带。
