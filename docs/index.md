---
layout: home
title: nanoMuse docs
hero:
  text: An open-source personal agent for every device you own.
  tagline: One agent on your phone, your computer and the web, one account across them. It does things instead of answering questions, keeps going when the app is closed, remembers you in files you can read, and asks before anything you could not undo. The whole set is one repository under GPL-3.0-or-later, and the same relay runs on a server of yours.
  actions:
    - theme: brand
      text: Install
      link: /android
    - theme: alt
      text: Try it in the browser
      link: https://demo.nanomuse.dev/
    - theme: alt
      text: Run it yourself
      link: /self-hosting
    - theme: alt
      text: GitHub
      link: https://github.com/nano-muse/nanoMuse
    - theme: alt
      text: Paper
      link: https://arxiv.org/abs/2610.08699
---

## Install

| | |
|---|---|
| **Browser** | [demo.nanomuse.dev](https://demo.nanomuse.dev/): a nanoMuse on a simulated phone, after a sign-in, with lines to try beside it in English and in Chinese. A demo; the apps below are the real thing |
| **Android** 8.0+, arm64 | [nanoMuse-1.0.2-arm64.apk](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-1.0.2-arm64.apk) · [how to install](/android) |
| **iPhone / iPad** | [TestFlight](https://testflight.apple.com/join/ZHexbDqc): a beta that passed Apple's beta review; the link installs it · [iOS](/ios) |
| **macOS** 12+ | [Apple Silicon](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-Desktop-1.0.2-mac-arm64.dmg) · [Intel](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-Desktop-1.0.2-mac-x64.dmg) · [the desktop app](/desktop) |
| **Windows** 10+ | [nanoMuse-Desktop-1.0.2-win-x64.exe](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-Desktop-1.0.2-win-x64.exe) |
| **Linux** x64 | [AppImage](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-Desktop-1.0.2-linux-x64.AppImage) · [.deb](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-Desktop-1.0.2-linux-x64.deb) · [tar.gz](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.2/nanoMuse-Desktop-1.0.2-linux-x64.tar.gz) |
| **Docker** | `bash scripts/self-host.sh --local` for your own relay; `docker compose up -d app` for the web app · [run it yourself](/self-hosting) |

Every download is on the [latest release](https://github.com/nano-muse/nanoMuse/releases/latest); the same files are at [nanomuse.cn/dl](https://nanomuse.cn/dl/) when GitHub is slow where you are.

[What changed in 1.0.2 Trim](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.2) · [What each client can do](/parity) · [Where to start contributing](/roadmap) · [What the relay keeps](/privacy) · [What stays on a phone, and whose it is](/sync)

## The film

<video controls playsinline preload="metadata" poster="https://nanomuse.cn/media/film/poster-en.png" style="width:100%;max-width:960px;border-radius:12px;display:block;margin:0 auto">
  <source src="https://nanomuse.cn/media/film/nanomuse-film-en-web.mp4" type="video/mp4">
</video>

74 seconds: what nanoMuse does on your phone, your computer and the web. Also in [Chinese](https://nanomuse.cn/media/film/nanomuse-film-zh-web.mp4).

::: info nanoMuse keeps evolving
A personal agent should not live only in someone else's cloud, so nanoMuse is the open-source, low-cost alternative: on your own devices, with a model you choose and a relay you can host yourself. We want to build it with developers and users everywhere, so that each person truly owns a personal agent. Open an [issue](https://github.com/nano-muse/nanoMuse/issues/new/choose) or send a [pull request](../CONTRIBUTING.md); either one helps nanoMuse get better.
:::

## Citation

The report *nanoMuse: An Open-Source Personal Agent for Every Device You Own* is on arXiv as [2610.08699](https://arxiv.org/abs/2610.08699): what a personal agent is, how Muse is built, and how nanoMuse answers it in the open. If you find nanoMuse useful, please cite the paper.

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
