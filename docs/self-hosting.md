# Run nanoMuse yourself

nanoMuse is one agent on your own devices, and nothing in it has to go through a server of ours. There are three ways to run it yourself, from the least work to the most. Most people want the first; a family or a small group that wants its own sign-in wants the second; the third is for the web app on a machine of your own.

| | What you run | What it gives you |
|---|---|---|
| [1. No server, your own key](#_1-no-server-your-own-key) | nothing | the apps talk to a model provider directly; the community relay is still used for sign-in and for the devices to find each other |
| [2. Your own relay](#_2-your-own-relay) | nanoMuse Cloud on a small VPS or a home server | your own accounts, sign-in codes, hub and conversation sync; nothing about your account touches nanomuse.cn |
| [3. A runtime of your own](#_3-a-runtime-of-your-own-for-the-web-app) | the Python runtime in Docker | the web app and the hands on a computer that is always on |

## 1. No server, your own key

The free allowance on the community relay runs out. When it does, or before, put a key of your own in the app: Alibaba Model Studio (百炼) inside mainland China, OpenRouter or any OpenAI-compatible endpoint elsewhere. The model requests then go from your device to that provider; the relay only sees the sign-in and the hub frames between your devices. [own-key.md](own-key.md) has the steps for every app. Nothing to install, nothing to keep running.

## 2. Your own relay

nanoMuse Cloud is the relay behind nanomuse.cn: sign-in by e-mail or phone, the account's models through one OpenAI-compatible endpoint, the hub the devices meet on, conversation sync, a web console at `/app` and an admin page at `/app/admin/`. It is one Python service and one SQLite file, in this repository under [`cloud/`](../cloud/README.md), and it runs the same on a server of yours.

### What you need

- **A machine.** A VPS with 1 vCPU and 1 GB of memory is enough for a family; the relay idles at a few tens of megabytes and the model work happens at the provider. Such a server costs on the order of ¥30–60 a month inside mainland China or US$4–6 outside it, from any provider; the relay does not care which. A home server or a spare laptop works for a LAN-only relay.
- **A domain** pointing at the machine (an A record), with ports 80 and 443 reachable. Caddy, which runs next to the relay, fetches and renews the Let's Encrypt certificate on its own. Skip this for a LAN-only relay.
- **A model provider key.** The relay spends *your* money on *your* provider: everyone who signs in on your relay is billed to that key, at the provider's prices, within the allowance you set (`ALLOWANCE_CNY`, `SIGNUP_OPEN`, `SIGNUP_PER_DOMAIN_DAY`, `SIGNUP_DOMAIN_BLOCK`, members in `ALLOWED_IDENTIFIERS`; [cloud/README.md](../cloud/README.md#settings)). Without a key, sign-in and the hub work and chat does not.
- **Docker** with the compose plugin, and `curl`.

### In one command

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
bash scripts/self-host.sh
```

The script asks five things: the domain (or `local`), an e-mail for Let's Encrypt, how sign-in codes go out, the provider's URL and key, the admin password. It writes `cloud/.env` with a fresh random `CLOUD_SECRET`, starts `docker compose`, waits for `/healthz` and prints the console and admin URLs. Running it again keeps the secrets and the accounts and only re-asks, with the current values as defaults. For this machine only, no domain and no TLS:

```bash
bash scripts/self-host.sh --local          # this machine only: http://127.0.0.1:8787, codes in the relay's log
bash scripts/self-host.sh --local --bind 0.0.0.0   # the phones on the same network too: the URLs carry this machine's LAN address
```

With `--bind 0.0.0.0` the relay listens on every interface and the script looks up the machine's LAN address (`192.168.1.20`, say) for `PUBLIC_BASE`, the invitation links and the URLs it prints, since that is the address the phones reach it at; when it cannot find one it says so and falls back to `127.0.0.1`. `--bind` with one address (a Tailscale address, for instance) publishes the port on that address only and uses it as given. Running the script again with another `--bind` moves the URLs along.

By hand instead of the script: `cd cloud && cp .env.example .env`, fill in `CLOUD_DOMAIN`, `PUBLIC_BASE`, `ACME_EMAIL`, `CLOUD_SECRET`, `CLOUD_ADMIN_TOKEN`, `UPSTREAM_KEY` and the sender settings, then `docker compose up -d`; or, without Caddy, `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`, with `RELAY_BIND=0.0.0.0` (or the machine's address) and `PUBLIC_BASE=http://<that address>:8787` in `cloud/.env` when other machines are to reach it. The relay runs as uid 10001 inside its container, and `cloud/data`, the bind-mounted data directory, must belong to that uid on the host: `mkdir -p data && sudo chown -R 10001:10001 data` before the first start, and once more when upgrading from a relay whose image ran as root (the script does this for you; a relay that cannot write the directory says so at start and stops).

Chat may use a different OpenAI-compatible provider while pictures and clips stay on
Model Studio: put the chat endpoint and key in `UPSTREAM_BASE` / `UPSTREAM_KEY`, and
the Model Studio native endpoint and key in `DASHSCOPE_BASE` / `DASHSCOPE_KEY`.
`DASHSCOPE_KEY` falls back to `UPSTREAM_KEY` when it is empty. If the change replaces
the chat menu, `CLOUD_MODEL_ALIASES` can map ids saved by existing clients to a model
in `CLOUD_MODELS`, for example `{"old-chat-model":"new-chat-model"}`.

### Sign-in codes

After `--local`, the script prints a *Codes* command that starts with `cd cloud &&`. Copy it from the repository root; it includes both compose files used for the local relay.

A code goes out every time someone signs in. `CODE_SENDER` says how:

- `log`: printed to the relay's log only (`cd cloud && docker compose logs relay` shows `verification code for …`). Fine for a family: you read the code out. This is what `--local` uses.
- `smtp`: by e-mail through a mailbox you own (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`). Any mailbox with SMTP works; a free one is enough for a few people.
- `aliyun`: by SMS to mainland China numbers through Alibaba Cloud: 号码认证服务 by default (`ALIYUN_SMS_API=dypns`, its ready-made templates), or 短信服务 with a signed template of your own (`ALIYUN_SMS_API=dysms`); the variables are in `cloud/.env.example`. `both` uses SMTP for addresses and Aliyun for numbers. SMS reaches mainland numbers only; everyone else signs in by e-mail.

### The admin page

`https://<your domain>/app/admin/` with the admin password (`CLOUD_ADMIN_TOKEN` in `cloud/.env`): the accounts, what each has spent, allowance and membership, nudge policies, the devices on the hub, the relay's own health. The same data is behind `/v1/admin/*` for scripts ([cloud/README.md](../cloud/README.md#operating)).

### Pointing the apps at it

Every app signs in against `https://cloud.nanomuse.cn` unless you tell it otherwise. The devices of one account must all point at the same relay; the hub and the conversations live there.

- **Android** (0.1.38). *Use a different server* under the sign-in form takes the relay's address; *Check* asks its `/healthz` and shows the version, *Use this server* keeps the address across launches. `https://` is required outside your own network; plain `http://` is accepted for a private address (`10.x`, `172.16-31.x`, `192.168.x`, `localhost`, a `.local` or `.ts.net` name). Settings → Account shows the server with *Change*, which signs the phone out first ([android.md](android.md)).
- **iPhone / iPad.** The same link on the sign-in sheet, with the same rules.
- **nanoMuse Desktop.** The relay is the `baseURL` of the plugin's cloud row. Add this to `cordis.patch.yml` in the desktop's profile, `~/.nanomuse/desktop/profiles/nanomuse/` (`%USERPROFILE%\.nanomuse\desktop\profiles\nanomuse\` on Windows; `NANOMUSE_DESKTOP_HOME` moves it), and restart the app:

  ```yaml
  - id: nanomuse-cloud
    name: dsh-nanomuse/cloud
    config:
      baseURL: https://cloud.example.com
      deviceName: ''
      statePath: ''
  ```

  Setting `NANOMUSE_CLOUD_URL=https://cloud.example.com` in the environment the app starts in does the same without editing the file ([desktop.md](desktop.md)).
- **The terminal runtime and the hosted web app** (`nanomuse …`, the root `docker-compose.yml`): `NANOMUSE_CLOUD_BASE_URL=https://cloud.example.com` in the environment or `.env`, or `[cloud] base_url` in `config/config.toml` ([configuration.md](configuration.md)).
- **The web console** is the relay's own `/app` (`https://<your domain>/app/`) and needs no pointing.

Invitations from your relay link to its console (`INVITE_URL`, set by the script), so a friend you invite lands on your relay, not on nanomuse.cn.

### Updating

```bash
cd nanoMuse && git pull
bash scripts/self-host.sh        # Enter through the questions; secrets and accounts are kept
# or: cd cloud && docker compose up -d --build
```

The database schema migrates forward on start. Read the release notes before a jump of several versions; the relay's version is in `GET /healthz`.

### Backing up

Everything the relay keeps is `cloud/data/cloud.db` (SQLite) plus `CLOUD_SECRET` in `cloud/.env`. The database is useless without the secret (the identifiers are hashed and encrypted with it, and so is a sign-in code still waiting to be used, which is only six digits), and the secret is useless without the database; back them up together, and never rotate the secret unless you mean to start over:

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

The copy is taken with SQLite's own backup API inside the running container (the image has no `sqlite3` command) and streamed out, so it is consistent while the relay keeps writing and lands as a file of yours, outside the data directory that belongs to uid 10001. A plain `cp data/cloud.db` is not consistent: under WAL the newest writes sit in `cloud.db-wal`, and a copy of the main file alone misses them.

Caddy's certificates live in the `caddy_data` volume and are fetched again if lost.

### What your relay stores

Hashed and encrypted identifiers, per-request counts and prices, the devices on the hub, and, only while *Sync conversations between my devices* is on, the text of the conversations so the other devices can show them. No files, no screenshots, no passwords. The full list, and what each switch does, is [privacy.md](privacy.md); as the operator you are the one it now describes.

## 3. A runtime of your own, for the web app

The phone and the desktop carry their own agent. The web app does not; it talks to the Python runtime, which on nanomuse.cn runs in a container per visitor. You can run that runtime on a machine of your own, in Docker, and open the web app on it from any browser:

```bash
cp .env.example .env && $EDITOR .env      # a model key, NANOMUSE_SERVER_TOKEN; NANOMUSE_CLOUD_BASE_URL for your own relay
nanomuse config init                      # or copy config/config.example.toml to config/config.toml
docker compose up -d app                  # the web app on http://<host>:8787, the URL with its token in the logs
```

If your local relay already uses port 8787, put `NANOMUSE_RUNTIME_PORT=8788` in the root `.env` before starting the app, then open it on port 8788. This changes the app's host port only; the container still listens on 8787. See [deployment.md](deployment.md#docker).

The container sees only its data volume and `./workspace`; capabilities are dropped. Keeping it running, a published image for arm64, and reaching it from outside your network are in [deployment.md](deployment.md). The runtime signs in to a relay like any other device (yours, from section 2, if you set `NANOMUSE_CLOUD_BASE_URL`), and then the phone can hand it tasks over the hub like a computer that is always on ([every-device.md](every-device.md)).

### The relay and the runtime in one command

When both live on the same machine, the script starts both and prints their addresses:

```bash
bash scripts/self-host.sh --local --with-runtime                # relay on 8787, web app on 8788
bash scripts/self-host.sh --local --with-runtime --runtime-port 9000   # another port for the web app
```

It writes `config/config.toml` from the example when that file is missing, because the container cannot start without it: a missing host file is mounted as a directory and the start fails with *not a directory*. If that has already happened, check that directory first, then use `sudo rmdir -- config/config.toml` if it is empty and run the script again. It also puts two lines in the root `.env` when they are not there yet: `NANOMUSE_SERVER_TOKEN`, so the web app's link stays the same across restarts, and `NANOMUSE_CLOUD_BASE_URL=http://relay:8787`. It never overwrites a value you set yourself. The relay's own settings stay in `cloud/.env`; back the two files up together.

`http://relay:8787` is the relay's name on the docker network the two containers share. That is why the runtime reaches the relay even under `--local` (where the relay publishes nothing but loopback) and on a server with a domain (where a round trip through the public name would need hairpin NAT on the router). Signing in on the runtime's page is also what gives it a model key: the relay is one more OpenAI-compatible provider to it, within the account's allowance, so the runtime's `.env` needs no key of its own.

To update, `git pull` and run the same command: both images are rebuilt and everything they keep stays put: `cloud/data` for the relay, the `nanomuse-data` volume for the runtime. The script never removes either; a `docker compose down -v` typed by hand at the repository root still deletes the runtime's volume.

The runtime listens on loopback by default, including when the relay has a domain. Its HTTP port is not covered by the relay’s Caddy TLS setup. Use an SSH tunnel or a TLS reverse proxy for remote access; `--local --bind 0.0.0.0` explicitly publishes both ports on the LAN. If the runtime cannot be created, joined to the relay network or started, the script fails and leaves the relay running.
