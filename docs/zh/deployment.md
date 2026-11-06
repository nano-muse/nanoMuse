# 部署

能够执行 shell 命令（操作系统命令）的智能体，应当在隔离环境中运行。在服务器上可以用容器隔离，让智能体只能访问自己的数据目录和工作区。

本文介绍如何在 Docker 中部署 Python 运行时，也就是为网页版执行任务的程序。如果你要自己提供登录、hub（设备互联）和同步服务，并让各个 App 连接它，请参阅[自己部署](self-hosting.md)。那一页也介绍了自行运行 nanoMuse 的三种方式。

## Docker {#docker}

```bash
cp .env.example .env && $EDITOR .env      # API key
nanomuse config init                      # or copy config/config.example.toml to config/config.toml
docker compose up -d app                  # the phone app on http://<host>:8787
docker compose logs app                   # shows the URL with the access token
```

如果 8787 端口已被占用，例如同一台机器上还运行着本地中继，可以改用其他宿主机端口：

```bash
NANOMUSE_RUNTIME_PORT=8788 docker compose up -d app
```

使用原来的访问令牌打开 `http://<host>:8788`。访问令牌是控制网页访问权限的凭据。若要让后续 compose 命令继续使用这个端口，在仓库根目录的 `.env` 中加入 `NANOMUSE_RUNTIME_PORT=8788`。这个变量只改变宿主机对外发布的端口；容器内部、健康检查以及日志中的 URL 仍使用 8787。不设置时，宿主机也使用 8787。

还可以通过以下方式运行：

```bash
docker compose run --rm muse                      # terminal chat
docker compose run --rm muse run "plan my week"   # one task
docker compose up -d daemon                       # advance goals on a timer, no UI
```

镜像以非 root 用户运行，并移除了全部 Linux capabilities（进程可获得的额外系统权限）。容器每 30 秒请求一次自身的 `/api/health` 做健康检查，`docker ps` 会显示 *healthy* 或 *unhealthy*。`muse` 和 `daemon` 不启动服务器，因此 compose 配置为它们禁用了这项检查。直接通过 `docker run` 运行 `chat` 或 `daemon` 时，需要加 `--no-healthcheck`。状态数据保存在两处：`nanomuse-data` 卷存放记忆、目标、保险库、审计日志和对话线程；`./workspace` 存放智能体处理的文件。`config/config.toml` 以只读方式挂载。请在 `.env` 中设置 `NANOMUSE_SERVER_TOKEN`，让访问令牌在重启后保持不变，然后在手机上用宿主机地址打开日志打印的 URL。

如果不想克隆仓库，可以直接运行发布镜像。镜像支持 linux/amd64 和 linux/arm64，因此也适用于树莓派和 Apple 芯片的 Mac：

```bash
docker run -d --name muse -p 8787:8787 --env-file .env \
  -v nanomuse-data:/data -v "$PWD/workspace:/workspace" \
  ghcr.io/nano-muse/nanomuse:latest
docker logs muse                          # the URL with the access token
```

`:latest` 和 `:X.Y.Z` 对应正式发布版本，`:edge` 随 `main` 分支更新。没有挂载 `config.toml` 时，镜像会使用 `config.example.toml` 作为初始配置。此时可以在 `.env` 中通过 `NANOMUSE_LLM_*` 设置模型，也可以在 App 的「连接」页面设置。

**附带浏览器的镜像**。`-browser` 标签包括 `:latest-browser`、`:X.Y.Z-browser`、`:edge-browser`，支持 linux/amd64。它们打包了 Chromium 浏览器和 Playwright 浏览器控制库，并在启动时启用浏览器工具。智能体可以操作网站，你也可以在手机上查看操作过程或接管，见 [App → 浏览器视图](app.md#what-is-on-the-screen)。这类镜像约大 400 MB。镜像通过 `NANOMUSE_BROWSER_ENABLED=1` 开启工具；在其他环境中，只要已安装 Playwright 和 Chromium，这个变量同样有效。

手动构建镜像：

```bash
docker build -t nanomuse .
docker build --build-arg WITH_BROWSER=1 -t nanomuse:browser .   # with Chromium
docker run -d --name muse -p 8787:8787 --env-file .env \
  -v nanomuse-data:/data -v "$PWD/workspace:/workspace" \
  -v "$PWD/config/config.toml:/app/config/config.toml:ro" nanomuse
```

## 不使用 Docker 时如何持续运行 {#keeping-it-running-without-docker}

可以用用户级 systemd 服务管理进程：

```ini
# ~/.config/systemd/user/nanomuse.service
[Unit]
Description=nanoMuse
After=network-online.target

[Service]
WorkingDirectory=%h/nanoMuse
ExecStart=%h/nanoMuse/.venv/bin/nanomuse serve --host 0.0.0.0 --no-qr
Restart=on-failure
EnvironmentFile=%h/nanoMuse/.env

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now nanomuse
loginctl enable-linger $USER          # keep it running after logout
journalctl --user -u nanomuse -f
```

## 从外部网络访问 {#reaching-it-from-outside-your-network}

不要将 8787 端口直接开放到互联网。以下方式都能保留原有的令牌验证：

- **Tailscale / WireGuard**：将服务绑定到 `0.0.0.0`，在手机上通过 tailnet 地址，也就是 Tailscale 私有网络中的地址访问。
- **TLS 反向代理**，例如 Caddy 或 nginx：将 `/` 和 `/ws` 转发至 `127.0.0.1:8787`，并为 `/ws` 启用 WebSocket 协议升级。WebSocket 是客户端与服务器保持连接、双向传消息的协议。代理后仍需通过令牌验证。

TLS 为连接提供加密，也是手机浏览器接收推送通知的前提。浏览器只允许在安全环境中使用 service worker（网页的后台脚本）和 Web Push（网页推送），这里的安全环境指 `https://` 或 `localhost`。可以为 Tailscale 地址配置 [`tailscale serve`](https://tailscale.com/kb/1312/serve)，也可以使用下面的 Caddy 配置：

```
muse.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

## 更新 {#updating}

```bash
git pull --ff-only && uv pip install -e ".[dev]"      # 源码安装
docker compose build && docker compose up -d app       # Docker，本机构建
docker pull ghcr.io/nano-muse/nanomuse:latest          # Docker，发布的镜像；拉完重新启动
```

同一个次版本内，SQLite、JSONL、JSON 数据格式保持向后兼容。
