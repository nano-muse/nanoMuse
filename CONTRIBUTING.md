# Contributing

Use nanoMuse for a real task, report what broke, then pick something focused. Issues and pull requests are welcome; for anything larger than a fix, open an issue first so we can agree on the shape. [docs/roadmap.md](docs/roadmap.md) says where help is wanted and where to start in each area. For a quick question or to talk through an idea before writing it up, there is a [Discord](https://discord.gg/bkTySmm28X); decisions still land in issues and pull requests, where they can be found later.

[AGENTS.md](AGENTS.md) is the short version of this file for coding agents and for people in a hurry: the layout, the check commands per area, and the conventions below in one screen. The two must agree; when they do not, fix both.

## Two trees

- **`android/`**: the phone apps. A modified copy of [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 imported with `git subtree` (GPL-3.0): the Android app under `android/src/android`, the iOS app under `android/src/ios`. Upstream's rules apply here (below), so that the subtree stays pullable.
- **Everything else is ours**: the Python runtime (`nanomuse/`), the relay (`cloud/`), the web console (`web/`), the desktop app (`harness/dsh-nanomuse/` and the Electron shell in `harness/desktop/`), the showcase (`demo/`), the docs (`docs/`, served by `website/`) and the scripts. One set of conventions, the ones in this file; [AGENTS.md](AGENTS.md) has the check command for each area and [docs/architecture.md](docs/architecture.md) explains how the pieces fit. [docs/roadmap.md](docs/roadmap.md) says which version brought what and where help is wanted.

## Licence and sign-off

nanoMuse is **GPL-3.0-or-later** ([LICENSE](LICENSE), [NOTICE](NOTICE)). By contributing you agree that your contribution is licensed the same way. Every commit must carry a [Developer Certificate of Origin](https://developercertificate.org) sign-off; `git commit -s` adds the line:

```
Signed-off-by: Your Name <you@example.com>
```

CI checks it. Not accepted, ever:

- code under a licence that cannot be combined with GPL-3.0 (GPL-2.0-*only*, SSPL, BUSL, "source-available", proprietary SDKs);
- anything obtained by decompiling, unpacking or scraping the Meta Muse app, or the OpenMinis binaries beyond what their source already shows;
- the OpenMinis or Meta Muse names and logos as part of nanoMuse's own identity (attribution in the About screen and NOTICE is required and stays).

## Working in `android/`

Upstream is a mirror of a private tree, squashed roughly monthly, and does not take pull requests. We have to be able to `git subtree pull` each release, so:

1. **Do not rename the Kotlin package** `com.openminis.app` or the Gradle `namespace`. Only the `applicationId` (`io.github.nanomuse.app`) is ours.
2. **Do not rename sandbox paths or CLI names** inside the root file system (`/var/minis`, `minis-global`, `minis-open`, `minis-mcp-cli`, `android-*`). They are upstream's contract with itself.
3. **New code goes in new files**: package `io.github.nanomuse.*` or a new file next to the upstream one. When an upstream file must change, add a `// nanoMuse:` comment at the spot, and make one change per spot.
4. **Rebranding is a script, not hand edits.** `scripts/rebrand.py` (names, ids, colours, links; Android and iOS), `scripts/gen-android-icons.py` and `scripts/gen-ios-icons.py` (icons) are idempotent; run them after every upstream pull. Do not fix a rebranding miss by hand; fix the script.
5. **Binary resources** (icon PNGs) are overwritten under the upstream name; on a pull conflict take ours (`git checkout --ours`).
6. **iOS follows the same rules.** The iOS half of upstream lives at `android/src/ios` (see [docs/ios.md](docs/ios.md)); our Swift goes in `android/src/ios/NanoMuse/`, an edit inside an upstream Swift file carries a `// nanoMuse:` comment.

Build steps are in [android/BUILDING.md](android/BUILDING.md) (upstream) and, for the toolchain this repository is built with, in `scripts/android/`: JDK 21, SDK CMake 3.22.1, NDK r27c, Go 1.25+, `gomobile`; `deps/build_proot.sh` builds proot from the `android/deps/proot` submodule (our fork; portable `awk`, no gawk needed) and must run before `scripts/prepare_android_sandbox.sh`.

### Pulling an upstream release

```bash
git fetch openminis --tags
git subtree pull --prefix=android openminis 1.14 -m "Merge OpenMinis 1.14"
git checkout --ours -- 'android/src/android/app/src/main/res/mipmap-*' \
    'android/src/ios/Assets.xcassets/AppIcon.appiconset' 'android/src/ios/Resources/AlternateIcons'
python scripts/rebrand.py && python scripts/gen-android-icons.py && python scripts/gen-ios-icons.py
# resolve the remaining conflicts at the `// nanoMuse:` marks, build, run the smoke list
```

## Working in the runtime, the relay and the web console

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"            # add ",browser" for the Playwright tool
nanomuse config init                  # config/config.toml is git-ignored
```

Before you push:

```bash
ruff check nanomuse tests scripts && ruff format nanomuse tests scripts
mypy                                           # types; config in pyproject.toml
python -m pytest -q                            # MockLLM only, no network
cd web && npm run check && npm run build       # if you touched web/; commit the build
cd cloud && pip install -e ".[dev]" && ruff check . && pytest   # if you touched the relay
```

The desktop app, the Electron shell and the docs site have their own lines in [AGENTS.md](AGENTS.md). Guidelines that apply everywhere: everything that acts goes through the Sentinel with an honest `risk`; secrets never reach the model (`{{vault:NAME}}`); test with `MockLLM`; no internal endpoints or keys in the repo; Ruff, line length 100, type hints; docs are part of the change.

## Every string in every language

nanoMuse is used in more than one country, so a user-visible string is never added in one language. Write it in English first, then in 简体中文, then in every other locale the file already has: `res/values-*/nm_strings.xml` on Android (keys start with `nm_`; upstream's `strings.xml` is not ours to edit), `Localizable.xcstrings` on iOS, `en` and `zh` in `harness/dsh-nanomuse/src/client/locales.ts` on the desktop, the console and e-mail templates in `cloud/`. Dates, numbers and currency use the person's locale. Do not assume a +86 phone number, a Chinese app or Beijing time: SMS codes reach mainland-China numbers only, so a sign-in screen says that and offers e-mail. The voice is the same in every language (plain, specific, no marketing words, no exclamation marks), and Meta's own UI text is never copied verbatim.

## Translating the docs

The docs site (nanomuse.cn/docs, built by `website/` from `docs/`) is in English and 简体中文. The Chinese pages live in `docs/zh/` with the **same file names** as the English ones (`docs/zh/android.md` is the twin of `docs/android.md`), and `website/.vitepress/config.mts` holds the Chinese nav and sidebar. A change to an English page updates its Chinese twin in the same pull request; a new English page gets a Chinese page and a line in both sidebars. `cd website && npm run docs:build` is the dead-link check for both languages.

Rules for a Chinese page:

- Facts are identical to the English page: version numbers, paths, commands, config keys, URLs, code blocks, table shapes and link targets. Nothing is added, softened or inflated.
- Every heading below the title keeps the English anchor: `## 安装 {#install}`. Links between pages (`android.md`, `configuration.md#connectors`) then work in both languages, and so do the sidebar's anchors.
- Paths: pages link to pages by bare name (`android.md`); images and other files under `docs/` are one level up (`../screenshots/feed.png`); the repository is two levels up (`../../nanomuse/config.py`).
- Voice as everywhere else: plain, specific, human; Chinese idiom, never a word-for-word rendering of the English sentence; no exclamation marks, no marketing words. Second person 你, the agent is 它; menu paths as 设置 → 账号 → 设备, button and switch names in 「」.
- Things are called what the apps' Chinese screens call them. The glossary below is derived from `res/values-zh/nm_strings.xml`, the `zh` block of `locales.ts`, `Localizable.xcstrings` (zh-Hans), `web/src/i18n/zh-CN.ts` and the relay console; when a screen and the glossary disagree, the screen wins and the glossary is corrected.

| English | 简体中文 | English | 简体中文 |
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
| memory / daily log | 记忆 / 日记 | SOUL, IDENTITY.md, MEMORY.md | unchanged |
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

## Commits and pull requests

- The subject line follows [Conventional Commits](https://www.conventionalcommits.org): `type(scope): what changed`, in the imperative, no full stop: `feat(android): hands capsule shows the model's thought`, `fix(relay): keep the face a device drew when another renames`, `docs(readme): move the translations to docs/readme/`, `test(gateway): sighted model for the operator lane`. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`; the scope is the part of the tree (`runtime`, `android`, `web`, `desktop`, `relay`, `showcase`, `mobilegym`, `harness`, `docs`, `deps`…). The body says why, in plain words. The *Commits* check on a pull request fails on a subject that does not fit; merge commits are exempt.
- One pull request, one topic. Screenshots for anything visible in the app.
- Say which device and Android version you tested on. Phone-side features are tested on real hardware; the emulator is x86_64 and cannot run the arm64 APK.
- `main` is protected. Code lands through a pull request, and the merge waits for four checks: the Python runtime on Ubuntu / Python 3.12, the web app build, the Android debug APK, and the DCO sign-off. Each workflow first works out which tree the change touched and skips the jobs that do not apply, so a docs-only pull request is not held up by a build it never needed. The rest of the matrix (other Python versions, macOS, Windows) runs and shows up, but does not gate the merge; the Python runtime's Windows job is marked experimental (its shell tool assumes a POSIX shell) and cannot fail the build; the Windows desktop app is built and released by its own workflow and is supported. GitHub runs no `pull_request` workflow at all while the branch conflicts with `main` (`gh pr checks` says "no checks reported", and it stays that way), so a pull request that shows no checks needs a rebase on `main` first, not a longer wait.
- Merges are **rebase** or **merge commit**, never squash: the `Signed-off-by` on each commit is the record, and squashing would drop it. A merge commit is also what `git subtree pull` needs for the `android/` tree.
- Maintainers work the same way: one branch and one pull request per version (`0.1.39`, `0.1.40`, …), merged when green, tagged and released from `main` (the recipe is below). Documentation and copy (READMEs, `docs/`, release notes) may go straight to `main`.
- Dependabot opens its pull requests once a month, grouped; they are merged when the checks are green, and a bump that changes the committed web bundle gets its rebuild right after.

## Releasing (maintainers)

A version is a plain number (`0.1.41`, `1.0.0`, …) because the apps' update check compares them; each release also carries a one-word English codename (Foundation, Identity, Home, … Choice, Keel; `CHANGELOG.md` has the list) and its title is `nanoMuse <version> · <Codename>`. The apps, the runtime, the web console and the desktop app share one version; the relay has its own (`cloud/pyproject.toml`) and moves only when it changed. Versions move in the release commit and nowhere else.

1. **The release commit** `build(release): <version> <Codename>`, on its own branch and pull request. `scripts/release-bump.sh <old> <new> <old-code> <new-code> [<relay-old> <relay-new>]` moves every version file (`pyproject.toml`, `nanomuse/__init__.py`, `CITATION.cff`, `web/package.json`, the two `harness/*/package.json` and their lock files, the relay console's `VERSION`, the `VERSION_NAME`/`VERSION_CODE` in `scripts/rebrand.py`); then `python scripts/rebrand.py` writes the Android `versionName`/`versionCode` and the iOS `MARKETING_VERSION` (a second run must print `clean`). `scripts/release-docs.py <old> <new> <OldName> <NewName> <date>` opens the version's block in `CHANGELOG.md` under *Unreleased* and moves the download links of `README.md`, `docs/readme/*` and `docs/index.md` to the new tag. By hand: the lead paragraph of the `CHANGELOG.md` block and the empty `### Cloud / Runtime / Web / Desktop / Android / iOS / Project` headings for the next *Unreleased*; `docs/releases/v<version>.md` from [docs/release-notes-template.md](docs/release-notes-template.md) (a short story, *Highlights*, *Upgrade Notes*, *Community*, English first and the same in Chinese in a collapsed block, every link checked); the *News* list of the ten READMEs (one short line per milestone, the date in inline code: milestones such as the paper and the first release stay, only the line that names the latest version is replaced by the new one, and the list stays newest first, so that line moves to the top); the past-releases row in `docs/roadmap.md`; any "next release" cell in `docs/parity.md`. Run the checks for what changed ([AGENTS.md](AGENTS.md); `scripts/rebrand.py` → `clean`, `connectors-json.mjs --check`, `providers-json.mjs --check`, `cd website && npm run docs:build`), and the *iOS · build check* workflow on the branch. Merge when green; `M` is the merge commit.
2. **The APK and the GitHub release.** `scripts/release-apk.sh <version>` at `M` builds the release APK, verifies the signature and writes the sha256; `scripts/release-apk.sh <version> --publish-only --target M` tags `v<version>` on `M` and creates the release (marked Latest; `--prerelease` for one that is not) with `docs/releases/v<version>.md` as the body. *What's Changed*, *New Contributors*, *Contributors* and the *Full Changelog* link are filled in from the pull requests merged since the previous tag by `scripts/release_notes.py` (`scripts/release_notes.py <version>` shows the body it would publish). The tag starts the desktop, harness, Docker and test workflows; the desktop installers, their `SHA256SUMS-desktop.txt`, the harness tarball and its `SHA256SUMS-harness.txt` are attached to the release by CI as they finish, the Docker image lands on `ghcr.io/nano-muse/nanomuse` as `<version>`, `<major.minor>` and `latest`. Every workflow must end green before the release is announced. The signing key is one key for every version so an update installs over the previous one; it is not in the repository and not in CI.
3. **The relay**, when its version moved: `cloud/deploy/nanomuse-hk/deploy.sh` from the checkout at `M`; `/healthz` must answer with the new version.
4. **TestFlight.** The *iOS · TestFlight* workflow on `main` (or a tag `ios-*`) uploads the build; its number is the run number. Once App Store Connect shows it processed, the external group gets it after Apple's beta review; `docs/releases/v<version>.md` names the build number. [docs/ios.md](docs/ios.md) has the details.
5. **The docs site and the homepage** ([nano-muse/nano-muse.github.io](https://github.com/nano-muse/nano-muse.github.io), live at nanomuse.cn within a minute of a push to `main`): `cd website && DOCS_BASE=/docs/ npm run docs:build` and copy `.vitepress/dist/` to the site's `docs/`; in `index.html` the version line (both languages), every download link and the `nanomuse.cn/dl/v<version>/` mirror link, the Docker tag, and the *News* list: the same lines as the README's in the same order, only the latest-version line is replaced, in both languages. The download mirror itself fills in on its own within fifteen minutes of the release.

A release that is only a docs fix goes straight to `main`; a release note that turned out wrong (a build number, a link) is fixed by a small pull request, never by rewriting history.

## Security issues

Open a private security advisory on GitHub rather than a public issue.
