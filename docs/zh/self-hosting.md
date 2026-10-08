# 自己部署 nanoMuse

nanoMuse 是跑在你自己设备上的一个智能体，里面没有任何东西非得经过我们的服务器。自己运行它有三条路，从最省事到最费事。多数人要的是第一条；想要自己的登录的一家人或一个小团体要第二条；第三条是给想在自己机器上跑网页版的人。

| | 你要运行什么 | 你得到什么 |
|---|---|---|
| [1. 不要服务器，用自己的 key](#_1-no-server-your-own-key) | 什么都不用 | 各个 App 直接和模型服务商对话；社区中继仍然用于登录和让设备互相找到 |
| [2. 自己的中继](#_2-your-own-relay) | 一台小 VPS 或家用服务器上的 nanoMuse Cloud | 你自己的账号、登录验证码、hub 和对话同步；关于你账号的一切都不碰 nanomuse.cn |
| [3. 自己的运行时](#_3-a-runtime-of-your-own-for-the-web-app) | Docker 里的 Python 运行时 | 网页版，以及一台常开电脑上的手 |

## 1. 不要服务器，用自己的 key {#_1-no-server-your-own-key}

社区中继上的免费额度是会用完的。用完的时候，或者在那之前，往 App 里放一把自己的 key——中国大陆用阿里云百炼，其他地方用 OpenRouter 或任何 OpenAI 兼容端点——模型请求就从你的设备直接发给那家服务商；中继只看得到登录，以及你的设备之间的 hub 帧。[own-key.md](own-key.md) 有每个 App 的步骤。不用装任何东西，不用让任何东西一直跑着。

## 2. 自己的中继 {#_2-your-own-relay}

nanoMuse Cloud 就是 nanomuse.cn 背后的那个中继：邮箱或手机号登录、通过一个 OpenAI 兼容端点提供账号的模型、设备相遇的 hub、对话同步、`/app` 下的网页控制台和 `/app/admin/` 下的管理页。它是一个 Python 服务加一个 SQLite 文件，在这个仓库的 [`cloud/`](../../cloud/README.md) 下，放到你的服务器上照样跑。

### 你需要什么 {#what-you-need}

- **一台机器。** 1 vCPU、1 GB 内存的 VPS 够一家人用；中继空闲时只占几十兆内存，模型的活在服务商那边干。这样一台服务器在中国大陆大约每月 ¥30–60，境外大约 US$4–6，哪家都行——中继不挑。只在局域网内用的中继，一台家用服务器或一台闲置笔记本就行。
- **一个域名**，指向这台机器（一条 A 记录），80 和 443 端口可达。和中继一起跑的 Caddy 会自己申请和续期 Let's Encrypt 证书。只在局域网内用的中继可以跳过这条。
- **一把模型服务商的 key。** 中继花的是*你的*钱、用的是*你的*服务商：在你的中继上登录的每个人都记在这把 key 上，按服务商的价格计费，在你设定的额度之内（`ALLOWANCE_CNY`、`SIGNUP_OPEN`，成员写在 `ALLOWED_IDENTIFIERS`——[cloud/README.md](../../cloud/README.md#settings)）。没有 key，登录和 hub 能用，聊天不能。
- **Docker**，带 compose 插件，还有 `curl`。

### 一条命令 {#in-one-command}

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
bash scripts/self-host.sh
```

脚本问五件事——域名（或 `local`）、给 Let's Encrypt 的邮箱、登录验证码怎么发出去、服务商的 URL 和 key、管理员密码——然后写出带一个新随机 `CLOUD_SECRET` 的 `cloud/.env`，启动 `docker compose`，等 `/healthz` 就绪，打印控制台和管理页的 URL。再跑一次会保留机密和账号，只是重新问一遍，把当前值作为默认值。只在这台机器上用、不要域名也不要 TLS：

```bash
bash scripts/self-host.sh --local          # http://127.0.0.1:8787, codes in the relay's log
bash scripts/self-host.sh --local --bind 0.0.0.0   # reachable from the phones on the same network
```

不用脚本、自己动手：`cd cloud && cp .env.example .env`，填上 `CLOUD_DOMAIN`、`PUBLIC_BASE`、`ACME_EMAIL`、`CLOUD_SECRET`、`CLOUD_ADMIN_TOKEN`、`UPSTREAM_KEY` 和发信设置，然后 `docker compose up -d`——或者不要 Caddy，`docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`。

### 登录验证码 {#sign-in-codes}

每次有人登录都会发出一个验证码。`CODE_SENDER` 决定怎么发：

- `log`——只打印到中继的日志：`cd cloud && docker compose logs relay` 里能看到 `verification code for …`。一家人用够了：你把验证码念给对方。`--local` 用的就是这个。
- `smtp`——通过你自己的一个邮箱发邮件（`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`）。任何支持 SMTP 的邮箱都行；几个人用，一个免费邮箱就够。
- `aliyun`——通过阿里云给中国大陆手机号发短信：默认走号码认证服务（`ALIYUN_SMS_API=dypns`，用它现成的模板），也可以走短信服务并使用你自己签约的模板（`ALIYUN_SMS_API=dysms`）；相关变量见 `cloud/.env.example`。`both` 对邮箱地址用 SMTP，对手机号用阿里云。短信只发得到中国大陆手机号；其他人都用邮箱登录。

### 管理页 {#the-admin-page}

`https://<your domain>/app/admin/`，用管理员密码（`cloud/.env` 里的 `CLOUD_ADMIN_TOKEN`）进入：各个账号、每个账号花了多少、额度和成员资格、提醒策略、hub 上的设备、中继自身的健康状况。同样的数据在 `/v1/admin/*` 后面供脚本使用（[cloud/README.md](../../cloud/README.md#operating)）。

### 把各个 App 指向它 {#pointing-the-apps-at-it}

每个 App 默认都在 `https://cloud.nanomuse.cn` 上登录，除非你另外告诉它。同一个账号的设备必须都指向同一个中继——hub 和对话都在那里。

- **Android**（0.1.38）。登录表单下面的「使用其他服务器」填中继地址；「检查」会访问它的 `/healthz` 并显示版本，「使用这个服务器」让这个地址在重启 App 之后也保留。在你自己的网络之外必须用 `https://`；私有地址（`10.x`、`172.16–31.x`、`192.168.x`、`localhost`、`.local` 或 `.ts.net` 名字）接受明文 `http://`。「设置 → 账号」显示当前服务器和「更换」，更换会先把手机退出登录（[android.md](android.md)）。
- **iPhone / iPad。** 登录页上同样的链接，同样的规则。
- **nanoMuse 桌面版。** 中继就是插件 cloud 一行的 `baseURL`。把下面这段加进桌面版配置档里的 `cordis.patch.yml`——`~/.nanomuse/desktop/profiles/nanomuse/`（Windows 上是 `%USERPROFILE%\.nanomuse\desktop\profiles\nanomuse\`；`NANOMUSE_DESKTOP_HOME` 可以把它挪走）——然后重启应用：

  ```yaml
  - id: nanomuse-cloud
    name: dsh-nanomuse/cloud
    config:
      baseURL: https://cloud.example.com
      deviceName: ''
      statePath: ''
  ```

  在应用启动的环境里设 `NANOMUSE_CLOUD_URL=https://cloud.example.com`，不用改文件也是一样的效果（[desktop.md](desktop.md)）。
- **终端运行时和托管的网页版**（`nanomuse …`、根目录的 `docker-compose.yml`）：环境变量或 `.env` 里的 `NANOMUSE_CLOUD_BASE_URL=https://cloud.example.com`，或者 `config/config.toml` 里的 `[cloud] base_url`（[configuration.md](configuration.md)）。
- **网页控制台**就是中继自己的 `/app`——`https://<your domain>/app/`——不需要指向。

从你的中继发出的邀请链接指向它自己的控制台（`INVITE_URL`，由脚本设置），所以你邀请的朋友落在你的中继上，而不是 nanomuse.cn。

### 更新 {#updating}

```bash
cd nanoMuse && git pull
bash scripts/self-host.sh        # Enter through the questions; secrets and accounts are kept
# or: cd cloud && docker compose up -d --build
```

数据库结构在启动时向前迁移。一次跨好几个版本的升级，先读发布说明；中继的版本号在 `GET /healthz` 里。

### 备份 {#backing-up}

中继保存的一切就是 `cloud/data/cloud.db`（SQLite）加上 `cloud/.env` 里的 `CLOUD_SECRET`。没有这个密钥，数据库就没用（标识符是用它哈希和加密的，还在等待使用的登录验证码也是，那只有六位数字），没有数据库，密钥也没用；两样一起备份，而且除非你打算从头来过，否则绝不要更换密钥：

```bash
cd cloud && docker compose exec relay sqlite3 /srv/nanomuse-cloud/data/cloud.db ".backup /srv/nanomuse-cloud/data/backup.db" \
  || cp data/cloud.db data/backup.db   # when the container has no sqlite3: stop the relay first for a clean copy
```

Caddy 的证书在 `caddy_data` 卷里，丢了会重新申请。

### 你的中继存什么 {#what-your-relay-stores}

哈希并加密过的标识符、每次请求的计数和价格、hub 上的设备，还有——只在「在我的设备之间同步对话」开着的时候——对话的文字，好让其他设备能显示它们。没有文件，没有截图，没有密码。完整清单和每个开关的作用在 [privacy.md](privacy.md)；作为运营者，那一页现在描述的就是你。

## 3. 自己的运行时，给网页版用 {#_3-a-runtime-of-your-own-for-the-web-app}

手机和桌面各自带着自己的智能体。网页版没有——它对话的是 Python 运行时，在 nanomuse.cn 上，每个访客有一个自己的容器。你可以把这个运行时跑在自己的机器上，在 Docker 里，然后从任何浏览器打开它上面的网页版：

```bash
cp .env.example .env && $EDITOR .env      # a model key, NANOMUSE_SERVER_TOKEN; NANOMUSE_CLOUD_BASE_URL for your own relay
nanomuse config init                      # or copy config/config.example.toml to config/config.toml
docker compose up -d app                  # the web app on http://<host>:8787, the URL with its token in the logs
```

容器只看得到它的数据卷和 `./workspace`；capability 都已丢弃。让它一直跑着、arm64 的发布镜像、从你的网络外面访问它，都在[部署](deployment.md)。这个运行时像其他任何设备一样登录到一个中继——设了 `NANOMUSE_CLOUD_BASE_URL` 的话，就是第 2 节里你自己的那个——之后手机就可以通过 hub 把任务交给它，像交给一台常开的电脑（[every-device.md](every-device.md)）。
