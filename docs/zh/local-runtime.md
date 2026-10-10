# 手机上的 nanoMuse：本地运行时

> **Python 线的设计记录。** 现在的 Android App 通过 OpenMinis 自己的 Linux 沙箱在手机上
> 运行智能体，不是通过这套 PRoot + Alpine + Python 的安排；你下载的 APK 里没有 `rootfs.yml`，
> 没有 `local`/`connect` 变体，也没有 `nanomuse-device` CLI。见 [android.md](android.md)。这一页提到的
> 文件（`scripts/rootfs/`、`android/native/`、`runtime/` 下的 Kotlin）已经不在源码树里，在历史中的
> `pre-openminis` 标签处。


Python 线的 Android App 有两个变体。**connect** 是你电脑上那个 `nanomuse serve` 的遥控器（[archive/android-python-line.md](../archive/android-python-line.md)）。**local** 是完整的一套：同一个 Python 服务器、它的工具和它的 Linux 沙箱，全在手机上运行，别的什么都不用装。这一页讲的是第二个。

一句话说清这个想法：APK 带一个小小的 Alpine Linux 根文件系统，里面有 Python 和 `nanomuse`；第一次启动时 App 把它解压到自己的私有存储，在 [PRoot](https://proot-me.github.io/)（一个不需要 root 的用户态 `chroot`）下面运行 `nanomuse serve`；然后 App 的 WebView 打开 `http://127.0.0.1:<port>/`。大脑没变。Kotlin 只是托着它。

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

## 用户看到什么 {#what-the-user-sees}

第一屏问**你的 nanoMuse 该住在哪**：「在这台手机上运行」或「连接我的电脑」。选第一个，会带着进度条解压根文件系统（磁盘上约 330 MB，一分钟上下），启动运行时，等它第一次健康检查通过，然后打开 App。从那以后，每次打开 App 都会启动运行时；一条安静的通知（「在这台手机上运行」，或者智能体此刻在做什么）表明它活着，带一个**停止**动作。手机重启后运行时自己回来，例程和目标检查照常进行。

失败都落在一个屏幕上，带运行时最后几行日志、一个**重试**和一个**从头开始**。从头开始回到第一屏；它不会删手机上的数据。

## 东西放在哪 {#where-things-live}

一切都在 App 的私有文件目录下（`/data/data/io.github.nanomuse.app/files`），其他 App 读不到：

| 路径 | 箱子里 | 是什么 |
| --- | --- | --- |
| `rootfs/` | `/` | Alpine + python + `nanomuse`。App 更新时整个替换 |
| `home/` | `/root` | 数据目录（`~/.nanomuse`）、工作区、npm 的全局包、uv 的缓存。跨更新保留 |
| `etc/resolv.conf`、`etc/hosts` | `/etc/…` | 每次启动前按手机的网络设置写出 |
| `proc/` | `/proc/stat` … | 替身，顶替 Android 对 App 隐藏的那些 `/proc` 文件 |
| `tmp/` | `/tmp` | 也是 PRoot 自己的临时空间 |
| `logs/runtime.log` | — | PRoot 和服务器的输出；到 2 MB 滚动 |

App 更新带来新的 `rootfs.tar.xz` 和新的版本戳；下一次启动发现戳和已安装的标记不同，就在旧树旁边解压再交换。`home/` 从不被碰，所以 profile、记忆、技能和工作区都还在。

## 怎么启动 {#how-it-is-started}

`LocalRuntime.command()` 组装 PRoot 命令行：

```
libproot.so -0 --kill-on-exit --link2symlink
    -r <files>/rootfs -w /root
    -b /dev -b /proc -b /sys
    -b <files>/home:/root  -b <files>/tmp:/tmp
    -b <files>/etc/resolv.conf:/etc/resolv.conf  -b <files>/etc/hosts:/etc/hosts
    [-b <files>/proc/stat:/proc/stat …  for each unreadable /proc file]
    /bin/sh /usr/local/bin/nanomuse-serve
```

- `-0`：假 root。`apk add` 之类想要 uid 0；这里哪儿都没有真正的 root。
- `--kill-on-exit`：App 被杀时不留孤儿进程。
- `--link2symlink`：Android 的文件系统拒绝对 App 的文件做硬链接；PRoot 用符号链接模拟（pip 和 apk 都会做硬链接）。
- 加载器在根文件系统之外：`PROOT_LOADER` 指向 App `nativeLibraryDir` 里的 `libproot-loader.so`，这是现代 Android 唯一允许 App 执行二进制文件的地方（W^X）。PRoot 本身以 `.so` 的形式放在 `jniLibs/` 下而不是作为资源文件，也是同一个原因。

还有环境变量（rootfs 里的 `nanomuse-serve` 读它们）：

| 变量 | 值 |
| --- | --- |
| `NANOMUSE_SERVER_PORT` / `NANOMUSE_SERVER_TOKEN` | 选一次的空闲回环端口；一个 32 字节的随机令牌。WebView 用同一对 |
| `NANOMUSE_DEVICE=android`、`NANOMUSE_DEVICE_MODEL`、`NANOMUSE_DEVICE_SDK` | Python 这边知道自己在手机上（`nanomuse/runtime.py`） |
| `NANOMUSE_HOST_URL` / `NANOMUSE_HOST_TOKEN` | App 自己的本地 API，当它运行一个时：它的设备能力以 MCP 服务器 `device` 的身份加入 |
| `NANOMUSE_REGION` | 手机的地区；`CN` 在第一次启动时切换 apk 和 pip 镜像（`nanomuse-mirror cn`） |
| `TZ` | 手机的 IANA 时区，例程才会在对的钟点触发 |
| `http_proxy` / `https_proxy` | 系统代理，设了的话 |
| `UV_LINK_MODE=symlink` | 否则 uv 会做硬链接 |
| `HOME=/root`、`PATH`、`LANG=C.UTF-8`、`TMPDIR=/tmp`、`PROOT_TMP_DIR` | 老几样 |

然后 `RuntimeService` 轮询 `GET /api/health`（冷启动第一次最多等两分钟；热启动几秒就有回应），成功后像通知服务那样订阅 `/ws`：审批、提问和完成的后台工作都经同一个 `Notifier` 变成通知，`status` 事件驱动通知文字和一把只在任务运行时持有的 `PARTIAL_WAKE_LOCK`（15 秒宽限，上限 30 分钟）。进程死了就带退避重启（2、4、8……60 秒），一分钟内五次之后放弃，显示日志。

## 醒来 {#waking-up}

屏幕关着时，Doze 会在维护窗口之间冻结 App 的进程，而一个睡到 07:30 的 Python 调度器不知道自己睡过了 07:30。所以两边共用一份日程，而不是各自计时：

- Python 调度器在一个 `asyncio.Event` 上打盹，不用固定定时器，并且知道最早有事要做的时刻（`Service.next_wake_at()`）：下一个提醒、下一次目标检查（推到安静时段之后）、智能体主动时的下一次后台巡查。它一变，就作为 `schedule` 事件发布到 `/ws`，并在 `GET /api/upcoming` 里以 `next_wake_at` 报告。
- `RuntimeService` 读它（连接建立后先从 `/api/upcoming`，之后从每个 `schedule` 事件），并为它设一个闹钟（`WakeAlarms`）：App 被允许设精确闹钟时用 `setExactAndAllowWhileIdle`，否则 `setAndAllowWhileIdle`。Android 14 不给新装的 App `SCHEDULE_EXACT_ALARM`，所以在用户到「设置 → 保持运行」里授权之前，走的多半是不精确那条路；不精确意味着落在 Android 的批处理窗口之内，最多晚几分钟，从不提前。
- 闹钟响时，`WakeReceiver` 捅一下服务：它拿起唤醒锁最多 45 秒，调用 `POST /api/tick`，再按运行时接下来宣布的时刻重新上闹钟。`tick` 置位事件，调度器醒来，看什么到期了就跑；运行期间的 `status` 事件让唤醒锁一直持有到任务结束，和用户亲自启动时完全一样。

没有事到期 → 没有闹钟，运行时闲着，直到 WebView 或某个通知动作唤醒它。在电脑上同一个 `next_wake_at` 只是信息（`nanomuse serve` 从不睡觉），`POST /api/tick` 无害：提前结束当前这一觉，仅此而已。

## 手机上的 Python 这一边 {#the-python-side-on-a-phone}

`nanomuse.runtime.device()` 读 `NANOMUSE_DEVICE*`。有了它：

- 沙箱如实描述自己：PRoot 下没有 bubblewrap，App 自己的根文件系统*就是*箱子。`Sandbox.describe()` 在系统提示里这么说，shell 直接运行。
- 设了 `NANOMUSE_HOST_URL` 时，`nanomuse serve` 把 App 的设备能力作为 MCP 服务器 `device` 加进来：Kotlin 这边在 `127.0.0.1` 上跑一个小 MCP 服务器，工具以 `device__<name>` 出现（`device__calendar_list`、`device__clipboard_read`……），各有自己的哨兵（Sentinel）默认值。这些工具、它们的权限、它们会问用户什么：[device.md](device.md)。
- **CLI 桥。** 每次 `shell` 和 `python_execute` 调用都拿到一个只管一条命令的令牌（`NANOMUSE_BRIDGE`、`NANOMUSE_BRIDGE_TOKEN`），在沙箱清洗掉环境里所有 `NANOMUSE_*` 之后加入，命令结束时吊销（后台子进程有 30 秒宽限）。rootfs 里三个只用标准库的小 CLI 用它回调服务器：

  | CLI | 作用 |
  | --- | --- |
  | `nanomuse-device <capability> [action] [k=v …]` | 设备工具：`clipboard read`、`calendar list from=2026-09-24`、`alarm set hour=7 minute=30 message=Train`、`contacts search query=张`、`notify title=Done body=Booked`、`location`、`photo pick`；`nanomuse-device list` 显示这台手机有什么（[device.md](device.md)） |
  | `nanomuse-browser <action> [k=v …]` | `browser` 工具：`navigate` / `extract` / `click` / `type` / `key` / `scroll` / `back` / `wait` / `screenshot` / `fetch URL [--post BODY]`（带浏览器的 cookie）/ `profile mobile\|desktop` / `close`（[browser.md](browser.md)） |
  | `nanomuse-open <url>` | 在 App 内的接管面板里打开页面；rootfs 把它设为 `BROWSER` |

  服务器把请求当作嵌套的工具调用，在发起命令的那个上下文里运行：同一个哨兵、同一套权限、同一条时间线（`tool` 事件带 `via: "shell"`），所以脚本和模型一样逃不出规则。不在手机上时（环境里没有 `NANOMUSE_BRIDGE`）这些 CLI 以 2 退出并留一行说明；在电脑上这些事反正是从桌面做的。

## 局限 {#limits}

- **PRoot 是用户态的。** 没有真正的 root，不能挂载，没有原始套接字，里面不能 `ptrace`（PRoot 自己已经在用它）。读 `/proc/self/…` 或 `/proc/stat` 的程序拿到的是真实的 Android 值或替身。任何想要 Android 不授予 App 的能力的事（绑定 1024 以下的端口、改 uid）都会失败，和在 Termux 里一样。
- **系统调用更慢。** PRoot 靠 `ptrace` 每一个系统调用工作。计算密集的 Python 几乎不受影响；系统调用密集的工作（`git clone` 一棵大树、`pip install` 很多小文件、`find /`）比原生慢 2–5 倍。`nanomuse serve` 本身大部分时间是空闲的。
- **musl，不是 glibc。** Alpine 用 musl。大多数 Python wheel 有 `musllinux` 版本；假定 glibc 的预编译二进制需要 `apk add gcompat`。Node 是 Alpine 的构建。
- **rootfs 里没有 Chromium。** Playwright 在这里跑不起浏览器；浏览器始终是 App 自己的 WebView（`Browser` 工具的设备后端，脚本里用 `nanomuse-browser`；[browser.md](browser.md)）。`apk add chromium` 装得上，但在 Android 的 PRoot 下启动不了。
- **存储。** 解压后约 330 MB，加上用户自己装的东西。压缩的 rootfs 不到 70 MB；APK 略多一点。
- **后台限制。** 在内存紧张或厂商激进的电池管理下，Android 仍可能杀掉服务（各厂商的电池放行设置在 [archive/android-python-line.md](../archive/android-python-line.md#keeping-it-running)）。服务是 `START_STICKY`，会重启；上面说的闹钟在进程之外存活，调度器回来后补上错过的例程。
- **箱子里有什么。** Alpine 的 `apk`、`git`、`curl`、`jq`、`bash`、`openssh-client`、带 `pip` 的 `python3`，以及带 `npm` 的 Node。`uv` 没有（35 MB）；`pip install uv` 能装上。`nanomuse-mirror cn|default` 在上游服务器和中国大陆的镜像之间切换 apk、pip 和 npm；第一次启动按手机的地区选。
- **Node 是可选的。** `NODE=0 scripts/rootfs/build.sh` 产出不带它的 rootfs，压缩后小约 12 MB。默认带上，因为展示站里的中国服务（lark-cli、`@tencentcloud/tmeet`、`12306-mcp`）都是 npm 包。

## 构建各个部分 {#building-the-pieces}

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

`scripts/rootfs/Dockerfile` 就是整个配方：一个 wheel 阶段从检出的代码构建 `nanomuse`，rootfs 阶段把 Alpine 包、Python 和这个 wheel 装进 `/opt/nanomuse`，按需装 Node，装两个辅助脚本（`nanomuse-serve`、`nanomuse-mirror`），然后裁掉测试、文档和缓存。`/etc/nanomuse-rootfs` 记下装了什么。体积门槛（`ROOTFS_MAX_MB`，80）在压缩后的 tar 超出预算时让构建失败。

PRoot 从 [Termux 分支](https://github.com/termux/proot)构建（`5.1.107.94`，带 Android 修补：`--link2symlink`、ashmem/memfd、加载器作为单独文件），配 talloc `2.4.3`，两者都用 SHA-256 钉死，用 NDK 的 clang 面向 API 26。PRoot 是 GPL-2.0；它作为 App 启动的独立可执行文件运行，没有链接进 App。它的声明和源码提供在 `THIRD_PARTY_NOTICES.md`。

Python 线的 CI 里有一个 `rootfs.yml` 工作流构建这两样并放进 `local` APK；这两个工作流都已不存在（现在的 `android.yml` 构建基于 OpenMinis 的 APK，[android.md](android.md)）。

## 文件 {#files}

| 文件 | 作用 |
| --- | --- |
| `android/app/src/main/java/…/runtime/LocalRuntime.kt` | 安装（带进度解压、交换、版本标记）、PRoot 命令和环境、网络文件、假 `/proc`、日志 |
| `…/runtime/TarUnpacker.kt` | 根文件系统的 tar 读取器：ustar / PAX / GNU 长文件名、符号链接、硬链接、权限位；拒绝会逃出目录的条目 |
| `…/runtime/RuntimeService.kt` | 前台服务：启动、健康检查、带退避的重启、`/ws` → 通知文字和唤醒锁、停止动作 |
| `…/Notifier.kt` | 事件 → 通知，和 `NotifyService`（远程模式）共用 |
| `nanomuse/runtime.py` | `device()`：Python 这边看到的手机；`device` MCP 服务器 |
| `nanomuse/bridge/` | 令牌、服务器这边（`/api/bridge/*`）、三个 CLI |
| `scripts/rootfs/` | Dockerfile、`build.sh`、rootfs 里的两个脚本 |
| `android/native/build-proot.sh` | 用 NDK 构建 PRoot + talloc |
