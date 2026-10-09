# nanoMuse <version> · <Codename>

<!-- The first line is the GitHub release title (scripts/release-apk.sh reads it).
     English first; the Chinese version of the same notes goes in the <details> block at the end.
     Codenames so far: Foundation, Identity, Home, Guardrails, Memory, Avatar, Welcome, Polish,
     Portrait, Motion, Hatch, Hands, Reach, Home, Stage, Palette, Open, Ensemble, Presence,
     Footing, Commons, Welcome, Signal, Mirror, Window, Ledger, Harness, Likeness, Rooms, Locks,
     Union, Steps, Turns, Accord, Thread, Weave, Loom, Keys, Clear, Choice, Keel, Ballast (CHANGELOG.md has the list). One word, capitalised.

     Voice: plain and specific, the maintainer talking to one person. Facts over promises; no
     slogans, no "every one brings…", no exclamation marks.

     The shape follows the releases people know (nanobot's): a short story, then Highlights,
     Upgrade Notes, Community; What's Changed, New Contributors, Contributors and the Full
     Changelog link are generated from the merged pull requests by scripts/release_notes.py
     where the marker below stands, when the release is published. -->

🐉 **nanoMuse `<version>` “<Codename>”** <one sentence: what this version is about>.

<One or two short paragraphs: the headline, and the other story; in plain words, what it means for the person using it.>

## Highlights

- **<Thing>.** <What it is, where to find it, what it replaces.>
- …

## Upgrade Notes

- **Android installs over <previous> and keeps your data.** `nanoMuse-<version>-arm64.apk` (Android 8.0+, arm64; versionCode <n>) is signed with the same key as every version before it. Verify with `sha256sum -c nanoMuse-<version>-arm64.apk.sha256`.
- **The desktop installers are not notarised.** On macOS open the app once from *System Settings → Privacy & Security → Open Anyway* (or right-click → *Open*); on Windows click *Run anyway*. They arrive a little after the APK (CI builds them from the tag), and `SHA256SUMS-desktop.txt` lists every checksum.
- <Anything a person upgrading must know: a setting that moved, a relay version an operator needs, a platform that needs a newer build.>
- **Where to get it.**

  | | |
  |---|---|
  | Browser | [demo.nanomuse.dev](https://demo.nanomuse.dev/): a nanoMuse on a simulated phone, after a sign-in; a demo, the apps below are the real thing |
  | Android 8.0+, arm64 | `nanoMuse-<version>-arm64.apk` |
  | iPhone, iPad | [TestFlight](https://testflight.apple.com/join/ZHexbDqc): a beta; build <n>, delivered once Apple's beta review has passed |
  | Windows 10+ | `nanoMuse-Desktop-<version>-win-x64.exe` (the desktop app, on DeepSeek Harness) |
  | macOS 12+ | `nanoMuse-Desktop-<version>-mac-arm64.dmg` / `-mac-x64.dmg` (or the `.zip`: unzip, drag to Applications) |
  | Linux x64 | `nanoMuse-Desktop-<version>-linux-x64.deb` / `.AppImage` (needs FUSE; `--appimage-extract-and-run` without) / `.tar.gz` (unpack anywhere, run `./nanomuse-desktop`) |
  | DeepSeek Harness Desktop you already run | `dsh-nanomuse-<version>.tgz`: `dsh plugin --profile desktop add …` ([how](https://github.com/nano-muse/nanoMuse/blob/main/harness/README.md)) |

  In our measurements GitHub's own downloads are quick from China as well; if they fail where you are, the same files are on [nanomuse.cn/dl/v<version>/](https://nanomuse.cn/dl/v<version>/) within fifteen minutes.

## Community

nanoMuse is open source, free and non-profit. Sign in with a phone number or an e-mail and you get a starting allowance; the developer pays for it. The account page shows what is left and how to add more. When it is gone, use your own key or a plan you already pay for ([how](https://github.com/nano-muse/nanoMuse/blob/main/docs/own-key.md)). With an account, the text of your conversations is kept on nanoMuse Cloud so that your devices show the same chats; one switch in Data controls turns it off and deletes it; nothing is sold ([privacy policy](https://nanomuse.cn/privacy/)); delete the account whenever you want.

A stable version is not the last word. We use it every day and know where it is rough; tell us where it broke for you and what you want it to do. Thanks to everyone who tried a build and reported what broke. [Open an issue](https://github.com/nano-muse/nanoMuse/issues/new/choose) · [send a pull request](https://github.com/nano-muse/nanoMuse/blob/main/CONTRIBUTING.md) · [Discussions](https://github.com/nano-muse/nanoMuse/discussions) · [Discord](https://discord.gg/bkTySmm28X) · [star the repo](https://github.com/nano-muse/nanoMuse); if it is useful to you, a star helps others find it.

Based on [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 (GPL-3.0), modified since 2026-09-24. The complete corresponding source of this build is tag `v<version>` plus the `android/deps/proot` submodule ([nano-muse/proot](https://github.com/nano-muse/proot)). The whole repository is GPL-3.0-or-later. nanoMuse Harness carries DeepSeek Harness unmodified, with its licence files inside; *harness* in the name is the word, not DeepSeek's. nanoMuse is not affiliated with Meta; Muse is a trademark of Meta Platforms, Inc. The desktop follows what Muse's app looks like and does, written down from using it; none of Meta's assets, code or content is in it.

<!-- pull requests -->

<details>
<summary>简体中文</summary>

🐉 **nanoMuse `<version>`「<Codename>」**：<一句话：这个版本是关于什么的>。

<一两段话：主线，以及另一条线；用平实的话说清对用的人意味着什么。>

### 亮点

- **<什么>。** <是什么、在哪里、替代了什么。>
- …

### 升级说明

- **Android 覆盖安装 <previous>，数据保留。** `nanoMuse-<version>-arm64.apk`（Android 8.0+，arm64；versionCode <n>）和之前每个版本用同一把签名。校验：`sha256sum -c nanoMuse-<version>-arm64.apk.sha256`。
- **桌面安装包没有经过公证。** macOS 第一次在「系统设置 → 隐私与安全性」里点「仍要打开」（或右键 → 「打开」），Windows 点「仍要运行」。安装包会比 APK 晚一点到（CI 从 tag 构建它们）；`SHA256SUMS-desktop.txt` 列出了所有校验值。
- <升级的人必须知道的事：挪了位置的设置、运维者需要的中转版本、需要新构建的平台。>
- **去哪下载。**

  | | |
  |---|---|
  | 浏览器 | [demo.nanomuse.dev](https://demo.nanomuse.dev/)：模拟手机里的一个 nanoMuse，登录后体验；这是演示，下面的应用才是正式版 |
  | Android 8.0+，arm64 | `nanoMuse-<version>-arm64.apk` |
  | iPhone、iPad | [TestFlight](https://testflight.apple.com/join/ZHexbDqc)：测试版，公开链接等 Apple 审核；第 <n> 个构建，通过后即可安装 |
  | Windows 10+ | `nanoMuse-Desktop-<version>-win-x64.exe`（桌面 App，基于 DeepSeek Harness） |
  | macOS 12+ | `nanoMuse-Desktop-<version>-mac-arm64.dmg` / `-mac-x64.dmg`（或 `.zip`：解压后拖进「应用程序」） |
  | Linux x64 | `nanoMuse-Desktop-<version>-linux-x64.deb` / `.AppImage`（需要 FUSE；没有就加 `--appimage-extract-and-run`）/ `.tar.gz`（解压到任意位置，运行 `./nanomuse-desktop`）|
  | 已在用 DeepSeek Harness Desktop | `dsh-nanomuse-<version>.tgz`：`dsh plugin --profile desktop add …`（[怎么装](https://github.com/nano-muse/nanoMuse/blob/main/harness/README.md)） |

  实测从国内直接下 GitHub 也不慢；万一下不动，同样的文件十五分钟内会出现在 [nanomuse.cn/dl/v<version>/](https://nanomuse.cn/dl/v<version>/)。

### 社区

nanoMuse 开源、免费、非营利。手机号或邮箱登录后有一份起始额度，钱是开发者出的；剩多少、怎么加，账号页里有数。用完可以换成自己的 key，或者用你已经在付费的套餐登录（[教程](https://github.com/nano-muse/nanoMuse/blob/main/docs/own-key.md)）。登录后，对话文字会保存在 nanoMuse Cloud，让你的几台设备看到同样的对话；「数据控制」里一个开关就能关掉并删除；数据不卖（[隐私政策](https://nanomuse.cn/privacy/)）；账号想删就删。

稳定版也不是最后一句话。我们自己每天在用，知道哪些地方还糙；哪里坏了、想要什么，直接提 issue。谢谢每一位装过、试过、报过问题的人。[提 issue](https://github.com/nano-muse/nanoMuse/issues/new/choose) · [发 PR](https://github.com/nano-muse/nanoMuse/blob/main/CONTRIBUTING.md) · [Discussions](https://github.com/nano-muse/nanoMuse/discussions) · [Discord](https://discord.gg/bkTySmm28X) · [点个 Star](https://github.com/nano-muse/nanoMuse)；觉得有用，点个 Star，让更多人看到。

基于 [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13（GPL-3.0），自 2026-09-24 起修改；本版本的完整对应源码是 tag `v<version>` 加子模块 `android/deps/proot`（[nano-muse/proot](https://github.com/nano-muse/proot)）。整个仓库以 GPL-3.0-or-later 发布。nanoMuse Harness 原样携带 DeepSeek Harness 及其许可证文件；名字里的 *harness* 是普通词，不是 DeepSeek 的名字。nanoMuse 与 Meta 无关，Muse 是 Meta Platforms, Inc. 的商标。桌面端照着 Muse 应用用起来的样子做，是用过之后写下来的；里面没有 Meta 的任何素材、代码或内容。

</details>
