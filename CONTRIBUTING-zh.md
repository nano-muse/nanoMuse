# 贡献指南

提交一个 issue 或发送一个 pull request 都可以帮助 nanoMuse 变得更好。先用 nanoMuse 完成一项真实任务，报告遇到的问题，然后挑一件范围明确的事情来做。除了小修复，其他改动请先提交 issue，让我们先就方案形态达成一致。[docs/roadmap.md](docs/roadmap.md) 说明了哪些地方需要帮助，以及各个领域该从哪里开始。如果有简单问题，或者想在整理成文字之前先讨论一个想法，可以加入 [Discord](https://discord.gg/bkTySmm28X)；不过决定仍会记录在 issue 和 pull request 里，方便以后查找。

[AGENTS.md](AGENTS.md) 是这份文件的简版，面向编程助手和赶时间的人：一屏之内说明目录结构、各领域的检查命令，以及下面的约定。两份文件必须保持一致；如果不一致，请同时修正。

## 两棵代码树

- **`android/`**：手机应用。这是用 `git subtree` 引入的 [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 修改副本（GPL-3.0）：Android 应用位于 `android/src/android`，iOS 应用位于 `android/src/ios`。这里沿用上游规则（见下文），以确保这棵子树仍可拉取。
- **其余部分都是我们的**：Python 运行时（`nanomuse/`）、中继（`cloud/`）、网页控制台（`web/`）、桌面版（`harness/dsh-nanomuse/`，以及 `harness/desktop/` 中的 Electron 外壳）、展示站（`demo/`）、文档（`docs/`，由 `website/` 提供服务）和脚本。这里只使用本文件中的一套约定；[AGENTS.md](AGENTS.md) 给出了各领域的检查命令，[docs/architecture.md](docs/architecture.md) 说明了各部分如何衔接。[docs/roadmap.md](docs/roadmap.md) 说明了哪个版本带来了什么，以及哪些地方需要帮助。

## 许可证与签署

nanoMuse 采用 **GPL-3.0-or-later**（[LICENSE](LICENSE)、[NOTICE](NOTICE)）。提交贡献即表示你同意自己的贡献也按相同许可证授权。每次提交都必须带有 [Developer Certificate of Origin](https://developercertificate.org) 签署；`git commit -s` 会添加这一行：

```
Signed-off-by: Your Name <you@example.com>
```

CI 会检查这项内容。以下内容一律不接受：

- 采用无法与 GPL-3.0 组合的许可证的代码（`GPL-2.0-only`、SSPL、BUSL、“源码可用”许可证、专有 SDK）；
- 通过反编译、解包、拦截或抓取 Meta Muse 应用（包括其系统提示词）获得的内容，或者超出 OpenMinis 源码已公开范围的二进制内容；
- 把 OpenMinis 或 Meta Muse 的名称和徽标作为 nanoMuse 自身身份的一部分（About 页面和 NOTICE 中的署名是必要内容，会保留），以及 Meta 的品牌截图；
- 内部规划材料：预算、容量估算、宣传草稿。仓库只保存实际运行的内容和解释这些内容所需的信息。

## 在 `android/` 中工作

上游是私有代码树的镜像，大约每月压缩成一个提交，并且不接受 pull request。每个版本我们都必须能够执行 `git subtree pull`，因此：

1. **不要重命名 Kotlin 包** `com.openminis.app` 或 Gradle `namespace`。只有 `applicationId`（`io.github.nanomuse.app`）属于我们。
2. **不要重命名根文件系统内的沙箱路径或 CLI 名称**（`/var/minis`、`minis-global`、`minis-open`、`minis-mcp-cli`、`android-*`）。这些是上游与自己约定的接口。
3. **新代码放在新文件里**：使用 `io.github.nanomuse.*` 包，或者在上游文件旁新建文件。必须修改上游文件时，在修改位置添加 `// nanoMuse:` 注释，并且每个位置只做一处修改。
4. **品牌替换由脚本完成，不手工修改。** `scripts/rebrand.py`（名称、ID、颜色、链接，覆盖 Android 和 iOS）、`scripts/gen-android-icons.py` 和 `scripts/gen-ios-icons.py`（图标）都是幂等的；每次拉取上游后都运行一次。品牌替换有遗漏时，修改脚本，不要手工修补。
5. **二进制资源**（图标 PNG）会以上游名称覆盖；拉取发生冲突时采用我们的版本（`git checkout --ours`）。
6. **iOS 遵循相同规则。** 上游的 iOS 部分位于 `android/src/ios`（见 [docs/ios.md](docs/ios.md)）；我们的 Swift 代码放在 `android/src/ios/NanoMuse/`，修改上游 Swift 文件时在修改位置添加 `// nanoMuse:` 注释。

构建步骤见 [android/BUILDING.md](android/BUILDING.md)（上游）以及 `scripts/android/` 中本仓库使用的工具链说明：JDK 21、SDK CMake 3.22.1、NDK r27c、Go 1.25+、`gomobile`。`android/deps/build_proot.sh` 从 `android/deps/proot` 子模块（我们的分支；使用可移植的 `awk`，不需要 gawk）构建 proot，并且必须在 `android/scripts/prepare_android_sandbox.sh` 之前运行。

### 拉取上游版本

```bash
git fetch openminis --tags
git subtree pull --prefix=android openminis 1.14 -m "Merge OpenMinis 1.14"
git checkout --ours -- 'android/src/android/app/src/main/res/mipmap-*' \
    'android/src/ios/Assets.xcassets/AppIcon.appiconset' 'android/src/ios/Resources/AlternateIcons'
python scripts/rebrand.py && python scripts/gen-android-icons.py && python scripts/gen-ios-icons.py
# resolve the remaining conflicts at the `// nanoMuse:` marks, build, run the smoke list
```

## 在运行时、中继和网页控制台中工作

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"            # add ",browser" for the Playwright tool
nanomuse config init                  # config/config.toml is git-ignored
```

推送之前：

```bash
ruff check nanomuse tests scripts && ruff format nanomuse tests scripts
mypy                                           # types; config in pyproject.toml
python -m pytest -q                            # MockLLM only, no network
cd web && npm run check && npm run build       # if you touched web/; commit the build
cd cloud && pip install -e ".[dev]" && ruff check . && ruff format --check . && pytest   # if you touched the relay
```

桌面版、Electron 外壳和文档站各自在 [AGENTS.md](AGENTS.md) 中有对应的检查命令。适用于所有领域的准则：所有会执行动作的操作都必须经过哨兵（Sentinel），并如实标注 `risk`；密钥绝不能传给模型（`{{vault:NAME}}`）；使用 `MockLLM` 测试；仓库中不得出现内部端点或密钥；使用 Ruff，行宽为 100，并添加类型标注；文档也是改动的一部分。

## 每种语言中的所有字符串

nanoMuse 在多个国家使用，因此用户可见的字符串不能只添加一种语言。先写英文，再写简体中文，然后补齐文件已有的其他所有语言：Android 的 `res/values-*/nm_strings.xml`（键名以 `nm_` 开头；上游的 `strings.xml` 不归我们编辑）、iOS 的 `Localizable.xcstrings`、桌面版 `harness/dsh-nanomuse/src/client/locales.ts` 中的 `en` 和 `zh`，以及 `cloud/` 中的控制台和电子邮件模板。日期、数字和货币使用用户所在地区的格式。不要假定手机号以 +86 开头、应用是中文界面或时区是北京时间：短信验证码只能发到中国大陆手机号，因此登录界面要说明这一点，并提供电子邮件方式。所有语言使用相同的语气（平实、具体，不使用营销词，不使用感叹号），也不要逐字照抄 Meta 自己的界面文案。应用和文档中的新文案不得使用长破折号或短破折号：逗号、冒号、括号或句号就能表达清楚；只有数据中的短横线才会保留（表格中的数字范围、代码示例、引用的日志行）。中文文案要按中文来写，不能逐字照搬英文，并避免使用颠覆、王炸、保姆级、一键和赋能；术语以本文下方的术语表为准。

## 翻译文档

文档站（nanomuse.cn/docs，由 `website/` 根据 `docs/` 构建）提供英文和简体中文。中文页面位于 `docs/zh/`，**文件名与英文页面相同**（`docs/zh/android.md` 对应 `docs/android.md`），中文导航和侧边栏在 `website/.vitepress/config.mts` 中配置。修改英文页面时，要在同一个 pull request 中更新对应的中文页面；新增英文页面时，要新增中文页面，并在两个侧边栏中都添加条目。`cd website && npm run docs:build` 是两种语言的死链检查。

中文页面的规则：

- 事实必须与英文页面完全相同：版本号、路径、命令、配置键、URL、代码块、表格结构和链接目标都不变。不新增、不弱化、不夸大任何内容。
- 标题下方的每一级标题都保留英文锚点：`## 安装 {#install}`。这样页面之间的链接（`android.md`、`configuration.md#connectors`）和侧边栏锚点在两种语言下都能工作。
- 路径：页面之间使用裸文件名链接（`android.md`）；`docs/` 下的图片和其他文件向上一级引用（`../screenshots/feed.png`）；仓库文件向上两级引用（`../../nanomuse/config.py`）。
- 语气与其他地方一致：平实、具体、自然；使用符合中文习惯的表达，不要逐字翻译英文句子；不使用感叹号，不使用营销词。称呼用户用“你”，称呼智能体用“它”；菜单路径写成“设置 → 账号 → 设备”，按钮和开关名称放在「」中。
- 事物名称以应用中文界面中的叫法为准。下方术语表来自 `res/values-zh/nm_strings.xml`、`locales.ts` 的 `zh` 部分、`Localizable.xcstrings`（zh-Hans）、`web/src/i18n/zh-CN.ts` 和中继控制台；界面与术语表不一致时，以界面为准，并修正术语表。
- 标点放在粗体或斜体标记之外：写 `**轨迹**：` 和 `*提议*：`，不要写 `**轨迹：**` 或 `*提议：*`。在 CommonMark 中，如果强调标记紧挨冒号或括号结束，并且后面还有字符，标记不会被正确闭合，网站上就会显示星号；`tests/test_docs_markup.py` 会渲染每个页面，并在这种情况下失败。

| 英文 | 简体中文 | 英文 | 简体中文 |
|---|---|---|---|
| agent | 智能体 | the relay / nanoMuse Cloud | 中继 / nanoMuse Cloud |
| free, open-source, non-profit | 免费、开源、非营利 | allowance, free allowance | 额度，免费额度 |
| sign in / sign out | 登录 / 退出登录 | one-time code | 验证码 |
| your own key | 自己的 key | provider | 服务商 |
| a plan you already pay for | 你已经在付费的套餐 | model group | 模型组 |
| Data controls | 数据控制 | sync conversations across my devices | 在我的设备之间同步对话 |
| the hub | hub（设备互联） | Devices | 设备 |
| remote control | 远程控制 | trusted (ask-free) devices | 免询问的设备 |
| Reach | Reach | Hands / the hands | 「手」/ 手；动手 |
| the hands' model | 手的模型 | the operator | 操作器 |
| computer use | 电脑操作 | the capsule | 胶囊 |
| the stage / the glow / the marker | 舞台 / 光晕 / 标记 | the trajectory | 轨迹 |
| accessibility service / overlay | 无障碍服务 / 悬浮窗权限 | Accessibility / Screen Recording (macOS) | 辅助功能 / 录屏 |
| Sentinel | 哨兵（Sentinel） | approval, approval card | 审批，审批卡片 |
| Allow once / for this session / always / Deny | 允许一次 / 本次对话都允许 / 总是允许 / 拒绝 | destructive / outbound / money / install | 删除 / 发送 / 付款 / 安装 |
| Permissions | 权限 | workspace / shared folders | 工作区 / 共享文件夹 |
| the vault | 保险库 | taint, tainted | 污染，已污染 |
| Feed / Ideas / Goals / Library | 动态 / 点子 / 目标 / 资源库 | Artifacts / Media | 构件 / 影音内容 |
| Routines / goal check | 例程 / 目标检查 | the rail / the rooms | 侧栏 / 房间 |
| main chat | 主要聊天 | side chats | 旁聊 |
| memory / daily log | 记忆 / 日记 | SOUL, IDENTITY.md, MEMORY.md | 保持不变 |
| avatar / the avatar studio | 形象 / 形象工作室 | moods (idle, working, waiting, happy, error) | 状态（待命、干活中、等你回复、搞定、出了点问题） |
| picture model / video model | 图像模型 / 视频模型 | skills / MCP server | 技能 / MCP 服务器 |
| Models (Chat / Operating the screen / Making pictures / Making clips) | 模型（对话 / 操作屏幕 / 生成图片 / 生成视频） | Automatic | 自动 |
| Use it for | 用它来做什么 | Use nanoMuse Cloud this time | 这次改用 nanoMuse Cloud |
| connectors | 连接器 | coding agents | 编程助手 |
| channels (Feishu, DingTalk, WeCom, Telegram) | 聊天入口 | deliver here | 推送到这里 |
| the web console / the web app | 网页控制台 / 网页版 | the desktop app | 桌面版 |
| the phone app | 手机 App | the runtime / the local runtime | 运行时 / 本地运行时 |
| the showcase | 展示站 | self-hosting | 自己部署 |
| quick chat / dictation | 快速唤起 / 听写 | roadmap / changelog / release notes | 路线图 / 更新日志 / 发布说明 |

最容易出错的两项：使用“非营利”，绝不使用“非盈利”；`nanoMuse Cloud` 是产品名，永远不翻译（不译成“云”或“云端”）。

## 事实以仓库为准

README、文档页面或发布说明中的每项功能、数字和计数，都必须能由读者在本仓库中核实：服务商数量是 `nanomuse/llm/providers.json` 的长度，语言数量是 `values-*` 目录的数量，连接器数量来自目录文件。已经发布的功能要描述它实际做什么，绝不能称为演示、预览或即将推出；尚未发布的功能写在[路线图](docs/roadmap.md)中，不要放进安装表。关于形象的文案只说明它的用途，不说明它包含多少张图片或多少个姿势，因为这是形象工作室的数据，并且会变化。

## 十份 README

`README.md` 和 `docs/readme/` 下的九份翻译是同一份文档的十种语言版本：章节相同、顺序相同、安装表相同、徽章相同、*News* 行相同，并且要在同一次提交中一起修改（`scripts/readme-contributors.py --check` 和 `tests/test_readme_contributors.py` 会检查其中一部分）。*Community Contributors* 头像会自动跟随 GitHub 贡献者列表：*Contributors* 工作流每晚以及每次推送到 `main` 后运行脚本；某份 README 落后时，它会在 `chore/readme-contributors` 分支上打开一个 pull request；维护者可以合并它，也可以设置 `CONTRIBUTORS_TOKEN` secret，让它在检查通过后自动合并。标题下方的徽章行有两行，较长的一行在前。一条 *News* 行是一句短句，开头用行内代码写日期，最多一个 emoji，最新的行在最前面；只有里程碑版本才添加一行，主版本（`x.0.0`）总是里程碑，较小的版本不是，之前的行保持原样，包括日期、版本和文字。

## 提交与 pull request

- 主题行遵循 [Conventional Commits](https://www.conventionalcommits.org)：`type(scope): what changed`，使用祈使语气，结尾不加句号，例如 `feat(android): hands capsule shows the model's thought`、`fix(relay): keep the face a device drew when another renames`、`docs(readme): move the translations to docs/readme/`、`test(gateway): sighted model for the operator lane`。类型包括：`feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`build`、`ci`、`chore`、`revert`；范围是代码树中的部分（`runtime`、`android`、`web`、`desktop`、`relay`、`showcase`、`mobilegym`、`harness`、`docs`、`deps`……）。正文用平实的语言说明原因。pull request 上的 *Commits* 检查会在主题不符合要求时失败；合并提交不受此限制。
- 一个 pull request 只处理一个主题。应用中有界面变化时附上截图，并遮住订单号、姓名、地址、主机名和密钥；项目公开的每张截图也要这样处理。
- 说明测试所用的设备和 Android 版本。手机端功能要在真实硬件上测试；模拟器是 x86_64，无法运行 arm64 APK。
- `main` 受保护。代码通过 pull request 合入，合并前要等待四项检查：Ubuntu / Python 3.12 上的 Python 运行时、网页应用构建、Android 调试 APK 和 DCO 签署。每个工作流会先判断改动了哪棵代码树，并跳过不适用的任务，因此只改文档的 pull request 不会被无关的构建拖住。矩阵中的其他 Python 版本、macOS 和 Windows 检查仍会运行并显示结果，但不会阻止合并；Python 运行时的 Windows 任务标记为实验性（其 shell 工具假定使用 POSIX shell），不能使构建失败；Windows 桌面版由独立工作流构建和发布，并且受支持。分支与 `main` 发生冲突时，GitHub 完全不会运行 `pull_request` 工作流（`gh pr checks` 会显示 “no checks reported”，而且会一直如此），所以没有显示检查结果的 pull request 需要先在 `main` 上 rebase，而不是继续等待。
- 合并方式为 **rebase** 或 **merge commit**，绝不使用 squash：每次提交上的 `Signed-off-by` 就是记录，squash 会丢掉它。`android/` 代码树执行 `git subtree pull` 也需要合并提交。
- 维护者遵循相同流程：每个版本（`0.1.39`、`0.1.40`……）使用一个分支和一个 pull request，检查通过后合并，再从 `main` 打标签并发布（流程见下文）。文档和文案（README、`docs/`、发布说明）可以直接提交到 `main`。
- Dependabot 每月打开一次 pull request，并按组处理；检查通过后合并。如果一次升级会改动已提交的构建产物（`nanomuse/server/static/` 下的网页应用、`cloud/nanomuse_cloud/console/admin/` 下的中继管理控制台），升级后要立即重新构建。

## Issue 与 pull request（维护者）

- 每个 issue 都要打标签：类型（`bug`、`enhancement`、`question`、`documentation`）、平台（`android`、`ios`、`desktop`、`web`、`runtime`、`cloud`），以及修复合并后的 `fixed on main`，或者带首个报告链接的 `duplicate`。
- 每个 pull request 也都要打标签，*Labels* 工作流会自动添加：根据它改动的文件判断平台（`.github/labeler.yml`），根据标题判断类型（`feat` 对应 `enhancement`，`fix` 对应 `bug`，`docs` 对应 `documentation`，`ci` 对应 `ci`，`build(release)` 对应 `release`，其他类型对应 `maintenance`）。工作流只会添加标签；如果标题或路径没有完整表达情况，维护者再手动调整。
- 修复要在 pull request 和提交正文中用 `For #N` 引用对应 issue，绝不使用 `Fixes #N`、`Closes #N` 或 `Resolves #N`：这些写法会在 pull request 合并时关闭 issue，而本项目的 issue 不会自动关闭。修复合入后，给 issue 添加 `fixed on main` 标签并回复说明；issue 会保持打开，直到维护者决定关闭，通常是在修复随某个版本发布之后，回复中会写明版本号。
- issue 和 pull request 的回复使用英文，一到三句平实的话，不使用列表，不添加落款；说明发现了什么，以及下一步会怎样。
- 维护者绝不 amend、带修改地 rebase 或重写贡献者的提交：提交上的 `Signed-off-by` 是贡献者的记录。需要调整的内容由维护者在同一分支上另做一次提交（或另开一个后续 pull request），然后用 merge commit 合并分支。无法接受某个 pull request 时，要在对应的 issue 上写明原因，方便以后找到结论。

## 发布（维护者）

版本号是普通数字（`0.1.41`、`1.0.0`……），因为应用的更新检查会比较它们；每个版本还带一个代号，即一个首字母大写、此前版本从未使用过的英文单词（Foundation、Identity、Home……Helm、Compass；名单见 `CHANGELOG.md`），标题为 `nanoMuse <version> · <Codename>`。各应用、运行时、网页控制台和桌面版共用一个版本号；中继有自己的版本号（`cloud/pyproject.toml`），只有发生改动时才更新。版本号只在发布提交中变更，其他时候不变。

当人们等待的修复（崩溃、安全问题、无法安装的应用）进入 `main` 后，就尽快发布；其他情况下每隔几天发布一次，前提是 *Unreleased* 中已有值得发布的内容。发布物包括：APK、TestFlight 构建、Windows、macOS 和 Linux 桌面安装包、harness tarball 和 Docker 镜像；不提供终端安装构建，也不发布预发布版，所有版本都标记为 *Latest*。打标签前，维护者要在手机上安装即将发布的构建，并走一遍主要流程。

1. **发布提交** `build(release): <version> <Codename>`，使用独立分支和 pull request。`scripts/release-bump.sh <old> <new> <old-code> <new-code> [<relay-old> <relay-new>]` 会更新所有版本文件（`pyproject.toml`、`nanomuse/__init__.py`、`CITATION.cff`、`web/package.json`、`harness/*/package.json` 两个文件及其锁文件、中继控制台的 `VERSION`、`scripts/rebrand.py` 中的 `VERSION_NAME`/`VERSION_CODE`；只有每个文件仍带着旧版本号时脚本才会写入，`--check` 会单独执行这项检查）；然后 `python scripts/rebrand.py` 写入 Android 的 `versionName`/`versionCode` 和 iOS 的 `MARKETING_VERSION`（第二次运行必须输出 `clean`）。`scripts/release-docs.py <old> <new> <OldName> <NewName> <date>` 会在 `CHANGELOG.md` 的 *Unreleased* 下建立该版本的区块，把 `README.md`、`docs/readme/*`、`docs/index.md` 和 `docs/zh/index.md` 中的下载链接更新到新标签，把 issue 表单（`.github/ISSUE_TEMPLATE/*.yml`）中的示例版本更新为新版本和 `versionCode`，把代号加入发布说明模板中的名单；如果带上 `--roadmap "<one line>" --roadmap-zh "<一句话>"`，它还会把该版本的行添加到 `docs/roadmap.md` 和 `docs/zh/roadmap.md` 过往版本表的末尾；*News* 列表保持原样，因为这些行是里程碑，会永久保留日期、版本和文字（`--dry-run` 会显示每个列表的前三行而不写入，脚本还会说明本次发布是否需要添加 News 行）。需要手工处理的内容包括：`CHANGELOG.md` 区块的首段，以及为下一个 *Unreleased* 保留空的 `### Cloud / Runtime / Web / Desktop / Android / iOS / Project` 标题；根据 [docs/release-notes-template.md](docs/release-notes-template.md) 编写 `docs/releases/v<version>.md`（一段短故事、*Highlights*、*Upgrade Notes*、*Community*，先英文，再在折叠区块中放同样的中文内容，所有链接都要检查）；如果本次发布是里程碑，就在 *News* 列表中添加一行，主版本（`x.0.0`）总是里程碑，较小的版本不是（一句话，大约一行，日期用行内代码，一个 emoji，放在列表最前面；同样的内容添加到十份 README 和首页；之前版本的行保持不变）；如果脚本运行时没有带 `--roadmap`，还要手工添加 `docs/roadmap.md` 和 `docs/zh/roadmap.md` 中的过往版本行；检查 `docs/parity.md` 中是否有“下一个版本”单元格；运行 `scripts/readme-contributors.py`，让十份 README 中的 *Community Contributors* 头像保持最新（`--check` 会说明它们是否最新）。针对改动内容运行检查（[AGENTS.md](AGENTS.md)；`scripts/rebrand.py` → `clean`、`connectors-json.mjs --check`、`providers-json.mjs --check`、`cd website && npm run docs:build`）；改动 `android/src/ios/` 时，*iOS · build check* 工作流会在 pull request 上运行，否则可以从 Actions 标签页手动启动。检查通过后合并；`M` 是合并提交。
2. **APK 和 GitHub 发布。** 在 `M` 上运行 `scripts/release-apk.sh <version>`，构建发布 APK，验证签名并写入 sha256；运行 `scripts/release-apk.sh <version> --publish-only --target M` 会在 `M` 上创建标签 `v<version>` 并创建发布（标记为 Latest；脚本还提供 `--prerelease`，但项目不使用），正文为 `docs/releases/v<version>.md`。`scripts/release_notes.py` 会根据上一个标签以来合并的 pull request 填入 *What's Changed*、*New Contributors*、*Contributors* 和 *Full Changelog* 链接（`scripts/release_notes.py <version>` 会显示即将发布的正文；失败时不会发布任何内容，修复原因后再次执行同样的 `--publish-only --target M` 命令即可继续）。标签会启动桌面版、harness、Docker 和测试工作流；桌面安装包、它们的 `SHA256SUMS-desktop.txt`、Windows 更新元数据（`latest.yml` 和安装包的 `.exe.blockmap`，供应用内更新使用）、harness tarball 及其 `SHA256SUMS-harness.txt` 会在 CI 完成时附加到发布中（某个桌面平台失败不会拖住其他平台：其他平台的安装包仍会附加，`SHA256SUMS-desktop.txt` 只列出这些安装包，但工作流最终会显示失败；平台问题修复后，在 *Actions → desktop app → Run workflow* 中把 `release_tag` 设为该标签，从仍带有该版本号的 `harness/desktop/package.json` 提交重新构建全部四个平台并替换整组产物）；Docker 镜像会以 `<version>`、`<major.minor>` 和 `latest` 推送到 `ghcr.io/nano-muse/nanomuse`。宣布发布前，所有工作流都必须通过。所有版本使用同一个签名密钥，这样更新可以覆盖安装上一个版本；该密钥不在仓库中，也不在 CI 中。
3. **中继**：版本号变更后，在 `M` 的检出目录中运行 `cloud/deploy/nanomuse-hk/deploy.sh`；`/healthz` 必须返回新版本号。
4. **TestFlight。** 维护者手动运行 *iOS · TestFlight* 工作流时（`gh workflow run "iOS · TestFlight" --ref main`，或推送 `ios-*` 标签；该工作流不会自行运行），它会构建并上传；构建号就是运行号。App Store Connect 显示处理完成后，外部测试组要等 Apple 的 beta 审核通过才会收到；`docs/releases/v<version>.md` 中要写明构建号。详情见 [docs/ios.md](docs/ios.md)。
5. **文档站和首页**（[nano-muse/nano-muse.github.io](https://github.com/nano-muse/nano-muse.github.io)，推送到 `main` 后一分钟内上线到 nanomuse.cn）：运行 `cd website && DOCS_BASE=/docs/ npm run docs:build`，再把 `.vitepress/dist/` 复制到站点的 `docs/`；在 `index.html` 中更新两种语言的版本行、所有下载链接和 `nanomuse.cn/dl/v<version>/` 镜像链接、Docker 标签，以及 *News* 列表：内容与 README 相同，顺序也相同，两种语言都要更新（只有里程碑版本才新增一行，规则同上；已有内容不重写、不删除）。下载镜像会在发布后十五分钟内自动补齐。

只修复文档的发布可以直接提交到 `main`；如果发布说明有误（构建号或链接错误），通过一个小 pull request 修正，绝不重写历史。

## 安全问题

请在 GitHub 上打开私密安全公告，不要创建公开 issue。
