<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/assets/brand/nanomuse-cover.png" alt="nanoMuse: an open-source personal agent for every device you own">
</p>

<p align="center">
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/README.md">English</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_zh.md">简体中文</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_zh-TW.md">繁體中文</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_es.md">Español</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_fr.md">Français</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_id.md">Bahasa Indonesia</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_ja.md">日本語</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_ko.md">한국어</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_ru.md">Русский</a> |
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/readme/README_vi.md">Tiếng Việt</a>
</p>
<p align="center">
  <a href="https://github.com/nano-muse/nanoMuse/stargazers"><img src="https://img.shields.io/github/stars/nano-muse/nanoMuse?style=flat&label=stars" alt="GitHub stars"></a>
  <a href="https://github.com/nano-muse/nanoMuse/releases"><img src="https://img.shields.io/github/downloads/nano-muse/nanoMuse/total?label=downloads" alt="Downloads"></a>
  <a href="https://github.com/nano-muse/nanoMuse/actions/workflows/ci.yml"><img src="https://github.com/nano-muse/nanoMuse/actions/workflows/ci.yml/badge.svg?branch=main" alt="Test Suite"></a>
  <a href="https://demo.nanomuse.dev/"><img src="https://img.shields.io/badge/Try_it-demo.nanomuse.dev-0a66e4" alt="Try it in the browser"></a>
  <a href="https://nanomuse.cn/"><img src="https://img.shields.io/badge/Website-nanomuse.cn-0a66e4" alt="Website"></a>
  <a href="https://arxiv.org/abs/2610.08699"><img src="https://img.shields.io/badge/arXiv-2610.08699-b31b1b" alt="Paper on arXiv"></a>
  <a href="https://github.com/nano-muse/nanoMuse/blob/main/LICENSE"><img src="https://img.shields.io/github/license/nano-muse/nanoMuse?label=license" alt="GPL-3.0-or-later"></a>
  <a href="https://discord.gg/bkTySmm28X"><img src="https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

**nanoMuse is an open-source personal agent for every device you own.** One agent with a name and a look of its own, in the style of Meta's [Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/): it does things instead of answering questions, keeps working while the app is closed, remembers you, and stops to ask before anything you could not undo.

*nano* means the whole set, small enough to run and deploy yourself: the phone app, the desktop app, the web console and the relay that joins them are all in this repository, under GPL-3.0-or-later. **[Free, open source, non-profit. Let's build it together.](CONTRIBUTING.md)** Sign in and you get a free allowance of model use on the community relay (the developer pays for it); when it is gone, [use your own key](docs/own-key.md). The same relay runs on a server of yours, so nothing has to leave your house. Latest: **1.0.0 Keel**, [release notes](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0) · [try it in the browser](https://demo.nanomuse.dev/).

https://github.com/user-attachments/assets/c7694d5a-9450-4f99-9254-5d70560d7565

<p align="center"><a href="https://nanomuse.cn/media/film/nanomuse-film-en-web.mp4">English</a> · <a href="https://nanomuse.cn/media/film/nanomuse-film-zh-web.mp4">中文</a> · <a href="https://nanomuse.cn/#film">nanomuse.cn</a></p>

## 🗞️ News

- `2026-10-07` 📄 Our paper is available on [arXiv](https://arxiv.org/abs/2610.08699).
- `2026-10-09` 🚀 Latest version: [1.0.0 Keel](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0).
- `2026-09-25` 🎉 nanoMuse is released.

Every version: [releases](https://github.com/nano-muse/nanoMuse/releases).

## Install

| | |
|---|---|
| **Browser** | [demo.nanomuse.dev](https://demo.nanomuse.dev/): a nanoMuse on a simulated phone, after a sign-in. A demo; the apps below are the real thing |
| **Android** 8.0+, arm64 | [nanoMuse-1.0.0-arm64.apk](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-1.0.0-arm64.apk): every version is signed with the same key and installs over the last |
| **iPhone / iPad** | [TestFlight](https://testflight.apple.com/join/ZHexbDqc): a beta; the link delivers the build once Apple's beta review has passed · [iOS](docs/ios.md) |
| **macOS** 12+ | [Apple Silicon](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-mac-arm64.dmg) · [Intel](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-mac-x64.dmg). Not notarised: right-click → *Open* the first time |
| **Windows** 10+ | [nanoMuse-Desktop-1.0.0-win-x64.exe](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-win-x64.exe): click *Run anyway* once |
| **Linux** x64 | [AppImage](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-linux-x64.AppImage) · [.deb](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-linux-x64.deb) · [tar.gz](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-linux-x64.tar.gz) |
| **Docker** | `bash scripts/self-host.sh --local` for your own relay; `docker compose up -d app` for the web app on a server of yours; see [self-hosting](docs/self-hosting.md) |

All downloads come from the [latest release](https://github.com/nano-muse/nanoMuse/releases/latest); the same files are on [nanomuse.cn/dl](https://nanomuse.cn/dl/) when GitHub is slow where you are. Open the app, sign in with an e-mail or a mainland-China phone number, and it has a model to think with. The phone, the desktop and the web share one account and show the same conversations.

## What it does

<table>
  <tr>
    <td width="50%" valign="top"><b>Does things.</b><br>A Linux shell, a browser, MCP servers and skills, and, with <i>Hands</i> on, the apps on your phone and the windows on your computer through their screens, for everything that never had an API.</td>
    <td width="50%" valign="top"><b>Asks first.</b><br>A stop before deleting, sending or paying, remembered for once, this chat or always; passwords and codes are yours to type. A login or a CAPTCHA is handed to you, <i>Done</i> resumes.</td>
  </tr>
  <tr>
    <td width="50%" valign="top"><b>Reaches your other devices.</b><br>Say it on the phone, it runs on your PC; <code>@Mac …</code> at the start of a message sends the task there. Approvals come back to the device in your hand.</td>
    <td width="50%" valign="top"><b>Keeps going.</b><br>Goals checked on a schedule, routines that run while the app is closed, a feed written for you each morning.</td>
  </tr>
  <tr>
    <td width="50%" valign="top"><b>Remembers you.</b><br>What it is, what it knows about you and when it wakes are Markdown files you can read and edit.</td>
    <td width="50%" valign="top"><b>Lives in your chat apps.</b><br>It answers in 飞书, 钉钉, 企业微信 and Telegram.</td>
  </tr>
  <tr>
    <td width="50%" valign="top"><b>A look of its own.</b><br>Describe one, your image model draws it, a video model makes it move. A small dragon by default.</td>
    <td width="50%" valign="top"><b>Any model.</b><br>The relay's allowance, your own key at one of eighteen providers (Bailian, OpenRouter, OpenAI, Gemini, DeepSeek and more), or a plan you already pay for: ChatGPT, Claude, Kimi. A provider without picture or video models leaves those two off, and the app says so.</td>
  </tr>
</table>

## How it works

Each device runs its own agent: the phone inside the APK (Alpine Linux under proot, a shell, a browser, MCP), the computer inside nanoMuse Desktop (DeepSeek Harness with the Python runtime for the hands). Signed in, they meet on the relay and can ask each other for things; the text of the conversations travels through it, files and screenshots stay where they were made.

<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/assets/brand/devices-loop.png" alt="Android, the desktop (Mac, Windows, Linux), iPhone and iPad, and the web app around one account: the relay signs the devices in and carries the conversation between them" width="92%">
</p>

[docs/every-device.md](docs/every-device.md) explains the devices, [docs/hub.md](docs/hub.md) the frames, [docs/cloud.md](docs/cloud.md) the relay, [docs/privacy.md](docs/privacy.md) what it keeps.

## Compared with Muse and OpenMinis

| | Meta Muse | OpenMinis | nanoMuse |
|---|---|---|---|
| Where the agent runs | A cloud VM per user | The phone it is installed on | Your phone, your computer, or a server of yours, one account across them |
| Apps without an API | Out of reach; the VM never touches your devices | An accessibility CLI on Android | The screen as a hand on the phone and the computer: screenshots, APIs first, you take over for logins. Not on iOS, where the system does not allow it |
| Other devices | Clients of one VM | The one it is installed on | Devices ask each other for things over the hub, with approvals where you are |
| Models | Meta's | Bring your own | The relay's free allowance, or your own |
| Licence | Closed | GPL-3.0 | GPL-3.0-or-later, built on OpenMinis |

## Docs

[nanomuse.cn/docs](https://nanomuse.cn/docs/): install per platform, every device, hands, connectors, memory, self-hosting, the protocols. The sources are in [docs/](docs/); what changed in each version is in the [CHANGELOG](CHANGELOG.md) and [docs/releases/](docs/releases/).

## Self-host

One VPS, one hour: [docs/self-hosting.md](docs/self-hosting.md). Three ways: no server at all with your own key, your own relay with `scripts/self-host.sh`, or a runtime of your own for the web app.

## Contribute

Use it for a real task, report what broke, then pick something focused: [CONTRIBUTING.md](CONTRIBUTING.md) has the setup and the conventions, [AGENTS.md](AGENTS.md) the rules a coding agent follows in this tree, and the [roadmap](docs/roadmap.md) says where to start. [Issues](https://github.com/nano-muse/nanoMuse/issues) · [Discussions](https://github.com/nano-muse/nanoMuse/discussions) · [Discord](https://discord.gg/bkTySmm28X).

## ⭐️ Citation

If you find nanoMuse useful, please cite the paper.

```bibtex
@misc{liu2026nanomuseopensourcepersonalagent,
      title={nanoMuse: An Open-Source Personal Agent for Every Device You Own}, 
      author={Guangyi Liu and Yong Liu and Jiangning Zhang},
      year={2026},
      eprint={2610.08699},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2610.08699}, 
}
```

## Acknowledgements

nanoMuse stands on other people's work; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) has the terms.

- [OpenMinis](https://github.com/OpenMinis/OpenMinis): the on-device agent the phone app is built on, with [proot](https://github.com/nano-muse/proot) and [Alpine Linux](https://alpinelinux.org/) for the sandbox.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): the agent harness the desktop app is a plugin of.
- [UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) (ByteDance): the desktop hands' operator is a port of theirs, and the stage's markers follow their ScreenMarker.
- [MobileGym](https://github.com/Purewhiter/mobilegym), [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench), [PhoneHarness](https://github.com/PhoneHarness/PhoneHarness), [CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse), [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM), [ClawGUI](https://github.com/ZJU-REAL/ClawGUI): the phone operator, the traces and the product ideas.

## Disclaimer

nanoMuse is an independent community project, not affiliated with or endorsed by Meta Platforms, Inc.; Muse is their trademark. The dragon is the project's own.

## License

[GPL-3.0-or-later](LICENSE). The phone app is based on OpenMinis 1.13 (GPL-3.0), modified since 2026-09-24; see [NOTICE](NOTICE). Earlier versions of the Python line were MIT (tag `pre-openminis`).
