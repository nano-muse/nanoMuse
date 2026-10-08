---
layout: home
title: nanoMuse 文档
hero:
  text: 开源的个人智能体，面向你的每一台设备。
  tagline: 一个智能体，在你的手机、电脑和网页上，一个账号串起来。它动手做事而不只是回答，App 关了也继续干，把记得的东西写在你读得懂的文件里，遇到无法撤销的操作会先问你。整套东西在一个仓库里，GPL-3.0-or-later；同一套中继也能跑在你自己的服务器上。
  actions:
    - theme: brand
      text: 安装
      link: /zh/android
    - theme: alt
      text: 在浏览器里看演示
      link: https://demo.nanomuse.dev/
    - theme: alt
      text: 自己部署
      link: /zh/self-hosting
    - theme: alt
      text: GitHub
      link: https://github.com/nano-muse/nanoMuse
    - theme: alt
      text: 论文
      link: https://arxiv.org/abs/2610.08699
---

## 安装

| | |
|---|---|
| **浏览器** | [demo.nanomuse.dev](https://demo.nanomuse.dev/)——登录之后，一台模拟手机里的 nanoMuse。这是演示；下面的 App 才是真的 |
| **Android** 8.0 以上，arm64 | [nanoMuse-1.0.0-arm64.apk](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-1.0.0-arm64.apk) · [怎么装](/zh/android) |
| **iPhone / iPad** | [TestFlight](https://testflight.apple.com/join/ZHexbDqc)——测试版；Apple 的 beta 审核通过后，这个链接就能装 · [iOS](/zh/ios) |
| **macOS** 12 以上 | [Apple 芯片](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-mac-arm64.dmg) · [Intel](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-mac-x64.dmg) · [桌面版](/zh/desktop) |
| **Windows** 10 以上 | [nanoMuse-Desktop-1.0.0-win-x64.exe](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-win-x64.exe) |
| **Linux** x64 | [AppImage](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-linux-x64.AppImage) · [.deb](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-linux-x64.deb) · [tar.gz](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.0/nanoMuse-Desktop-1.0.0-linux-x64.tar.gz) |
| **Docker** | `bash scripts/self-host.sh --local` 搭自己的中继；`docker compose up -d app` 跑网页版 · [自己部署](/zh/self-hosting) |

所有下载都在 [最新版本](https://github.com/nano-muse/nanoMuse/releases/latest)；GitHub 下不动的话，同样的文件在 [nanomuse.cn/dl](https://nanomuse.cn/dl/)。

[1.0.0 Keel 改了什么](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.0) · [每个客户端能做什么](/zh/parity) · [从哪儿开始参与](/zh/roadmap) · [中继保存什么](/zh/privacy) · [什么留在手机上，归谁](/zh/sync)

## 宣传片

<video controls playsinline preload="metadata" poster="https://nanomuse.cn/media/film/poster-zh.png" style="width:100%;max-width:960px;border-radius:12px;display:block;margin:0 auto">
  <source src="https://nanomuse.cn/media/film/nanomuse-film-zh-web.mp4" type="video/mp4">
</video>

74 秒，看 nanoMuse 在手机、电脑和网页上做什么。还有[英文版](https://nanomuse.cn/media/film/nanomuse-film-en-web.mp4)。

## 引用

报告《nanoMuse: An Open-Source Personal Agent for Every Device You Own》在 arXiv 上，编号 [2610.08699](https://arxiv.org/abs/2610.08699)：什么是个人智能体，Muse 是怎么搭的，nanoMuse 又是怎样用开源的方式回应的。如果 nanoMuse 对你有帮助，欢迎引用我们的论文。

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
