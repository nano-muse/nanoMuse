# 部署

Meta 把每个 Muse 跑在一台按用户隔离的安全虚拟机里。在本地，最接近的做法是一个容器：智能体只看得到它的数据目录和工作区。

这一页讲的是 Python 运行时（网页版背后的智能体）怎么在 Docker 里跑。自己运行中继（你自己的登录、hub 和同步）并把各个 App 指向它，见[自己部署](self-hosting.md)，那一页也把自己运行 nanoMuse 的三条路按顺序排好了。

## Docker {#docker}

```bash
cp .env.example .env && $EDITOR .env      # API key
nanomuse config init                      # or copy config/config.example.toml to config/config.toml
docker compose up -d app                  # the phone app on http://<host>:8787
docker compose logs app                   # shows the URL with the access token
```

其他入口：

```bash
docker compose run --rm muse                      # terminal chat
docker compose run --rm muse run "plan my week"   # one task
docker compose up -d daemon                       # advance goals on a timer, no UI
```

镜像以非 root 用户运行，所有 capability 都已丢弃。状态放在两个卷里：`nanomuse-data`（记忆、目标、保险库、审计日志、对话线程）和 `./workspace`（智能体的文件）。`config/config.toml` 以只读方式挂载。在 `.env` 里设好 `NANOMUSE_SERVER_TOKEN`，令牌就不会每次重启都变；然后在手机上用主机的地址打开打印出来的那个 URL。

不克隆仓库，直接用发布的镜像（linux/amd64 和 linux/arm64，所以树莓派或 Apple 芯片的 Mac 也行）：

```bash
docker run -d --name muse -p 8787:8787 --env-file .env \
  -v nanomuse-data:/data -v "$PWD/workspace:/workspace" \
  ghcr.io/nano-muse/nanomuse:latest
docker logs muse                          # the URL with the access token
```

`:latest` 和 `:X.Y.Z` 跟随正式版本；`:edge` 跟随 `main`。没有挂载 `config.toml` 时，镜像从 `config.example.toml` 起步，所以模型要在 `.env` 里（`NANOMUSE_LLM_*`）或 App 的「连接」屏幕里设。

**带浏览器。** `-browser` 标签（`:latest-browser`、`:X.Y.Z-browser`、`:edge-browser`；linux/amd64）打包了 Chromium 和 Playwright，启动时浏览器工具就是开着的，智能体可以使用网站，你可以在手机上旁观和接管（见 [App → 浏览器视图](app.md#what-is-on-the-screen)）。它大约大 400 MB。在那个镜像里打开这个工具的是 `NANOMUSE_BROWSER_ENABLED=1`；只要装了 Playwright 和 Chromium，这个变量在哪里都管用。

自己构建：

```bash
docker build -t nanomuse .
docker build --build-arg WITH_BROWSER=1 -t nanomuse:browser .   # with Chromium
docker run -d --name muse -p 8787:8787 --env-file .env \
  -v nanomuse-data:/data -v "$PWD/workspace:/workspace" \
  -v "$PWD/config/config.toml:/app/config/config.toml:ro" nanomuse
```

## 不用 Docker 也让它一直跑着 {#keeping-it-running-without-docker}

一个用户级的 systemd 单元就够了：

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

## 从你的网络外面访问它 {#reaching-it-from-outside-your-network}

不要把 8787 端口直接暴露到互联网。几个能保住令牌机制的选项：

- **Tailscale / WireGuard**：绑定到 `0.0.0.0`，在手机上打开 tailnet 地址。
- **带 TLS 的反向代理**（Caddy、nginx）：把 `/` 和 `/ws`（WebSocket 升级）代理到 `127.0.0.1:8787`。令牌照样有效。

TLS 也是手机上推送通知的开关：浏览器只在安全上下文（`https://` 或 `localhost`）里允许 service worker 和 Web Push。一个配了 [`tailscale serve`](https://tailscale.com/kb/1312/serve) 的 Tailscale 地址，或者像下面这样一段 Caddy 配置，就够了：

```
muse.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

## 更新 {#updating}

```bash
uv tool upgrade nanomuse                               # PyPI install (or: pip install -U nanomuse)
git pull --ff-only && uv pip install -e ".[dev]"      # source install
docker compose build && docker compose up -d app       # Docker
```

数据格式（SQLite、JSONL、JSON）在同一个次版本号内保持向后兼容。
