# 手机上的 nanoMuse：本地运行时

> **旧版 Python 实现的设计记录**。当前 Android App 使用 OpenMinis 自带的 Linux 沙箱在手机上运行智能体，不再使用本文的 PRoot + Alpine + Python 方案。你下载的 APK 中没有 `rootfs.yml`，没有 `local` / `connect` 构建变体，也没有 `nanomuse-device` 命令行工具。当前实现见 [android.md](android.md)。本文提到的 `scripts/rootfs/`、`android/native/` 和 `runtime/` 下的 Kotlin 文件已从当前源码移除，可以在历史标签 `pre-openminis` 中查看。

旧版 Python 实现的 Android App 有两个变体。**connect** 用来远程操作电脑上的 `nanomuse serve`，见 [archive/android-python-line.md](../archive/android-python-line.md)。**local** 则将同一个 Python 服务器、工具和 Linux 沙箱全部放在手机上运行，无需另外安装其他程序。本文介绍 local 变体。

它的工作方式是：APK 内置一个小型 Alpine Linux 根文件系统（运行 Linux 程序所需的目录和文件），其中已安装 Python 和 `nanomuse`。首次启动时，App 将其解压到私有存储，使用 [PRoot](https://proot-me.github.io/) 运行 `nanomuse serve`。PRoot 在用户态模拟 `chroot`，让程序使用指定目录作为根目录，不需要取得手机的 root 权限。App 随后用 WebView（内嵌浏览器）打开 `http://127.0.0.1:<port>/`。智能体的 Python 实现保持不变，Kotlin 代码负责安装、启动和管理它。

```
┌─ nanoMuse.apk ───────────────────────────────────────────────────┐
│  Kotlin shell            assets/rootfs.tar.xz     lib/…/libproot.so │
│  ConnectActivity         Alpine 3.21 aarch64      PRoot 5.1        │
│  RuntimeService  ──┐     python 3.12, nanomuse    libproot-loader.so│
│  WebView ──────────┼──►  node 22 (optional)                        │
└────────────────────┼─────────────────────────────────────────────┘
                     │ starts, watches, restarts
        ┌────────────▼──────────────────────────────────────────────┐
        │ proot -0 -r files/rootfs -b files/home:/root … \           │
        │       /bin/sh /usr/local/bin/nanomuse-serve                │
        │   └─ nanomuse serve --host 127.0.0.1 --port N --token T    │
        │        shell / python / files / browser / MCP / skills     │
        └───────────────────────────────────────────────────────────┘
```

## 用户看到的流程 {#what-the-user-sees}

首屏询问在哪里运行 nanoMuse，提供「在这台手机上运行」和「连接我的电脑」两个选项。选择前者后，App 显示解压进度，安装根文件系统。解压后约占 330 MB，通常需要一分钟左右。随后 App 启动运行时（实际执行智能体任务的程序），等待首次健康检查通过，再进入主界面。此后每次打开 App，都会启动运行时；一条不发出提示声的通知会显示「在这台手机上运行」或智能体当前任务，并提供「停止」操作。手机重启后，运行时也会自动恢复，让例程和目标检查继续执行。

如果启动失败，错误页面会显示运行时最后几行日志，并提供「重试」和「从头开始」。选择「从头开始」会返回首屏，不会删除手机上的数据。

## 数据存放位置 {#where-things-live}

所有内容都位于 App 的私有文件目录 `/data/data/io.github.nanomuse.app/files`，其他 App 无法读取：

| 路径 | 运行环境内的路径 | 内容 |
| --- | --- | --- |
| `rootfs/` | `/` | Alpine、Python 和 `nanomuse`，更新 App 时整体替换 |
| `home/` | `/root` | 数据目录 `~/.nanomuse`、工作区、npm 全局包和 uv 缓存，更新后保留 |
| `etc/resolv.conf`、`etc/hosts` | `/etc/…` | 每次启动前根据手机网络设置生成 |
| `proc/` | `/proc/stat` … | 替代 Android 不允许 App 读取的 `/proc` 文件 |
| `tmp/` | `/tmp` | 临时目录，同时供 PRoot 使用 |
| `logs/runtime.log` | — | PRoot 和服务器输出的日志，到 2 MB 时轮换 |

更新 App 时会带入新的 `rootfs.tar.xz` 和版本标记。下次启动发现安装标记与新版本不一致时，App 会先在原目录旁解压新版，再替换旧目录。它不会修改 `home/`，因此配置档案、记忆、技能和工作区都会保留。

## 启动方式 {#how-it-is-started}

`LocalRuntime.command()` 负责构造 PRoot 命令行：

```
libproot.so -0 --kill-on-exit --link2symlink
    -r <files>/rootfs -w /root
    -b /dev -b /proc -b /sys
    -b <files>/home:/root  -b <files>/tmp:/tmp
    -b <files>/etc/resolv.conf:/etc/resolv.conf  -b <files>/etc/hosts:/etc/hosts
    [-b <files>/proc/stat:/proc/stat …  for each unreadable /proc file]
    /bin/sh /usr/local/bin/nanomuse-serve
```

- `-0`：向程序模拟 uid 0。`apk add` 等命令要求 root 身份，但这里并没有取得真正的 root 权限。
- `--kill-on-exit`：App 进程被终止时，同时结束它启动的进程，避免遗留孤儿进程。
- `--link2symlink`：Android 不允许对 App 文件创建硬链接，PRoot 因此用符号链接模拟。pip 和 apk 都会创建硬链接。
- 加载器存放在根文件系统之外。`PROOT_LOADER` 指向 App 的 `nativeLibraryDir` 中的 `libproot-loader.so`。现代 Android 按 W^X 限制可执行文件，这里是允许 App 执行二进制文件的位置。出于同样原因，PRoot 本体作为 `.so` 文件放在 `jniLibs/`，不作为普通资源打包。

根文件系统中的 `nanomuse-serve` 还会读取以下环境变量：

| 变量 | 值 |
| --- | --- |
| `NANOMUSE_SERVER_PORT` / `NANOMUSE_SERVER_TOKEN` | 首次选定的空闲回环端口，以及 32 字节随机令牌；WebView 使用同一组值连接 |
| `NANOMUSE_DEVICE=android`、`NANOMUSE_DEVICE_MODEL`、`NANOMUSE_DEVICE_SDK` | 告诉 Python 程序当前运行在手机上，见 `nanomuse/runtime.py` |
| `NANOMUSE_HOST_URL` / `NANOMUSE_HOST_TOKEN` | App 提供本地 API（程序调用接口）时的地址与凭据；手机功能作为名为 `device` 的 MCP 服务器接入 |
| `NANOMUSE_REGION` | 手机地区；值为 `CN` 时，首次启动会通过 `nanomuse-mirror cn` 切换 apk 和 pip 镜像源 |
| `TZ` | 手机的 IANA 时区，让例程按手机当地时间触发 |
| `http_proxy` / `https_proxy` | 已配置的系统代理 |
| `UV_LINK_MODE=symlink` | 让 uv 使用符号链接，否则它会创建硬链接 |
| `HOME=/root`、`PATH`、`LANG=C.UTF-8`、`TMPDIR=/tmp`、`PROOT_TMP_DIR` | 常规的主目录、命令搜索路径、语言及临时目录设置 |

随后 `RuntimeService` 轮询 `GET /api/health`。首次冷启动最多等待两分钟，后续启动通常几秒内响应。检查成功后，它会像通知服务一样订阅 `/ws`：审批（需要你决定是否允许操作）、提问和已完成的后台任务，都由同一个 `Notifier` 转成通知。`status` 事件更新通知文字，并控制 `PARTIAL_WAKE_LOCK`（让任务执行期间 CPU 保持运行的唤醒锁）。锁仅在执行任务时持有，附加 15 秒宽限期，最长持有 30 分钟。进程退出后，服务按 2、4、8……60 秒的间隔逐步延迟重启；一分钟内达到五次后停止重试并显示日志。

## 按时唤醒 {#waking-up}

屏幕关闭后，Android 的 Doze 省电机制会在系统维护窗口之间冻结 App 进程。Python 调度器即使原计划在 07:30 恢复，也可能错过时间。因此，Python 和 Android 共用一份待执行时间表，由 Android 负责唤醒：

- Python 调度器等待 `asyncio.Event` 事件，而不是使用固定计时器。`Service.next_wake_at()` 给出最近一次待执行时间，可能是提醒、避开安静时段后的目标检查，或主动模式下的下一次后台检查。时间变化时，运行时会向 `/ws` 发布 `schedule` 事件，也会在 `GET /api/upcoming` 中以 `next_wake_at` 返回该时间。
- `RuntimeService` 连接后先读取 `/api/upcoming`，随后接收每个 `schedule` 事件，并通过 `WakeAlarms` 设置一次系统闹钟。App 有精确闹钟权限时调用 `setExactAndAllowWhileIdle`，否则调用 `setAndAllowWhileIdle`。Android 14 不会向新安装的 App 自动授予 `SCHEDULE_EXACT_ALARM`；用户在设置 → 保持运行中授权前，通常使用非精确闹钟。这类闹钟由 Android 合并触发，最多延后几分钟，不会提前执行。
- 闹钟触发后，`WakeReceiver` 通知服务，最多获取 45 秒唤醒锁，并调用 `POST /api/tick`，然后按运行时给出的下次时间重新设闹钟。`tick` 触发事件，Python 调度器恢复执行并处理到期任务。任务期间的 `status` 事件会继续维持唤醒锁，直到工作完成，与用户手动启动任务时相同。

没有待执行事项时，不设系统闹钟，运行时保持空闲，直到 WebView 或通知操作将其唤醒。在电脑上，`nanomuse serve` 不会被手机省电机制冻结，因此 `next_wake_at` 仅供查看。调用 `POST /api/tick` 只会提前结束调度器当前的等待，没有其他影响。

## Python 如何适配手机 {#the-python-side-on-a-phone}

`nanomuse.runtime.device()` 读取 `NANOMUSE_DEVICE*` 环境变量，随后影响以下行为：

- 沙箱会如实说明隔离方式。PRoot 中没有 bubblewrap 隔离工具，App 的根文件系统本身就是运行环境。`Sandbox.describe()` 会在系统提示词中说明这一点，shell 命令直接运行。
- 设置 `NANOMUSE_HOST_URL` 后，`nanomuse serve` 会将 App 的手机功能作为名为 `device` 的 MCP 服务器加入。MCP 是让智能体发现和调用外部工具的协议。Kotlin 程序在 `127.0.0.1` 上运行小型 MCP 服务器，工具以 `device__<name>` 命名，例如 `device__calendar_list` 和 `device__clipboard_read`，每个工具都有各自的哨兵（Sentinel）默认权限规则。工具、权限和用户授权流程见 [device.md](device.md)。
- **命令行桥接**。每次调用 `shell` 或 `python_execute` 时，沙箱先移除环境中的全部 `NANOMUSE_*`，再加入仅对当前命令有效的凭据 `NANOMUSE_BRIDGE` 和 `NANOMUSE_BRIDGE_TOKEN`。命令结束后凭据即被撤销，后台子进程有 30 秒宽限期。根文件系统中有三个只依赖 Python 标准库的 CLI（命令行工具），使用这组凭据回调服务器：

  | CLI | 作用 |
  | --- | --- |
  | `nanomuse-device <capability> [action] [k=v …]` | 调用设备工具：`clipboard read`、`calendar list from=2026-09-24`、`alarm set hour=7 minute=30 message=Train`、`contacts search query=张`、`notify title=Done body=Booked`、`location`、`photo pick`；`nanomuse-device list` 列出当前手机支持的功能，见 [device.md](device.md) |
  | `nanomuse-browser <action> [k=v …]` | 调用 `browser` 工具：`navigate` / `extract` / `click` / `type` / `key` / `scroll` / `back` / `wait` / `screenshot` / `fetch URL [--post BODY]`（携带浏览器 cookie）/ `profile mobile\|desktop` / `close`，见 [browser.md](browser.md) |
  | `nanomuse-open <url>` | 在 App 的浏览器接管面板中打开页面；根文件系统将该命令设为 `BROWSER` |

  服务器会在发起命令的上下文中，把这类请求作为嵌套工具调用执行。它们使用相同的哨兵、权限和时间线，`tool` 事件带有 `via: "shell"`。因此脚本调用同样受权限规则约束。在手机之外，如果环境中没有 `NANOMUSE_BRIDGE`，这些 CLI 会打印一行说明并以状态码 2 退出；电脑上的相应操作由桌面端完成。

## 限制 {#limits}

- **PRoot 运行在用户态**。它不提供真正的 root 权限，不能挂载文件系统、使用原始套接字，也不能在内部再次使用 `ptrace`，因为 PRoot 自身已在使用它。程序读取 `/proc/self/…` 或 `/proc/stat` 时，得到的是 Android 的真实数据或替代文件。绑定 1024 以下端口、更改 uid 等 Android 不允许 App 执行的操作仍会失败，与 Termux 相同。
- **系统调用会变慢**。PRoot 使用 `ptrace` 跟踪每次系统调用。以计算为主的 Python 程序几乎不受影响；频繁调用系统功能的操作，例如用 `git clone` 克隆大型仓库、用 `pip install` 安装大量小文件或执行 `find /`，会比原生运行慢 2–5 倍。`nanomuse serve` 自身大部分时间处于空闲状态。
- **使用 musl 标准库**。Alpine 使用 musl，常见 Python wheel 安装包通常有 `musllinux` 版本。如果预编译二进制依赖 glibc，需要执行 `apk add gcompat`。Node 也使用 Alpine 版本。
- **根文件系统不运行 Chromium**。Playwright 无法在这里启动浏览器，浏览操作始终使用 App 自带 WebView，即 `Browser` 工具的设备后端；脚本通过 `nanomuse-browser` 访问，见 [browser.md](browser.md)。`apk add chromium` 虽能安装，但 Chromium 无法在 Android 的 PRoot 中启动。
- **存储空间**。解压后约占 330 MB，另加用户自行安装的软件。压缩根文件系统小于 70 MB，APK 会略大一些。
- **后台运行限制**。内存不足或厂商电池管理较严格时，Android 仍可能终止服务。各厂商的电池设置见 [archive/android-python-line.md](../archive/android-python-line.md#keeping-it-running)。服务采用 `START_STICKY`，会尝试重启；前文的系统闹钟不依赖进程存活。运行时恢复后，调度器会补做错过的例程。
- **预装软件**。包含 Alpine 的 `apk`、`git`、`curl`、`jq`、`bash`、`openssh-client`、带 `pip` 的 `python3`，以及带 `npm` 的 Node。未预装体积为 35 MB 的 `uv`，需要时可执行 `pip install uv`。`nanomuse-mirror cn|default` 可以在上游服务器和中国大陆镜像之间切换 apk、pip、npm 软件源，首次启动按手机地区选择。
- **Node 可省略**。使用 `NODE=0 scripts/rootfs/build.sh` 可构建不含 Node 的根文件系统，压缩后约小 12 MB。默认包含 Node，是因为展示站使用的中国服务工具 lark-cli、`@tencentcloud/tmeet`、`12306-mcp` 都以 npm 包提供。

## 构建各部分，历史版本 `pre-openminis` {#building-the-pieces}

```bash
# the root file system (Docker with QEMU for arm64: docker run --privileged --rm tonistiigi/binfmt --install arm64)
scripts/rootfs/build.sh                # → dist/rootfs/nanomuse-rootfs-<ver>-aarch64.tar.xz + .json,
                                       #   copied to android/app/src/local/assets/rootfs.{tar.xz,json}
APK_MIRROR=https://mirrors.aliyun.com PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  scripts/rootfs/build.sh              # the same, with mirrors for the build machine only
scripts/rootfs/build.sh --platform linux/amd64 --no-install   # the same image for your computer, to poke at

# PRoot (needs the Android NDK)
ANDROID_NDK_HOME=~/Android/Sdk/ndk/27.2.12479018 android/native/build-proot.sh
                                       # → android/app/src/local/jniLibs/arm64-v8a/libproot{,-loader}.so

# the app
cd android && ./gradlew assembleLocalDebug assembleConnectDebug   # app/build/outputs/apk/{local,connect}/debug/
```

`scripts/rootfs/Dockerfile` 定义了完整构建流程。wheel 阶段从当前检出的代码构建 `nanomuse` 安装包；rootfs 阶段将 Alpine 软件包、Python 和 wheel 安装到 `/opt/nanomuse`，按配置加入 Node，再安装 `nanomuse-serve`、`nanomuse-mirror` 两个辅助脚本，最后删除测试、文档和缓存。`/etc/nanomuse-rootfs` 记录安装内容。如果压缩 tar 的体积超过 `ROOTFS_MAX_MB`，默认 80 MB，构建就会失败。

PRoot 基于 [Termux 分支](https://github.com/termux/proot)的 `5.1.107.94` 构建。该分支包含 Android 所需修改：`--link2symlink`、ashmem/memfd，以及独立的加载器文件。构建还使用 talloc `2.4.3`。两者都通过 SHA-256 固定来源内容，并用 NDK 的 clang 面向 API 26 编译。PRoot 采用 GPL-2.0 许可，作为 App 启动的独立可执行程序运行，没有链接进 App。许可声明和源码提供说明见 `THIRD_PARTY_NOTICES.md`。

旧版 Python 实现的 CI（自动构建与检查流程）使用 `rootfs.yml` 工作流构建这些内容，并放入 `local` APK。相关工作流现在都已移除；当前 `android.yml` 构建的是基于 OpenMinis 的 APK，见 [android.md](android.md)。

## 文件职责，历史版本 `pre-openminis` {#files}

| 文件 | 作用 |
| --- | --- |
| `android/app/src/main/java/…/runtime/LocalRuntime.kt` | 安装流程，包括解压进度、目录替换和版本标记；构造 PRoot 命令与环境，生成网络配置和替代 `/proc` 文件，管理日志 |
| `…/runtime/TarUnpacker.kt` | 读取根文件系统 tar，支持 ustar / PAX / GNU 长文件名、符号链接、硬链接和权限位；拒绝会越出目标目录的条目 |
| `…/runtime/RuntimeService.kt` | 前台服务，负责启动、健康检查、延迟重启、将 `/ws` 事件转成通知文字并管理唤醒锁，以及处理停止操作 |
| `…/Notifier.kt` | 将事件转成通知，与远程模式的 `NotifyService` 共用 |
| `nanomuse/runtime.py` | 通过 `device()` 向 Python 提供手机信息，并配置 `device` MCP 服务器 |
| `nanomuse/bridge/` | 管理令牌、`/api/bridge/*` 服务端接口和三个 CLI |
| `scripts/rootfs/` | Dockerfile、`build.sh` 和根文件系统内的两个辅助脚本 |
| `android/native/build-proot.sh` | 使用 NDK 构建 PRoot 和 talloc |
