---
layout: home
title: nanoMuse 文档
hero:
  text: 在手机、电脑和网页上使用同一个开源智能体。
  tagline: 用一个账号连接你的设备，让 nanoMuse 帮你执行任务。关闭 App 后，它仍可继续处理任务；它的记忆保存在你能阅读的文件中，执行不可撤销的操作前会征求你的同意。项目的全部代码都在同一个仓库中，采用 GPL-3.0-or-later 许可证。负责登录和设备通信的中继服务也可以部署在你自己的服务器上。
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

智能体（agent）是能调用工具、执行任务的 AI 程序。中继（relay）负责账号登录和设备之间的通信。文档里的其他技术名词可查阅[术语表](glossary.md)。

## 选择安装方式 {#install}

| | |
|---|---|
| **浏览器** | 打开 [demo.nanomuse.dev](https://demo.nanomuse.dev/) 并登录，即可在模拟手机上体验 nanoMuse。页面提供可点击的中英文任务示例。此页面用于演示，日常使用请安装下面的 App |
| **Android** 8.0 及以上，arm64 | [nanoMuse-1.0.9-arm64.apk](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-1.0.9-arm64.apk) · [安装说明](android.md) |
| **iPhone / iPad** | 通过 [TestFlight](https://testflight.apple.com/join/ZHexbDqc) 安装。TestFlight 是 Apple 分发测试版 App 的工具，此版本已通过 Apple 的测试版审核 · [iOS 使用说明](ios.md) |
| **macOS** 12 及以上 | [Apple 芯片](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-Desktop-1.0.9-mac-arm64.dmg) · [Intel 芯片](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-Desktop-1.0.9-mac-x64.dmg) · [桌面版使用说明](desktop.md) |
| **Windows** 10 以上 | [nanoMuse-Desktop-1.0.9-win-x64.exe](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-Desktop-1.0.9-win-x64.exe) |
| **Linux** x64 | [AppImage](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-Desktop-1.0.9-linux-x64.AppImage) · [.deb](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-Desktop-1.0.9-linux-x64.deb) · [tar.gz](https://github.com/nano-muse/nanoMuse/releases/download/v1.0.9/nanoMuse-Desktop-1.0.9-linux-x64.tar.gz) |
| **Docker** | 用 `bash scripts/self-host.sh --local` 部署自己的中继，用 `docker compose up -d app` 运行网页版。Docker 用容器封装程序及其运行环境 · [部署说明](self-hosting.md) |

全部安装包都在[最新版本下载页](https://github.com/nano-muse/nanoMuse/releases/latest)。如果 GitHub 下载缓慢，可以从 [nanomuse.cn/dl](https://nanomuse.cn/dl/) 下载相同的文件。

[1.0.9 Tiller 更新内容](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.9) · [各客户端的功能对照](parity.md) · [参与贡献与后续计划](roadmap.md) · [中继保存的数据](privacy.md) · [手机数据的保存与归属](sync.md)

## 宣传片 {#the-film}

<video controls playsinline preload="metadata" poster="https://nanomuse.cn/media/film/poster-zh.png" style="width:100%;max-width:960px;border-radius:12px;display:block;margin:0 auto">
  <source src="https://nanomuse.cn/media/film/nanomuse-film-zh-web.mp4" type="video/mp4">
</video>

这段 74 秒的视频介绍 nanoMuse 在手机、电脑和网页上的功能，也提供[英文版](https://nanomuse.cn/media/film/nanomuse-film-en-web.mp4)。

::: info 参与改进 nanoMuse
nanoMuse 提供开源、低成本的个人智能体方案：你可以在自己的设备上运行，选择模型，也可以自行部署中继。项目希望与各地的开发者和使用者一起完善这些功能，让使用者自己掌握智能体。你可以提交 [issue](https://github.com/nano-muse/nanoMuse/issues/new/choose)（问题或建议），也可以提交 [PR](../../CONTRIBUTING.md)（供项目维护者审阅的代码或文档修改）。
:::

## 引用 {#citation}

报告《nanoMuse: An Open-Source Personal Agent for Every Device You Own》发布在论文预印本平台 arXiv，编号为 [2610.08699](https://arxiv.org/abs/2610.08699)。报告介绍了个人智能体的概念、Muse 的架构，以及 nanoMuse 的开源实现。如果你的工作使用了 nanoMuse，可以按以下格式引用。

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
