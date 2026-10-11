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
- **A model provider key.** The relay spends *your* money on *your* provider: everyone who signs in on your relay is billed to that key, at the provider's prices, within the allowance you set (`ALLOWANCE_CNY`, `SIGNUP_OPEN`, members in `ALLOWED_IDENTIFIERS`; [cloud/README.md](../cloud/README.md#settings)). Without a key, sign-in and the hub work and chat does not.
- **Docker** with the compose plugin, and `curl`.

### In one command

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
bash scripts/self-host.sh
```

The script asks five things: the domain (or `local`), an e-mail for Let's Encrypt, how sign-in codes go out, the provider's URL and key, the admin password. It writes `cloud/.env` with a fresh random `CLOUD_SECRET`, starts `docker compose`, waits for `/healthz` and prints the console and admin URLs. Running it again keeps the secrets and the accounts and only re-asks, with the current values as defaults. For this machine only, no domain and no TLS:

```bash
bash scripts/self-host.sh --local          # http://127.0.0.1:8787, codes in the relay's log
bash scripts/self-host.sh --local --bind 0.0.0.0   # reachable from the phones on the same network
```

By hand instead of the script: `cd cloud && cp .env.example .env`, fill in `CLOUD_DOMAIN`, `PUBLIC_BASE`, `ACME_EMAIL`, `CLOUD_SECRET`, `CLOUD_ADMIN_TOKEN`, `UPSTREAM_KEY` and the sender settings, then `docker compose up -d`; or, without Caddy, `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`.

### Sign-in codes

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
cd cloud && docker compose exec relay sqlite3 /srv/nanomuse-cloud/data/cloud.db ".backup /srv/nanomuse-cloud/data/backup.db" \
  || cp data/cloud.db data/backup.db   # when the container has no sqlite3: stop the relay first for a clean copy
```

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

The container sees only its data volume and `./workspace`; capabilities are dropped. Keeping it running, a published image for arm64, and reaching it from outside your network are in [deployment.md](deployment.md). The runtime signs in to a relay like any other device (yours, from section 2, if you set `NANOMUSE_CLOUD_BASE_URL`), and then the phone can hand it tasks over the hub like a computer that is always on ([every-device.md](every-device.md)).
