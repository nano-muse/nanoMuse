# Third-party notices

nanoMuse is licensed under the GNU General Public License, version 3 or later ([LICENSE](LICENSE), [NOTICE](NOTICE)). It stands on other people's work; this file says whose, and on what terms. Three lists: what the phone apps are built from, what our own runtime, relay, desktop and web code include, and projects we learned from without taking code.

## The phone apps (`android/`: Android and iOS)

### OpenMinis (GPL-3.0)

The app is a modified copy of [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 (tag `1.13`, commit `4ef2900`), Copyright (C) the OpenMinis authors, imported with `git subtree` so that its history is in ours. Modifications since 2026-09-24 are recorded in `git log -- android/`, and every edit inside an upstream file carries a `// nanoMuse:` comment. The OpenMinis name and logo are theirs and are not used for this application. Both phone apps come from that subtree: the Android app in `android/src/android`, the iOS app in `android/src/ios`. What follows is OpenMinis's own third-party list for the parts this tree builds; upstream's full inventory with versions is [android/THIRD_PARTY_LICENSES.md](android/THIRD_PARTY_LICENSES.md).

### Native code (`android/deps/`)

| Component | Source | License | Notes |
|---|---|---|---|
| [proot](https://github.com/nano-muse/proot) | git submodule `android/deps/proot`, our fork of [OpenMinis/proot](https://github.com/OpenMinis/proot), itself a fork of [termux/proot](https://github.com/termux/proot) | **GPL-2.0** | The Linux sandbox. Runs as a separate program (`assets/proot-aarch64`; also shipped as `lib/arm64-v8a/libproot.so` and the two loaders so the installer places them where Android lets them execute). Built by `android/deps/build_proot.sh`. |
| [talloc](https://talloc.samba.org) (Samba) | vendored at `android/deps/talloc` | **LGPL-3.0-or-later** | Memory allocator proot is statically linked against |
| [cppjieba](https://github.com/yanyiwu/cppjieba) | vendored in `jieba_jni` | **MIT** | Chinese word segmentation (header-only + dictionaries) |
| [rclone](https://github.com/rclone/rclone) | `android/deps/rclone-mobile`, built into `rclone.aar` by `android/deps/build_rclone_android.sh` with [gomobile](https://pkg.go.dev/golang.org/x/mobile) (BSD-3-Clause) | **MIT** | Remote destinations for backup (SMB / WebDAV / SFTP / S3 / FTP) |
| Alpine Linux minirootfs | downloaded at build time by `android/scripts/prepare_android_sandbox.sh` | Aggregate of package licenses (musl **MIT**, BusyBox **GPL-2.0**, …) | Not stored in this repository; bundled into the APK as the default root file system |

### Gradle dependencies

| Library | Version | License |
|---|---|---|
| AndroidX / Jetpack (Compose BOM 2025.09.00, core-ktx, lifecycle, activity, navigation, Room, DataStore, security-crypto, browser, webkit, exifinterface, material3-adaptive) | see `android/src/android/app/build.gradle.kts` | **Apache-2.0** (Google / AOSP) |
| OkHttp + okhttp-sse | 4.12.0 | **Apache-2.0** |
| kotlinx-serialization-json | 1.7.3 | **Apache-2.0** |
| kotlinx-coroutines-android | 1.9.0 | **Apache-2.0** |
| Coil (coil-compose) | 2.7.0 | **Apache-2.0** |
| multiplatform-markdown-renderer (+ m3), mikepenz | 0.33.0 | **Apache-2.0** |
| Reorderable (sh.calvin.reorderable) | 2.4.0 | **Apache-2.0** |
| ACRA (acra-core) | 5.12.0 | **Apache-2.0** |
| Shizuku API + provider (dev.rikka.shizuku) | 13.1.5 | **MIT** |
| RealTimeCutVADLibraryForAndroid (JitPack) | see build file | **MIT** (Silero VAD **MIT**, ONNX Runtime **MIT**, WebRTC APM **BSD-3-Clause**) |

Test-only: JUnit 4.13.2 (**EPL-1.0**), MockWebServer 4.12.0 (**Apache-2.0**), kotlinx-coroutines-test 1.9.0 (**Apache-2.0**), org.json 20231013 (**Public Domain / JSON License**).

### Bundled assets

| Asset | Location | License |
|---|---|---|
| KaTeX | `app/src/main/assets/katex/` | **MIT** |
| jieba dictionaries | `app/src/main/assets/jieba/` | **MIT** (cppjieba distribution) |
| models.dev registry snapshot | `app/src/main/assets/models-dev-api.json` | **MIT** ([models.dev](https://models.dev)) |

### The iOS app (`android/src/ios`)

| Component | Source | License | Notes |
|---|---|---|---|
| [iSH](https://github.com/OpenMinis/ish-arm64) (arm64 fork) | git submodule `android/deps/ish` | **GPL-3.0** (later contributions also GPL-2.0), with an App Store distribution exception (`LICENSE.IOS`) | x86 Linux user-mode emulation: the sandbox on iOS |
| [FFmpeg](https://ffmpeg.org) 6.1.2 with [LAME](https://lame.sourceforge.io) 3.100 | built by `android/deps/build_ffmpeg.sh` (LAME vendored at `android/deps/lame-3.100`) | **LGPL-2.1-or-later** (FFmpeg, built without `--enable-gpl`/`--enable-nonfree`), **LGPL-2.0-or-later** (LAME) | Dynamic frameworks; keep the LGPL configuration |
| [rclone](https://github.com/rclone/rclone) | `android/deps/rclone-mobile`, built by `android/deps/build_rclone_ios.sh` with gomobile | **MIT** | Remote destinations for backup |
| Alpine Linux minirootfs | downloaded at build time by `android/deps/prepare_alpine_rootfs.sh` | aggregate of package licenses | The sandbox's root file system; not stored in this repository |
| [cppjieba](https://github.com/yanyiwu/cppjieba) and its dictionaries | `android/src/ios/Vendor/cppjieba`, `Resources/jieba.dict.utf8`, `Resources/hmm_model.utf8` | **MIT** | Chinese word segmentation |
| `cl100k_base` vocabulary (OpenAI [tiktoken](https://github.com/openai/tiktoken)) | `android/src/ios/Shared/cl100k_base.tiktoken`, read by `BPETokenizer.swift` | **MIT** | Token counting |
| models.dev registry snapshot | `android/src/ios/Resources/models-dev-api.json` | **MIT** ([models.dev](https://models.dev)) | |
| Swift packages: SwiftAnthropic (**MIT**), swift-cmark (**BSD-2-Clause**), SwiftMath (**MIT**), RealTimeCutVADLibrary (**MIT**) and the Apache-2.0 Swift Server packages they pull in | `Minis.xcodeproj`, pinned in `Package.resolved` | as listed | Versions in upstream's inventory |

### The nanoMuse mark

The name nanoMuse and the mark in `assets/brand/` are the project's own. Use them to refer to this project; do not use them to suggest that something else is nanoMuse or endorsed by it.

## The runtime, the relay, the web console and the showcase (`nanomuse/`, `cloud/`, `web/`, `demo/`)

Our own code, GPL-3.0-or-later like the rest. Third-party code inside it keeps its own licence and notice; the ports named below say where they come from.

### MemGUI-Bench (MIT)

The phone operator (`nanomuse/phone/operator.py`) is a port of the `mobile_use` operator in [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) (`src/mobile_world/agents/implementations/qwen3vl.py` and its prompt): the tool schema, the system prompt's wording, the `Thought` / `Action` / `<tool_call>` reply shape, the 999-grid coordinates and the step history. Rewritten in nanoMuse's own structure, with rules added (passwords, payments, `ask_user`), Sentinel labels and traces.

```
MIT License

Copyright (c) 2026 MemGUI-Bench

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### MobileGym (Apache-2.0 code, CC BY-NC 4.0 data)

[MobileGym](https://github.com/Purewhiter/mobilegym) is the simulated Android phone the showcase runs on. `demo/mobilegym/apps/nanoMuse/` is an app module written for it; `demo/mobilegym/install.sh` copies the module into a MobileGym checkout and the showcase image (`demo/showcase/caddy/Dockerfile`) builds MobileGym with it. MobileGym's code is Apache-2.0; its default app data (`mobilegym-data`: synthetic and sanitised content, icons) is [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), **non-commercial use only**; the hosted showcase serves it as a free demonstration and nothing else. The finger overlay in `gui.ts` follows MobileGym's own touch-feedback timing.

### modern-screenshot (MIT)

The showcase's in-page screenshots use [modern-screenshot](https://github.com/qq15725/modern-screenshot) (Copyright (c) 2021-present wxm), pulled in at build time by `install.sh`.

### Caddy modules (Apache-2.0)

The showcase's Caddy is built with [caddy-dns/cloudflare](https://github.com/caddy-dns/cloudflare) (DNS-01 certificates) and [WeidiDeng/caddy-cloudflare-ip](https://github.com/WeidiDeng/caddy-cloudflare-ip) (trusted proxy ranges), both Apache-2.0, like [Caddy](https://github.com/caddyserver/caddy) itself.

### Figtree (SIL Open Font License 1.1)

The web app's typeface, [Figtree](https://github.com/erikdkennedy/figtree) by Erik Kennedy, ships in `web/public/fonts/` under the OFL (`web/public/fonts/OFL.txt`).

### nanobot (MIT)

The Feishu channel's WebSocket runner (`nanomuse/channels/feishu.py`, class `_Runner`) follows the shape of `FeishuWsRunner` in [nanobot](https://github.com/HKUDS/nanobot) (Copyright (c) 2025 HKUDS): the SDK's client on a thread with its own event loop, swapping the module-level loop and calling its private `_connect` / `_disconnect` / `_ping_loop`. Rewritten for nanoMuse's channel base; the arrangement is theirs.

### UI-TARS-desktop (Apache-2.0)

The desktop app's hands on the computer are ported from [UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) (Copyright (c) 2025 Bytedance, Inc. and its affiliates), Apache-2.0:

- `harness/desktop/src/operator.ts`: the operator (`NutJSOperator` in `packages/ui-tars/operators/nut-js/src/index.ts`, `NutJSElectronOperator` in `apps/ui-tars/src/main/agent/operator.ts`, `getScreenSize` in `apps/ui-tars/src/main/utils/screen.ts`): the screenshot through Electron's `desktopCapturer` at the display's size with the libnut fallback, the action switch (move straight to the point, a 100 ms rest, then the click; drag; scroll; type through the clipboard; the hotkey table with `ctrl` as ⌘ on a Mac), the screen size as logical size × scale factor (1 on macOS), the mouse speed.
- `harness/desktop/resources/glow.html`: the prediction marker (`apps/ui-tars/src/main/shared/setOfMarks.ts`, `apps/ui-tars/src/main/window/ScreenMarker.ts`): the turning dashed ring with a dot at the point and the action's name beside it; the edge flow was already after their "screen water flow".
- `nanomuse/computer/coords.py`: `smart_resize` and the picture-size rules (`smartResizeForV15` in `packages/ui-tars/action-parser/src/actionParser.ts`, `parseBoxToScreenCoords` in `packages/ui-tars/sdk/src/utils.ts`: factor 28, the pixel bounds, the 1000-grid conversion).
- `harness/desktop/src/mac-permissions.ts`: the macOS permission arrangement (`apps/ui-tars/src/main/utils/systemPermissions.ts`): the two native modules below, `getAuthStatus` for Screen Recording and Accessibility, the system's own prompts at launch and the Screen Recording pane opened when it is missing; and the Chromium `disable-features` switch for ScreenCaptureKit thumbnails (electron/electron#44504) in `main.ts`.

Each file carries the attribution line; rewritten in nanoMuse's structure (the operator answers the runtime over loopback HTTP rather than running the model loop itself). The dependency `@computer-use/nut-js` (`harness/desktop/package.json`) is their fork of nut.js, Apache-2.0, with libnut's prebuilt addon per platform. Two more of their packages are optional dependencies of the desktop app, macOS only, both **MIT**: `@computer-use/node-mac-permissions` 2.2.2 (nut-tree's fork of Shelley Vohr's [node-mac-permissions](https://github.com/codebytere/node-mac-permissions); a prebuilt universal `permissions.node` for TCC status and the system prompts) and `@computer-use/mac-screen-capture-permissions` 1.0.2 (a fork of George Karagkiaouris's [mac-screen-capture-permissions](https://github.com/karaggeorge/mac-screen-capture-permissions); `CGPreflightScreenCaptureAccess` through a small N-API addon built at install time on a Mac, with `electron-util`, `execa` and `macos-version`, all MIT, beneath it).

### Python and JavaScript dependencies

Installed from PyPI and npm, not vendored; each carries its own license: openai, pydantic, httpx, typer, rich, loguru, cryptography, tenacity, ddgs, beautifulsoup4, html2text, mcp, fastapi, uvicorn, qrcode, pywebpush, python-dateutil, pillow, pypdf (Python); lark-oapi, dingtalk-stream, wecom-aibot-sdk-python when the `channels` extras are installed; react, react-dom, react-markdown, remark-gfm, lucide-react, tailwindcss, vite (web); `@computer-use/nut-js`, `@computer-use/node-mac-permissions`, `@computer-use/mac-screen-capture-permissions` (desktop, above). `pip show <name>` / `npm view <name> license` for any of them.

### Tools called, not bundled

[bubblewrap](https://github.com/containers/bubblewrap) (LGPL-2.0-or-later) sandboxes commands on Linux when installed; [Playwright](https://github.com/microsoft/playwright) (Apache-2.0) drives the browser tool when the `browser` extra is installed. Neither is part of the package.

## Learned from, no code taken

- **Meta Muse**: the product shape, one agent with a name and a look of its own, a feed, goals, "asks before anything you could not undo". nanoMuse is an independent project, not affiliated with or endorsed by Meta Platforms, Inc.; nothing of the Muse app was decompiled or copied.
- **[PhoneHarness](https://github.com/PhoneHarness/PhoneHarness)**: deterministic-first routing (a tool that does the thing exactly beats the GUI) and a JSONL trace per run rendered to HTML. Ideas only: the repository carries no license.
- **[CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse)** (MIT): product designs we follow rather than code: durable tasks with a take-control hand-off, watches, ideas with evidence, a follow-up queue, "content is evidence, not permission", background-update preferences.
- **[Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)** (Apache-2.0) and **[ClawGUI](https://github.com/ZJU-REAL/ClawGUI)** (Apache-2.0): reference points for operating a phone through its screen (package tables, Shizuku, a built-in IME, a floating bar). When code from either lands, it will be listed above.
- **[browser-use](https://github.com/browser-use/browser-use)** (MIT): the element-annotation idea behind the browser tool.
