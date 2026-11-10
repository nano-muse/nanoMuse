# Third-party notices

### Remodex (Apache-2.0)

The apply_patch reader in `nanomuse/coding/timeline.py` and
`harness/dsh-nanomuse/src/coding-timeline.ts` adapts
`phodex-bridge/src/apply-patch-changes.js` from Remodex at
commit `f67b1499dbd8ace7a23902fad3242cc88f7e9a9e`,
Copyright 2025-2026 Emanuele Di Pietro. Modifications are documented in those files.
The full licence is retained below in [Apache License 2.0 (Remodex)](#apache-license-20-remodex).
The iOS layout follows nanoMuse's own components. No Remodex relay, SDK or daemon is shipped.

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
| Haze (dev.chrisbanes.haze:haze-android), the blur behind the bottom bar | 1.6.10 | **Apache-2.0** |
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

### The default face

The dragon that every app wears until a person picks another is the project's own asset, under the same GPL-3.0-or-later as the rest of the repository. The maintainer made it on 2026-09-25 (commit `58ccf1aa`): the five stills (`idle`, `working`, `waiting`, `happy`, `error`; WebP, 1024 × 1024) were drawn and posed with Alibaba Cloud Model Studio's `qwen-image-3.0-pro`, and the four short clips were animated from them with MiniMax's `MiniMax-H3`. The one set of files is shipped byte for byte in `web/public/avatars/dragon-*` (and the built copy under `nanomuse/server/static/avatars/`), `harness/dsh-nanomuse/assets/dragon-*`, the Android app's `res/drawable-nodpi/nm_avatar_*.webp` and `res/raw/nm_motion_*.mp4`, the iOS app's `NanoMuse/Resources/dragon-*`, and `demo/mobilegym/apps/nanoMuse/res/dragon-idle.webp`. The terms of the two services under which generated output may be redistributed are not recorded in this repository; the maintainer is the one to confirm them.

## The runtime, the relay, the web console, the desktop app and the showcase (`nanomuse/`, `cloud/`, `web/`, `harness/`, `demo/`)

Our own code, GPL-3.0-or-later like the rest. Third-party code inside it keeps its own licence and notice; the ports named below say where they come from.

### DeepSeek Harness (MIT)

The desktop app is a plugin for [DeepSeek Harness](https://www.npmjs.com/package/@deepseek-ai/dsh) (`@deepseek-ai/dsh` and the `@deepseek-ai/dsh-*` packages, 0.2.0-rc.2, MIT), carried inside nanoMuse Desktop unmodified with every package's licence file; it is not vendored in this repository (`harness/dsh-nanomuse/package.json`, `harness/desktop/scripts/prepare-dsh.mjs`). "DeepSeek Harness" and "DSH" are DeepSeek's names; *harness* in `harness/` is the word ([harness/README.md](harness/README.md#licence-and-names)). The shell is [Electron](https://github.com/electron/electron) (MIT), installed by npm at build time.

### DSH Desktop Windows console adapter (MIT)

The Windows ACL runner adapter in `harness/dsh-nanomuse/src/windows-*.ts` is adapted from
[DSH Desktop](https://github.com/anywhere-labs/dsh-desktop).

```
MIT License

Copyright (c) 2026 Anywhere Labs

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

The web app's typeface, [Figtree](https://github.com/erikdkennedy/figtree) by Erik Kennedy, ships in `web/public/fonts/` under the OFL (`web/public/fonts/OFL.txt`). The desktop app and the docs site are set in the system's fonts (`harness/dsh-nanomuse/src/client/styles.ts`, `website/.vitepress/theme/custom.css`; VitePress's default theme still ships its own Inter files, OFL, in the built site); the Android app's monospace face, JetBrains Mono under `res/font/`, is upstream's and covered by the OpenMinis inventory above.

### simple-icons (CC0 1.0)

The brand marks beside the services in the desktop app's connector catalogue are SVG paths from [simple-icons](https://simpleicons.org/) 16.33.0, written into `harness/dsh-nanomuse/src/client/brand-marks.ts` by `harness/dsh-nanomuse/scripts/brand-marks.mjs`. The set is CC0 1.0; the marks and names themselves belong to the services they stand for and only say which service a row is.

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

Installed from PyPI and npm, not vendored; each carries its own license: openai, pydantic, httpx, typer, rich, loguru, cryptography, tenacity, ddgs, beautifulsoup4, html2text, mcp, fastapi, uvicorn, qrcode, pywebpush, python-dateutil, pillow, pypdf, zstandard (Python); lark-oapi, dingtalk-stream, wecom-aibot-sdk-python when the `channels` extras are installed; react, react-dom, react-markdown, remark-gfm, lucide-react, tailwindcss, vite (web); `@computer-use/nut-js`, `@computer-use/node-mac-permissions`, `@computer-use/mac-screen-capture-permissions` (desktop, above). `pip show <name>` / `npm view <name> license` for any of them.

### Tools called, not bundled

[bubblewrap](https://github.com/containers/bubblewrap) (LGPL-2.0-or-later) sandboxes commands on Linux when installed; [Playwright](https://github.com/microsoft/playwright) (Apache-2.0) drives the browser tool when the `browser` extra is installed. Neither is part of the package. The relay downloads [ip2region](https://github.com/lionsoul2014/ip2region)'s `xdb` database (Apache-2.0) once into its data directory to name the country, province and city of an address on the operator's page (`cloud/nanomuse_cloud/geo.py`); the file is not in this repository.

## Learned from, no code taken

- **Meta Muse**: the product shape, one agent with a name and a look of its own, a feed, goals, "asks before anything you could not undo". nanoMuse is an independent project, not affiliated with or endorsed by Meta Platforms, Inc.; nothing of the Muse app was decompiled or copied.
- **[PhoneHarness](https://github.com/PhoneHarness/PhoneHarness)**: deterministic-first routing (a tool that does the thing exactly beats the GUI) and a JSONL trace per run rendered to HTML. Ideas only: the repository carries no license.
- **[CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse)** (MIT): product designs we follow rather than code: durable tasks with a take-control hand-off, watches, ideas with evidence, a follow-up queue, "content is evidence, not permission", background-update preferences.
- **[Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)** (Apache-2.0) and **[ClawGUI](https://github.com/ZJU-REAL/ClawGUI)** (Apache-2.0): reference points for operating a phone through its screen (package tables, Shizuku, a built-in IME, a floating bar). When code from either lands, it will be listed above.
- **[browser-use](https://github.com/browser-use/browser-use)** (MIT): the element-annotation idea behind the browser tool.

## Apache License 2.0 (Remodex)

The following is the original licence text distributed with Remodex.

```text
Apache License
Version 2.0, January 2004
http://www.apache.org/licenses/

TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

1. Definitions.

"License" shall mean the terms and conditions for use, reproduction,
and distribution as defined by Sections 1 through 9 of this document.

"Licensor" shall mean the copyright owner or entity authorized by
the copyright owner that is granting the License.

"Legal Entity" shall mean the union of the acting entity and all
other entities that control, are controlled by, or are under common
control with that entity. For the purposes of this definition,
"control" means (i) the power, direct or indirect, to cause the
direction or management of such entity, whether by contract or
otherwise, or (ii) ownership of fifty percent (50%) or more of the
outstanding shares, or (iii) beneficial ownership of such entity.

"You" (or "Your") shall mean an individual or Legal Entity
exercising permissions granted by this License.

"Source" form shall mean the preferred form for making modifications,
including but not limited to software source code, documentation
source, and configuration files.

"Object" form shall mean any form resulting from mechanical
transformation or translation of a Source form, including but
not limited to compiled object code, generated documentation,
and conversions to other media types.

"Work" shall mean the work of authorship, whether in Source or
Object form, made available under the License, as indicated by a
copyright notice that is included in or attached to the work
(an example is provided in the Appendix below).

"Derivative Works" shall mean any work, whether in Source or Object
form, that is based on (or derived from) the Work and for which the
editorial revisions, annotations, elaborations, or other modifications
represent, as a whole, an original work of authorship. For the purposes
of this License, Derivative Works shall not include works that remain
separable from, or merely link (or bind by name) to the interfaces of,
the Work and Derivative Works thereof.

"Contribution" shall mean any work of authorship, including
the original version of the Work and any modifications or additions
to that Work or Derivative Works thereof, that is intentionally
submitted to Licensor for inclusion in the Work by the copyright owner
or by an individual or Legal Entity authorized to submit on behalf of
the copyright owner. For the purposes of this definition, "submitted"
means any form of electronic, verbal, or written communication sent
to the Licensor or its representatives, including but not limited to
communication on electronic mailing lists, source code control systems,
and issue tracking systems that are managed by, or on behalf of, the
Licensor for the purpose of discussing and improving the Work, but
excluding communication that is conspicuously marked or otherwise
designated in writing by the copyright owner as "Not a Contribution."

"Contributor" shall mean Licensor and any individual or Legal Entity
on behalf of whom a Contribution has been received by Licensor and
subsequently incorporated within the Work.

2. Grant of Copyright License. Subject to the terms and conditions of
this License, each Contributor hereby grants to You a perpetual,
worldwide, non-exclusive, no-charge, royalty-free, irrevocable
copyright license to reproduce, prepare Derivative Works of,
publicly display, publicly perform, sublicense, and distribute the
Work and such Derivative Works in Source or Object form.

3. Grant of Patent License. Subject to the terms and conditions of
this License, each Contributor hereby grants to You a perpetual,
worldwide, non-exclusive, no-charge, royalty-free, irrevocable
(except as stated in this section) patent license to make, have made,
use, offer to sell, sell, import, and otherwise transfer the Work,
where such license applies only to those patent claims licensable
by such Contributor that are necessarily infringed by their
Contribution(s) alone or by combination of their Contribution(s)
with the Work to which such Contribution(s) was submitted. If You
institute patent litigation against any entity (including a
cross-claim or counterclaim in a lawsuit) alleging that the Work
or a Contribution incorporated within the Work constitutes direct
or contributory patent infringement, then any patent licenses
granted to You under this License for that Work shall terminate
as of the date such litigation is filed.

4. Redistribution. You may reproduce and distribute copies of the
Work or Derivative Works thereof in any medium, with or without
modifications, and in Source or Object form, provided that You
meet the following conditions:

(a) You must give any other recipients of the Work or Derivative
    Works a copy of this License; and

(b) You must cause any modified files to carry prominent notices
    stating that You changed the files; and

(c) You must retain, in the Source form of any Derivative Works
    that You distribute, all copyright, patent, trademark, and
    attribution notices from the Source form of the Work,
    excluding those notices that do not pertain to any part of
    the Derivative Works; and

(d) If the Work includes a "NOTICE" text file as part of its
    distribution, then any Derivative Works that You distribute must
    include a readable copy of the attribution notices contained
    within such NOTICE file, excluding those notices that do not
    pertain to any part of the Derivative Works, in at least one
    of the following places: within a NOTICE text file distributed
    as part of the Derivative Works; within the Source form or
    documentation, if provided along with the Derivative Works; or,
    within a display generated by the Derivative Works, if and
    wherever such third-party notices normally appear. The contents
    of the NOTICE file are for informational purposes only and
    do not modify the License. You may add Your own attribution
    notices within Derivative Works that You distribute, alongside
    or as an addendum to the NOTICE text from the Work, provided
    that such additional attribution notices cannot be construed
    as modifying the License.

You may add Your own copyright statement to Your modifications and
may provide additional or different license terms and conditions
for use, reproduction, or distribution of Your modifications, or
for any such Derivative Works as a whole, provided Your use,
reproduction, and distribution of the Work otherwise complies with
the conditions stated in this License.

5. Submission of Contributions. Unless You explicitly state otherwise,
any Contribution intentionally submitted for inclusion in the Work
by You to the Licensor shall be under the terms and conditions of
this License, without any additional terms or conditions.
Notwithstanding the above, nothing herein shall supersede or modify
the terms of any separate license agreement you may have executed
with Licensor regarding such Contributions.

6. Trademarks. This License does not grant permission to use the trade
names, trademarks, service marks, or product names of the Licensor,
except as required for reasonable and customary use in describing the
origin of the Work and reproducing the content of the NOTICE file.

7. Disclaimer of Warranty. Unless required by applicable law or
agreed to in writing, Licensor provides the Work (and each
Contributor provides its Contributions) on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
implied, including, without limitation, any warranties or conditions
of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
PARTICULAR PURPOSE. You are solely responsible for determining the
appropriateness of using or redistributing the Work and assume any
risks associated with Your exercise of permissions under this License.

8. Limitation of Liability. In no event and under no legal theory,
whether in tort (including negligence), contract, or otherwise,
unless required by applicable law (such as deliberate and grossly
negligent acts) or agreed to in writing, shall any Contributor be
liable to You for damages, including any direct, indirect, special,
incidental, or consequential damages of any character arising as a
result of this License or out of the use or inability to use the
Work (including but not limited to damages for loss of goodwill,
work stoppage, computer failure or malfunction, or any and all
other commercial damages or losses), even if such Contributor
has been advised of the possibility of such damages.

9. Accepting Warranty or Additional Liability. While redistributing
the Work or Derivative Works thereof, You may choose to offer,
and charge a fee for, acceptance of support, warranty, indemnity,
or other liability obligations and/or rights consistent with this
License. However, in accepting such obligations, You may act only
on Your own behalf and on Your sole responsibility, not on behalf
of any other Contributor, and only if You agree to indemnify,
defend, and hold each Contributor harmless for any liability
incurred by, or claims asserted against, such Contributor by reason
of your accepting any such warranty or additional liability.

END OF TERMS AND CONDITIONS

APPENDIX: How to apply the Apache License to your work.

To apply the Apache License to your work, attach the following
boilerplate notice, with the fields enclosed by brackets "[]"
replaced with your own identifying information. (Don't include
the brackets!) The text should be enclosed in the appropriate
comment syntax for the file format. We also recommend that a
file or class name and description of purpose be included on the
same "printed page" as the copyright notice for easier
identification within third-party archives.

Copyright 2025-2026 Emanuele Di Pietro

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
