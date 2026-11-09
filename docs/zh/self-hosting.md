# 自己运行 nanoMuse {#自己部署-nanomuse}

nanoMuse 可以在你自己的设备上运行，使用时不一定要经过我们提供的服务器。下面按维护工作从少到多，介绍三种做法。多数人只需给 App 填入自己的模型 key；家庭或小团队如果还想自己管理登录账号，可以部署中继；需要在自己的机器上使用网页版，则部署 Python 运行时。

> 术语说明：中继是负责登录和设备通信的服务器；hub 是同一账号下的设备互联服务；运行时是实际运行智能体、调用工具的程序；key 是模型服务商用来识别账号和计费的密钥。

| | 需要运行什么 | 可以做什么 |
|---|---|---|
| [1. 不部署服务器，使用自己的 key](#_1-no-server-your-own-key) | 不需要额外运行服务 | App 直接向模型服务商发请求；登录和设备发现仍使用社区中继 |
| [2. 部署自己的中继](#_2-your-own-relay) | 在小型 VPS 或家用服务器上运行 nanoMuse Cloud | 自己管理账号、登录验证码、hub 和对话同步；账号信息不经过 nanomuse.cn |
| [3. 为网页版部署自己的运行时](#_3-a-runtime-of-your-own-for-the-web-app) | 在 Docker 中运行 Python 运行时 | 在常开的电脑上运行网页版和执行设备操作的「手」 |

## 1. 不部署服务器，使用自己的 key {#_1-no-server-your-own-key}

社区中继提供的免费额度会用完。你可以在用完后，或提前在 App 中填入自己的 key。在中国大陆可以使用阿里云百炼，其他地区可以使用 OpenRouter 或任何兼容 OpenAI 接口的服务。此后，模型请求会从设备直接发送给所选服务商。如果仍登录账号，中继还会处理账号和设备之间通过 hub 传递的消息帧（协议中的一条消息）；启用记录功能时，App 也会把使用自有 key 的对话轮次上传到中继的账号记录。对话同步与训练数据开关分别控制其他用途，详见[隐私说明](privacy.md)。各个 App 的设置步骤见 [own-key.md](own-key.md)。这种方式无需安装或维护额外服务。

## 2. 部署自己的中继 {#_2-your-own-relay}

nanoMuse Cloud 是 nanomuse.cn 使用的中继服务。它提供邮箱或手机号登录，通过一个兼容 OpenAI 的接口提供账号可用的模型，还负责 hub、对话同步、`/app` 网页控制台和 `/app/admin/` 管理页。它由一个 Python 服务和一个 SQLite 数据库文件组成，代码在仓库的 [`cloud/`](../../cloud/README.md) 目录中，也可以部署到你自己的服务器上。

### 准备条件 {#what-you-need}

- **机器**。家庭使用时，1 vCPU、1 GB 内存的 VPS（虚拟服务器）即可。中继空闲时只占几十 MB 内存，模型计算由服务商完成。这类服务器在中国大陆每月约 ¥30–60，在其他地区约 US$4–6，选择哪家主机服务商都可以。如果只在局域网使用，家用服务器或闲置笔记本也能运行。
- **域名**。通过 A 记录将域名指向服务器，并开放 80 和 443 端口。与中继一起运行的 Caddy 会自动申请并续期 Let's Encrypt 证书。只在局域网使用时，可以省去域名和证书。
- **模型服务商的 key**。中继使用你的 key 向你的模型服务商付费。所有登录到这个中继的用户，都按服务商价格计费到这个 key，并受你设置的额度和注册规则限制：`ALLOWANCE_CNY`、`SIGNUP_OPEN`、`SIGNUP_PER_DOMAIN_DAY`、`SIGNUP_DOMAIN_BLOCK`，以及 `ALLOWED_IDENTIFIERS` 中的成员。配置说明见 [cloud/README.md](../../cloud/README.md#settings)。不填 key 时，登录和 hub 可以使用，但无法聊天。
- **Docker**，需带 compose 插件，并安装 `curl`。

### 用脚本部署 {#in-one-command}

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
bash scripts/self-host.sh
```

脚本会询问五项信息：域名或 `local`、用于 Let's Encrypt 的邮箱、验证码发送方式、模型服务商的 URL 和 key、管理员密码。随后，它会生成随机的 `CLOUD_SECRET` 并写入 `cloud/.env`，启动 `docker compose`，等待 `/healthz` 健康检查通过，最后打印控制台和管理页地址。再次运行时，已有密钥和账号会保留，提问时会以当前配置作为默认值。若只在本机使用，可以不配域名和 TLS（为网络连接加密的协议）：

```bash
bash scripts/self-host.sh --local          # 只给这台机器用：http://127.0.0.1:8787，验证码打在中继日志里
bash scripts/self-host.sh --local --bind 0.0.0.0   # 同一网络里的手机也能用：各处 URL 写的是这台机器的局域网地址
```

使用 `--bind 0.0.0.0` 时，中继监听所有网络接口。脚本会查找本机的局域网地址，例如 `192.168.1.20`，并将它用于 `PUBLIC_BASE`、邀请链接和打印的访问地址，因为手机需要通过这个地址连接。找不到局域网地址时，脚本会提示，并改用 `127.0.0.1`。如果为 `--bind` 指定一个地址，例如 Tailscale 地址，端口就只发布到该地址，链接也原样使用它。再次运行并更换 `--bind` 后，这些链接也会更新。

也可以手动配置：运行 `cd cloud && cp .env.example .env`，填写 `CLOUD_DOMAIN`、`PUBLIC_BASE`、`ACME_EMAIL`、`CLOUD_SECRET`、`CLOUD_ADMIN_TOKEN`、`UPSTREAM_KEY` 和验证码发送设置，再运行 `docker compose up -d`。不使用 Caddy 时，改为 `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`。如果需要让其他机器访问，还要在 `cloud/.env` 中设置 `RELAY_BIND=0.0.0.0` 或本机地址，并设置 `PUBLIC_BASE=http://<那个地址>:8787`。容器内的中继使用 uid 10001 运行，因此挂载的数据目录 `cloud/data` 在宿主机上也必须归该 uid 所有。首次启动前，执行 `mkdir -p data && sudo chown -R 10001:10001 data`；从以 root 运行的旧镜像升级时，也要执行一次。部署脚本会自动处理；如果中继无法写入目录，会在启动时说明原因并停止。

聊天可以改用其他兼容 OpenAI 接口的服务商，同时继续用百炼生成图片和视频。将聊天接口地址和 key 填入 `UPSTREAM_BASE` / `UPSTREAM_KEY`，将百炼原生接口地址和 key 填入 `DASHSCOPE_BASE` / `DASHSCOPE_KEY`。`DASHSCOPE_KEY` 为空时会使用 `UPSTREAM_KEY`。如果同时更换了聊天模型菜单，可以通过 `CLOUD_MODEL_ALIASES` 把旧客户端保存的模型 ID 映射到 `CLOUD_MODELS` 中的模型，例如 `{"old-chat-model":"new-chat-model"}`。

### 登录验证码 {#sign-in-codes}

使用 `--local` 后，脚本会打印一条标为 *Codes*、以 `cd cloud &&` 开头的命令。在仓库根目录复制执行即可，命令已经包含本地中继所需的两个 compose 文件。

每次有人登录，中继都会发送验证码。`CODE_SENDER` 决定发送方式：

- `log`：只写入中继日志。运行 `cd cloud && docker compose logs relay` 可以看到 `verification code for …`。家庭使用时，你可以从日志中读取并转告验证码。`--local` 默认采用这种方式。
- `smtp`：通过你自己的邮箱发送邮件，需要填写 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`。任何支持 SMTP（邮件发送协议）的邮箱都可以，几个人使用时免费邮箱即可。
- `aliyun`：通过阿里云向中国大陆手机号发送短信。默认使用号码认证服务及其预设模板，即 `ALIYUN_SMS_API=dypns`；也可以使用短信服务和自己申请的模板，即 `ALIYUN_SMS_API=dysms`。相关变量见 `cloud/.env.example`。设为 `both` 时，邮箱地址走 SMTP，手机号走阿里云。短信只支持中国大陆手机号，其他用户请用邮箱登录。

### 管理页 {#the-admin-page}

打开 `https://<your domain>/app/admin/`，输入管理员密码，即 `cloud/.env` 中的 `CLOUD_ADMIN_TOKEN`。这里可以查看账号、各账号的开销、额度与成员资格、提醒策略、hub 中的设备，以及中继健康状况。脚本也可以通过 `/v1/admin/*` 获取同样的数据，见 [cloud/README.md](../../cloud/README.md#operating)。

### 让各个 App 连接你的中继 {#pointing-the-apps-at-it}

各个 App 默认登录 `https://cloud.nanomuse.cn`。使用自建中继时，需要分别修改服务器地址。同一账号的所有设备必须连接同一个中继，因为设备互联和对话都由它管理。

- **Android**（0.1.38）。点击登录表单下方的「使用其他服务器」，填写中继地址。「检查」会请求服务器的 `/healthz` 并显示版本；「使用这个服务器」会保存地址，重启 App 后仍然有效。在自己的网络之外必须使用 `https://`；私有地址允许使用明文 `http://`，包括 `10.x`、`172.16-31.x`、`192.168.x`、`localhost`，以及 `.local` 或 `.ts.net` 域名。设置 → 账号中会显示当前服务器；点击「更换」会先退出手机上的账号，见 [android.md](android.md)。
- **iPhone / iPad**。登录页有相同入口，规则也相同。
- **nanoMuse 桌面版**。中继地址由插件 cloud 配置项中的 `baseURL` 决定。桌面版配置目录是 `~/.nanomuse/desktop/profiles/nanomuse/`，Windows 上为 `%USERPROFILE%\.nanomuse\desktop\profiles\nanomuse\`；也可以通过 `NANOMUSE_DESKTOP_HOME` 更改目录。将以下内容加入其中的 `cordis.patch.yml`，然后重启应用：

  ```yaml
  - id: nanomuse-cloud
    name: dsh-nanomuse/cloud
    config:
      baseURL: https://cloud.example.com
      deviceName: ''
      statePath: ''
  ```

  也可以在应用启动环境中设置 `NANOMUSE_CLOUD_URL=https://cloud.example.com`，效果相同，无需改文件，见 [desktop.md](desktop.md)。
- **终端运行时和托管的网页版**，即 `nanomuse …` 和仓库根目录 `docker-compose.yml` 启动的服务：在环境变量或 `.env` 中设置 `NANOMUSE_CLOUD_BASE_URL=https://cloud.example.com`，也可以修改 `config/config.toml` 的 `[cloud] base_url`，见 [configuration.md](configuration.md)。
- **网页控制台**由中继自身的 `/app` 提供，地址为 `https://<your domain>/app/`，不需要另设服务器地址。

你的中继发出的邀请链接会指向自己的控制台。这个地址由脚本设置的 `INVITE_URL` 决定，因此受邀朋友会进入你的中继。

### 更新 {#updating}

```bash
cd nanoMuse && git pull
bash scripts/self-host.sh        # Enter through the questions; secrets and accounts are kept
# or: cd cloud && docker compose up -d --build
```

中继启动时会自动升级数据库结构。如果一次跨多个版本升级，请先阅读发布说明。可以通过 `GET /healthz` 查看中继版本。

### 备份 {#backing-up}

中继将账号数据保存在 SQLite 数据库 `cloud/data/cloud.db` 中，使用 `cloud/.env` 中的 `CLOUD_SECRET`，并将记录中的媒体文件保存在 `MEDIA_DIR`，默认是数据库旁的 `blobs/` 目录。恢复账号数据及其媒体文件时，这三部分都需要备份。数据库中的标识符使用这个密钥进行哈希和加密；尚未使用的六位登录验证码也受它保护。缺少密钥，数据库无法继续使用；只有密钥而没有数据库也无法恢复。除非准备清空重来，否则不要更换这个密钥：

```bash
cd cloud && docker compose exec -T relay python - > cloud-$(date -u +%Y%m%d).db <<'EOF'
import os, shutil, sqlite3, sys
src = sqlite3.connect("/srv/nanomuse-cloud/data/cloud.db")
dst = sqlite3.connect("/tmp/backup.db")
src.backup(dst)
dst.close(); src.close()
with open("/tmp/backup.db", "rb") as f:
    shutil.copyfileobj(f, sys.stdout.buffer)
os.remove("/tmp/backup.db")
EOF
```

上面的命令在运行中的容器内调用 SQLite 备份 API（供程序调用的接口），然后把备份内容输出到宿主机。镜像不含 `sqlite3` 命令。即使中继仍在写数据库，这种备份也能保持数据一致；生成的文件归你所有，且保存在 uid 10001 所属的数据目录之外。直接运行 `cp data/cloud.db` 则无法保证一致：WAL 模式下，最新写入可能还在 `cloud.db-wal` 日志文件中，只复制主数据库会漏掉这些内容。

上面的命令只备份数据库。还需要另行保存 `CLOUD_SECRET` 和 `MEDIA_DIR` 中的文件，并与数据库备份一起保管。

Caddy 证书保存在 `caddy_data` 卷中；如果丢失，Caddy 会重新申请。

定时备份脚本 `cloud/deploy/nanomuse-hk/backup.sh` 需要宿主机安装 Python 3 和
`flock`。开始复制前，脚本会检查数据库和备份目录所在文件系统中普通用户可用的空间。
每个文件系统至少需要数据库与 WAL 文件总大小的两倍，再留出 5 GiB 供服务继续运行。
脚本不允许多个备份同时执行。空间不足时，任务会在复制和清理旧备份之前退出，并在
日志中记录所需空间和可用空间。请先扩容或检查可保留的恢复点，再重新运行。这个检查
不会删除备份，也无法阻止其他进程占用空间。上面的手动备份命令不包含此检查。

### 你的中继保存哪些数据 {#what-your-relay-stores}


中继保存经过哈希和加密的标识符、每次请求的数量和价格，以及 hub 中的设备。默认配置 `RECORD_TURNS=1` 还会保存完整的模型请求与回复，包括已登录 App 上传的自有 key 对话轮次；图片、音频和短片保存在 `MEDIA_DIR` 中。设置 `RECORD_TURNS=0` 可以关闭这份账号记录。「在我的设备之间同步对话」控制的是另一份供设备显示的聊天副本，训练数据开关则决定哪些内容用于训练。完整数据清单及各开关的作用见 [privacy.md](privacy.md)。部署自己的中继后，那一页所说的运营者就是你。

## 3. 为网页版部署自己的运行时 {#_3-a-runtime-of-your-own-for-the-web-app}

手机 App 和桌面版都自带智能体，网页版则连接 Python 运行时。在 nanomuse.cn 上，每位访客都有自己的运行时容器。你也可以在自己的机器上用 Docker 运行它，然后通过任意浏览器打开随附的网页版：

```bash
cp .env.example .env && $EDITOR .env      # a model key, NANOMUSE_SERVER_TOKEN; NANOMUSE_CLOUD_BASE_URL for your own relay
nanomuse config init                      # or copy config/config.example.toml to config/config.toml
docker compose up -d app                  # the web app on http://<host>:8787, the URL with its token in the logs
```

如果本地中继已经占用 8787 端口，请在启动网页版前，将 `NANOMUSE_RUNTIME_PORT=8788` 加入仓库根目录的 `.env`，然后用 8788 端口访问。这个设置只修改宿主机发布的端口，容器内仍监听 8787，见[部署](deployment.md#docker)。

容器只能访问自己的数据卷和 `./workspace`，并且已移除 Linux capabilities（容器进程可使用的额外系统权限）。如何持续运行、使用 arm64 发布镜像，以及从外部网络访问，见[部署](deployment.md)。运行时像其他设备一样登录中继；设置 `NANOMUSE_CLOUD_BASE_URL` 后，就会使用第 2 节中的自建中继。登录后，手机可以通过 hub 把任务交给它，相当于把工作交给一台常开的电脑，见[每台设备](every-device.md)。

### 同时启动中继和运行时 {#the-relay-and-the-runtime-in-one-command}

如果两者部署在同一台机器上，脚本可以同时启动它们，并显示各自地址：

```bash
bash scripts/self-host.sh --local --with-runtime                # 中继在 8787，网页版在 8788
bash scripts/self-host.sh --local --with-runtime --runtime-port 9000   # 网页版换个端口
```

`config/config.toml` 不存在时，脚本会从示例创建该文件。容器启动需要这个文件；如果宿主机缺少它，Docker 会将同名目录挂载进去，随后报 *not a directory* 并启动失败。如果已经出现这种情况，请先检查该目录，确认它为空后运行 `sudo rmdir -- config/config.toml`，再执行部署脚本。脚本还会在仓库根目录 `.env` 中补充尚未设置的两项：`NANOMUSE_SERVER_TOKEN` 用来保持重启后的网页版链接不变，`NANOMUSE_CLOUD_BASE_URL=http://relay:8787` 用来指定中继。你已经设置的值不会被覆盖。中继自身的配置仍在 `cloud/.env`，请一起备份这两个文件。

`http://relay:8787` 中的 `relay` 是中继容器在共享 Docker 网络中的名称。运行时通过这个内部地址连接，所以即使使用 `--local`、中继只向本机回环地址开放端口，运行时也能访问。中继配置了公网域名时，内部地址也能避免经公网域名绕回本机，而这种绕行原本需要路由器支持 hairpin NAT。你在运行时页面登录后，它便能使用账号的模型访问凭据：运行时将中继视为一个兼容 OpenAI 的服务商，消耗账号额度，无需在自己的 `.env` 中另填 key。

更新时先运行 `git pull`，再执行同一条部署命令。脚本会重新构建两个镜像，保留中继的 `cloud/data` 和运行时的 `nanomuse-data` 卷。脚本不会删除这两处数据；但如果你在仓库根目录手动执行 `docker compose down -v`，仍会删除运行时的数据卷。

运行时默认只监听回环地址，也就是仅允许本机访问；即使中继配置了域名，这一点也不变。中继的 Caddy TLS 配置不保护运行时的 HTTP 端口。远程访问时，请使用 SSH 隧道或 TLS 反向代理。显式设置 `--local --bind 0.0.0.0` 才会将两个端口都发布到局域网。运行时创建、加入中继网络或启动失败时，脚本会报错，已运行的中继会继续运行。
